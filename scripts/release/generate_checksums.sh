#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ARTIFACT_DIR="${1:-$REPO_ROOT/dist}"
OUTPUT_FILE="${2:-$ARTIFACT_DIR/SHA256SUMS.txt}"

mkdir -p "$ARTIFACT_DIR"

if command -v shasum >/dev/null 2>&1; then
  HASH_TOOL=(shasum -a 256)
elif command -v sha256sum >/dev/null 2>&1; then
  HASH_TOOL=(sha256sum)
else
  echo "[release] ERROR: neither shasum nor sha256sum is available." >&2
  exit 1
fi

TMP_FILE="$(mktemp)"
trap 'rm -f "$TMP_FILE"' EXIT

find "$ARTIFACT_DIR" -maxdepth 1 -type f ! -name "$(basename "$OUTPUT_FILE")" -print0 | \
  sort -z | \
  while IFS= read -r -d '' file; do
    (cd "$ARTIFACT_DIR" && "${HASH_TOOL[@]}" "$(basename "$file")")
  done > "$TMP_FILE"

mv "$TMP_FILE" "$OUTPUT_FILE"

echo "[release] Wrote checksums: $OUTPUT_FILE" >&2
