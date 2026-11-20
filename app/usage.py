from __future__ import annotations

import logging
import os
import sqlite3
import time
from pathlib import Path

from .models import SearchResult

LOGGER = logging.getLogger(__name__)
# An item opened a month ago counts half as much as one opened today.
HALF_LIFE_SECONDS = 30 * 86400


def usage_key(result: SearchResult) -> str | None:
    if result.kind == "app" and result.payload is not None:
        return "app:" + (result.payload.get_id() or result.name)
    if result.kind in {"file", "folder"} and result.path is not None:
        return str(result.path)
    return None


class UsageStore:
    """Remembers what was opened so frequent results can rank first."""

    def __init__(self, path: Path | None):
        self.path = path
        self.entries: dict[str, tuple[float, float]] = {}
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS usage ("
                "key TEXT PRIMARY KEY, weight REAL NOT NULL, used_at REAL NOT NULL)"
            )
            for key, weight, used_at in connection.execute(
                "SELECT key, weight, used_at FROM usage"
            ):
                self.entries[key] = (weight, used_at)
        # The file lists what the user opens; keep it private.
        os.chmod(path, 0o600)

    def _connection(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5)

    def record(self, result: SearchResult, now: float | None = None) -> None:
        key = usage_key(result)
        if key is None or self.path is None:
            return
        now = time.time() if now is None else now
        weight = self._decayed(key, now) + 1.0
        self.entries[key] = (weight, now)
        try:
            with self._connection() as connection:
                connection.execute(
                    "INSERT INTO usage(key, weight, used_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET weight=excluded.weight, "
                    "used_at=excluded.used_at",
                    (key, weight, now),
                )
        except sqlite3.Error:
            LOGGER.warning("Cannot save usage history", exc_info=True)

    def score(self, result: SearchResult, now: float | None = None) -> float:
        key = usage_key(result)
        if key is None:
            return 0.0
        return self._decayed(key, time.time() if now is None else now)

    def _decayed(self, key: str, now: float) -> float:
        entry = self.entries.get(key)
        if entry is None:
            return 0.0
        weight, used_at = entry
        return weight * 0.5 ** (max(0.0, now - used_at) / HALF_LIFE_SECONDS)
