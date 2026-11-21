from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from .models import SearchResult
from .ranking import NO_MATCH, name_tier

LOGGER = logging.getLogger(__name__)
REFRESH_SECONDS = 300
# Profile folders of Chromium-based browsers, relative to the home directory.
_CHROMIUM_DIRECTORIES = (
    ".config/google-chrome", ".config/chromium", ".config/BraveSoftware/Brave-Browser",
    ".config/microsoft-edge", ".config/vivaldi", ".config/opera",
    "snap/chromium/common/chromium",
)
_FIREFOX_DIRECTORIES = (".mozilla/firefox", "snap/firefox/common/.mozilla/firefox")


@dataclass(frozen=True)
class Bookmark:
    title: str
    url: str


def chromium_bookmarks(file: Path) -> list[Bookmark]:
    """Bookmarks from one Chromium-format `Bookmarks` JSON file."""
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    found: list[Bookmark] = []
    pending = list(data.get("roots", {}).values()) if isinstance(data, dict) else []
    while pending:
        node = pending.pop()
        if not isinstance(node, dict):
            continue
        if node.get("type") == "url" and isinstance(node.get("url"), str):
            found.append(Bookmark(str(node.get("name") or node["url"]), node["url"]))
        pending.extend(node.get("children") or [])
    return found


def firefox_bookmarks(file: Path) -> list[Bookmark]:
    """Bookmarks from one Firefox `places.sqlite`, read without locking it."""
    try:
        # Firefox keeps the file locked while it runs; immutable mode only reads.
        connection = sqlite3.connect(f"file:{file}?mode=ro&immutable=1", uri=True, timeout=2)
    except sqlite3.Error:
        return []
    try:
        rows = connection.execute(
            "SELECT b.title, p.url FROM moz_bookmarks b "
            "JOIN moz_places p ON p.id = b.fk WHERE b.type = 1"
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        connection.close()
    return [Bookmark(title or url, url) for title, url in rows if url]


def load_bookmarks(home: Path) -> list[Bookmark]:
    """Every web bookmark found in the browsers' profile folders, without duplicates."""
    found: list[Bookmark] = []
    for directory in _CHROMIUM_DIRECTORIES:
        for file in sorted((home / directory).glob("*/Bookmarks")) + [home / directory / "Bookmarks"]:
            found.extend(chromium_bookmarks(file))
    for directory in _FIREFOX_DIRECTORIES:
        for file in sorted((home / directory).glob("*/places.sqlite")):
            found.extend(firefox_bookmarks(file))
    unique: dict[str, Bookmark] = {}
    for bookmark in found:
        if bookmark.url.startswith(("http://", "https://")):
            unique.setdefault(bookmark.url, bookmark)
    return list(unique.values())


class BookmarkCatalog:
    """Browser bookmarks, reread from disk every few minutes."""

    def __init__(self, home: Path | None = None):
        self.home = home or Path.home()
        self.bookmarks: list[Bookmark] = []
        self.loaded_at = 0.0

    def _refresh(self) -> None:
        if time.monotonic() - self.loaded_at < REFRESH_SECONDS and self.loaded_at:
            return
        try:
            self.bookmarks = load_bookmarks(self.home)
        except Exception:
            # Bookmark titles and addresses are private: log the failure only.
            LOGGER.warning("Cannot read browser bookmarks")
        self.loaded_at = time.monotonic()

    def search(self, tokens: list[str], limit: int) -> list[SearchResult]:
        if not tokens:
            return []
        self._refresh()
        ranked = []
        for bookmark in self.bookmarks:
            tier = name_tier(bookmark.title, tokens)
            if tier == NO_MATCH:
                haystack = (bookmark.title + " " + bookmark.url).casefold()
                if not all(token in haystack for token in tokens):
                    continue
            ranked.append((tier, len(bookmark.title), bookmark.title.casefold(), bookmark))
        ranked.sort(key=lambda item: item[:3])
        return [
            SearchResult(
                kind="bookmark",
                name=bookmark.title,
                detail=bookmark.url,
                created_at=None,
                payload=bookmark.url,
            )
            for _tier, _length, _name, bookmark in ranked[:limit]
        ]
