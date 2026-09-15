#!/usr/bin/env bash
# Install the Total Size column extension for the current user.
#
# Installs nautilus-python if it is missing, then copies one file into
# ~/.local/share/nautilus-python/extensions/.
#
#   ./install.sh               install the extension, and its one dependency
#   ./install.sh --skip-deps   copy the file only, touch nothing else
#   ./install.sh --uninstall   remove the extension
#
# The .deb and .rpm need none of this. Both declare nautilus-python as a
# dependency, so apt and dnf install it themselves; this is for running from
# a clone, where no package manager knows this project exists.
#
# It installs rather than advises on purpose. The previous version printed a
# warning and copied the file anyway, which is the worst of both: the
# extension lands on disk, nautilus silently refuses to load it because the
# loader is missing, and the one line explaining why has already scrolled off
# the screen. Nobody reads a warning that did not stop anything. So this
# either finishes the job or fails loudly, and there is no third outcome.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${HOME}/.local/share/nautilus-python/extensions"
FILE="show_folder_size.py"
SRC="${HERE}/${FILE}"

ACTION=install
SKIP_DEPS=0

if [[ -t 1 ]]; then
    BOLD=$'\033[1m'; RED=$'\033[1;31m'; GREEN=$'\033[1;32m'; OFF=$'\033[0m'
else
    BOLD=""; RED=""; GREEN=""; OFF=""
fi

step() { printf '\n%s==>%s %s\n' "${BOLD}" "${OFF}" "$*"; }
die() {
    printf '\n%s==> FAILED:%s %s\n' "${RED}" "${OFF}" "$1" >&2
    shift
    for line in "$@"; do printf '    %s\n' "${line}" >&2; done
    exit 1
}

# The header comment is the help text. Printed from the file so the two
# cannot drift, and found rather than counted, because a hardcoded line
# range goes stale the moment anyone edits the comment.
usage() {
    awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' \
        "${BASH_SOURCE[0]}"
}

for arg in "$@"; do
    case "${arg}" in
        --uninstall)          ACTION=uninstall ;;
        --skip-deps)          SKIP_DEPS=1 ;;
        -y|--yes)             ;;   # accepted and ignored: installing is now the default
        -h|--help)            usage; exit 0 ;;
        *) printf 'error: unknown option %s\n\n' "${arg}" >&2; usage >&2; exit 2 ;;
    esac
done

if [[ "${ACTION}" == "uninstall" ]]; then
    rm -fv "${DEST}/${FILE}"
    printf '\n%s==> Removed.%s Run '\''nautilus -q'\'' to unload it.\n' "${GREEN}" "${OFF}"
    echo "    nautilus-python is left installed; remove it yourself if you want it gone."
    exit 0
fi

[[ -f "${SRC}" ]] || die "${FILE} not found next to this script." \
    "Run this from a clone of the repository."

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
dep_argv() {
    if   command -v apt-get >/dev/null 2>&1; then
        printf '%s\n' apt-get install -y python3-nautilus
    elif command -v dnf >/dev/null 2>&1; then
        printf '%s\n' dnf install -y nautilus-python
    elif command -v zypper >/dev/null 2>&1; then
        printf '%s\n' zypper --non-interactive install python3-nautilus
    elif command -v pacman >/dev/null 2>&1; then
        printf '%s\n' pacman -S --needed --noconfirm nautilus-python
    fi
}

install_loader() {
    local argv=() runner=()
    mapfile -t argv < <(dep_argv)

    [[ ${#argv[@]} -gt 0 ]] || die \
        "nautilus-python is missing, and no package manager I know was found." \
        "Tried: apt-get, dnf, zypper, pacman." \
        "Install nautilus-python yourself, then run this again." \
        "Or use --skip-deps to copy the extension anyway."

    if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
        command -v sudo >/dev/null 2>&1 || die \
            "nautilus-python is missing and sudo is not available." \
            "Run this as root: ${argv[*]}"
        runner=(sudo)
    fi

    step "Installing nautilus-python (${argv[*]})"
    echo "    The extension cannot load without it. Ctrl-C now to stop."
    "${runner[@]}" "${argv[@]}" || die \
        "'${runner[*]:+${runner[*]} }${argv[*]}' failed." \
        "Fix that, then run this script again." \
        "Or use --skip-deps to copy the extension anyway."
}

if loader_present; then
    step "nautilus-python is already installed"
elif [[ "${SKIP_DEPS}" -eq 1 ]]; then
    step "nautilus-python is missing, and --skip-deps was given"
    echo "    The column will not appear until you install it yourself."
else
    install_loader
    loader_present || die \
        "nautilus-python installed, but its loader still is not there." \
        "Looked for libnautilus-python.so under /usr/lib64, /usr/lib and" \
        "the multiarch directories, in extensions-4 and extensions-3.0." \
        "Please open an issue with your distro and 'nautilus --version'."
fi

# nautilus-python scans the user directory AND the system ones, imports every
# .py it finds in each, and appends whatever providers it finds to one list.
# It does not notice that the same module name turned up twice. The result is
# the provider registered twice and TWO "Total Size" columns drawn, which is
# the exact symptom this project already shipped once, in the 0.5.0 rename.
# So say something before creating the second copy rather than after.
for system_copy in /usr/share/nautilus-python/extensions/"${FILE}"                    /usr/local/share/nautilus-python/extensions/"${FILE}"; do
    [[ -e "${system_copy}" ]] || continue
    step "Heads up: ${FILE} is already installed system-wide"
    echo "    ${system_copy}"
    echo "    Two copies means nautilus loads it twice and draws TWO Total Size"
    echo "    columns. Remove the package (apt remove / dnf remove"
    echo "    show-folder-size-nautilus) if you want this user copy instead,"
    echo "    or run ./install.sh --uninstall to keep the packaged one."
done

step "Installing the extension"
mkdir -p "${DEST}"
cp -v "${SRC}" "${DEST}/"

printf '\n%s==> Done.%s Now run:  nautilus -q\n' "${GREEN}" "${OFF}"
echo "    That closes any open file manager windows; the next launch loads"
echo "    the extension. Switch to List View and the Total Size column is"
echo "    already there, enabled on first load."
