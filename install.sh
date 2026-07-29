#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
service_dir="${HOME}/.config/systemd/user"
application_dir="${HOME}/.local/share/applications"
icon_dir="${HOME}/.local/share/icons/hicolor/scalable/apps"
binding_path="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/searchy/"
media_schema="org.gnome.settings-daemon.plugins.media-keys"
binding_schema="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:${binding_path}"

if [ ! -f "${project_dir}/.env" ]; then
    install -m 0600 "${project_dir}/.env.example" "${project_dir}/.env"
fi
# Searchy owns this file and uses the same shortcut value as the running service.
. "${project_dir}/.env"
native_shortcut=${NATIVE_SHORTCUT:-"<Alt>s"}

for command in python3 gapplication gsettings systemctl; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "Missing required command: ${command}" >&2
        exit 1
    fi
done
python3 -c "import gi; gi.require_version('Gtk', '4.0'); gi.require_version('Adw', '1')"

mkdir -p "$service_dir" "$application_dir" "$icon_dir"
python3 - \
    "${project_dir}/searchy.service" \
    "${service_dir}/searchy.service" \
    "$project_dir" <<'PY'
import sys
from pathlib import Path

source, destination, project_dir = sys.argv[1:]
template = Path(source).read_text(encoding="utf-8")
if template.count("@PROJECT_DIR@") != 2:
    raise SystemExit("Service template must contain exactly two @PROJECT_DIR@ placeholders")

# Prevent percent signs in the path from being interpreted as systemd specifiers.
escaped_dir = project_dir.replace("%", "%%")
Path(destination).write_text(
    template.replace("@PROJECT_DIR@", escaped_dir),
    encoding="utf-8",
)
Path(destination).chmod(0o644)
PY
install -m 0644 "${project_dir}/io.github.alighonimbini.Searchy.desktop" \
    "${application_dir}/io.github.alighonimbini.Searchy.desktop"
install -m 0644 "${project_dir}/io.github.alighonimbini.Searchy.svg" \
    "${icon_dir}/io.github.alighonimbini.Searchy.svg"
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "${HOME}/.local/share/icons/hicolor" ||
        echo "Warning: could not refresh the user icon cache." >&2
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$application_dir"
fi

current_bindings=$(gsettings get "$media_schema" custom-keybindings)
updated_bindings=$(python3 - "$current_bindings" "$binding_path" <<'PY'
import ast
import sys

raw, path = sys.argv[1:]
if raw.startswith("@as "):
    raw = raw[4:]
bindings = ast.literal_eval(raw)
if path not in bindings:
    bindings.append(path)
print(repr(bindings))
PY
)
gsettings set "$media_schema" custom-keybindings "$updated_bindings"
gsettings set "$binding_schema" name "Searchy"
gsettings set "$binding_schema" command \
    "gapplication action io.github.alighonimbini.Searchy show-search"
gsettings set "$binding_schema" binding "$native_shortcut"

systemctl --user daemon-reload
systemctl --user enable searchy.service
systemctl --user restart searchy.service
sleep 1
if ! systemctl --user is-active --quiet searchy.service; then
    echo "Searchy failed to start. Recent logs:" >&2
    journalctl --user -u searchy.service -n 30 --no-pager >&2
    exit 1
fi

echo "Searchy is installed and running with shortcut ${native_shortcut}."
echo "Logs: journalctl --user -u searchy.service -f"
