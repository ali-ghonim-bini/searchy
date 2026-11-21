from __future__ import annotations

import unittest

from app.commands import (
    SYSTEM_COMMANDS,
    is_shell_query,
    shell_results,
    system_results,
    terminal_run_command,
)


class CommandTests(unittest.TestCase):
    def names(self, text: str) -> list[str]:
        return [result.name for result in system_results(text.split())]

    def test_system_actions_match_names_and_keywords(self) -> None:
        self.assertEqual(self.names("lock"), ["Lock Screen"])
        self.assertEqual(self.names("sleep"), ["Suspend"])
        self.assertEqual(self.names("reboot"), ["Restart"])
        self.assertEqual(self.names("power off"), ["Shut Down"])
        self.assertEqual(self.names("log out"), ["Log Out"])
        self.assertEqual(self.names("report"), [])
        self.assertEqual(self.names(""), [])

    def test_only_harmless_actions_skip_confirmation(self) -> None:
        unconfirmed = {c.name for c in SYSTEM_COMMANDS if c.confirmation is None}
        self.assertEqual(unconfirmed, {"Lock Screen", "Suspend"})

    def test_shell_query(self) -> None:
        self.assertTrue(is_shell_query("  > ls"))
        self.assertFalse(is_shell_query("ls > out"))
        installed = {"gnome-terminal": "/usr/bin/gnome-terminal"}.get
        results = shell_results(">  echo 'a b' | wc ", installed)
        self.assertEqual(results[0].payload, ["sh", "-c", "echo 'a b' | wc"])
        self.assertEqual(results[1].payload[:4], ["/usr/bin/gnome-terminal", "--", "sh", "-c"])
        self.assertTrue(results[1].payload[4].startswith("echo 'a b' | wc; "))
        self.assertEqual(len(shell_results("> ls", {}.get)), 1)
        self.assertEqual(shell_results(">", installed), [])

    def test_terminal_runner_per_terminal(self) -> None:
        self.assertEqual(
            terminal_run_command("ls", {"ptyxis": "/usr/bin/ptyxis"}.get)[:3],
            ["/usr/bin/ptyxis", "--new-window", "--"],
        )
        self.assertIsNone(terminal_run_command("ls", {}.get))


if __name__ == "__main__":
    unittest.main()
