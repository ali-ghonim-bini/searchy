from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .config import DEFAULT_EXCLUDE, DEFAULT_WEB_SEARCH_URL, Config, env_path

ENV_PATH = env_path()
SHORTCUT_KEY = "NATIVE_SHORTCUT"
_SAFE_VALUE = re.compile(r"[A-Za-z0-9_./:~,-]*")
_ASSIGNMENT = re.compile(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    group: str
    default: str
    # "bool", "text", "int:<min>:<max>" or "choice:<a>,<b>,..."
    kind: str = "text"
    hint: str = ""


FIELDS = (
    Field("DEFAULT_SEARCH_TYPE", "Search by default", "Search", "everything",
          "choice:everything,apps,files,folders"),
    Field("RESULT_LIMIT", "Maximum results", "Search", "100", "int:10:1000"),
    Field("REMEMBER_USAGE", "Rank what you open often first", "Search", "true", "bool"),
    Field("SEARCH_BOOKMARKS", "Show browser bookmarks", "Search", "true", "bool"),
    Field("WEB_SEARCH_URL", "Web search address", "Search", DEFAULT_WEB_SEARCH_URL,
          hint="Must contain {query}. Leave empty to turn the offer off."),
    Field(SHORTCUT_KEY, "Shortcut", "Window", "<Alt>f", hint="GNOME syntax, such as <Alt>f"),
    Field("SHOW_PREVIEW", "Preview pane", "Window", "true", "bool"),
    Field("HIDE_ON_FOCUS_LOSS", "Hide when another window is focused", "Window", "true", "bool"),
    Field("SEARCH_ROOTS", "Folders to index", "Indexing", "~", hint="Separate with colons"),
    Field("EXCLUDE", "Folders to skip", "Indexing", DEFAULT_EXCLUDE,
          hint="Names or paths, separated with colons"),
    Field("INDEX_HIDDEN", "Index hidden folders", "Indexing", "false", "bool"),
    Field("INDEX_REMOVABLE", "Index removable drives", "Indexing", "false", "bool"),
    Field("INDEX_INTERVAL_SECONDS", "Seconds between full rescans", "Indexing", "3600",
          "int:60:86400"),
)


def read_values(path: Path) -> dict[str, str]:
    """The value of every setting: what the file says, else the default."""
    values = {field.key: field.default for field in FIELDS}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            match = _ASSIGNMENT.match(line)
            if match and not line.lstrip().startswith("#") and match[1] in values:
                values[match[1]] = line.split("=", 1)[1].strip().strip("'\"")
    return values


def _quoted(key: str, value: str) -> str:
    # The file is read by the shell, by systemd and by Searchy; single quotes suit all three.
    if "'" in value or "\n" in value or "\r" in value:
        raise ValueError(f"{key} cannot contain a quote mark or a line break")
    return value if _SAFE_VALUE.fullmatch(value) and value else f"'{value}'"


def write_values(path: Path, values: dict[str, str]) -> None:
    """Update settings in place, keeping comments, order and unrelated lines."""
    remaining = {key: _quoted(key, value) for key, value in values.items()}
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    output = []
    for line in lines:
        match = _ASSIGNMENT.match(line)
        if match and not line.lstrip().startswith("#") and match[1] in remaining:
            output.append(f"{match[1]}={remaining.pop(match[1])}")
        else:
            output.append(line)
    output.extend(f"{key}={value}" for key, value in remaining.items())
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text("\n".join(output) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def validate(values: dict[str, str]) -> None:
    """Raise ValueError with a message for the user if the settings would not load."""
    for key, value in values.items():
        _quoted(key, value)
    if not values.get(SHORTCUT_KEY, "").strip():
        raise ValueError("Shortcut cannot be empty")
    with tempfile.TemporaryDirectory() as directory:
        candidate = Path(directory) / ".env"
        write_values(candidate, values)
        # Ignore the running service's environment: only the file is being checked.
        Config.load(candidate, environ={})


def save(path: Path, values: dict[str, str]) -> None:
    validate(values)
    write_values(path, values)


def build_dialog(values: dict[str, str], on_apply):
    """The preferences dialog. `on_apply(values)` returns an error message or None."""
    import gi

    gi.require_version("Adw", "1")
    gi.require_version("Gtk", "4.0")
    from gi.repository import Adw, Gtk

    dialog = Adw.PreferencesDialog(title="Searchy Settings")
    page = Adw.PreferencesPage()
    dialog.add(page)
    rows: dict[str, object] = {}
    groups: dict[str, Adw.PreferencesGroup] = {}
    for field in FIELDS:
        if field.group not in groups:
            groups[field.group] = Adw.PreferencesGroup(title=field.group)
            page.add(groups[field.group])
        value = values.get(field.key, field.default)
        if field.kind == "bool":
            row = Adw.SwitchRow(title=field.label, active=value.lower() in {"1", "true", "yes", "on"})
        elif field.kind.startswith("int:"):
            _kind, low, high = field.kind.split(":")
            row = Adw.SpinRow.new_with_range(float(low), float(high), 1)
            row.set_title(field.label)
            row.set_value(float(value) if value.isdigit() else float(field.default))
        elif field.kind.startswith("choice:"):
            choices = field.kind.split(":", 1)[1].split(",")
            row = Adw.ComboRow(title=field.label, model=Gtk.StringList.new(choices))
            row.set_selected(choices.index(value) if value in choices else 0)
        else:
            row = Adw.EntryRow(title=field.label, text=value)
            if field.hint:
                row.set_tooltip_text(field.hint)
        rows[field.key] = row
        groups[field.group].add(row)

    def collect() -> dict[str, str]:
        collected = {}
        for field in FIELDS:
            row = rows[field.key]
            if field.kind == "bool":
                collected[field.key] = "true" if row.get_active() else "false"
            elif field.kind.startswith("int:"):
                collected[field.key] = str(int(row.get_value()))
            elif field.kind.startswith("choice:"):
                collected[field.key] = field.kind.split(":", 1)[1].split(",")[row.get_selected()]
            else:
                collected[field.key] = row.get_text().strip()
        return collected

    def apply(_button) -> None:
        error = on_apply(collect())
        if error:
            dialog.add_toast(Adw.Toast(title=error, timeout=6))

    footer = Adw.PreferencesGroup(
        description="Applying saves the settings and restarts Searchy. "
        "Changing what is indexed rebuilds the index."
    )
    button = Gtk.Button(label="Apply and Restart", halign=Gtk.Align.END)
    button.add_css_class("suggested-action")
    button.connect("clicked", apply)
    footer.add(button)
    page.add(footer)
    dialog.rows = rows
    dialog.collect = collect
    dialog.apply_button = button
    return dialog


_BINDING_PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/searchy/"


def shortcut_command(binding: str) -> list[str]:
    """The gsettings call that moves the GNOME shortcut install.sh created."""
    schema = f"org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:{_BINDING_PATH}"
    return ["gsettings", "set", schema, "binding", binding]


def keybinding_commands(binding: str, current_list: str) -> list[list[str]]:
    """The gsettings calls that create the GNOME shortcut, as install.sh does."""
    import ast

    raw = current_list[4:] if current_list.startswith("@as ") else current_list
    paths = [item for item in ast.literal_eval(raw or "[]") if item != _BINDING_PATH]
    paths.append(_BINDING_PATH)
    schema = f"org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:{_BINDING_PATH}"
    return [
        ["gsettings", "set", "org.gnome.settings-daemon.plugins.media-keys",
         "custom-keybindings", repr(paths)],
        ["gsettings", "set", schema, "name", "Searchy"],
        ["gsettings", "set", schema, "command",
         "gapplication action io.github.alighonimbini.Searchy show-search"],
        ["gsettings", "set", schema, "binding", binding],
    ]


RESTART_COMMAND = ["systemctl", "--user", "restart", "searchy.service"]
