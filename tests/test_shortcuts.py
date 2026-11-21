from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app import shortcuts
from app.cli import set_shortcut


class ShortcutTests(unittest.TestCase):
    def test_desktop_detection(self) -> None:
        cases = {
            "ubuntu:GNOME": "gnome", "GNOME": "gnome", "KDE": "kde", "sway": "sway",
            "Hyprland": "hyprland", "XFCE": "xfce", "": "other", "LXQt": "other",
        }
        for value, expected in cases.items():
            self.assertEqual(shortcuts.detect_desktop({"XDG_CURRENT_DESKTOP": value}), expected)
        self.assertEqual(shortcuts.detect_desktop({"SWAYSOCK": "/run/sway.sock"}), "sway")
        self.assertEqual(
            shortcuts.detect_desktop({"HYPRLAND_INSTANCE_SIGNATURE": "x", "XDG_CURRENT_DESKTOP": "GNOME"}),
            "hyprland",
        )

    def test_bindings_translate_gnome_syntax(self) -> None:
        self.assertEqual(
            shortcuts.sway_binding("<Alt>f"), f"bindsym Mod1+f exec {shortcuts.SHOW_COMMAND}"
        )
        self.assertEqual(
            shortcuts.sway_binding("<Super><Shift>space"),
            f"bindsym Mod4+Shift+space exec {shortcuts.SHOW_COMMAND}",
        )
        self.assertEqual(
            shortcuts.hyprland_binding("<Alt>f"), f"bind = ALT, F, exec, {shortcuts.SHOW_COMMAND}"
        )
        self.assertEqual(
            shortcuts.hyprland_binding("<Control><Super>space"),
            f"bind = CTRL SUPER, space, exec, {shortcuts.SHOW_COMMAND}",
        )
        for bad in ("<Hyper>f", "<Alt>", ""):
            with self.assertRaises(ValueError, msg=bad):
                shortcuts.sway_binding(bad)

    def test_write_adds_once_and_updates_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sway" / "config"
            path.parent.mkdir()
            path.write_text("set $mod Mod4\nbindsym $mod+Return exec foot", encoding="utf-8")
            first = shortcuts.sway_binding("<Alt>f")
            self.assertTrue(shortcuts.write_binding(path, first))
            self.assertFalse(shortcuts.write_binding(path, first))
            self.assertTrue(shortcuts.write_binding(path, shortcuts.sway_binding("<Alt>s")))
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("set $mod Mod4\nbindsym $mod+Return exec foot\n"))
            self.assertEqual(text.count("searchy shortcut"), 2)
            self.assertIn("Mod1+s", text)
            self.assertNotIn("Mod1+f", text)

    def test_setup_prints_or_writes_per_desktop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            printed = set_shortcut("sway", "<Alt>f", False, home)
            self.assertIn(shortcuts.sway_binding("<Alt>f"), printed[1])
            self.assertFalse((home / ".config/sway/config").exists())
            written = set_shortcut("hyprland", "<Alt>f", True, home)
            self.assertIn("Added the shortcut", written[0])
            self.assertIn("bind = ALT, F", (home / ".config/hypr/hyprland.conf").read_text())
            kde = set_shortcut("kde", "<Alt>f", True, home)
            self.assertIn("System Settings", kde[0])
            self.assertIn(shortcuts.SHOW_COMMAND, kde[1])


if __name__ == "__main__":
    unittest.main()
