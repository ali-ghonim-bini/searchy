from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.config import Config
from app.database import IndexedPath, SearchDatabase
from app.excludes import PathFilter
from app.indexer import FileIndexer


class IndexerTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve() / "home"
        self.state = Path(directory.name).resolve() / "state"
        for name in (
            "docs/report.txt",
            "docs/.draft.txt",
            ".cache/blob.bin",
            "project/node_modules/package/index.js",
            "project/main.py",
            "skipped/inner/file.txt",
        ):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x", encoding="utf-8")
        self.state.mkdir()
        self.database = SearchDatabase(self.state / "index.sqlite3")

    def indexed(self, root: Path, patterns: tuple[str, ...], index_hidden: bool) -> set[str]:
        path_filter = PathFilter.create(self.state, patterns, index_hidden)
        indexer = FileIndexer(self.database, (root,), path_filter, 3600, lambda message: None)
        return {str(entry.path.relative_to(root)) for entry in indexer._walk(root)}

    def test_hidden_and_named_directories_are_skipped(self) -> None:
        found = self.indexed(self.root, ("node_modules",), False)
        self.assertEqual(
            found,
            {
                ".", "docs", "docs/report.txt", "docs/.draft.txt", "project",
                "project/main.py", "skipped", "skipped/inner", "skipped/inner/file.txt",
            },
        )

    def test_hidden_directories_can_be_indexed(self) -> None:
        found = self.indexed(self.root, (), True)
        self.assertIn(".cache/blob.bin", found)
        self.assertIn("project/node_modules/package/index.js", found)

    def test_path_pattern_skips_one_directory(self) -> None:
        found = self.indexed(self.root, (str(self.root / "skipped"),), False)
        self.assertNotIn("skipped", found)
        self.assertIn("docs/report.txt", found)

    def test_a_hidden_search_root_is_still_indexed(self) -> None:
        self.assertEqual(self.indexed(self.root / ".cache", (), False), {".", "blob.bin"})

    def test_file_sizes_are_indexed(self) -> None:
        path_filter = PathFilter.create(self.state, (), False)
        indexer = FileIndexer(self.database, (self.root,), path_filter, 3600, lambda m: None)
        sizes = {entry.path.name: entry.size for entry in indexer._walk(self.root)}
        self.assertEqual((sizes["report.txt"], sizes["docs"]), (1, None))

    def test_older_index_gains_the_size_column(self) -> None:
        import sqlite3

        path = self.state / "old.sqlite3"
        SearchDatabase(path)
        connection = sqlite3.connect(path)
        connection.execute("ALTER TABLE entries DROP COLUMN size")
        connection.execute("UPDATE metadata SET value = '3' WHERE key = 'schema_version'")
        connection.commit()
        connection.close()
        upgraded = SearchDatabase(path)
        upgraded.upsert_many([IndexedPath(self.root / "a.bin", "file", None, 1.0, 42)], 1)
        self.assertEqual(upgraded.search("a.bin", 5)[0].size, 42)

    def test_reset_discards_the_index(self) -> None:
        self.database.upsert_many([IndexedPath(self.root / "docs", "folder", None, 1.0)], 1)
        self.database.set_index_rules("old")
        self.database.reset()
        self.assertEqual(self.database.count(), 0)
        self.assertIsNone(self.database.index_rules())


class ConfigTests(unittest.TestCase):
    def load(self, text: str) -> Config:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(text, encoding="utf-8")
            return Config.load(env_file)

    def test_exclude_defaults_skip_dependency_directories(self) -> None:
        config = self.load("")
        self.assertIn("node_modules", config.exclude_patterns)
        self.assertFalse(config.index_hidden)

    def test_exclude_settings_are_read(self) -> None:
        config = self.load("EXCLUDE=build:~/Downloads\nINDEX_HIDDEN=true\n")
        self.assertEqual(config.exclude_patterns, ("build", "~/Downloads"))
        self.assertTrue(config.index_hidden)

    def test_invalid_boolean_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.load("INDEX_HIDDEN=maybe\n")


if __name__ == "__main__":
    unittest.main()
