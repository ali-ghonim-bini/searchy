from __future__ import annotations

import ctypes
import errno
import logging
import os
import select
import struct
import threading
import time
from collections.abc import Callable
from pathlib import Path

from .birthtime import creation_time
from .database import IndexedPath, SearchDatabase

LOGGER = logging.getLogger(__name__)

IN_ATTRIB = 0x00000004
IN_CLOSE_WRITE = 0x00000008
IN_MOVED_FROM = 0x00000040
IN_MOVED_TO = 0x00000080
IN_CREATE = 0x00000100
IN_DELETE = 0x00000200
IN_DELETE_SELF = 0x00000400
IN_MOVE_SELF = 0x00000800
IN_Q_OVERFLOW = 0x00004000
IN_IGNORED = 0x00008000
IN_ISDIR = 0x40000000
WATCH_MASK = (
    IN_ATTRIB
    | IN_CLOSE_WRITE
    | IN_MOVED_FROM
    | IN_MOVED_TO
    | IN_CREATE
    | IN_DELETE
    | IN_DELETE_SELF
    | IN_MOVE_SELF
)


class FileIndexer:
    def __init__(
        self,
        database: SearchDatabase,
        roots: tuple[Path, ...],
        excluded_root: Path,
        interval: int,
        on_status: Callable[[str], None],
    ):
        self.database = database
        self.roots = roots
        self.excluded_root = excluded_root.resolve()
        self.interval = interval
        self.on_status = on_status
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, name="searchy-indexer", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3)

    def _run(self) -> None:
        if self.database.index_is_fresh(self.interval):
            count = self.database.count()
            LOGGER.info("Using current index with %s items", count)
            self.on_status(f"{count} items indexed")
        else:
            self._reconcile()
        while not self.stop_event.is_set():
            try:
                folder_count = self.database.folder_count()
                watch_limit = _inotify_watch_limit()
                if folder_count < watch_limit:
                    watcher = _InotifyWatcher(
                        self.roots,
                        self.excluded_root,
                        self.database,
                        self.stop_event,
                    )
                    watcher.watch_until(time.monotonic() + self.interval)
                else:
                    LOGGER.warning(
                        "Index has %s folders, above inotify limit %s; "
                        "using periodic reconciliation",
                        folder_count,
                        watch_limit,
                    )
                    self.stop_event.wait(self.interval)
                if not self.stop_event.is_set():
                    self._reconcile()
            except Exception:
                LOGGER.exception("Indexer cycle failed")
                self.on_status("Index update failed; retrying")
                self.stop_event.wait(min(self.interval, 30))

    def _reconcile(self) -> None:
        started_at = time.monotonic()
        LOGGER.info("Starting filesystem index reconciliation")
        self.on_status("Indexing files...")
        generation = self.database.next_generation()
        batch: list[IndexedPath] = []
        for root in self.roots:
            if not root.exists():
                LOGGER.warning("Search root does not exist: %s", root)
                continue
            for entry in self._walk(root):
                if self.stop_event.is_set():
                    return
                batch.append(entry)
                if len(batch) >= 500:
                    self.database.upsert_many(batch, generation)
                    batch.clear()
        self.database.upsert_many(batch, generation)
        if self.stop_event.is_set():
            return
        self.database.finish_generation(generation, self.roots)
        count = self.database.count()
        duration = time.monotonic() - started_at
        LOGGER.info(
            "Filesystem index reconciliation completed: items=%s duration_seconds=%.1f",
            count,
            duration,
        )
        self.on_status(f"{count} items indexed")

    def _walk(self, root: Path):
        pending = [root]
        while pending:
            directory = pending.pop()
            if _is_excluded(directory, self.excluded_root):
                continue
            indexed = _metadata(directory)
            if indexed:
                yield indexed
            try:
                with os.scandir(directory) as iterator:
                    children = list(iterator)
            except (OSError, PermissionError):
                continue
            for child in children:
                path = Path(child.path)
                if _is_excluded(path, self.excluded_root):
                    continue
                try:
                    if child.is_dir(follow_symlinks=False):
                        pending.append(path)
                    else:
                        indexed = _metadata(path)
                        if indexed:
                            yield indexed
                except OSError:
                    continue


class _InotifyWatcher:
    def __init__(
        self,
        roots: tuple[Path, ...],
        excluded_root: Path,
        database: SearchDatabase,
        stop_event: threading.Event,
    ):
        self.roots = roots
        self.excluded_root = excluded_root
        self.database = database
        self.stop_event = stop_event
        self.paths: dict[int, Path] = {}
        self.libc = ctypes.CDLL(None, use_errno=True)
        self.fd = self.libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        if self.fd < 0:
            raise OSError(ctypes.get_errno(), "inotify_init1 failed")
        for root in roots:
            self._add_tree(root)

    def watch_until(self, deadline: float) -> None:
        try:
            while not self.stop_event.is_set() and time.monotonic() < deadline:
                readable, _, _ = select.select([self.fd], [], [], 1.0)
                if readable and not self._read_events():
                    return
        finally:
            os.close(self.fd)

    def _add_tree(self, root: Path) -> None:
        for directory, subdirectories, _files in os.walk(root, followlinks=False):
            path = Path(directory)
            subdirectories[:] = [
                name
                for name in subdirectories
                if not _is_excluded(path / name, self.excluded_root)
            ]
            if _is_excluded(path, self.excluded_root):
                continue
            wd = self.libc.inotify_add_watch(
                self.fd, os.fsencode(path), ctypes.c_uint32(WATCH_MASK)
            )
            if wd < 0:
                error = ctypes.get_errno()
                if error in {errno.ENOSPC, errno.EMFILE}:
                    LOGGER.warning("Inotify limit reached; relying on periodic reconciliation")
                    return
                continue
            self.paths[wd] = path

    def _read_events(self) -> bool:
        try:
            data = os.read(self.fd, 1024 * 256)
        except BlockingIOError:
            return True
        offset = 0
        while offset < len(data):
            wd, mask, _cookie, name_length = struct.unpack_from("iIII", data, offset)
            offset += 16
            raw_name = data[offset : offset + name_length].split(b"\0", 1)[0]
            offset += name_length
            if mask & IN_Q_OVERFLOW:
                LOGGER.warning("Inotify queue overflowed; starting reconciliation")
                return False
            directory = self.paths.get(wd)
            if directory is None:
                continue
            path = directory / os.fsdecode(raw_name) if raw_name else directory
            if mask & (IN_DELETE | IN_MOVED_FROM | IN_DELETE_SELF | IN_MOVE_SELF):
                self.database.delete_path(path)
            if mask & (IN_CREATE | IN_MOVED_TO | IN_CLOSE_WRITE | IN_ATTRIB):
                indexed = _metadata(path)
                if indexed:
                    self.database.upsert(indexed)
                if mask & IN_ISDIR and mask & (IN_CREATE | IN_MOVED_TO):
                    self._add_tree(path)
            if mask & IN_IGNORED:
                self.paths.pop(wd, None)
        return True


def _metadata(path: Path) -> IndexedPath | None:
    try:
        stat = path.stat(follow_symlinks=False)
        kind = "folder" if path.is_dir() and not path.is_symlink() else "file"
        return IndexedPath(path, kind, creation_time(path), stat.st_mtime)
    except (OSError, PermissionError):
        return None


def _is_excluded(path: Path, excluded_root: Path) -> bool:
    try:
        path.resolve().relative_to(excluded_root)
        return True
    except (ValueError, OSError):
        return False


def _inotify_watch_limit() -> int:
    try:
        return int(Path("/proc/sys/fs/inotify/max_user_watches").read_text().strip())
    except (OSError, ValueError):
        return 65536
