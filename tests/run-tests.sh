#!/usr/bin/env bash
# Run every test in this directory. Exits non-zero if any of them fail.
#
# Tests that need downloaded fixtures skip themselves with a message rather
# than failing, so this is safe to run on a clean clone with no network.
# For the full set, run tests/fetch-abi-fixtures.sh first.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "${HERE}")"

status=0

run() {
    echo "=============================================================="
    echo "  $1"
    echo "=============================================================="
    shift
    if "$@"; then
        echo
    else
        echo "  ^^ FAILED"
        echo
        status=1
    fi
}

run "compile: every python file parses" \
    python3 -m py_compile \
        "${ROOT}/show_folder_size.py" \
        "${ROOT}/show-folder-size-index" \
        "${ROOT}/show-folder-size-setup"

run "ABI selection (no network needed)" \
    python3 "${HERE}/test_abi_selection.py"

run "ABI registration against real Nautilus libraries" \
    python3 "${HERE}/test_abi_live.py"

echo "=============================================================="
if [[ ${status} -eq 0 ]]; then
    echo "  all tests passed"
else
    echo "  SOMETHING FAILED -- see above"
fi
echo "=============================================================="
exit ${status}
