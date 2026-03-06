#!/bin/bash
set -e
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo "Creating venv..."
  # Use --copies to avoid symlink issues on external drives (exFAT/NTFS/APFS)
  if ! python3 -m venv --copies .venv; then
    echo "Primary venv creation failed. Trying virtualenv in-place..."
    python3 -m pip install --user virtualenv
    if ! python3 -m virtualenv --copies .venv; then
      echo "In-place virtualenv failed. Trying temp dir on same drive..."
      TMP_VENV=".venv_tmp"
      rm -rf "$TMP_VENV"
      python3 -m virtualenv --copies "$TMP_VENV"
      mv "$TMP_VENV" .venv
    fi
  fi
fi

. .venv/bin/activate
.venv/bin/python -m pip install --upgrade pip

echo "Installing dependencies..."
.venv/bin/python -m pip install -r requirements.txt

echo "Done. You can now run run_mac.command"
