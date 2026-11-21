#!/bin/sh
# Builds dist/searchy_<version>_all.deb from this checkout. Needs only dpkg-deb.
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
version=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "${project_dir}/app/__init__.py")
if [ -z "$version" ]; then
    echo "Could not read the version from app/__init__.py" >&2
    exit 1
fi
build_dir=$(mktemp -d)
trap 'rm -rf "$build_dir"' EXIT
root="${build_dir}/searchy_${version}_all"
app_id="io.github.alighonimbini.Searchy"

install -d "${root}/DEBIAN" "${root}/usr/share/searchy/app" "${root}/usr/bin" \
    "${root}/usr/lib/systemd/user" "${root}/usr/share/dbus-1/services" \
    "${root}/usr/share/applications" "${root}/usr/share/icons/hicolor/scalable/apps" \
    "${root}/usr/share/doc/searchy"

install -m 0644 "${project_dir}"/app/*.py "${root}/usr/share/searchy/app/"
install -m 0644 "${project_dir}/.env.example" "${root}/usr/share/doc/searchy/env.example"
install -m 0644 "${project_dir}/README.md" "${root}/usr/share/doc/searchy/README.md"
install -m 0644 "${project_dir}/${app_id}.desktop" "${root}/usr/share/applications/"
install -m 0644 "${project_dir}/${app_id}.svg" "${root}/usr/share/icons/hicolor/scalable/apps/"
install -m 0644 "${project_dir}/${app_id}.dbus-service" \
    "${root}/usr/share/dbus-1/services/${app_id}.service"

# Same unit as install.sh writes, pointed at the packaged code and per-user settings.
sed -e 's|@PROJECT_DIR@|/usr/share/searchy|g' \
    -e 's|^EnvironmentFile=.*|EnvironmentFile=-%h/.config/searchy/.env|' \
    "${project_dir}/searchy.service" > "${root}/usr/lib/systemd/user/searchy.service"
chmod 0644 "${root}/usr/lib/systemd/user/searchy.service"

cat > "${root}/usr/bin/searchy" <<'EOF'
#!/bin/sh
cd /usr/share/searchy && exec /usr/bin/python3 -m app.cli "$@"
EOF
chmod 0755 "${root}/usr/bin/searchy"

installed_size=$(du -sk "${root}/usr" | cut -f1)
cat > "${root}/DEBIAN/control" <<EOF
Package: searchy
Version: ${version}
Section: utils
Priority: optional
Architecture: all
Installed-Size: ${installed_size}
Depends: python3 (>= 3.10), python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1 (>= 1.5), libglib2.0-bin, systemd
Recommends: ripgrep
Maintainer: Searchy maintainers <noreply@example.invalid>
Homepage: https://github.com/ali-ghonim-bini/searchy
Description: Instant desktop search for GNOME on Wayland
 Searches applications, files and folders from a launcher window opened
 with a keyboard shortcut. Runs as a user service and keeps a small index
 of file names up to date.
 .
 After installing, each user runs "searchy setup" once to set the shortcut
 and start the service.
EOF

cat > "${root}/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "configure" ]; then
    echo "Searchy is installed. Each user runs once: searchy setup"
fi
EOF
cat > "${root}/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
# Drop any system-wide enablement an administrator added; per-user state is left alone.
if [ "$1" = "remove" ] && command -v systemctl >/dev/null 2>&1; then
    systemctl --global disable searchy.service >/dev/null 2>&1 || true
fi
EOF
chmod 0755 "${root}/DEBIAN/postinst" "${root}/DEBIAN/prerm"

mkdir -p "${project_dir}/dist"
dpkg-deb --root-owner-group --build "$root" "${project_dir}/dist/searchy_${version}_all.deb" >/dev/null
echo "${project_dir}/dist/searchy_${version}_all.deb"
