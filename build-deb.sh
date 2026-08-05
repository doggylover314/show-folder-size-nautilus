#!/usr/bin/env bash
# Build a .deb for show-folder-size-nautilus.
#
# Needs only dpkg-deb (dpkg-dev), which Debian/Ubuntu already have.
# Produces ./dist/show-folder-size-nautilus_<version>_all.deb
#
# The package installs one Python file system-wide to
# /usr/share/nautilus-python/extensions/ and nothing else. It runs no
# maintainer scripts that touch your files and does not restart nautilus for
# you -- you do that yourself with `nautilus -q`.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${HERE}/show_folder_size.py"
PKG="show-folder-size-nautilus"
ARCH="all"
MAINTAINER="doggylover314 <doggylover314@users.noreply.github.com>"
HOMEPAGE="https://github.com/doggylover314/show-folder-size-nautilus"

command -v dpkg-deb >/dev/null 2>&1 || {
    echo "error: dpkg-deb not found. Install it with: sudo apt install dpkg-dev" >&2
    exit 1
}
[[ -f "${SRC}" ]] || { echo "error: ${SRC} not found" >&2; exit 1; }

# Single source of truth for the version: __version__ in the extension.
VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "${SRC}")"
[[ -n "${VERSION}" ]] || { echo "error: could not read __version__ from ${SRC}" >&2; exit 1; }

BUILD="${HERE}/build/${PKG}_${VERSION}_${ARCH}"
OUT="${HERE}/dist"

echo "Building ${PKG} ${VERSION}"
rm -rf "${BUILD}"
mkdir -p "${BUILD}/DEBIAN" \
         "${BUILD}/usr/share/nautilus-python/extensions" \
         "${BUILD}/usr/bin" \
         "${BUILD}/usr/share/doc/${PKG}"

install -m 0644 "${SRC}" "${BUILD}/usr/share/nautilus-python/extensions/"
install -m 0755 "${HERE}/show-folder-size-index" "${BUILD}/usr/bin/show-folder-size-index"
install -m 0644 "${HERE}/README.md"  "${BUILD}/usr/share/doc/${PKG}/"
install -m 0644 "${HERE}/INSTALL.md" "${BUILD}/usr/share/doc/${PKG}/"

# Debian wants the licence as `copyright`.
install -m 0644 "${HERE}/LICENSE" "${BUILD}/usr/share/doc/${PKG}/copyright"

gzip -9cn "${HERE}/CHANGELOG.md" > "${BUILD}/usr/share/doc/${PKG}/changelog.gz"
chmod 0644 "${BUILD}/usr/share/doc/${PKG}/changelog.gz"

cat > "${BUILD}/DEBIAN/control" <<EOF
Package: ${PKG}
Version: ${VERSION}
Section: gnome
Priority: optional
Architecture: ${ARCH}
Depends: python3 (>= 3.8), python3-nautilus, python3-gi, nautilus (>= 43), debconf (>= 0.5) | debconf-2.0
Maintainer: ${MAINTAINER}
Homepage: ${HOMEPAGE}
Description: Total Size column for GNOME Files showing recursive folder sizes
 Adds an optional "Total Size" column to the Nautilus list view that shows the
 recursive size of a folder's contents, the same number the Properties window
 reports, instead of the built-in item count.
 .
 Sizes are measured in the background with Gio.File.measure_disk_usage and
 cached in memory, so browsing never blocks. The extension only reads the
 filesystem: no writes, no network access and no subprocesses.
 .
 After installing, run "nautilus -q", then enable the column in List View via
 the view menu, Visible Columns.
 .
 The show-folder-size-index command pre-computes sizes for whole drives so browsing
 them is instant from the first look.
EOF

# debconf asks where to keep the size cache and postinst records the answer in
# /etc/show-folder-size-nautilus.conf. This uses debconf rather than a bare `read`
# because package installs are frequently non-interactive (unattended-upgrades,
# images, CI) and a prompt on stdin would hang them forever. debconf handles
# preseeding and non-interactive frontends properly.
#
# Still no service and no restart: an extension runs inside nautilus, there is
# nothing to daemonise, and killing a running file manager during a package
# install would be rude.
for script in config postinst postrm; do
    install -m 0755 "${HERE}/debian/${script}" "${BUILD}/DEBIAN/${script}"
done
install -m 0644 "${HERE}/debian/templates" "${BUILD}/DEBIAN/templates"

dpkg-deb --root-owner-group --build "${BUILD}" >/dev/null

mkdir -p "${OUT}"
DEB="${OUT}/${PKG}_${VERSION}_${ARCH}.deb"
mv "${BUILD}.deb" "${DEB}"
rm -rf "${HERE}/build"

echo
echo "Built: ${DEB}"
echo
dpkg-deb --info "${DEB}" | sed 's/^/  /'
echo "  Contents:"
dpkg-deb --contents "${DEB}" | sed 's/^/    /'
echo
echo "Install with:  sudo apt install ${DEB}"
echo "Then run:      nautilus -q"
