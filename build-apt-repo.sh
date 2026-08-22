#!/usr/bin/env bash
# Assemble a signed apt repository from the .deb files in dist/.
#
# This is the "auto upgrade" mechanism: rather than this project growing a
# self-updater, it publishes an apt repository and the machine's own update
# process upgrades it like anything else. That keeps three promises the
# README makes and a self-updater would have broken -- no network access from
# our own code, no background service, and no privileged helper -- while
# actually being MORE automatic than a bespoke updater, because unattended
# upgrades and the Software app already know how to use it.
#
#   ./build-apt-repo.sh --key <KEYID>
#   ./build-apt-repo.sh --key <KEYID> --out apt --suite stable
#
# Produces ./apt/, ready to publish as the root of a GitHub Pages site.
#
# apt REQUIRES the repository to be signed. There is a well-known workaround,
# [trusted=yes] in the sources line, and it is not offered here: it disables
# the check that stops whoever controls the network from handing your users a
# different package. Signing is one command; teaching people to disable
# verification is forever.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

KEY=""
OUT="${HERE}/apt"
SUITE="stable"
ORIGIN="show-folder-size-nautilus"
# nautilus-total-size is the name this project used up to 0.4.0. Its .debs are
# still in dist/, and publishing them would put an obsolete package name in
# front of users as something installable. Excluded unless asked for, which is
# worth having because installing 0.4.0 and upgrading is the only real test of
# the Conflicts/Replaces rename handling.
INCLUDE_LEGACY=0
LEGACY_PACKAGE="nautilus-total-size"
# Architecture: all packages must still be advertised under each concrete
# architecture. Some apt versions only fetch binary-<arch> for the arches they
# are configured for and never look at binary-all, so an arch-all package that
# exists only there is invisible on those machines.
ARCHES=(all amd64 arm64 i386)

while [[ $# -gt 0 ]]; do
    case "$1" in
        --key)   KEY="$2"; shift 2 ;;
        --out)   OUT="$2"; shift 2 ;;
        --suite) SUITE="$2"; shift 2 ;;
        --include-legacy) INCLUDE_LEGACY=1; shift ;;
        -h|--help)
            sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) echo "error: unknown argument: $1" >&2; exit 1 ;;
    esac
done

[[ -n "${KEY}" ]] || {
    echo "error: --key <KEYID> is required (the GPG key to sign with)." >&2
    echo "       Create one, if you have not:" >&2
    echo "         gpg --quick-generate-key 'Your Name <you@example.com>' default default never" >&2
    echo "       Then list it:  gpg --list-secret-keys --keyid-format=long" >&2
    exit 1
}

for tool in apt-ftparchive dpkg-scanpackages gpg; do
    command -v "${tool}" >/dev/null 2>&1 || {
        echo "error: ${tool} not found. Install: sudo apt install apt-utils dpkg-dev gnupg" >&2
        exit 1
    }
done

gpg --list-secret-keys "${KEY}" >/dev/null 2>&1 || {
    echo "error: no secret key matching '${KEY}' in your keyring." >&2
    exit 1
}

shopt -s nullglob
DEBS=("${HERE}/dist/"*.deb)
shopt -u nullglob
[[ ${#DEBS[@]} -gt 0 ]] || {
    echo "error: no .deb files in ${HERE}/dist. Run ./build-deb.sh first." >&2
    exit 1
}

echo "Building apt repository in ${OUT}"
rm -rf "${OUT}"
mkdir -p "${OUT}/pool/main"

# Every .deb in dist/ goes in, old versions included and deliberately. An apt
# repository holding only the newest version cannot answer "install 0.6.0" or
# roll anyone back, and the whole point of this exercise is upgrades: there
# has to be something to upgrade FROM.
POOLED=0
for deb in "${DEBS[@]}"; do
    package="$(dpkg-deb --field "${deb}" Package)"
    if [[ "${package}" == "${LEGACY_PACKAGE}" && ${INCLUDE_LEGACY} -eq 0 ]]; then
        echo "  skip: ${package} $(dpkg-deb --field "${deb}" Version) (obsolete name; --include-legacy to publish it)"
        continue
    fi
    letter="${package:0:1}"
    mkdir -p "${OUT}/pool/main/${letter}/${package}"
    install -m 0644 "${deb}" "${OUT}/pool/main/${letter}/${package}/"
    echo "  pool: ${package} $(dpkg-deb --field "${deb}" Version)"
    POOLED=$((POOLED + 1))
done

[[ ${POOLED} -gt 0 ]] || {
    echo "error: nothing to publish." >&2
    exit 1
}

cd "${OUT}"

for arch in "${ARCHES[@]}"; do
    mkdir -p "dists/${SUITE}/main/binary-${arch}"
    # -m (--multiversion) is not optional here. Without it dpkg-scanpackages
    # emits only the NEWEST version of each package name, so every older
    # release sits in the pool unreachable: apt cannot install one, cannot be
    # rolled back to one, and there is nothing to upgrade FROM, which is the
    # one thing this repository exists to make possible.
    dpkg-scanpackages -m --arch all pool/main /dev/null 2>/dev/null \
        > "dists/${SUITE}/main/binary-${arch}/Packages"
    gzip -9cn "dists/${SUITE}/main/binary-${arch}/Packages" \
        > "dists/${SUITE}/main/binary-${arch}/Packages.gz"
done
echo "  index: $(grep -c '^Package:' "dists/${SUITE}/main/binary-all/Packages") package(s) per architecture"

# apt-ftparchive computes the checksums of everything under dists/<suite>,
# which is what apt verifies each Packages file against. Hand-rolling that is
# possible and is how repositories end up subtly broken.
apt-ftparchive \
    -o "APT::FTPArchive::Release::Origin=${ORIGIN}" \
    -o "APT::FTPArchive::Release::Label=${ORIGIN}" \
    -o "APT::FTPArchive::Release::Suite=${SUITE}" \
    -o "APT::FTPArchive::Release::Codename=${SUITE}" \
    -o "APT::FTPArchive::Release::Architectures=${ARCHES[*]}" \
    -o "APT::FTPArchive::Release::Components=main" \
    -o "APT::FTPArchive::Release::Description=Total Size column for GNOME Files" \
    release "dists/${SUITE}" > "dists/${SUITE}/Release"

# InRelease (signature inline) is what modern apt fetches; Release.gpg is the
# detached form older clients ask for. Ship both: they cost nothing and the
# failure mode of missing one is an unhelpful "repository is not signed".
rm -f "dists/${SUITE}/InRelease" "dists/${SUITE}/Release.gpg"
gpg --batch --yes --default-key "${KEY}" \
    --clearsign -o "dists/${SUITE}/InRelease" "dists/${SUITE}/Release"
gpg --batch --yes --default-key "${KEY}" \
    -abs -o "dists/${SUITE}/Release.gpg" "dists/${SUITE}/Release"

# The public key, dearmored, because that is the form signed-by= wants. Armour
# it and apt fails with a message that does not mention the encoding.
gpg --export "${KEY}" > "${OUT}/show-folder-size-nautilus.gpg"

# GitHub Pages runs Jekyll by default, which silently omits directories that
# begin with an underscore and can rewrite what it serves. .nojekyll turns
# that off and publishes the tree verbatim, which is what a repository needs.
touch "${OUT}/.nojekyll"

echo
echo "Built: ${OUT}"
echo "Signed with: $(gpg --list-secret-keys --keyid-format=long "${KEY}" | sed -n 's/^ *//;2p')"
echo
echo "Publish the contents of ${OUT} as the root of your Pages site, then"
echo "users add it once with:"
echo
cat <<'INSTRUCTIONS'
  sudo install -d -m 0755 /etc/apt/keyrings
  sudo curl -fsSL -o /etc/apt/keyrings/show-folder-size-nautilus.gpg \
    https://doggylover314.github.io/show-folder-size-nautilus/show-folder-size-nautilus.gpg
  echo "deb [signed-by=/etc/apt/keyrings/show-folder-size-nautilus.gpg] https://doggylover314.github.io/show-folder-size-nautilus stable main" \
    | sudo tee /etc/apt/sources.list.d/show-folder-size-nautilus.list
  sudo apt update
  sudo apt install show-folder-size-nautilus

From then on it upgrades with the rest of the system: no updater in this
project, nothing checking the network from inside nautilus, and unattended
upgrades pick it up on its own.
INSTRUCTIONS
