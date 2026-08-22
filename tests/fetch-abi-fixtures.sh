#!/usr/bin/env bash
# Download the libnautilus-extension libraries and typelibs that
# test_abi_live.py registers against.
#
# These come from the Ubuntu archive and are EXTRACTED, never installed:
# everything lands in tests/fixtures/, which is gitignored. Nothing touches
# the system, no root is needed, and deleting tests/fixtures/ undoes it.
#
# Why bother: this project supports three extension ABIs and only one of them
# can be present on any given machine. Without these, "works on Nautilus 42"
# is an assertion nobody has tested. With them, the registration path actually
# runs against the real libraries from Nautilus 42.6 and 50.2.2.
#
# Roughly 60 KB of downloads. Re-running is cheap; existing files are reused.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIX="${HERE}/fixtures"
POOL="http://archive.ubuntu.com/ubuntu/pool/main/n/nautilus"

command -v curl >/dev/null 2>&1 || { echo "error: curl not found" >&2; exit 1; }
command -v dpkg-deb >/dev/null 2>&1 || {
    echo "error: dpkg-deb not found. Install dpkg-dev." >&2; exit 1; }

# name-in-fixtures : .deb in the pool
#
# 42.6 is the last ABI 3.0 release (Ubuntu 22.04 LTS); 50.2.2 is the newest
# ABI 4.1 at the time of writing. 4.0 is not fetched because the machine
# doing the developing already had it -- add it here if that stops being true.
FETCH=(
    "lib-3.0:libnautilus-extension1a_42.6-0ubuntu2_amd64.deb"
    "typelib-3.0:gir1.2-nautilus-3.0_42.6-0ubuntu2_amd64.deb"
    "lib-4.1:libnautilus-extension4_50.2.2-0ubuntu0.1_amd64.deb"
    "typelib-4.1:gir1.2-nautilus-4.1_50.2.2-0ubuntu0.1_amd64.deb"
)

mkdir -p "${FIX}"
for entry in "${FETCH[@]}"; do
    name="${entry%%:*}"
    deb="${entry#*:}"
    target="${FIX}/${name}"

    if [[ -d "${target}" ]]; then
        echo "have    ${name}"
        continue
    fi

    echo "fetch   ${name}  (${deb})"
    if ! curl -fsS --max-time 120 -o "${FIX}/${deb}" "${POOL}/${deb}"; then
        echo "error: could not download ${deb}." >&2
        echo "       The archive drops old versions when a release goes EOL;" >&2
        echo "       check ${POOL}/ and update the version in this script." >&2
        exit 1
    fi

    # curl -f catches an HTTP error, but a transparent proxy can still hand
    # back a 200 with an error page in it. Extraction is the real check.
    mkdir -p "${target}"
    if ! dpkg-deb -x "${FIX}/${deb}" "${target}" 2>/dev/null; then
        rm -rf "${target}"
        echo "error: ${deb} downloaded but is not a .deb. Got $(
            stat -c%s "${FIX}/${deb}") bytes, probably an error page." >&2
        exit 1
    fi
    rm -f "${FIX}/${deb}"
done

echo
echo "Fixtures ready in tests/fixtures/ :"
find "${FIX}" \( -name 'libnautilus-extension.so.*' -o -name '*.typelib' \) \
     -printf '  %8s  %P\n' 2>/dev/null | sort -k2 || true
echo
echo "Now run:  tests/run-tests.sh"
