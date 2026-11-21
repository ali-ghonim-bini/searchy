#!/bin/sh
set -eu

service_file="${HOME}/.config/systemd/user/searchy.service"
application_file="${HOME}/.local/share/applications/io.github.alighonimbini.Searchy.desktop"
dbus_service_file="${HOME}/.local/share/dbus-1/services/io.github.alighonimbini.Searchy.service"
icon_root="${HOME}/.local/share/icons/hicolor"
icon_file="${icon_root}/scalable/apps/io.github.alighonimbini.Searchy.svg"
binding_path="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/searchy/"
media_schema="org.gnome.settings-daemon.plugins.media-keys"
binding_schema="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:${binding_path}"

systemctl --user disable --now searchy.service 2>/dev/null || true
rm -f "$service_file" "$application_file" "$dbus_service_file" "$icon_file" \
    "${HOME}/.local/bin/searchy"
if command -v gtk-update-icon-cache >/dev/null 2>&1 && [ -d "$icon_root" ]; then
    gtk-update-icon-cache -f -t "$icon_root" ||
        echo "Warning: could not refresh the user icon cache." >&2
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "${HOME}/.local/share/applications"
fi
systemctl --user daemon-reload

# Other desktops have no Searchy entry in gsettings to remove.
if command -v gsettings >/dev/null 2>&1 &&
    gsettings list-schemas | grep -qx "$media_schema"; then
current_bindings=$(gsettings get "$media_schema" custom-keybindings)
updated_bindings=$(python3 - "$current_bindings" "$binding_path" <<'PY'
import ast
import sys

raw, path = sys.argv[1:]
if raw.startswith("@as "):
    raw = raw[4:]
print(repr([item for item in ast.literal_eval(raw) if item != path]))
PY
)
gsettings set "$media_schema" custom-keybindings "$updated_bindings"
gsettings reset-recursively "$binding_schema"
fi

if [ "${1:-}" = "--purge" ]; then
    rm -rf "${HOME}/.local/state/searchy"
    echo "Searchy and its index were removed."
else
    echo "Searchy was removed; its index was preserved."
fi
