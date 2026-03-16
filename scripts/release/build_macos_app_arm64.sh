#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SPEC_PATH="$REPO_ROOT/packaging/sdapp.spec"
DIST_ROOT="$REPO_ROOT/dist"
ARCH_DIST="$DIST_ROOT/macos-arm64"
WORK_PATH="$REPO_ROOT/build/pyinstaller-arm64"
ZIP_OUT="$DIST_ROOT/sdapp-macos-arm64.zip"

cd "$REPO_ROOT"

if ! "$PYTHON_BIN" -m PyInstaller --version >/dev/null 2>&1; then
  echo "[release] ERROR: PyInstaller is not installed. Install with: $PYTHON_BIN -m pip install pyinstaller" >&2
  exit 1
fi

rm -rf "$ARCH_DIST" "$WORK_PATH" "$ZIP_OUT"
mkdir -p "$ARCH_DIST"

if command -v arch >/dev/null 2>&1; then
  arch -arm64 "$PYTHON_BIN" -m PyInstaller "$SPEC_PATH" --noconfirm --clean --distpath "$ARCH_DIST" --workpath "$WORK_PATH"
else
  "$PYTHON_BIN" -m PyInstaller "$SPEC_PATH" --noconfirm --clean --distpath "$ARCH_DIST" --workpath "$WORK_PATH"
fi

APP_BUNDLE="$ARCH_DIST/SDApp.app"
if [ ! -d "$APP_BUNDLE" ]; then
  echo "[release] ERROR: expected app bundle not found: $APP_BUNDLE" >&2
  exit 1
fi

if command -v ditto >/dev/null 2>&1; then
  (cd "$ARCH_DIST" && ditto -c -k --sequesterRsrc --keepParent "SDApp.app" "$ZIP_OUT")
else
  (cd "$ARCH_DIST" && zip -r "$ZIP_OUT" "SDApp.app")
fi

echo "[release] macOS arm64 bundle ready: $APP_BUNDLE" >&2
echo "[release] Archive: $ZIP_OUT" >&2
