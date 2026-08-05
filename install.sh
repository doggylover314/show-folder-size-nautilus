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

if ! ls /usr/lib/*/nautilus/extensions-4/libnautilus-python.so >/dev/null 2>&1; then
    echo "warning: libnautilus-python.so (extensions-4) not found." >&2
    echo "         Install nautilus-python first - see INSTALL.md." >&2
fi

mkdir -p "${DEST}"
cp -v "${SRC}" "${DEST}/"

echo
echo "Installed to ${DEST}/${FILE}"
echo "Now run:  nautilus -q      (this closes open file manager windows)"
echo "Then reopen Files, switch to List View, and enable the"
echo "'Total Size' column via the view menu -> Visible Columns."
