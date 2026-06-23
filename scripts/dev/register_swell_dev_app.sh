#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
APP_NAME="${APP_NAME:-Swell Dev}"
APP_BUNDLE="${APP_BUNDLE:-$REPO_ROOT/build/dev-macos/$APP_NAME.app}"
CONTENTS_DIR="$APP_BUNDLE/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RESOURCES_DIR="$CONTENTS_DIR/Resources"
LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
APP_ICON_SRC="$REPO_ROOT/swell/resources/assets/app_icon.icns"
DOC_ICON_SRC="$REPO_ROOT/swell/resources/assets/swell_doc_icon.icns"
LAUNCH_SCRIPT="$REPO_ROOT/run_mac.command"
LAUNCHER_PATH="$MACOS_DIR/SwellDev"
PLIST_PATH="$CONTENTS_DIR/Info.plist"

if [ ! -x "$LAUNCH_SCRIPT" ]; then
  echo "Launch script not found or not executable: $LAUNCH_SCRIPT" >&2
  exit 1
fi

if [ ! -f "$APP_ICON_SRC" ]; then
  echo "App icon missing: $APP_ICON_SRC" >&2
  exit 1
fi

if [ ! -f "$DOC_ICON_SRC" ]; then
  echo "Document icon missing: $DOC_ICON_SRC" >&2
  exit 1
fi

if [ ! -x "$LSREGISTER" ]; then
  echo "lsregister not found at expected path: $LSREGISTER" >&2
  exit 1
fi

rm -rf "$APP_BUNDLE"
mkdir -p "$MACOS_DIR" "$RESOURCES_DIR"

cp "$APP_ICON_SRC" "$RESOURCES_DIR/app_icon.icns"
cp "$DOC_ICON_SRC" "$RESOURCES_DIR/swell_doc_icon.icns"

cat >"$LAUNCHER_PATH" <<EOF
#!/bin/bash
set -euo pipefail
exec "$LAUNCH_SCRIPT" "\$@"
EOF
chmod +x "$LAUNCHER_PATH"

cat >"$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>en</string>
  <key>CFBundleDisplayName</key>
  <string>$APP_NAME</string>
  <key>CFBundleDocumentTypes</key>
  <array>
    <dict>
      <key>CFBundleTypeIconFile</key>
      <string>swell_doc_icon.icns</string>
      <key>CFBundleTypeName</key>
      <string>Swell Project</string>
      <key>CFBundleTypeRole</key>
      <string>Editor</string>
      <key>LSHandlerRank</key>
      <string>Owner</string>
      <key>LSItemContentTypes</key>
      <array>
        <string>com.swell.project.dev</string>
        <!-- Legacy SDApp project UTI retained for source-checkout file association testing. -->
        <string>com.sdapp.project.dev</string>
      </array>
    </dict>
  </array>
  <key>CFBundleExecutable</key>
  <string>SwellDev</string>
  <key>CFBundleIconFile</key>
  <string>app_icon.icns</string>
  <key>CFBundleIdentifier</key>
  <string>com.swell.desktop.dev</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>$APP_NAME</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>dev</string>
  <key>CFBundleVersion</key>
  <string>dev</string>
  <key>LSMinimumSystemVersion</key>
  <string>11.0</string>
  <key>UTExportedTypeDeclarations</key>
  <array>
    <dict>
      <key>UTTypeConformsTo</key>
      <array>
        <string>public.data</string>
      </array>
      <key>UTTypeDescription</key>
      <string>Swell Project</string>
      <key>UTTypeIdentifier</key>
      <string>com.swell.project.dev</string>
      <key>UTTypeTagSpecification</key>
      <dict>
        <key>public.filename-extension</key>
        <array>
          <string>swell</string>
        </array>
        <key>public.mime-type</key>
        <string>application/x-swell</string>
      </dict>
    </dict>
    <dict>
      <key>UTTypeConformsTo</key>
      <array>
        <string>public.data</string>
      </array>
      <key>UTTypeDescription</key>
      <string>Legacy Swell Project</string>
      <key>UTTypeIdentifier</key>
      <!-- Legacy SDApp project UTI retained for source-checkout file association testing. -->
      <string>com.sdapp.project.dev</string>
      <key>UTTypeTagSpecification</key>
      <dict>
        <key>public.filename-extension</key>
        <array>
          <string>sdproj</string>
        </array>
        <key>public.mime-type</key>
        <string>application/x-sdproj</string>
      </dict>
    </dict>
  </array>
</dict>
</plist>
EOF

printf 'APPL????' >"$CONTENTS_DIR/PkgInfo"

"$LSREGISTER" -f "$APP_BUNDLE"
killall Finder >/dev/null 2>&1 || true

echo "Registered dev app bundle: $APP_BUNDLE"
echo "Double-clicking .swell or legacy .sdproj should now open through the source checkout launcher."
