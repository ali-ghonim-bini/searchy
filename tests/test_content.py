from __future__ import annotations

import shutil
import tempfile
import threading
import unittest
from pathlib import Path

from app.content import content_command, matches_query, parse_match, search_content
from app.query import parse_query


class ContentCommandTests(unittest.TestCase):
    def test_command_carries_excludes_and_extensions(self) -> None:
        command = content_command(
            "due date", (Path("/home/u"),), ("node_modules",), ("md", "txt"), False,
            {"rg": "/usr/bin/rg"}.get,
        )
        self.assertEqual(command[0], "/usr/bin/rg")
        self.assertEqual(command[-3:], ["--", "due date", "/home/u"])
        for expected in ("!node_modules", "*.md", "*.txt", "--fixed-strings"):
            self.assertIn(expected, command)
        self.assertNotIn("--hidden", command)
        self.assertIsNone(content_command("x", (), (), (), False, {}.get))

    def test_text_starting_with_a_dash_is_not_an_option(self) -> None:
        command = content_command("--version", (Path("/r"),), (), (), True, {"rg": "rg"}.get)
        self.assertLess(command.index("--"), command.index("--version"))
        self.assertIn("--hidden", command)

    def test_parse_match(self) -> None:
        self.assertEqual(
            parse_match(b"/home/u/a:b.txt\x0012:  due   date: friday"),
            (Path("/home/u/a:b.txt"), 12, "due date: friday"),
        )
        self.assertIsNone(parse_match(b"garbage"))

    def test_remaining_words_and_filters(self) -> None:
        path = Path("/home/u/Documents/notes/todo.md")
        self.assertTrue(matches_query(path, parse_query("content:x todo in:doc")))
        self.assertFalse(matches_query(path, parse_query("content:x report")))
        self.assertFalse(matches_query(path, parse_query("content:x in:pictures")))


@unittest.skipUnless(shutil.which("rg"), "needs ripgrep")
class ContentSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        files = {
            "docs/plan.md": "Budget\nThe Due Date is Friday\n",
            "docs/other.txt": "nothing relevant\n",
            ".secret/hidden.md": "due date hidden\n",
            "node_modules/pkg/readme.md": "due date in a dependency\n",
            "data.bin": "due date\x00\x01binary",
        }
        for name, text in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    def search(self, text: str, hidden: bool = False, cancel=None) -> list:
        return search_content(
            parse_query(text), (self.root,), ("node_modules",), hidden, 50, cancel
        )

    def test_finds_text_ignoring_case_and_shows_the_line(self) -> None:
        results = self.search('content:"due date"')
        self.assertEqual([r.name for r in results], ["plan.md"])
        self.assertTrue(results[0].detail.endswith("line 2: The Due Date is Friday"))

    def test_hidden_only_when_enabled_and_excludes_always_skipped(self) -> None:
        names = sorted(r.name for r in self.search('content:"due date"', hidden=True))
        self.assertEqual(names, ["hidden.md", "plan.md"])

    def test_filters_and_limits(self) -> None:
        self.assertEqual(self.search('content:"due date" ext:txt'), [])
        self.assertEqual(self.search("content:du"), [])
        self.assertEqual(self.search('content:"due date" kind:folder'), [])
        cancelled = threading.Event()
        cancelled.set()
        self.assertEqual(self.search('content:"due date"', cancel=cancelled), [])


if __name__ == "__main__":
    unittest.main()
