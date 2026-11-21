from __future__ import annotations

import re
from pathlib import Path

SHOW_COMMAND = "gapplication action io.github.alighonimbini.Searchy show-search"
_BLOCK_START = "# >>> searchy shortcut >>>"
_BLOCK_END = "# <<< searchy shortcut <<<"
_MODIFIER = re.compile(r"<([^<>]+)>")
# GNOME accelerator modifiers and what Sway and Hyprland call them.
_SWAY_MODIFIERS = {
    "alt": "Mod1", "mod1": "Mod1", "super": "Mod4", "mod4": "Mod4", "meta": "Mod4",
    "ctrl": "Ctrl", "control": "Ctrl", "primary": "Ctrl", "shift": "Shift",
}
_HYPRLAND_MODIFIERS = {
    "alt": "ALT", "mod1": "ALT", "super": "SUPER", "mod4": "SUPER", "meta": "SUPER",
    "ctrl": "CTRL", "control": "CTRL", "primary": "CTRL", "shift": "SHIFT",
}


def detect_desktop(environ: dict[str, str]) -> str:
    """Which desktop the session runs: gnome, kde, sway, hyprland, xfce or other."""
    if environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return "hyprland"
    if environ.get("SWAYSOCK"):
        return "sway"
    names = environ.get("XDG_CURRENT_DESKTOP", "").lower().split(":")
    for desktop, known in (
        ("gnome", {"gnome", "unity", "ubuntu", "pop", "budgie"}),
        ("kde", {"kde", "plasma"}),
        ("sway", {"sway"}),
        ("hyprland", {"hyprland"}),
        ("xfce", {"xfce"}),
    ):
        if known.intersection(names):
            return desktop
    return "other"


def parse_accelerator(accelerator: str) -> tuple[list[str], str]:
    """Split GNOME syntax such as `<Alt><Shift>f` into modifiers and a key."""
    modifiers = [item.lower() for item in _MODIFIER.findall(accelerator)]
    key = _MODIFIER.sub("", accelerator).strip()
    if not key or any(item not in _SWAY_MODIFIERS for item in modifiers):
        raise ValueError(f"Cannot understand the shortcut {accelerator!r}")
    return modifiers, key


def sway_binding(accelerator: str) -> str:
    modifiers, key = parse_accelerator(accelerator)
    keys = "+".join([*(_SWAY_MODIFIERS[item] for item in modifiers), key])
    return f"bindsym {keys} exec {SHOW_COMMAND}"


def hyprland_binding(accelerator: str) -> str:
    modifiers, key = parse_accelerator(accelerator)
    held = " ".join(_HYPRLAND_MODIFIERS[item] for item in modifiers)
    return f"bind = {held}, {key.upper() if len(key) == 1 else key}, exec, {SHOW_COMMAND}"


def config_file(desktop: str, home: Path) -> Path | None:
    return {
        "sway": home / ".config/sway/config",
        "hyprland": home / ".config/hypr/hyprland.conf",
    }.get(desktop)


def instructions(desktop: str, accelerator: str, home: Path) -> list[str]:
    """What the user must do to get the shortcut on a desktop Searchy cannot set it on."""
    if desktop == "sway":
        return [
            f"Add this line to {config_file(desktop, home)}, or run: searchy setup --write",
            f"    {sway_binding(accelerator)}",
            "Then reload Sway: swaymsg reload",
        ]
    if desktop == "hyprland":
        return [
            f"Add this line to {config_file(desktop, home)}, or run: searchy setup --write",
            f"    {hyprland_binding(accelerator)}",
            "Hyprland reloads its configuration by itself.",
        ]
    where = {
        "kde": "System Settings > Keyboard > Shortcuts > Add New > Command or Script",
        "xfce": "Settings > Keyboard > Application Shortcuts > Add",
    }.get(desktop, "your desktop's keyboard shortcut settings")
    return [f"In {where}, bind a key to this command:", f"    {SHOW_COMMAND}"]


def write_binding(path: Path, line: str) -> bool:
    """Put the shortcut in a marked block of a config file. Returns False if unchanged."""
    block = f"{_BLOCK_START}\n{line}\n{_BLOCK_END}\n"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    start, end = text.find(_BLOCK_START), text.find(_BLOCK_END)
    if start >= 0 and end > start:
        updated = text[:start] + block + text[end + len(_BLOCK_END) :].lstrip("\n")
    else:
        updated = text + ("" if not text or text.endswith("\n") else "\n") + block
    if updated == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(updated, encoding="utf-8")
    return True
