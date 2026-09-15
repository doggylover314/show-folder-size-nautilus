#!/usr/bin/env bash
# Assemble a signed dnf/yum repository from the .rpm files in dist/.
#
# The Fedora counterpart of build-apt-repo.sh, and it exists for the same
# reason: rather than this project growing a self-updater, it publishes a
# repository and the machine's own update process upgrades it like anything
# else. No network access from our own code, no background service, no
# privileged helper, and it is more automatic than a bespoke updater because
# dnf-automatic and GNOME Software already know how to use it.
#
#   ./build-dnf-repo.sh --key <KEYID>
#   ./build-dnf-repo.sh --key <KEYID> --out dnf --base-url https://example.com/rpm
#
# Produces ./dnf/, ready to publish under the rpm/ path of a Pages site, so
# that one site can carry both repositories without them colliding: apt owns
# dists/ and pool/ at the root, this owns everything under rpm/.
#
# Two signatures, and both are needed, which is the part people get wrong:
#
#   repomd.xml.asc  signs the metadata, and is what repo_gpgcheck=1 checks.
#   each .rpm       signed in place, and is what gpgcheck=1 checks.
#
# Signing only the metadata leaves gpgcheck=1 failing on every package, and
# signing only the packages leaves the index itself unauthenticated. dnf will
# happily let you disable either check; that is not offered here, for the
# same reason [trusted=yes] is not offered in the apt script.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

KEY=""
OUT="${HERE}/dnf"
REPO_ID="show-folder-size-nautilus"
BASE_URL="https://doggylover314.github.io/show-folder-size-nautilus/rpm"
KEYFILE="RPM-GPG-KEY-show-folder-size-nautilus"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --key)      KEY="$2"; shift 2 ;;
        --out)      OUT="$2"; shift 2 ;;
        --base-url) BASE_URL="${2%/}"; shift 2 ;;
        -h|--help)
            awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' \
                "${BASH_SOURCE[0]}"
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

for tool in createrepo_c rpmsign gpg; do
    command -v "${tool}" >/dev/null 2>&1 || {
        echo "error: ${tool} not found." >&2
        echo "       Fedora:        sudo dnf install createrepo_c rpm-sign gnupg2" >&2
        echo "       Debian/Ubuntu: sudo apt install createrepo-c rpm gnupg" >&2
        exit 1
    }
done

gpg --list-secret-keys "${KEY}" >/dev/null 2>&1 || {
    echo "error: no secret key matching '${KEY}' in your keyring." >&2
    exit 1
}

shopt -s nullglob
RPMS=("${HERE}/dist/"*.rpm)
shopt -u nullglob
[[ ${#RPMS[@]} -gt 0 ]] || {
    echo "error: no .rpm files in ${HERE}/dist. Run ./build-rpm.sh first." >&2
    exit 1
}

echo "Building dnf repository in ${OUT}"
rm -rf "${OUT}"
mkdir -p "${OUT}/packages"

# Copy before signing. rpmsign rewrites the file in place, and dist/ holds the
# artifacts that get attached to a GitHub release -- those should stay exactly
# as build-rpm.sh produced them rather than quietly gaining a signature
# halfway through a release.
for rpm in "${RPMS[@]}"; do
    cp "${rpm}" "${OUT}/packages/"
    echo "  package: $(basename "${rpm}")"
done

# --define rather than a ~/.rpmmacros edit: this has to work on a machine
# whose macros nobody has set up, and it must not leave state behind on one
# whose macros are already set to something else.
echo "  signing packages"
rpmsign --define "_gpg_name ${KEY}" --addsign "${OUT}/packages/"*.rpm >/dev/null

# Prove it took, because a repository that silently published unsigned
# packages would not fail here -- it would fail at every user's dnf.
#
# Read the output, not the exit status. `rpm -K` exits NON-ZERO on a
# correctly signed package whenever the public key is absent from rpm's own
# keyring, which is a different keyring from gpg's and one the build machine
# has no reason to have populated. Piping into grep does not help either:
# under `set -o pipefail` the pipeline reports rpm's status, not grep's, so
# the check failed on packages it had just signed successfully.
for rpm in "${OUT}/packages/"*.rpm; do
    verified="$(rpm -Kv "${rpm}" 2>/dev/null || true)"
    case "${verified}" in
        *Signature*) ;;
        *) echo "error: $(basename "${rpm}") is still unsigned after rpmsign." >&2
           exit 1 ;;
    esac
done

echo "  indexing"
createrepo_c --quiet "${OUT}"

# repo_gpgcheck=1 looks for repomd.xml.asc next to repomd.xml. Detached and
# armoured, which is the one combination dnf accepts here.
rm -f "${OUT}/repodata/repomd.xml.asc"
gpg --batch --yes --default-key "${KEY}" \
    --detach-sign --armor -o "${OUT}/repodata/repomd.xml.asc" \
    "${OUT}/repodata/repomd.xml"

# Check our own work: this one can be verified completely, because the signing
# key is in the keyring we just signed with.
gpg --batch --verify "${OUT}/repodata/repomd.xml.asc" \
    "${OUT}/repodata/repomd.xml" 2>/dev/null || {
    echo "error: the metadata signature does not verify against ${KEY}." >&2
    exit 1
}

# Armoured, unlike the apt key. apt's signed-by= wants the dearmoured binary
# form; dnf's gpgkey= wants this one. Same key, two encodings, and each tool
# fails with a message that does not mention encoding when given the other.
gpg --armor --export "${KEY}" > "${OUT}/${KEYFILE}"

cat > "${OUT}/${REPO_ID}.repo" <<EOF
[${REPO_ID}]
name=Total Size column for GNOME Files
baseurl=${BASE_URL}
enabled=1
gpgcheck=1
repo_gpgcheck=1
gpgkey=${BASE_URL}/${KEYFILE}
metadata_expire=6h
EOF

# GitHub Pages runs Jekyll by default, which silently omits directories that
# begin with an underscore and can rewrite what it serves. .nojekyll turns
# that off and publishes the tree verbatim, which is what a repository needs.
touch "${OUT}/.nojekyll"

echo
echo "Built: ${OUT}"
echo "Signed with: $(gpg --list-secret-keys --keyid-format=long "${KEY}" | sed -n 's/^ *//;2p')"
echo "  $(find "${OUT}/packages" -name '*.rpm' | wc -l) package(s), metadata signed"
echo
echo "Publish the contents of ${OUT} at ${BASE_URL}, then users add it once with:"
echo
cat <<INSTRUCTIONS
  sudo curl -fsSL -o /etc/yum.repos.d/${REPO_ID}.repo \\
    ${BASE_URL}/${REPO_ID}.repo
  sudo dnf install ${REPO_ID}

dnf shows the key's fingerprint and asks before importing it the first time.
From then on it upgrades with the rest of the system: no updater in this
project, nothing checking the network from inside nautilus, and dnf-automatic
picks it up with no further setup.
INSTRUCTIONS
