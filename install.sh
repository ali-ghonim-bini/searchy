#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
service_dir="${HOME}/.config/systemd/user"
application_dir="${HOME}/.local/share/applications"
dbus_service_dir="${HOME}/.local/share/dbus-1/services"
icon_dir="${HOME}/.local/share/icons/hicolor/512x512/apps"
binding_path="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/searchy/"
media_schema="org.gnome.settings-daemon.plugins.media-keys"
binding_schema="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:${binding_path}"

if [ ! -f "${project_dir}/.env" ]; then
    install -m 0600 "${project_dir}/.env.example" "${project_dir}/.env"
fi
# Searchy owns this file and uses the same shortcut value as the running service.
. "${project_dir}/.env"
native_shortcut=${NATIVE_SHORTCUT:-"<Alt>f"}

for command in python3 gapplication gsettings systemctl; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "Missing required command: ${command}" >&2
        exit 1
    fi
done
python3 -c "import gi; gi.require_version('Gtk', '4.0'); gi.require_version('Adw', '1')"

mkdir -p "$service_dir" "$application_dir" "$dbus_service_dir" "$icon_dir"

# Drop any older enablement (it used default.target, which starts before Wayland).
systemctl --user disable searchy.service 2>/dev/null || true
escaped_dir=$(printf '%s' "$project_dir" | sed 's/[&|\\]/\\&/g')
sed "s|@PROJECT_DIR@|${escaped_dir}|g" "${project_dir}/searchy.service" \
    > "${service_dir}/searchy.service"
chmod 0644 "${service_dir}/searchy.service"

# Lets the shortcut (gapplication) start the service on demand.
install -m 0644 "${project_dir}/io.github.alighonimbini.Searchy.dbus-service" \
    "${dbus_service_dir}/io.github.alighonimbini.Searchy.service"
install -m 0644 "${project_dir}/io.github.alighonimbini.Searchy.desktop" \
    "${application_dir}/io.github.alighonimbini.Searchy.desktop"
install -m 0644 "${project_dir}/logo_2.png" \
    "${icon_dir}/io.github.alighonimbini.Searchy.png"
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "${HOME}/.local/share/icons/hicolor"
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
# Type=dbus makes this wait until the service has claimed its bus name.
if ! systemctl --user restart searchy.service; then
    echo "Searchy failed to start. Recent logs:" >&2
    journalctl --user -u searchy.service -n 30 --no-pager >&2
    exit 1
fi

echo "Searchy is installed and running with shortcut ${native_shortcut}."
echo "Logs: journalctl --user -u searchy.service -f"
