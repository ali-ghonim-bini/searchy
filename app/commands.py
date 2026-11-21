from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass

from .models import SearchResult
from .ranking import NO_MATCH, name_tier

SHELL_PREFIX = ">"
# How each terminal is told to run a command: the arguments placed before it.
_TERMINAL_RUNNERS = (
    ("ptyxis", ("--new-window", "--")),
    ("gnome-terminal", ("--",)),
    ("kgx", ("-e",)),
    ("konsole", ("-e",)),
    ("xfce4-terminal", ("-x",)),
    ("x-terminal-emulator", ("-e",)),
)
_KEEP_OPEN = '; printf "\\n[finished: press Enter to close] "; read _'


@dataclass(frozen=True)
class SystemCommand:
    name: str
    keywords: str
    argv: tuple[str, ...]
    # Asked before running; None for actions that are trivially undone.
    confirmation: str | None = None


SYSTEM_COMMANDS = (
    SystemCommand("Lock Screen", "lock", ("loginctl", "lock-session")),
    SystemCommand("Suspend", "sleep suspend", ("systemctl", "suspend")),
    SystemCommand(
        "Log Out", "logout sign out", ("gnome-session-quit", "--logout", "--no-prompt"),
        "Log out now? Unsaved work in open applications may be lost.",
    ),
    SystemCommand(
        "Restart", "reboot restart", ("systemctl", "reboot"),
        "Restart the computer now? Unsaved work may be lost.",
    ),
    SystemCommand(
        "Shut Down", "shutdown power off poweroff", ("systemctl", "poweroff"),
        "Shut down the computer now? Unsaved work may be lost.",
    ),
)


def system_results(tokens: list[str]) -> list[SearchResult]:
    """System actions whose name or keywords match what was typed."""
    if not tokens:
        return []
    results = []
    for command in SYSTEM_COMMANDS:
        by_name = name_tier(command.name, tokens) != NO_MATCH
        by_keyword = all(
            any(word.startswith(token) for word in command.keywords.split()) for token in tokens
        )
        if by_name or by_keyword:
            results.append(
                SearchResult(
                    kind="system",
                    name=command.name,
                    detail="System action" + ("  |  asks first" if command.confirmation else ""),
                    created_at=None,
                    payload=command,
                )
            )
    return results


def is_shell_query(text: str) -> bool:
    return text.lstrip().startswith(SHELL_PREFIX)


def shell_results(
    text: str, which: Callable[[str], str | None] = shutil.which
) -> list[SearchResult]:
    """Rows offered for `> some command`: run it quietly, or in a terminal."""
    command = text.lstrip()[len(SHELL_PREFIX) :].strip()
    if not command:
        return []
    results = [
        SearchResult(
            kind="command",
            name=f"Run: {command}",
            detail="Runs in the background from your home folder; output is not shown",
            created_at=None,
            payload=["sh", "-c", command],
        )
    ]
    in_terminal = terminal_run_command(command, which)
    if in_terminal:
        results.append(
            SearchResult(
                kind="command",
                name=f"Run in a terminal: {command}",
                detail="Opens a terminal and keeps it open when the command ends",
                created_at=None,
                payload=in_terminal,
            )
        )
    return results


def terminal_run_command(
    command: str, which: Callable[[str], str | None] = shutil.which
) -> list[str] | None:
    for name, arguments in _TERMINAL_RUNNERS:
        executable = which(name)
        if executable:
            return [executable, *arguments, "sh", "-c", command + _KEEP_OPEN]
    return None
