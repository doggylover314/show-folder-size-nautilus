#!/usr/bin/env bash
# Install the Total Size column extension for the current user.
# Copies one file; touches nothing else. Run with --uninstall to remove it.
set -euo pipefail

DEST="${HOME}/.local/share/nautilus-python/extensions"
FILE="show_folder_size.py"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/${FILE}"

if [[ "${1:-}" == "--uninstall" ]]; then
    rm -fv "${DEST}/${FILE}"
    echo "Removed. Run 'nautilus -q' to unload it."
    exit 0
fi

if [[ ! -f "${SRC}" ]]; then
    echo "error: ${FILE} not found next to this script" >&2
    exit 1
fi

# Both spellings of the library directory, because they are both real:
# Debian and Ubuntu use a multiarch triplet (/usr/lib/x86_64-linux-gnu),
# Fedora, openSUSE and Arch use /usr/lib64 or plain /usr/lib. A glob written
# for one of them silently warns on the others -- /usr/lib/*/... does not
# match /usr/lib64/..., so this used to tell every Fedora user that a package
# they had just installed was missing.
if ! ls /usr/lib/*/nautilus/extensions-4/libnautilus-python.so \
       /usr/lib64/nautilus/extensions-4/libnautilus-python.so \
       /usr/lib/nautilus/extensions-4/libnautilus-python.so \
       >/dev/null 2>&1; then
    echo "warning: libnautilus-python.so (extensions-4) not found." >&2
    echo "         Install it first - python3-nautilus on Debian/Ubuntu," >&2
    echo "         nautilus-python on Fedora. See INSTALL.md." >&2
fi

mkdir -p "${DEST}"
cp -v "${SRC}" "${DEST}/"

echo
echo "Installed to ${DEST}/${FILE}"
echo "Now run:  nautilus -q      (this closes open file manager windows)"
echo "Then reopen Files, switch to List View, and enable the"
echo "'Total Size' column via the view menu -> Visible Columns."
