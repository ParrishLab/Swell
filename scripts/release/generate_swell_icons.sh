#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ASSET_DIR="$REPO_ROOT/swell/resources/assets"

PRIMARY_SOURCE_DEFAULT="$ASSET_DIR/swell_doc_icon_source.png"
FALLBACK_SOURCE_DEFAULT="$ASSET_DIR/swell_doc_icon_reference.jpg"
SOURCE_PATH="${1:-$PRIMARY_SOURCE_DEFAULT}"
FALLBACK_PATH="${2:-$FALLBACK_SOURCE_DEFAULT}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [ ! -f "$SOURCE_PATH" ]; then
  if [ -f "$FALLBACK_PATH" ]; then
    SOURCE_PATH="$FALLBACK_PATH"
  else
    echo "No source image found. Looked for:"
    echo "  $SOURCE_PATH"
    echo "  $FALLBACK_PATH"
    exit 1
  fi
fi

mkdir -p "$ASSET_DIR"
if [ "$SOURCE_PATH" != "$ASSET_DIR/swell_doc_icon_source.png" ]; then
  cp "$SOURCE_PATH" "$ASSET_DIR/swell_doc_icon_source.png"
fi
if [ -f "$FALLBACK_PATH" ]; then
  if [ "$FALLBACK_PATH" != "$ASSET_DIR/swell_doc_icon_reference.jpg" ]; then
    cp "$FALLBACK_PATH" "$ASSET_DIR/swell_doc_icon_reference.jpg"
  fi
fi

"$PYTHON_BIN" - "$SOURCE_PATH" "$ASSET_DIR/swell_doc_icon.ico" "$ASSET_DIR/swell_doc_icon.icns" <<'PY'
from pathlib import Path
import sys

from PIL import Image

src = Path(sys.argv[1]).expanduser().resolve()
ico_out = Path(sys.argv[2]).expanduser().resolve()
icns_out = Path(sys.argv[3]).expanduser().resolve()

img = Image.open(src).convert("RGBA")

ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
img.save(ico_out, format="ICO", sizes=ico_sizes)

icns_sizes = [(16, 16), (32, 32), (64, 64), (128, 128), (256, 256), (512, 512), (1024, 1024)]
img.save(icns_out, format="ICNS", sizes=icns_sizes)
PY

echo "Generated:"
echo "  $ASSET_DIR/swell_doc_icon.ico"
echo "  $ASSET_DIR/swell_doc_icon.icns"
