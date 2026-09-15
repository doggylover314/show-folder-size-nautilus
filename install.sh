#!/usr/bin/env bash
# Install the Total Size column extension for the current user.
#
# Copies one file into ~/.local/share/nautilus-python/extensions/. If the
# nautilus-python loader is missing it offers to install that first, because
# without it nautilus never even looks at this file: there is no error, no
# column, and nothing anywhere that says why.
#
#   ./install.sh               ask before installing anything system-wide
#   ./install.sh --yes         don't ask
#   ./install.sh --skip-deps   never touch the package manager
#   ./install.sh --uninstall   remove the extension
#
# The .deb and .rpm need none of this. Both declare nautilus-python as a
# dependency, so apt and dnf install it themselves; this script exists for
# the case where someone is running from a clone and no package manager
# knows anything about this project.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${HOME}/.local/share/nautilus-python/extensions"
FILE="show_folder_size.py"
SRC="${HERE}/${FILE}"

ACTION=install
ASSUME_YES=0
SKIP_DEPS=0

# The header comment above is the help text. Printing it from the file keeps
# the two from drifting, but only if the range is found rather than counted:
# a line number goes stale the moment anyone edits the comment.
usage() {
    awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' \
        "${BASH_SOURCE[0]}"
}

for arg in "$@"; do
    case "${arg}" in
        --uninstall)  ACTION=uninstall ;;
        -y|--yes)     ASSUME_YES=1 ;;
        --skip-deps)  SKIP_DEPS=1 ;;
        -h|--help)    usage; exit 0 ;;
        *) echo "error: unknown option ${arg}" >&2; usage >&2; exit 2 ;;
    esac
done

if [[ "${ACTION}" == "uninstall" ]]; then
    rm -fv "${DEST}/${FILE}"
    echo "Removed. Run 'nautilus -q' to unload it."
    echo "nautilus-python is left alone; remove it yourself if you want it gone."
    exit 0
fi

[[ -f "${SRC}" ]] || { echo "error: ${FILE} not found next to this script" >&2; exit 1; }

# Where nautilus-python puts its loader varies twice over: the library
# directory differs by distro (a multiarch triplet on Debian and Ubuntu,
# lib64 on Fedora and openSUSE) and the extensions directory differs by ABI
# (extensions-4 on Nautilus 43 and later, extensions-3.0 before it). Globbing
# both beats hardcoding one path, which is how this script used to tell every
# Fedora user that a package they already had was missing.
loader_present() {
    local dir so
    for dir in /usr/lib64 /usr/lib /usr/lib/*-linux-gnu \
               /usr/local/lib64 /usr/local/lib; do
        [[ -d "${dir}" ]] || continue
        for so in "${dir}"/nautilus/extensions-*/libnautilus-python.so; do
            [[ -e "${so}" ]] && return 0
        done
    done
    return 1
}

# Four package managers, four different names for one package, none of them
# guessed: each was checked against that distro's current package index.
# Arch is the one that catches people out -- it is nautilus-python there now,
# and python-nautilus, which this project's README recommended for a year,
# does not exist at all. openSUSE ships versioned packages
# (python313-nautilus and so on) with python3-nautilus as a provides alias,
# so the plain name still resolves.
dep_package() {
    if   command -v apt-get >/dev/null 2>&1; then echo "python3-nautilus"
    elif command -v dnf     >/dev/null 2>&1; then echo "nautilus-python"
    elif command -v zypper  >/dev/null 2>&1; then echo "python3-nautilus"
    elif command -v pacman  >/dev/null 2>&1; then echo "nautilus-python"
    fi
}

dep_argv() {
    local pkg="$1"
    if   command -v apt-get >/dev/null 2>&1; then
        printf '%s\n' apt-get install -y "${pkg}"
    elif command -v dnf >/dev/null 2>&1; then
        printf '%s\n' dnf install -y "${pkg}"
    elif command -v zypper >/dev/null 2>&1; then
        printf '%s\n' zypper --non-interactive install "${pkg}"
    elif command -v pacman >/dev/null 2>&1; then
        printf '%s\n' pacman -S --needed --noconfirm "${pkg}"
    fi
}

install_loader() {
    local pkg argv=() runner=() reply
    pkg="$(dep_package)"
    if [[ -z "${pkg}" ]]; then
        echo "warning: nautilus-python is missing and no package manager this" >&2
        echo "         script knows (apt-get, dnf, zypper, pacman) was found." >&2
        echo "         Install it yourself and re-run." >&2
        return 1
    fi
    mapfile -t argv < <(dep_argv "${pkg}")

    if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
        if ! command -v sudo >/dev/null 2>&1; then
            echo "warning: ${pkg} is missing and sudo is not available." >&2
            echo "         Run this as root:  ${argv[*]}" >&2
            return 1
        fi
        runner=(sudo)
    fi

    echo "nautilus-python is not installed. Without it nautilus will ignore"
    echo "this extension entirely, with no error to tell you so."
    echo
    echo "  ${runner[*]:+${runner[*]} }${argv[*]}"
    echo

    # Never sudo without being told to. --yes covers scripted installs; an
    # absent terminal means nobody is there to answer, so print the command
    # and let them run it rather than hanging on a prompt forever.
    if [[ "${ASSUME_YES}" -ne 1 ]]; then
        if [[ ! -t 0 ]]; then
            echo "warning: not running on a terminal, so not asking. Run the" >&2
            echo "         command above, or re-run with --yes." >&2
            return 1
        fi
        read -r -p "Run it now? [Y/n] " reply
        if [[ "${reply}" =~ ^[Nn] ]]; then
            echo "Skipped. The column will not appear until it is installed."
            return 1
        fi
    fi

    "${runner[@]}" "${argv[@]}"
}

if ! loader_present; then
    if [[ "${SKIP_DEPS}" -eq 1 ]]; then
        echo "warning: nautilus-python not found, and --skip-deps was given." >&2
    else
        install_loader || true
        if ! loader_present; then
            echo "warning: still cannot find libnautilus-python.so. Copying the" >&2
            echo "         extension anyway; it will start working once" >&2
            echo "         nautilus-python is installed." >&2
        fi
    fi
fi

mkdir -p "${DEST}"
cp -v "${SRC}" "${DEST}/"

echo
echo "Installed to ${DEST}/${FILE}"
echo "Now run:  nautilus -q      (this closes open file manager windows)"
echo "Then reopen Files and switch to List View. The Total Size column turns"
echo "itself on the first time the extension loads."
