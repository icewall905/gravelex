#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
repo="${GRAVELEX_REPOSITORY:?Set GRAVELEX_REPOSITORY to the GitHub owner/repository to download from}"
[[ "$repo" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || { echo 'Invalid owner/repository' >&2; exit 1; }
mkdir -p downloads
tmp="$(mktemp -d downloads/.fetch.XXXXXX)"
trap 'rm -rf "$tmp"' EXIT
curl --fail --location --proto '=https' "https://github.com/$repo/releases/latest/download/GravelEx.apk" -o "$tmp/GravelEx.apk"
curl --fail --location --proto '=https' "https://github.com/$repo/releases/latest/download/SHA256SUMS" -o "$tmp/SHA256SUMS"
(cd "$tmp" && sha256sum --check SHA256SUMS)
mv "$tmp/GravelEx.apk" downloads/GravelEx.apk
echo 'Verified latest APK saved in downloads/GravelEx.apk'
