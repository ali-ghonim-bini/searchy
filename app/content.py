from __future__ import annotations

import logging
import os
import select
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

from .models import SearchResult
from .query import Query

LOGGER = logging.getLogger(__name__)
MIN_CONTENT_LENGTH = 3
TIME_LIMIT_SECONDS = 15
# Large files are rarely documents, and reading them makes every search slow.
MAX_FILE_SIZE = "2M"
EXCERPT_LENGTH = 90


def content_command(
    text: str,
    roots: tuple[Path, ...],
    exclude_names: tuple[str, ...],
    extensions: tuple[str, ...],
    index_hidden: bool,
    which: Callable[[str], str | None] = shutil.which,
) -> list[str] | None:
    """The ripgrep call that lists files containing `text`, with the matching line."""
    executable = which("rg")
    if executable is None:
        return None
    command = [
        executable, "--fixed-strings", "--ignore-case", "--max-count", "1",
        "--line-number", "--no-heading", "--null", "--no-messages", "--color", "never",
        "--max-filesize", MAX_FILE_SIZE, "--max-columns", "300",
    ]
    if index_hidden:
        command.append("--hidden")
    for name in exclude_names:
        command += ["--glob", f"!{name}"]
    for extension in extensions:
        command += ["--glob", f"*.{extension}"]
    return [*command, "--", text, *(str(root) for root in roots)]


def parse_match(line: bytes) -> tuple[Path, int, str] | None:
    """Split one `path NUL line-number:text` record."""
    path, separator, rest = line.partition(b"\0")
    number, colon, text = rest.partition(b":")
    if not separator or not colon or not number.isdigit():
        return None
    excerpt = " ".join(text.decode("utf-8", "replace").split())
    return Path(os.fsdecode(path)), int(number), excerpt[:EXCERPT_LENGTH]


def matches_query(path: Path, query: Query) -> bool:
    """Apply the words and filters that ripgrep was not asked to check."""
    folded = str(path).casefold()
    if not all(token in folded for token in query.tokens):
        return False
    parent = str(path.parent).casefold()
    if not all("/" + folder in parent for folder in query.folders):
        return False
    if query.has_size_filter or query.modified_after or query.modified_before:
        try:
            stat = path.stat()
        except OSError:
            return False
        if query.min_size is not None and stat.st_size < query.min_size:
            return False
        if query.max_size is not None and stat.st_size > query.max_size:
            return False
        if query.modified_after is not None and stat.st_mtime < query.modified_after:
            return False
        if query.modified_before is not None and stat.st_mtime >= query.modified_before:
            return False
    return True


def search_content(
    query: Query,
    roots: tuple[Path, ...],
    exclude_names: tuple[str, ...],
    index_hidden: bool,
    limit: int,
    cancel_event: threading.Event | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> list[SearchResult]:
    """Files under the search roots whose text contains `query.content`."""
    text = query.content or ""
    if len(text) < MIN_CONTENT_LENGTH or query.kind in {"app", "folder"}:
        return []
    command = content_command(text, roots, exclude_names, query.extensions, index_hidden, which)
    if command is None:
        LOGGER.warning("Content search needs ripgrep (rg), which is not installed")
        return []
    results: list[SearchResult] = []
    deadline = time.monotonic() + TIME_LIMIT_SECONDS
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL
    )
    try:
        pending = b""
        while len(results) < limit and time.monotonic() < deadline:
            if cancel_event and cancel_event.is_set():
                return []
            readable, _, _ = select.select([process.stdout], [], [], 0.2)
            if not readable:
                continue
            chunk = os.read(process.stdout.fileno(), 65536)
            if not chunk:
                break
            pending += chunk
            *lines, pending = pending.split(b"\n")
            for line in lines:
                match = parse_match(line)
                if match is None or not matches_query(match[0], query):
                    continue
                path, number, excerpt = match
                results.append(
                    SearchResult(
                        kind="file",
                        name=path.name,
                        detail=f"{path.parent}  |  line {number}: {excerpt}",
                        created_at=None,
                        path=path,
                        source_path=path,
                    )
                )
                if len(results) >= limit:
                    break
    finally:
        # Stop reading the disk as soon as enough was found or the search was replaced.
        process.kill()
        process.wait()
        process.stdout.close()
    return results
