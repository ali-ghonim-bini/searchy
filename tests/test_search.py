from __future__ import annotations

import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

from app.database import IndexedPath, SearchDatabase
from app.models import SearchResult
from app.query import parse_query
from app.ranking import NO_MATCH, match_spans, name_tier, sort_key, tokenize


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
        self.assertFalse(parse_query("ab cd").searches_files)
        self.assertTrue(parse_query("ab cde").searches_files)

    def test_hidden_paths_sort_last_within_a_tier(self) -> None:
        visible = SearchResult("file", "notes.txt", "", None, Path("/home/u/notes.txt"))
        hidden = SearchResult("file", "notes.txt", "", None, Path("/home/u/.cache/notes.txt"))
        tokens = tokenize("notes")
        self.assertLess(sort_key(visible, tokens), sort_key(hidden, tokens))


class HighlightTests(unittest.TestCase):
    def test_spans_cover_every_matched_word(self) -> None:
        self.assertEqual(
            match_spans("Annual Report 2024.pdf", ["2024", "report"]), [(7, 13), (14, 18)]
        )

    def test_overlapping_and_repeated_matches_merge(self) -> None:
        self.assertEqual(match_spans("banana", ["ana", "nan"]), [(1, 6)])
        self.assertEqual(match_spans("a-a", ["a"]), [(0, 1), (2, 3)])

    def test_no_match_and_length_changing_names(self) -> None:
        self.assertEqual(match_spans("Firefox", ["frfx"]), [])
        self.assertEqual(match_spans("Straße", ["stra"]), [])


class QueryTests(unittest.TestCase):
    def test_filters_are_separated_from_words(self) -> None:
        query = parse_query("Annual ext:.PDF in:Documents/ kind:files report")
        self.assertEqual(query.tokens, ("annual", "report"))
        self.assertEqual(query.extensions, ("pdf",))
        self.assertEqual(query.folders, ("documents",))
        self.assertEqual(query.kind, "file")

    def test_unknown_or_unfinished_filters(self) -> None:
        self.assertEqual(parse_query("kind:banana").tokens, ("kind:banana",))
        self.assertEqual(parse_query("ext: in:").extensions, ())
        self.assertFalse(parse_query("ext:").searches_files)
        self.assertEqual(parse_query("12:30").tokens, ("12:30",))

    def test_quotes_group_words(self) -> None:
        query = parse_query('in:"My Documents" "annual report" ext:pdf')
        self.assertEqual(query.folders, ("my documents",))
        self.assertEqual(query.tokens, ("annual report",))
        self.assertEqual(query.extensions, ("pdf",))

    def test_unfinished_quote_is_tolerated(self) -> None:
        self.assertEqual(parse_query('"annual rep').tokens, ("annual rep",))
        self.assertEqual(parse_query('in:"my doc').folders, ("my doc",))
        self.assertEqual(parse_query('""').tokens, ())

    def test_size_filter(self) -> None:
        self.assertEqual(parse_query("size:>100mb").min_size, 100_000_000)
        self.assertEqual(parse_query("size:1.5gb").min_size, 1_500_000_000)
        self.assertEqual(parse_query("size:<10kb").max_size, 10_000)
        both = parse_query("size:>1mb size:<2mb")
        self.assertEqual((both.min_size, both.max_size), (1_000_000, 2_000_000))
        self.assertEqual(parse_query("size:huge").tokens, ("size:huge",))
        self.assertTrue(parse_query("size:>1gb").searches_files)

    def test_modified_filter(self) -> None:
        now = datetime(2026, 5, 10, 15, 30).timestamp()
        midnight = datetime(2026, 5, 10).timestamp()
        self.assertEqual(parse_query("modified:today", now).modified_after, midnight)
        yesterday = parse_query("modified:yesterday", now)
        self.assertEqual(
            (yesterday.modified_after, yesterday.modified_before), (midnight - 86400, midnight)
        )
        self.assertEqual(parse_query("modified:<7d", now).modified_after, now - 7 * 86400)
        self.assertEqual(parse_query("modified:>1y", now).modified_before, now - 365 * 86400)
        self.assertEqual(parse_query("modified:soon", now).tokens, ("modified:soon",))

    def test_filter_alone_can_search_files(self) -> None:
        self.assertTrue(parse_query("ext:pdf").searches_files)
        self.assertFalse(parse_query("kind:file ab").searches_files)


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

    def test_extension_filter(self) -> None:
        self.assertEqual(self.names("ext:jpg"), ["/home/u/Pictures/holiday.jpg"])
        self.assertEqual(self.names("report ext:jpg"), [])
        self.assertEqual(len(self.names("ext:jpg,pdf")), 5)

    def test_folder_filter(self) -> None:
        self.assertEqual(
            self.names("ext:pdf in:invoices"), ["/home/u/Documents/invoices/march 2024.pdf"]
        )
        self.assertEqual(self.names("report in:pict"), [])
        self.assertNotIn("/home/u/.cache/app/report.pdf", self.names("report in:doc"))

    def test_kind_filter_in_the_query(self) -> None:
        self.assertEqual(self.names("invoices kind:folder"), ["/home/u/Documents/invoices"])
        self.assertEqual(self.names("invoices kind:app"), [])

    def test_filter_does_not_list_unfiltered_folder_contents(self) -> None:
        self.assertEqual(self.names("invoices ext:jpg"), [])

    def test_quoted_phrase_must_be_contiguous(self) -> None:
        self.assertEqual(
            self.names('"report 2024"'), ["/home/u/Documents/Annual Report 2024.pdf"]
        )
        self.assertEqual(self.names('"2024 report"'), [])

    def test_folder_filter_with_spaces(self) -> None:
        self.database.upsert_many(
            [IndexedPath(Path("/home/u/My Documents/plan.txt"), "file", None, 1.0)], 1
        )
        self.assertEqual(self.names('plan in:"my documents"'), ["/home/u/My Documents/plan.txt"])
        self.assertEqual(self.names('plan in:"my pictures"'), [])

    def test_size_and_date_filters_select_files(self) -> None:
        now = time.time()
        self.database.upsert_many(
            [
                IndexedPath(Path("/home/u/big.iso"), "file", None, now - 40 * 86400, 2_000_000_000),
                IndexedPath(Path("/home/u/small.txt"), "file", None, now - 3600, 500),
                IndexedPath(Path("/home/u/bigdir"), "folder", None, now - 3600, None),
            ],
            1,
        )
        self.assertEqual(self.names("size:>1gb"), ["/home/u/big.iso"])
        self.assertEqual(self.names("size:<1kb"), ["/home/u/small.txt"])
        self.assertEqual(self.names("big modified:<1d"), ["/home/u/bigdir"])
        self.assertEqual(self.names("big modified:>30d"), ["/home/u/big.iso"])
        self.assertEqual(self.database.search("size:>1gb", 5)[0].size, 2_000_000_000)

    def test_kind_filter_and_special_characters(self) -> None:
        self.assertEqual(self.names("invoices", "folder"), ["/home/u/Documents/invoices"])
        self.assertEqual(self.names('rep"ort 100%'), [])


if __name__ == "__main__":
    unittest.main()
