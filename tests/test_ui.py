from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, GLib, Gtk

from app.catalog import ApplicationCatalog
from app.database import IndexedPath, SearchDatabase
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

    def test_matched_letters_are_bold_and_markup_is_escaped(self) -> None:
        from app.ui import _highlighted

        self.assertEqual(_highlighted("a<b>&file", ["file"]), "a&lt;b&gt;&amp;<b>file</b>")
        self.assertEqual(_highlighted("plain", []), "plain")

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
class ExtraResultTests(unittest.TestCase):
    def setUp(self) -> None:
        Adw.init()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.window = SearchWindow(
            None,
            SearchDatabase(Path(directory.name) / "index.sqlite3"),
            ApplicationCatalog(),
            UsageStore(None),
            50,
            "everything",
            web_search_url="https://duckduckgo.com/?q={query}",
        )
        self.addCleanup(self.window.shutdown)
        self.window._recent_files = lambda: [file_result("recent.txt")]
        self.copied: list[str] = []
        self.window._copy_text = self.copied.append
        self.window.search_generation = 1

    def shown(self, text: str, results: list[SearchResult]) -> list[SearchResult]:
        self.window.search.set_text(text)
        self.window._apply_results(self.window.search_generation, results)
        return self.window.results

    def test_calculation_is_the_first_result_and_enter_copies_it(self) -> None:
        results = self.shown("6*7", [file_result("6x7.txt")])
        self.assertEqual([result.kind for result in results], ["calc", "file"])
        self.window._open_result(results[0])
        self.assertEqual(self.copied, ["42"])

    def test_web_search_is_offered_only_when_nothing_matches(self) -> None:
        self.assertEqual([r.kind for r in self.shown("zzqx", [])], ["web"])
        self.assertEqual([r.kind for r in self.shown("file", [file_result("file.txt")])], ["file"])
        self.assertEqual(self.shown("", []), [])

    def test_empty_box_lists_recent_files_before_unused_apps(self) -> None:
        app = SearchResult("app", "Zed", "", None)
        results = self.window._idle_results("everything", [app])
        self.assertEqual([result.name for result in results], ["recent.txt", "Zed"])
        self.assertEqual(self.window._idle_results("folders", [app]), [])


@unittest.skipUnless(HAS_DISPLAY, "needs a graphical session")
class PreviewPaneTests(unittest.TestCase):
    def make_window(self, show_preview: bool) -> SearchWindow:
        Adw.init()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        window = SearchWindow(
            None,
            SearchDatabase(self.directory / "index.sqlite3"),
            ApplicationCatalog(),
            UsageStore(None),
            50,
            "everything",
            show_preview=show_preview,
        )
        self.addCleanup(window.shutdown)
        window.search_generation = 1
        return window

    def test_selected_file_is_previewed_and_apps_are_not(self) -> None:
        window = self.make_window(True)
        path = self.directory / "notes.txt"
        path.write_text("hello preview", encoding="utf-8")
        result = SearchResult("file", "notes.txt", str(self.directory), None, path, path)
        window._apply_results(1, [result, SearchResult("app", "Zed", "", None)])
        self.assertTrue(window.preview_pane.get_visible())
        self.assertEqual(window.preview_title.get_text(), "notes.txt")
        from app.ui import _load_preview

        window._show_preview(window.preview_generation, *_load_preview(path))
        self.assertEqual(window.preview_text.get_text(), "hello preview")
        self.assertIn("Size: 13 bytes", window.preview_details.get_text())
        window.list_box.select_row(window.list_box.get_row_at_index(1))
        self.assertFalse(window.preview_pane.get_visible())

    def test_stale_preview_is_ignored_and_setting_hides_the_pane(self) -> None:
        window = self.make_window(True)
        path = self.directory / "a.txt"
        path.write_text("old", encoding="utf-8")
        from app.ui import _load_preview

        window._show_preview(window.preview_generation - 1, *_load_preview(path))
        self.assertEqual(window.preview_text.get_text(), "")
        hidden = self.make_window(False)
        hidden._apply_results(1, [SearchResult("file", "a.txt", "", None, path, path)])
        self.assertFalse(hidden.preview_pane.get_visible())


@unittest.skipUnless(HAS_DISPLAY, "needs a graphical session")
class ResultActionTests(unittest.TestCase):
    def setUp(self) -> None:
        Adw.init()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.database = SearchDatabase(self.directory / "index.sqlite3")
        self.window = SearchWindow(
            None, self.database, ApplicationCatalog(), UsageStore(None), 50, "everything"
        )
        self.addCleanup(self.window.shutdown)
        self.path = self.directory / "draft.txt"
        self.path.write_text("x", encoding="utf-8")
        (self.directory / "taken.txt").touch()
        self.result = SearchResult(
            "file", "draft.txt", str(self.directory), None, self.path, self.path
        )
        self.spawned: list[tuple] = []
        self.copied: list = []
        self.window._spawn = lambda command, directory: self.spawned.append((command, directory))
        self.window._copy_files = self.copied.extend
        self.hidden = False
        self.window.set_visible = lambda visible: setattr(self, "hidden", not visible)

    def test_rename_moves_the_file_and_updates_the_index(self) -> None:
        self.database.upsert_many([IndexedPath(self.path, "file", None, 1.0)], 1)
        self.assertTrue(self.window._rename(self.result, "final.txt"))
        self.assertFalse(self.path.exists())
        self.assertTrue((self.directory / "final.txt").exists())
        self.assertEqual([r.name for r in self.database.search("final", 5)], ["final.txt"])
        self.assertEqual(self.database.search("draft", 5), [])

    def test_rename_never_overwrites(self) -> None:
        self.assertFalse(self.window._rename(self.result, "taken.txt"))
        self.assertTrue(self.path.exists())
        self.assertIn("already exists", self.window.status.get_text())
        self.assertFalse(self.window._rename(self.result, "a/b"))

    def test_terminal_opens_in_the_files_folder(self) -> None:
        self.window._open_terminal(self.result)
        if self.spawned:
            self.assertEqual(self.spawned[0][1], self.directory)
            self.assertTrue(self.hidden)
        else:
            self.assertEqual(self.window.status.get_text(), "No terminal application was found")

    def test_copy_file_puts_the_file_on_the_clipboard(self) -> None:
        self.window._copy_file(self.result)
        self.assertEqual(self.copied, [self.path])
        self.assertIn("Copied draft.txt", self.window.status.get_text())


@unittest.skipUnless(HAS_DISPLAY, "needs a graphical session")
class CommandTests(unittest.TestCase):
    def setUp(self) -> None:
        Adw.init()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.window = SearchWindow(
            None,
            SearchDatabase(Path(directory.name) / "index.sqlite3"),
            ApplicationCatalog(),
            UsageStore(None),
            50,
            "everything",
            web_search_url="https://duckduckgo.com/?q={query}",
        )
        self.addCleanup(self.window.shutdown)
        # Nothing here may really run a command, lock the screen or power off.
        self.spawned: list[list[str]] = []
        self.window._spawn = lambda command, directory: self.spawned.append(command)
        self.presented: list[str] = []
        self.window._run_system_command = self.record_system
        self.hidden = False
        self.window.set_visible = lambda visible: setattr(self, "hidden", not visible)

    def record_system(self, command) -> None:
        self.presented.append(command.name)

    def search(self, text: str) -> list[SearchResult]:
        self.window.search.set_text(text)
        self.window._begin_search()
        return self.window.results

    def test_shell_prefix_offers_to_run_and_runs_only_on_enter(self) -> None:
        results = self.search("> echo hi")
        self.assertEqual(results[0].payload, ["sh", "-c", "echo hi"])
        self.assertTrue(all(result.kind == "command" for result in results))
        self.assertEqual(self.spawned, [])
        self.window._open_result(results[0])
        self.assertEqual(self.spawned, [["sh", "-c", "echo hi"]])
        self.assertTrue(self.hidden)

    def test_bare_prefix_offers_nothing_not_even_a_web_search(self) -> None:
        self.assertEqual(self.search(">"), [])
        self.assertEqual(self.search(">   "), [])

    def test_system_actions_are_listed_and_handed_to_the_confirming_step(self) -> None:
        # The Apps filter answers at once; file results arrive from a worker thread.
        self.window.search_type.set_selected(1)
        results = [r for r in self.search("restart") if r.kind == "system"]
        self.assertEqual([r.name for r in results], ["Restart"])
        self.window._open_result(results[0])
        self.assertEqual((self.presented, self.spawned), (["Restart"], []))


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
