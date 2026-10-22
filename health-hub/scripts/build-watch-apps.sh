#!/usr/bin/env bash
# Build Pebble watch apps against a deployment URL without changing source files.
# Requires the Pebble SDK CLI, Python 3, and a valid public HTTPS base URL.
set -euo pipefail

PUBLIC_URL="${PUBLIC_URL:?Set PUBLIC_URL, for example https://health.example.net}"
PUBLIC_URL="$(python3 - "$PUBLIC_URL" <<'PY'
import sys
from urllib.parse import urlsplit, urlunsplit

value = sys.argv[1].rstrip("/")
parts = urlsplit(value)
if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
    raise SystemExit("PUBLIC_URL must be an HTTPS base URL without credentials, query, or fragment")
print(urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", "")))
PY
)"

HEALTH_HUB_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE_DIR="$HEALTH_HUB_DIR/watchapps"
PEBBLE="${PEBBLE:-pebble}"
OUT="${OUT:-$HEALTH_HUB_DIR/dist/watchapps}"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"

declare -A OUTPUTS=(
  [hrv-watch]=pebblefit-hrv.pbw
  [history-watch]=pebblefit-history.pbw
  [today-watch]=pebblefit-today.pbw
  [watchapp]=pebble-health-sync.pbw
)

for app in hrv-watch history-watch today-watch watchapp; do
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  cp -R "$SOURCE_DIR/$app/." "$tmp/"
  python3 - "$tmp/src/pkjs/index.js" "$PUBLIC_URL" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
source = path.read_text()
source = source.replace("https://pebble-health.example.lan", sys.argv[2])
if "https://pebble-health.example.lan" in source:
    raise SystemExit(f"Unreplaced URL placeholder in {path}")
path.write_text(source)
PY
  (cd "$tmp" && "$PEBBLE" build >/dev/null)
  mapfile -t packages < <(find "$tmp/build" -maxdepth 1 -type f -name '*.pbw' -print)
  if [[ "${#packages[@]}" -ne 1 ]]; then
    printf 'Pebble SDK must produce exactly one package for %s; found %s\n' "$app" "${#packages[@]}" >&2
    exit 1
  fi
  package="${packages[0]}"
  cp "$package" "$OUT/${OUTPUTS[$app]}"
  rm -rf "$tmp"
  trap - EXIT
  printf 'Built %s\n' "$OUT/${OUTPUTS[$app]}"
done
