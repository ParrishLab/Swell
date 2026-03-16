#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

cd "$REPO_ROOT"

echo "[release] Cleaning build outputs..." >&2
rm -rf "$REPO_ROOT/dist" "$REPO_ROOT/build"

if ! "$PYTHON_BIN" -m build --version >/dev/null 2>&1; then
  echo "[release] ERROR: python build module is not installed. Install with: $PYTHON_BIN -m pip install build" >&2
  exit 1
fi

echo "[release] Building wheel + sdist..." >&2
"$PYTHON_BIN" -m build

if "$PYTHON_BIN" -m twine --version >/dev/null 2>&1; then
  echo "[release] Running twine check..." >&2
  "$PYTHON_BIN" -m twine check dist/*
else
  echo "[release] twine not installed; skipping twine check." >&2
fi

echo "[release] Python artifacts complete." >&2
