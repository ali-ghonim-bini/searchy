from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path

LOGGER = logging.getLogger(__name__)
# Where desktop sessions mount removable drives for the logged-in user.
_MOUNT_PARENTS = ("/media", "/run/media")


def is_removable_path(path: Path, user: str | None = None) -> bool:
    """Whether `path` is where a desktop session mounts a removable drive."""
    user = user or os.environ.get("USER", "")
    parts = path.parts
    for parent in _MOUNT_PARENTS:
        prefix = Path(parent).parts
        if parts[: len(prefix)] == prefix and len(parts) == len(prefix) + 2:
            return bool(user) and parts[len(prefix)] == user
    return False


class DriveMonitor:
    """Tells the indexer when removable drives are mounted and unmounted."""

    def __init__(self, on_added: Callable[[Path], object], on_removed: Callable[[Path], object]):
        from gi.repository import Gio

        self.on_added = on_added
        self.on_removed = on_removed
        # Keep a reference: the monitor stops emitting once it is collected.
        self.monitor = Gio.VolumeMonitor.get()
        self.monitor.connect("mount-added", lambda _monitor, mount: self._changed(mount, True))
        self.monitor.connect("mount-removed", lambda _monitor, mount: self._changed(mount, False))
        for mount in self.monitor.get_mounts():
            self._changed(mount, True)

    def _changed(self, mount, added: bool) -> None:
        location = mount.get_root().get_path()
        if not location:
            return
        path = Path(location)
        if not is_removable_path(path):
            return
        LOGGER.info("Removable drive %s", "mounted" if added else "unmounted")
        (self.on_added if added else self.on_removed)(path)
