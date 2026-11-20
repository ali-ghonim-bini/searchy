from __future__ import annotations

import stat
import tempfile
import unittest
from pathlib import Path

from app.models import SearchResult
from app.ranking import sort_key, tokenize
from app.usage import HALF_LIFE_SECONDS, UsageStore


def file_result(name: str) -> SearchResult:
    return SearchResult("file", name, "", None, Path("/home/u") / name)


class UsageTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "usage.sqlite3"

    def test_opened_results_rank_first_within_a_tier(self) -> None:
        store = UsageStore(self.path)
        short, used = file_result("figs.txt"), file_result("figures-2024.txt")
        store.record(used)
        tokens = tokenize("fig")
        ranked = sorted([short, used], key=lambda r: sort_key(r, tokens, store.score(r)))
        self.assertEqual(ranked[0], used)

    def test_better_match_still_beats_usage(self) -> None:
        store = UsageStore(self.path)
        exact, used = file_result("fig"), file_result("figures.txt")
        store.record(used)
        tokens = tokenize("fig")
        ranked = sorted([used, exact], key=lambda r: sort_key(r, tokens, store.score(r)))
        self.assertEqual(ranked[0], exact)

    def test_history_persists_and_decays(self) -> None:
        store = UsageStore(self.path)
        result = file_result("notes.txt")
        store.record(result, now=1000.0)
        store.record(result, now=1000.0)
        reloaded = UsageStore(self.path)
        self.assertAlmostEqual(reloaded.score(result, now=1000.0), 2.0)
        self.assertAlmostEqual(reloaded.score(result, now=1000.0 + HALF_LIFE_SECONDS), 1.0)

    def test_history_file_is_private(self) -> None:
        UsageStore(self.path)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)

    def test_disabled_store_records_nothing(self) -> None:
        store = UsageStore(None)
        result = file_result("notes.txt")
        store.record(result)
        self.assertEqual(store.score(result), 0.0)

    def test_empty_query_lists_most_used_first(self) -> None:
        store = UsageStore(self.path)
        a, b = file_result("alpha"), file_result("beta")
        store.record(b)
        ranked = sorted([a, b], key=lambda r: sort_key(r, [], store.score(r)))
        self.assertEqual(ranked, [b, a])


if __name__ == "__main__":
    unittest.main()
