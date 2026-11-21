from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.actions import rename_target, terminal_command, terminal_directory


class ActionTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        (self.root / "a.txt").write_text("a", encoding="utf-8")
        (self.root / "b.txt").write_text("b", encoding="utf-8")

    def test_rename_target(self) -> None:
        path = self.root / "a.txt"
        self.assertEqual(rename_target(path, "  c.txt "), self.root / "c.txt")
        for bad in ("", "   ", "x/y.txt", "..", "a.txt", "b.txt"):
            with self.assertRaises(ValueError, msg=bad):
                rename_target(path, bad)

    def test_terminal_uses_the_first_one_installed(self) -> None:
        installed = {"gnome-terminal": "/usr/bin/gnome-terminal", "konsole": "/usr/bin/konsole"}
        self.assertEqual(
            terminal_command(Path("/home/u/My Docs"), installed.get),
            ["/usr/bin/gnome-terminal", "--working-directory=/home/u/My Docs"],
        )
        self.assertEqual(
            terminal_command(Path("/x"), {"x-terminal-emulator": "/usr/bin/xte"}.get),
            ["/usr/bin/xte"],
        )
        self.assertIsNone(terminal_command(Path("/x"), {}.get))

    def test_terminal_opens_in_a_files_folder(self) -> None:
        self.assertEqual(terminal_directory(self.root / "a.txt"), self.root)
        self.assertEqual(terminal_directory(self.root), self.root)


if __name__ == "__main__":
    unittest.main()
