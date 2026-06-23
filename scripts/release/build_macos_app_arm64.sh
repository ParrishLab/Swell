#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SPEC_PATH="$REPO_ROOT/packaging/swell.spec"
DIST_ROOT="$REPO_ROOT/dist"
ARCH_DIST="$DIST_ROOT/macos-arm64"
WORK_PATH="$REPO_ROOT/build/pyinstaller-arm64"
ZIP_OUT="$DIST_ROOT/swell-macos-arm64.zip"
SIGNATURE_OUT="$DIST_ROOT/swell-macos-arm64-signature.json"
SIGN_UPDATES_FLAG="${SWELL_SIGN_UPDATES:-true}"
SIGN_UPDATES_FLAG_NORMALIZED="$(printf '%s' "$SIGN_UPDATES_FLAG" | tr '[:upper:]' '[:lower:]')"

cd "$REPO_ROOT"

if ! "$PYTHON_BIN" -m PyInstaller --version >/dev/null 2>&1; then
  echo "[release] ERROR: PyInstaller is not installed. Install with: $PYTHON_BIN -m pip install pyinstaller" >&2
  exit 1
fi

"$PYTHON_BIN" "$REPO_ROOT/scripts/release/validate_model_runtime.py"

rm -rf "$ARCH_DIST" "$WORK_PATH" "$ZIP_OUT" "$SIGNATURE_OUT"
mkdir -p "$ARCH_DIST"

if command -v arch >/dev/null 2>&1; then
  arch -arm64 "$PYTHON_BIN" -m PyInstaller "$SPEC_PATH" --noconfirm --clean --distpath "$ARCH_DIST" --workpath "$WORK_PATH"
else
  "$PYTHON_BIN" -m PyInstaller "$SPEC_PATH" --noconfirm --clean --distpath "$ARCH_DIST" --workpath "$WORK_PATH"
fi

APP_BUNDLE="$ARCH_DIST/Swell.app"
if [ ! -d "$APP_BUNDLE" ]; then
  echo "[release] ERROR: expected app bundle not found: $APP_BUNDLE" >&2
  exit 1
fi

if command -v ditto >/dev/null 2>&1; then
  (cd "$ARCH_DIST" && ditto -c -k --sequesterRsrc --keepParent "Swell.app" "$ZIP_OUT")
else
  (cd "$ARCH_DIST" && zip -r "$ZIP_OUT" "Swell.app")
fi

if [[ "$SIGN_UPDATES_FLAG_NORMALIZED" == "1" || "$SIGN_UPDATES_FLAG_NORMALIZED" == "true" || "$SIGN_UPDATES_FLAG_NORMALIZED" == "yes" ]]; then
  "$PYTHON_BIN" "$REPO_ROOT/scripts/release/sign_macos_update.py" \
    --repo-root "$REPO_ROOT" \
    --archive "$ZIP_OUT" \
    --output "$SIGNATURE_OUT"
  echo "[release] Signature: $SIGNATURE_OUT" >&2
else
  echo "[release] Sparkle signature generation skipped (SWELL_SIGN_UPDATES disabled)." >&2
fi

echo "[release] macOS arm64 bundle ready: $APP_BUNDLE" >&2
echo "[release] Archive: $ZIP_OUT" >&2
