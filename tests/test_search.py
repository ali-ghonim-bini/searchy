from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.database import IndexedPath, SearchDatabase
from app.models import SearchResult
from app.ranking import NO_MATCH, is_indexable, name_tier, sort_key, tokenize


class RankingTests(unittest.TestCase):
    def test_tiers_order_better_matches_first(self) -> None:
        tiers = [
            name_tier("report.pdf", ["report"]),
            name_tier("report-final.pdf", ["report"]),
            name_tier("annual report.pdf", ["report"]),
            name_tier("myreports.pdf", ["report"]),
        ]
        self.assertEqual(tiers, sorted(tiers))
        self.assertEqual(len(set(tiers)), 4)

    def test_words_match_in_any_order(self) -> None:
        self.assertLess(name_tier("Annual Report 2024.pdf", ["2024", "report"]), NO_MATCH)
        self.assertEqual(name_tier("Annual Report.pdf", ["2024", "report"]), NO_MATCH)

    def test_initials_and_fuzzy_match_single_words(self) -> None:
        self.assertEqual(name_tier("Visual Studio Code", ["vsc"]), 4)
        self.assertEqual(name_tier("Firefox", ["frfx"]), 5)
        self.assertEqual(name_tier("Firefox", ["xyz"]), NO_MATCH)

    def test_indexable_needs_one_long_word(self) -> None:
        self.assertFalse(is_indexable("ab cd"))
        self.assertTrue(is_indexable("ab cde"))

    def test_hidden_paths_sort_last_within_a_tier(self) -> None:
        visible = SearchResult("file", "notes.txt", "", None, Path("/home/u/notes.txt"))
        hidden = SearchResult("file", "notes.txt", "", None, Path("/home/u/.cache/notes.txt"))
        tokens = tokenize("notes")
        self.assertLess(sort_key(visible, tokens), sort_key(hidden, tokens))


class DatabaseSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = SearchDatabase(Path(self.directory.name) / "index.sqlite3")
        paths = [
            ("/home/u/Documents/invoices/march 2024.pdf", "file"),
            ("/home/u/Documents/invoices", "folder"),
            ("/home/u/Documents/Annual Report 2024.pdf", "file"),
            ("/home/u/Documents/report.pdf", "file"),
            ("/home/u/.cache/app/report.pdf", "file"),
            ("/home/u/Pictures/holiday.jpg", "file"),
        ]
        self.database.upsert_many(
            (IndexedPath(Path(path), kind, None, 1.0) for path, kind in paths), 1
        )

    def names(self, query: str, kind: str | None = None) -> list[str]:
        return [str(result.path) for result in self.database.search(query, 50, kind)]

    def test_words_match_in_any_order(self) -> None:
        self.assertEqual(
            self.names("2024 report"), ["/home/u/Documents/Annual Report 2024.pdf"]
        )

    def test_word_can_match_a_parent_folder(self) -> None:
        self.assertIn("/home/u/Documents/invoices/march 2024.pdf", self.names("invoices march"))

    def test_short_word_filters_names(self) -> None:
        self.assertEqual(self.names("holiday jp"), ["/home/u/Pictures/holiday.jpg"])
        self.assertEqual(self.names("holiday zz"), [])

    def test_hidden_directories_rank_after_visible_ones(self) -> None:
        # Both are exact name matches, so only the hidden directory separates them.
        self.assertEqual(
            self.names("report", "file")[:2],
            ["/home/u/Documents/report.pdf", "/home/u/.cache/app/report.pdf"],
        )

    def test_kind_filter_and_special_characters(self) -> None:
        self.assertEqual(self.names("invoices", "folder"), ["/home/u/Documents/invoices"])
        self.assertEqual(self.names('rep"ort 100%'), [])


if __name__ == "__main__":
    unittest.main()
