from __future__ import annotations

import stat
import tempfile
import unittest
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk

from app import settings
from app.config import Config

HAS_DISPLAY = Gdk.Display.get_default() is not None


class SettingsFileTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / ".env"
        self.path.write_text(
            "# my notes\nSEARCH_ROOTS=~\nNATIVE_SHORTCUT='<Alt>f'\nCUSTOM_THING=keep me\n"
            "RESULT_LIMIT=100\n",
            encoding="utf-8",
        )

    def test_defaults_fill_what_the_file_lacks(self) -> None:
        values = settings.read_values(self.path)
        self.assertEqual(values["NATIVE_SHORTCUT"], "<Alt>f")
        self.assertEqual(values["SHOW_PREVIEW"], "true")
        self.assertEqual(set(values), {field.key for field in settings.FIELDS})

    def test_save_keeps_comments_order_and_unknown_lines(self) -> None:
        values = settings.read_values(self.path)
        values.update(RESULT_LIMIT="250", NATIVE_SHORTCUT="<Super>space", SHOW_PREVIEW="false")
        settings.save(self.path, values)
        lines = self.path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(
            lines[:5],
            ["# my notes", "SEARCH_ROOTS=~", "NATIVE_SHORTCUT='<Super>space'",
             "CUSTOM_THING=keep me", "RESULT_LIMIT=250"],
        )
        self.assertIn("SHOW_PREVIEW=false", lines)
        self.assertIn("WEB_SEARCH_URL='https://duckduckgo.com/?q={query}'", lines)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        loaded = Config.load(self.path, environ={})
        self.assertEqual((loaded.result_limit, loaded.show_preview), (250, False))
        self.assertEqual(settings.read_values(self.path), values)

    def test_bad_values_are_rejected_and_nothing_is_written(self) -> None:
        before = self.path.read_text(encoding="utf-8")
        for key, value in (
            ("WEB_SEARCH_URL", "https://example.com/nothing"),
            ("NATIVE_SHORTCUT", "  "),
            ("EXCLUDE", "it's"),
            ("SEARCH_ROOTS", ""),
            ("SEARCH_ROOTS", "~\nEVIL=1"),
        ):
            values = settings.read_values(self.path)
            values[key] = value
            with self.assertRaises(ValueError, msg=key):
                settings.save(self.path, values)
            self.assertEqual(self.path.read_text(encoding="utf-8"), before)

    def test_environment_does_not_leak_into_validation(self) -> None:
        loaded = Config.load(self.path, environ={"RESULT_LIMIT": "7"})
        self.assertEqual(loaded.result_limit, 7)
        self.assertEqual(Config.load(self.path, environ={}).result_limit, 100)

    def test_settings_location_for_checkout_and_package(self) -> None:
        import os

        from app.config import env_path

        project = self.path.parent
        self.assertEqual(env_path({}, project), project / ".env")
        self.assertEqual(env_path({"SEARCHY_ENV_FILE": "/x/custom.env"}, project), Path("/x/custom.env"))
        packaged = project / "usr-share-searchy"
        packaged.mkdir()
        packaged.chmod(0o555)
        self.addCleanup(packaged.chmod, 0o755)
        if os.access(packaged, os.W_OK):
            self.skipTest("running as a user who can write anywhere")
        self.assertEqual(
            env_path({"XDG_CONFIG_HOME": "/cfg"}, packaged), Path("/cfg/searchy/.env")
        )
        self.assertEqual(env_path({}, packaged), Path.home() / ".config/searchy/.env")

    def test_keybinding_commands_keep_other_shortcuts(self) -> None:
        commands = settings.keybinding_commands("<Alt>f", "@as ['/other/', '%s']" % settings._BINDING_PATH)
        self.assertEqual(commands[0][-1], repr(["/other/", settings._BINDING_PATH]))
        self.assertEqual(commands[-1][-2:], ["binding", "<Alt>f"])
        self.assertEqual(settings.keybinding_commands("<Alt>f", "@as []")[0][-1], repr([settings._BINDING_PATH]))

    def test_saving_creates_the_settings_folder(self) -> None:
        nested = self.path.parent / "config" / "searchy" / ".env"
        settings.save(nested, settings.read_values(nested))
        self.assertTrue(nested.is_file())

    def test_shortcut_command(self) -> None:
        command = settings.shortcut_command("<Super>space")
        self.assertEqual((command[:2], command[-2:]), (["gsettings", "set"], ["binding", "<Super>space"]))


@unittest.skipUnless(HAS_DISPLAY, "needs a graphical session")
class SettingsDialogTests(unittest.TestCase):
    def test_dialog_round_trips_values_and_reports_errors(self) -> None:
        Adw.init()
        values = {field.key: field.default for field in settings.FIELDS}
        values.update(RESULT_LIMIT="250", SHOW_PREVIEW="false", DEFAULT_SEARCH_TYPE="files")
        applied: list[dict[str, str]] = []
        dialog = settings.build_dialog(values, lambda new: applied.append(new) or None)
        self.assertEqual(dialog.collect(), values)
        dialog.rows["INDEX_HIDDEN"].set_active(True)
        dialog.rows["EXCLUDE"].set_text(" build:dist ")
        dialog.apply_button.emit("clicked")
        self.assertEqual(
            (applied[0]["INDEX_HIDDEN"], applied[0]["EXCLUDE"], applied[0]["RESULT_LIMIT"]),
            ("true", "build:dist", "250"),
        )
        failing = settings.build_dialog(values, lambda new: "Not valid")
        failing.apply_button.emit("clicked")


if __name__ == "__main__":
    unittest.main()
