#!/bin/bash
set -euo pipefail

# Build a fresh portable bundle from this workspace.
# Update these paths as needed.
MODEL_PATH="/Users/claydunford/sam2_models/sam2.1_hiera_base_plus.pt"
CONFIGS_PATH="/Users/claydunford/miniforge3/envs/sam_imaging/lib/python3.11/site-packages/sam2/configs"   # Path to SAM2 configs folder that contains sam2/ and sam2.1/
BUILD_VENV=1   # Set to 1 to create .venv and install requirements in the portable bundle
PYTHON_BIN="python3"

APP_ROOT="$(cd "$(dirname "$0")" && pwd)"
BUILD_ROOT="${APP_ROOT}/dist"
OUT_DIR="${BUILD_ROOT}/portable_app"

if [ -z "$CONFIGS_PATH" ]; then
  echo "CONFIGS_PATH is empty. Set it to your SAM2 configs directory (should contain sam2/ and sam2.1/)."
  exit 1
fi

if [ ! -f "$MODEL_PATH" ]; then
  echo "Model file not found: $MODEL_PATH"
  exit 1
fi

if [ ! -d "$CONFIGS_PATH" ]; then
  echo "Configs path not found: $CONFIGS_PATH"
  exit 1
fi

rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

# Copy app source and configs
cp -R "$APP_ROOT/app" "$OUT_DIR/app"
cp "$APP_ROOT/config.json" "$OUT_DIR/config.json"
cp "$APP_ROOT/requirements.txt" "$OUT_DIR/requirements.txt"
cp "$APP_ROOT/run_win.bat" "$OUT_DIR/run_win.bat"
cp "$APP_ROOT/run_mac.command" "$OUT_DIR/run_mac.command"
cp "$APP_ROOT/bootstrap_win.bat" "$OUT_DIR/bootstrap_win.bat"
cp "$APP_ROOT/bootstrap_mac.command" "$OUT_DIR/bootstrap_mac.command"
if [ -d "$APP_ROOT/assets" ]; then
  cp -R "$APP_ROOT/assets" "$OUT_DIR/assets"
fi

mkdir -p "$OUT_DIR/models" "$OUT_DIR/configs"
cp "$MODEL_PATH" "$OUT_DIR/models/"

# Expect CONFIGS_PATH to include sam2/ and sam2.1/ subfolders
cp -R "$CONFIGS_PATH"/* "$OUT_DIR/configs/"

# Ensure scripts are executable on macOS/Linux
chmod +x "$OUT_DIR/run_mac.command" "$OUT_DIR/bootstrap_mac.command"

if [ "$BUILD_VENV" -eq 1 ]; then
  echo "Creating portable venv..."
  if [ ! -x "$OUT_DIR/.venv/bin/python" ]; then
    "$PYTHON_BIN" -m venv "$OUT_DIR/.venv"
  fi
  "$OUT_DIR/.venv/bin/python" -m pip install --upgrade pip
  echo "Installing dependencies into portable venv..."
  "$OUT_DIR/.venv/bin/python" -m pip install -r "$OUT_DIR/requirements.txt"
  echo "Note: Torch may require a platform-specific install. If SAM2 fails, install torch in the portable venv."
fi

echo "Portable bundle created at: $OUT_DIR"
