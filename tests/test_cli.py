from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from app.cli import status_lines
from app.config import Config
from app.database import IndexedPath, SearchDatabase
from app.excludes import PathFilter
from app.indexer import FileIndexer


class StatusTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        env_file = self.directory / ".env"
        env_file.write_text(
            f"SEARCH_ROOTS={self.directory}\nDATABASE_PATH={self.directory}/state/index.sqlite3\n",
            encoding="utf-8",
        )
        self.config = Config.load(env_file)

    def test_missing_index(self) -> None:
        self.assertEqual(
            status_lines(self.config, "inactive"),
            ["Service:        inactive", "Index:          not built yet"],
        )

    def test_reports_counts_and_last_scan(self) -> None:
        database = SearchDatabase(self.config.database_path)
        database.upsert_many(
            [
                IndexedPath(self.directory / "docs", "folder", None, 1.0),
                IndexedPath(self.directory / "docs/a.txt", "file", None, 1.0),
            ],
            1,
        )
        text = "\n".join(status_lines(self.config, "active"))
        self.assertIn("Indexed items:  2 (1 folders)", text)
        self.assertIn("first scan has not finished", text)
        database.finish_generation(1, (self.directory,))
        text = "\n".join(status_lines(self.config, "active", now=time.time() + 7200))
        self.assertIn("(2 h ago)", text)
        self.assertIn("Live updates:   on", text)


class ReindexTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve() / "home"
        state = Path(directory.name).resolve() / "state"
        (self.root / "docs").mkdir(parents=True)
        (self.root / "docs/a.txt").write_text("x", encoding="utf-8")
        state.mkdir()
        self.database = SearchDatabase(state / "index.sqlite3")
        self.database.set_index_rules("rules")
        self.indexer = FileIndexer(
            self.database, (self.root,), PathFilter.create(state, (), False), 3600,
            lambda message: None,
        )
        self.addCleanup(self.indexer.stop)

    def wait_for(self, condition) -> bool:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if condition():
                return True
            time.sleep(0.05)
        return False

    def test_rebuild_request_discards_stale_entries_and_keeps_rules(self) -> None:
        self.indexer.start()
        self.assertTrue(self.wait_for(lambda: self.database.last_completed_at() is not None))
        # An entry outside the roots is never cleaned up by an ordinary rescan.
        stale = IndexedPath(Path("/elsewhere/stale.txt"), "file", None, 1.0)
        self.database.upsert_many([stale], 1, track_scan=False)
        self.assertEqual(len(self.database.search("stale", 5)), 1)
        self.indexer.request_reindex(rebuild=True)
        self.assertTrue(self.wait_for(lambda: not self.database.search("stale", 5)))
        self.assertTrue(self.wait_for(lambda: self.database.count() == 3))
        self.assertEqual(self.database.index_rules(), "rules")

    def test_reindex_request_runs_a_new_scan(self) -> None:
        self.indexer.start()
        self.assertTrue(self.wait_for(lambda: self.database.last_completed_at() is not None))
        first = self.database.last_completed_at()
        self.indexer.request_reindex()
        self.assertTrue(self.wait_for(lambda: self.database.last_completed_at() != first))


if __name__ == "__main__":
    unittest.main()
