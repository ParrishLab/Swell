#!/bin/bash
set -e
cd "$(dirname "$0")"

if [ -f ".venv/bin/python3" ]; then
  UPDATER_PY=".venv/bin/python3"
elif [ -f ".venv/bin/python" ]; then
  UPDATER_PY=".venv/bin/python"
else
  UPDATER_PY="python3"
fi

"$UPDATER_PY" tools/startup_update.py || true

if [ -x "./SD_Segmenter" ]; then
  ./SD_Segmenter
elif [ -f ".venv/bin/python3" ]; then
  .venv/bin/python3 -m app.app
elif [ -f ".venv/bin/python" ]; then
  .venv/bin/python -m app.app
else
  echo "Warning: .venv not found. Falling back to system python."
  python3 -m app.app
fi
