#!/bin/bash
set -euo pipefail

APP_PATH="${1:-/Applications/Swell.app}"
LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"

if [ ! -d "$APP_PATH" ]; then
  echo "App bundle not found: $APP_PATH"
  exit 1
fi

if [ ! -x "$LSREGISTER" ]; then
  echo "lsregister not found at expected path."
  exit 1
fi

"$LSREGISTER" -f "$APP_PATH"
killall Finder >/dev/null 2>&1 || true

echo "Refreshed LaunchServices registration for $APP_PATH."
echo "Existing .swell files should now pick up the registered icon/association."
