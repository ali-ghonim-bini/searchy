from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, GLib, Gtk

from app.catalog import ApplicationCatalog
from app.database import SearchDatabase
from app.models import SearchResult
from app.ui import SearchWindow
from app.usage import UsageStore

HAS_DISPLAY = Gdk.Display.get_default() is not None


def file_result(name: str) -> SearchResult:
    path = Path("/home/u") / name
    return SearchResult("file", name, "/home/u", None, path, path)


@unittest.skipUnless(HAS_DISPLAY, "needs a graphical session")
class KeyboardTests(unittest.TestCase):
    def setUp(self) -> None:
        Adw.init()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        database = SearchDatabase(Path(directory.name) / "index.sqlite3")
        self.window = SearchWindow(
            None, database, ApplicationCatalog(), UsageStore(None), 50, "everything"
        )
        self.addCleanup(self.window.shutdown)
        self.opened: list[str] = []
        self.revealed: list[str] = []
        self.window._open_result = lambda result, popover=None: self.opened.append(result.name)
        self.window._reveal_result = lambda result, popover=None: self.revealed.append(
            result.name
        )
        # Tests must not overwrite the real clipboard.
        self.copied: list[str] = []
        self.window._copy_text = self.copied.append
        self.window.search_generation = 1
        self.window._apply_results(1, [file_result(f"file{n}.txt") for n in range(1, 4)])

    def press(self, keyval: int, state: Gdk.ModifierType = Gdk.ModifierType(0)) -> bool:
        return self.window._on_key_pressed(None, keyval, 0, state)

    def test_enter_opens_the_selected_result(self) -> None:
        self.press(Gdk.KEY_Down)
        self.press(Gdk.KEY_Return)
        self.assertEqual(self.opened, ["file2.txt"])

    def test_control_enter_reveals_instead_of_opening(self) -> None:
        self.press(Gdk.KEY_Return, Gdk.ModifierType.CONTROL_MASK)
        self.assertEqual((self.opened, self.revealed), ([], ["file1.txt"]))

    def test_alt_digit_opens_that_result(self) -> None:
        self.assertTrue(self.press(Gdk.KEY_3, Gdk.ModifierType.ALT_MASK))
        self.assertTrue(self.press(Gdk.KEY_9, Gdk.ModifierType.ALT_MASK))
        self.assertEqual(self.opened, ["file3.txt"])

    def test_plain_digit_is_left_for_typing(self) -> None:
        self.assertFalse(self.press(Gdk.KEY_3))
        self.assertEqual(self.opened, [])

    def test_copy_path_reports_in_the_status_line(self) -> None:
        self.assertTrue(
            self.press(Gdk.KEY_C, Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK)
        )
        self.assertEqual(self.window.status.get_text(), "Copied path of file1.txt")
        self.assertEqual(self.copied, ["/home/u/file1.txt"])
        self.assertFalse(self.press(Gdk.KEY_c, Gdk.ModifierType.CONTROL_MASK))


@unittest.skipUnless(HAS_DISPLAY, "needs a graphical session")
class FocusTests(unittest.TestCase):
    def make_window(self, hide_on_focus_loss: bool) -> SearchWindow:
        Adw.init()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        window = SearchWindow(
            None,
            SearchDatabase(Path(directory.name) / "index.sqlite3"),
            ApplicationCatalog(),
            UsageStore(None),
            50,
            "everything",
            hide_on_focus_loss,
        )
        self.addCleanup(window.shutdown)
        self.hidden = False
        window.get_visible = lambda: not self.hidden
        window.set_visible = lambda visible: setattr(self, "hidden", not visible)
        return window

    def change_focus(self, window: SearchWindow, active: bool) -> None:
        window.is_active = lambda: active
        window._on_active_changed(window, None)
        # The window decides shortly after losing focus; run that check now.
        if window.focus_check_id:
            GLib.source_remove(window.focus_check_id)
            window.focus_check_id = 0
            window._check_focus()

    def test_stays_open_while_its_dropdown_is_open(self) -> None:
        window = self.make_window(True)
        self.change_focus(window, True)
        window.search_type.get_last_child().popup()
        self.assertTrue(window._has_open_popup())
        self.change_focus(window, False)
        self.assertFalse(self.hidden)
        window.search_type.get_last_child().popdown()
        self.assertFalse(window._has_open_popup())
        self.assertFalse(window._check_focus())
        self.assertTrue(self.hidden)

    def test_stays_open_if_focus_returns_before_the_check(self) -> None:
        window = self.make_window(True)
        self.change_focus(window, True)
        window.is_active = lambda: False
        window._on_active_changed(window, None)
        window.is_active = lambda: True
        self.assertFalse(window._check_focus())
        self.assertFalse(self.hidden)

    def test_hides_after_losing_focus(self) -> None:
        window = self.make_window(True)
        self.change_focus(window, True)
        self.change_focus(window, False)
        self.assertTrue(self.hidden)

    def test_stays_open_if_it_never_had_focus(self) -> None:
        window = self.make_window(True)
        self.change_focus(window, False)
        self.assertFalse(self.hidden)

    def test_stays_open_while_a_dialog_is_shown(self) -> None:
        window = self.make_window(True)
        self.change_focus(window, True)
        window.dialog_open = True
        self.change_focus(window, False)
        self.assertFalse(self.hidden)

    def test_setting_can_keep_it_open(self) -> None:
        window = self.make_window(False)
        self.change_focus(window, True)
        self.change_focus(window, False)
        self.assertFalse(self.hidden)


if __name__ == "__main__":
    unittest.main()
