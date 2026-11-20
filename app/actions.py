from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

# Each entry is a terminal and the arguments that start it in a directory.
_TERMINALS = (
    ("ptyxis", ("--new-window", "-d", "{directory}")),
    ("gnome-terminal", ("--working-directory={directory}",)),
    ("kgx", ("--working-directory={directory}",)),
    ("konsole", ("--workdir", "{directory}")),
    ("xfce4-terminal", ("--working-directory={directory}",)),
    ("x-terminal-emulator", ()),
)


def terminal_command(
    directory: Path, which: Callable[[str], str | None] = shutil.which
) -> list[str] | None:
    """The command that opens the first installed terminal in `directory`."""
    for name, arguments in _TERMINALS:
        executable = which(name)
        if executable:
            return [executable, *(item.format(directory=directory) for item in arguments)]
    return None


def terminal_directory(path: Path) -> Path:
    return path if path.is_dir() else path.parent


def rename_target(path: Path, new_name: str) -> Path:
    """Where `path` would move to; raises ValueError with a message for the user."""
    name = new_name.strip()
    if not name:
        raise ValueError("Enter a name")
    if "/" in name or name in {".", ".."}:
        raise ValueError("A name cannot contain “/”")
    target = path.with_name(name)
    if target == path:
        raise ValueError("That is already its name")
    if target.exists():
        raise ValueError(f"“{name}” already exists in this folder")
    return target


def open_with_applications(path: Path, limit: int = 4) -> list:
    """Other applications that can open `path`, most suitable first."""
    from gi.repository import Gio

    file = Gio.File.new_for_path(str(path))
    try:
        info = file.query_info("standard::content-type", Gio.FileQueryInfoFlags.NONE, None)
    except Exception:
        return []
    applications = Gio.AppInfo.get_recommended_for_type(info.get_content_type())
    return [app for app in applications if app.should_show()][:limit]
