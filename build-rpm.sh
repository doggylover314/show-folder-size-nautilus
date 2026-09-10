#!/usr/bin/env bash
# Build an .rpm for show-folder-size-nautilus.
#
# Needs rpmbuild (the `rpm-build` package on Fedora, `rpm` on Debian/Ubuntu).
# Produces ./dist/show-folder-size-nautilus-<version>-1.<dist>.noarch.rpm
#
# This is the Fedora Workstation counterpart of build-deb.sh and installs the
# same payload: the extension into /usr/share/nautilus-python/extensions/, two
# commands into /usr/bin, and the desktop integration -- .desktop entry, icon,
# AppStream metainfo, the gschema override that makes the column visible by
# default, and the /etc/xdg/autostart entry that keeps folder sizes indexed.
#
# Everything that is not packaging-format-specific comes out of data/, shared
# with build-deb.sh, so the two packages cannot drift apart. The spec itself
# is fedora/show-folder-size-nautilus.spec and its header explains the three
# places the RPM genuinely differs from the .deb.
#
# It does NOT have to be run on Fedora. rpmbuild is available on Debian and
# Ubuntu too, and the result is a noarch package with no compiled anything in
# it, so a build here is the same package as a build there. What a foreign
# build cannot do is run the two validators in %check -- they are skipped with
# a message rather than failing the build. Read a build on Ubuntu as "the
# package is assembled correctly", not as "the spec passed Fedora's checks".
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${HERE}/show_folder_size.py"
PKG="show-folder-size-nautilus"
SPEC="${HERE}/fedora/${PKG}.spec"
APPID="io.github.doggylover314.ShowFolderSizeSetup"
OUT="${HERE}/dist"

command -v rpmbuild >/dev/null 2>&1 || {
    echo "error: rpmbuild not found." >&2
    echo "       Fedora:        sudo dnf install rpm-build" >&2
    echo "       Debian/Ubuntu: sudo apt install rpm" >&2
    exit 1
}
[[ -f "${SRC}" ]]  || { echo "error: ${SRC} not found" >&2; exit 1; }
[[ -f "${SPEC}" ]] || { echo "error: ${SPEC} not found" >&2; exit 1; }

# Single source of truth for the version: __version__ in the extension.
VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "${SRC}")"
[[ -n "${VERSION}" ]] || {
    echo "error: could not read __version__ from ${SRC}" >&2; exit 1; }

# Two version numbers are carried outside the extension and both drift
# silently when nobody checks them: the newest <release> in the AppStream
# metainfo, which is what GNOME Software shows, and the spec's own fallback
# Version, which is what a hand-run `rpmbuild -ba` would stamp on the package.
# Refuse to build rather than ship either one wrong.
META="${HERE}/data/${APPID}.metainfo.xml"
META_VERSION="$(sed -n 's/.*<release version="\([^"]*\)".*/\1/p' "${META}" \
                | head -n 1)"
if [[ "${META_VERSION}" != "${VERSION}" ]]; then
    echo "error: version drift. show_folder_size.py says ${VERSION}, but the" >&2
    echo "       newest <release> in ${META##*/} says ${META_VERSION}." >&2
    echo "       Add a <release version=\"${VERSION}\" date=\"...\"> entry." >&2
    exit 1
fi

SPEC_VERSION="$(sed -n 's/^%global upstream_version \(.*\)$/\1/p' "${SPEC}")"
if [[ "${SPEC_VERSION}" != "${VERSION}" ]]; then
    echo "error: version drift. show_folder_size.py says ${VERSION}, but" >&2
    echo "       ${SPEC##*/} says %global upstream_version ${SPEC_VERSION}." >&2
    exit 1
fi

TOP="${HERE}/build/rpm"
DIR="${PKG}-${VERSION}"

echo "Building ${PKG} ${VERSION}"
rm -rf "${TOP}"
mkdir -p "${TOP}"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS} "${TOP}/${DIR}"

# The tarball rpmbuild unpacks. %autosetup expects it to contain one directory
# named <name>-<version>, which is why this copies into ${DIR} rather than
# taring the working tree in place. Only what the package installs goes in:
# no .git, no dist/, no tests/fixtures.
for item in show_folder_size.py show-folder-size-index show-folder-size-setup \
            README.md INSTALL.md CHANGELOG.md LICENSE data; do
    cp -r "${HERE}/${item}" "${TOP}/${DIR}/"
done
tar -czf "${TOP}/SOURCES/${DIR}.tar.gz" -C "${TOP}" "${DIR}"
rm -rf "${TOP}/${DIR}"

# On an RPM-managed system rpmbuild checks BuildRequires against the package
# database, which is right and should stay on. On Debian or Ubuntu that
# database is empty, so every BuildRequires "fails" whether or not the tool is
# installed -- `rpm -q rpm` is the cheapest way to tell those two situations
# apart. --nodeps there skips a check that could only ever be wrong; %check
# still looks for the validators itself and says which it skipped.
RPMBUILD_ARGS=()
if ! rpm -q rpm >/dev/null 2>&1; then
    echo "note: no rpm package database here, so BuildRequires cannot be"
    echo "      checked. Building with --nodeps; %check will say which"
    echo "      validators it had to skip."
    RPMBUILD_ARGS+=(--nodeps)
fi

rpmbuild -bb "${SPEC}" \
    --define "_topdir ${TOP}" \
    --define "_version ${VERSION}" \
    --define "_build_id_links none" \
    "${RPMBUILD_ARGS[@]}"

mkdir -p "${OUT}"
found=0
while IFS= read -r -d '' rpm; do
    cp "${rpm}" "${OUT}/"
    echo
    echo "Built: ${OUT}/$(basename "${rpm}")"
    found=1
done < <(find "${TOP}/RPMS" -name '*.rpm' -print0)
[[ ${found} -eq 1 ]] || { echo "error: rpmbuild produced no .rpm" >&2; exit 1; }

rm -rf "${HERE}/build"

RPM="$(find "${OUT}" -name "${PKG}-${VERSION}-*.noarch.rpm" | head -n 1)"
echo
rpm -qip "${RPM}" | sed 's/^/  /'
echo "  Contents:"
rpm -qlvp "${RPM}" | sed 's/^/    /'
echo
echo "Install with:  sudo dnf install ${RPM}"
echo "Then run:      nautilus -q"
