#!/usr/bin/env bash
# Assemble the GitHub Pages site: the apt repository at the root, the dnf
# repository under rpm/, both signed with one key, from the packages in dist/.
#
#   ./build-site.sh --key <KEYID>
#   ./build-site.sh --key <KEYID> --out site --base-url https://example.com
#
# This is what .github/workflows/release.yml runs. It is a script rather than
# workflow steps so that the exact thing CI publishes can be built and tested
# on a laptop first.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KEY=""
OUT="${HERE}/site"
BASE_URL="https://doggylover314.github.io/show-folder-size-nautilus"

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
[[ -n "${KEY}" ]] || { echo "error: --key <KEYID> is required." >&2; exit 1; }
[[ "${OUT}" = /* ]] || OUT="${PWD}/${OUT}"

# Order matters: both builders start with rm -rf of their output directory,
# and the apt one owns the site root. Built the other way round, apt would
# delete the dnf repository it had just been handed.
"${HERE}/build-apt-repo.sh" --key "${KEY}" --out "${OUT}" >/dev/null
"${HERE}/build-dnf-repo.sh" --key "${KEY}" --out "${OUT}/rpm" \
    --base-url "${BASE_URL}/rpm" >/dev/null

# Something at the root, so that anyone who follows the URL finds out what
# it is rather than getting a 404.
cat > "${OUT}/index.html" <<EOF
<!doctype html>
<meta charset="utf-8">
<title>show-folder-size-nautilus packages</title>
<h1>show-folder-size-nautilus</h1>
<p>A Total Size column for GNOME Files. This site is its package repository;
the project is at
<a href="https://github.com/doggylover314/show-folder-size-nautilus">GitHub</a>.</p>
<h2>Fedora</h2>
<pre>sudo curl -fsSL -o /etc/yum.repos.d/show-folder-size-nautilus.repo \\
  ${BASE_URL}/rpm/show-folder-size-nautilus.repo
sudo dnf install show-folder-size-nautilus</pre>
<h2>Debian and Ubuntu</h2>
<pre>sudo curl -fsSL -o /etc/apt/keyrings/show-folder-size-nautilus.gpg \\
  ${BASE_URL}/show-folder-size-nautilus.gpg
echo "deb [signed-by=/etc/apt/keyrings/show-folder-size-nautilus.gpg] ${BASE_URL} stable main" \\
  | sudo tee /etc/apt/sources.list.d/show-folder-size-nautilus.list
sudo apt update && sudo apt install show-folder-size-nautilus</pre>
EOF

echo "Built: ${OUT}"
echo "  apt: ${BASE_URL}/  (dists/, pool/)"
echo "  dnf: ${BASE_URL}/rpm/"
