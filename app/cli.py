from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from . import __version__
from .config import Config
from .database import SearchDatabase

APPLICATION_ID = "io.github.alighonimbini.Searchy"
SERVICE = "searchy.service"


def _age(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} min ago"
    if minutes < 48 * 60:
        return f"{minutes // 60} h ago"
    return f"{minutes // 1440} days ago"


def _size(path: Path) -> str:
    size = sum(
        Path(str(path) + suffix).stat().st_size
        for suffix in ("", "-wal")
        if Path(str(path) + suffix).exists()
    )
    return f"{size / 1_000_000:.0f} MB"


def _watch_limit() -> int:
    try:
        return int(Path("/proc/sys/fs/inotify/max_user_watches").read_text().strip())
    except (OSError, ValueError):
        return 65536


def service_state() -> str:
    try:
        completed = subprocess.run(
            ["systemctl", "--user", "is-active", SERVICE],
            capture_output=True, text=True, check=False, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return completed.stdout.strip() or "unknown"


def status_lines(config: Config, state: str, now: float | None = None) -> list[str]:
    lines = [f"Service:        {state}"]
    if not config.database_path.exists():
        return lines + ["Index:          not built yet"]
    database = SearchDatabase(config.database_path)
    folders = database.folder_count()
    completed_at = database.last_completed_at()
    now = time.time() if now is None else now
    if completed_at is None:
        scan = "first scan has not finished"
    else:
        stamp = datetime.fromtimestamp(completed_at).strftime("%Y-%m-%d %H:%M")
        scan = f"{stamp} ({_age(now - completed_at)})"
    limit = _watch_limit()
    live = "on" if folders < limit else f"off, rescans every {config.index_interval_seconds} s"
    return lines + [
        f"Indexed items:  {database.count():,} ({folders:,} folders)",
        f"Last full scan: {scan}",
        f"Index size:     {_size(config.database_path)}",
        f"Live updates:   {live} ({folders:,} folders, watch limit {limit:,})",
        f"Search roots:   {', '.join(str(root) for root in config.search_roots)}",
    ]


def _send(action: str) -> int:
    try:
        return subprocess.run(
            ["gapplication", "action", APPLICATION_ID, action], check=False, timeout=30
        ).returncode
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"Could not reach Searchy: {error}", file=sys.stderr)
        return 1


def setup() -> int:
    """Per-user steps a system package cannot do: the shortcut and starting the service."""
    from . import settings

    binding = settings.read_values(settings.ENV_PATH)[settings.SHORTCUT_KEY]
    try:
        current = subprocess.run(
            ["gsettings", "get", "org.gnome.settings-daemon.plugins.media-keys",
             "custom-keybindings"],
            capture_output=True, text=True, check=True, timeout=10,
        ).stdout.strip()
        for command in settings.keybinding_commands(binding, current):
            subprocess.run(command, check=True, timeout=10)
        print(f"Shortcut set to {binding}.")
    except (OSError, subprocess.SubprocessError, ValueError, SyntaxError) as error:
        print(f"Could not set the GNOME shortcut: {error}", file=sys.stderr)
        print(f"Bind a key yourself to: gapplication action {APPLICATION_ID} show-search")
    code = subprocess.run(
        ["systemctl", "--user", "enable", "--now", SERVICE], check=False
    ).returncode
    print("Searchy is running." if code == 0 else "Could not start the service.")
    return code


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="searchy", description="Control the Searchy service.")
    parser.add_argument("--version", action="version", version=f"searchy {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="show the service and index state")
    reindex = commands.add_parser("reindex", help="rescan the search roots now")
    reindex.add_argument(
        "--rebuild", action="store_true", help="discard the index and build it again"
    )
    commands.add_parser("show", help="show or hide the search window")
    commands.add_parser("settings", help="open the settings window")
    commands.add_parser(
        "setup", help="set the shortcut and start the service (after installing the package)"
    )
    options = parser.parse_args(arguments)
    if options.command == "status":
        try:
            config = Config.load()
        except ValueError as error:
            print(f"Invalid configuration: {error}", file=sys.stderr)
            return 2
        print("\n".join(status_lines(config, service_state())))
        return 0
    if options.command == "show":
        return _send("show-search")
    if options.command == "settings":
        return _send("settings")
    if options.command == "setup":
        return setup()
    code = _send("rebuild-index" if options.rebuild else "reindex")
    if code == 0:
        print(
            "Rebuilding the index from scratch." if options.rebuild else "Rescan started.",
            "Run 'searchy status' to see when it finishes.",
        )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
