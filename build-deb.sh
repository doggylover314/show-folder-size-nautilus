#!/usr/bin/env bash
# Build a .deb for show-folder-size-nautilus.
#
# Needs only dpkg-deb (dpkg-dev), which Debian/Ubuntu already have.
# Produces ./dist/show-folder-size-nautilus_<version>_all.deb
#
# The package installs the extension to /usr/share/nautilus-python/extensions/,
# two commands to /usr/bin, and desktop integration: a .desktop entry, an icon,
# AppStream metainfo, a gschema override that makes the column visible by
# default, and an /etc/xdg/autostart entry that keeps folder sizes indexed.
#
# Its maintainer scripts write /etc/show-folder-size-nautilus.conf and rebuild
# three system caches (gschema, desktop, icon). They touch nothing in anyone's
# home directory and do not restart nautilus for you -- you do that yourself
# with `nautilus -q`.
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
APPID="io.github.doggylover314.ShowFolderSizeSetup"
# Must match AUTOSTART_DESKTOP_NAME in show_folder_size.py: the setup app
# overrides this exact filename in ~/.config/autostart to switch the login
# indexer off, and an override under any other name does nothing at all.
AUTOSTART_ID="io.github.doggylover314.ShowFolderSizeIndex"

# The AppStream metainfo carries its own version list, and GNOME Software
# shows the newest entry in it rather than the dpkg version. Nothing links the
# two, so they drift silently: 0.6.0 sat in the metainfo through several
# releases and the only symptom was the wrong version in the software centre.
# Refuse to build rather than ship that.
META="${HERE}/debian/${APPID}.metainfo.xml"
META_VERSION="$(sed -n 's/.*<release version="\([^"]*\)".*/\1/p' "${META}" | head -n 1)"
if [[ "${META_VERSION}" != "${VERSION}" ]]; then
    echo "error: version drift. show_folder_size.py says ${VERSION}, but the" >&2
    echo "       newest <release> in ${META##*/} says ${META_VERSION}." >&2
    echo "       Add a <release version=\"${VERSION}\" date=\"...\"> entry." >&2
    exit 1
fi

mkdir -p "${BUILD}/DEBIAN" \
         "${BUILD}/usr/share/nautilus-python/extensions" \
         "${BUILD}/usr/bin" \
         "${BUILD}/usr/share/applications" \
         "${BUILD}/usr/share/metainfo" \
         "${BUILD}/usr/share/glib-2.0/schemas" \
         "${BUILD}/usr/share/icons/hicolor/scalable/apps" \
         "${BUILD}/etc/xdg/autostart" \
         "${BUILD}/usr/share/doc/${PKG}"

install -m 0644 "${SRC}" "${BUILD}/usr/share/nautilus-python/extensions/"
install -m 0755 "${HERE}/show-folder-size-index" "${BUILD}/usr/bin/show-folder-size-index"
install -m 0755 "${HERE}/show-folder-size-setup" "${BUILD}/usr/bin/show-folder-size-setup"
install -m 0644 "${HERE}/README.md"  "${BUILD}/usr/share/doc/${PKG}/"
install -m 0644 "${HERE}/INSTALL.md" "${BUILD}/usr/share/doc/${PKG}/"

# Desktop integration. The .desktop gives the setup app a menu entry; the
# metainfo is what makes GNOME Software render this as an application with an
# icon and a description instead of a bare package name when the .deb is
# opened by double-clicking it.
install -m 0644 "${HERE}/debian/${APPID}.desktop" \
        "${BUILD}/usr/share/applications/"
install -m 0644 "${HERE}/debian/${APPID}.metainfo.xml" \
        "${BUILD}/usr/share/metainfo/"
install -m 0644 "${HERE}/debian/${APPID}.svg" \
        "${BUILD}/usr/share/icons/hicolor/scalable/apps/"

# Makes Total Size a visible column by default. postinst recompiles the
# schema cache, without which an override file has no effect at all.
install -m 0644 "${HERE}/debian/90_${PKG}.gschema.override" \
        "${BUILD}/usr/share/glib-2.0/schemas/"

# The login indexer, for every account on the machine. /etc/xdg/autostart
# rather than /usr/share: the XDG autostart spec looks in $XDG_CONFIG_DIRS,
# which is /etc/xdg, and a per-user file of the same name in
# ~/.config/autostart replaces it -- which is how "Folder Size Setup" can
# switch it off for one account without root.
#
# NOT a conffile: it is under /etc but it is ours, users override it in their
# own directory rather than by editing it, and listing it would mean a dpkg
# prompt on every upgrade for a file nobody was supposed to edit.
install -m 0644 "${HERE}/debian/${AUTOSTART_ID}.desktop" \
        "${BUILD}/etc/xdg/autostart/"

# Debian wants the licence as `copyright`.
install -m 0644 "${HERE}/LICENSE" "${BUILD}/usr/share/doc/${PKG}/copyright"

gzip -9cn "${HERE}/CHANGELOG.md" > "${BUILD}/usr/share/doc/${PKG}/changelog.gz"
chmod 0644 "${BUILD}/usr/share/doc/${PKG}/changelog.gz"

# The GTK4 and libadwaita typelibs moved from Depends to Recommends, and the
# nautilus (>= 43) floor is gone. Only the setup window needs GTK4; the
# extension and the indexer do not, and the extension now asks for the 3.0
# extension ABI when 4.0 is absent (structurally -- that path is UNVERIFIED,
# see the note in show_folder_size.py). A hard dependency on either meant the
# refused to install on a desktop where the column would have worked, which is
# the opposite of the intent. show-folder-size-setup exits with a message
# naming the missing packages rather than a typelib traceback.
#
# Conflicts/Replaces/Provides on nautilus-total-size, the name this package
# used up to 0.4.0. The rename in 0.5.0 also renamed every file it ships
# (total_size_column.py -> show_folder_size.py, total-size-index ->
# show-folder-size-index), so dpkg saw two unrelated packages with no
# overlapping paths and cheerfully installed both -- nautilus then loaded two
# extensions and drew TWO "Total Size" columns. Conflicts+Replaces is the
# standard renamed-package pair and makes apt remove the old one.
cat > "${BUILD}/DEBIAN/control" <<EOF
Package: ${PKG}
Version: ${VERSION}
Section: gnome
Priority: optional
Architecture: ${ARCH}
Depends: python3 (>= 3.8), python3-nautilus, python3-gi, nautilus, debconf (>= 0.5) | debconf-2.0
Recommends: gir1.2-gtk-4.0, gir1.2-adw-1
Conflicts: nautilus-total-size
Replaces: nautilus-total-size
Provides: nautilus-total-size
Maintainer: ${MAINTAINER}
Homepage: ${HOMEPAGE}
Description: Total Size column for GNOME Files showing recursive folder sizes
 Adds an optional "Total Size" column to the Nautilus list view that shows the
 recursive size of a folder's contents, the same number the Properties window
 reports, instead of the built-in item count.
 .
 Sizes are measured in the background with Gio.File.measure_disk_usage and
 cached on disk, so browsing never blocks and a folder measured once stays
 instant across restarts. There is no network access and no subprocess use.
 Writes are limited to the size cache, one marker file recording that the
 column was enabled, and that column setting itself; the extension's header
 comment lists each one and how to prevent it.
 .
 The column is enabled automatically the first time the extension loads, so
 after installing you only need to run "nautilus -q". Untick it in List View
 under the view menu, Visible Columns, if you would rather not have it.
 .
 Folder sizes are indexed at each login, in full the first time and then only
 where something changed, after a short delay and at low priority. Each user
 can switch that off or choose which folders it covers.
 .
 "Folder Size Setup" (show-folder-size-setup) is a small window for choosing
 where sizes are cached, what the login indexing covers, and for pre-indexing
 whole drives on the spot. The same indexing is available on the command line
 as show-folder-size-index.
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
