from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.bookmarks import BookmarkCatalog, load_bookmarks


class BookmarkTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name)
        chrome = self.home / ".config/google-chrome/Default"
        chrome.mkdir(parents=True)
        tree = {
            "roots": {
                "bookmark_bar": {
                    "type": "folder",
                    "children": [
                        {"type": "url", "name": "Python Docs", "url": "https://docs.python.org/"},
                        {
                            "type": "folder",
                            "children": [
                                {"type": "url", "name": "", "url": "https://example.org/nested"},
                                {"type": "url", "name": "Local", "url": "file:///etc/hosts"},
                            ],
                        },
                    ],
                },
                "sync_transaction_version": "7",
            }
        }
        (chrome / "Bookmarks").write_text(json.dumps(tree), encoding="utf-8")
        firefox = self.home / ".mozilla/firefox/abc.default"
        firefox.mkdir(parents=True)
        connection = sqlite3.connect(firefox / "places.sqlite")
        connection.executescript(
            """
            CREATE TABLE moz_places (id INTEGER PRIMARY KEY, url TEXT);
            CREATE TABLE moz_bookmarks (id INTEGER PRIMARY KEY, type INTEGER, fk INTEGER, title TEXT);
            INSERT INTO moz_places VALUES (1, 'https://www.rust-lang.org/'), (2, 'https://docs.python.org/');
            INSERT INTO moz_bookmarks VALUES (1, 1, 1, 'Rust Language'), (2, 2, NULL, 'A Folder'),
                                             (3, 1, 2, 'Python again');
            """
        )
        connection.commit()
        connection.close()
        (self.home / ".config/chromium/Default").mkdir(parents=True)
        (self.home / ".config/chromium/Default/Bookmarks").write_text("{broken", encoding="utf-8")

    def test_loads_every_browser_once_and_only_web_addresses(self) -> None:
        found = {bookmark.url: bookmark.title for bookmark in load_bookmarks(self.home)}
        self.assertEqual(
            found,
            {
                "https://docs.python.org/": "Python Docs",
                "https://example.org/nested": "https://example.org/nested",
                "https://www.rust-lang.org/": "Rust Language",
            },
        )

    def test_search_matches_title_or_address(self) -> None:
        catalog = BookmarkCatalog(self.home)
        self.assertEqual([r.name for r in catalog.search(["rust"], 5)], ["Rust Language"])
        self.assertEqual([r.payload for r in catalog.search(["nested"], 5)], ["https://example.org/nested"])
        self.assertEqual(catalog.search(["zzqx"], 5), [])
        self.assertEqual(catalog.search([], 5), [])
        result = catalog.search(["python"], 5)[0]
        self.assertEqual((result.kind, result.detail), ("bookmark", "https://docs.python.org/"))

    def test_no_browsers_installed(self) -> None:
        with tempfile.TemporaryDirectory() as empty:
            self.assertEqual(BookmarkCatalog(Path(empty)).search(["x"], 5), [])


if __name__ == "__main__":
    unittest.main()
