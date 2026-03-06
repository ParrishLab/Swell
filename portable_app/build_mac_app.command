#!/bin/bash
set -e
cd "$(dirname "$0")"

APP_NAME="SD_Segmenter"
DIST_DIR="dist_app"

# Ensure build deps + runtime deps (PyInstaller analyzes imports)
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
python3 -m pip install -r requirements-build.txt

# Clean previous build
rm -rf build "$DIST_DIR"

# Build app bundle (onedir for easier external assets)
# Workaround for OpenMP runtime duplication during torch import
export KMP_DUPLICATE_LIB_OK=TRUE
pyinstaller \
  --name "$APP_NAME" \
  --windowed \
  --icon "assets/app_icon.icns" \
  --onedir \
  --clean \
  --hidden-import cv2 \
  --collect-binaries cv2 \
  --collect-submodules cv2 \
  --add-data "config.json:." \
  --add-data "configs:configs" \
  app/app.py

# Arrange output
mkdir -p "$DIST_DIR"
rm -rf "$DIST_DIR/$APP_NAME"
cp -R "dist/$APP_NAME" "$DIST_DIR/$APP_NAME"

# Copy models folder next to app (external, avoids bundling huge weights)
mkdir -p "$DIST_DIR/$APP_NAME/models"
cp -R "models/"* "$DIST_DIR/$APP_NAME/models/" 2>/dev/null || true

# Copy configs next to app as a fallback
mkdir -p "$DIST_DIR/$APP_NAME/configs"
cp -R "configs/"* "$DIST_DIR/$APP_NAME/configs/" 2>/dev/null || true

# Copy run scripts
cp run_mac.command "$DIST_DIR/$APP_NAME/run_mac.command"
cp run_win.bat "$DIST_DIR/$APP_NAME/run_win.bat" 2>/dev/null || true

chmod +x "$DIST_DIR/$APP_NAME/run_mac.command"

echo "Built app at: $DIST_DIR/$APP_NAME"
