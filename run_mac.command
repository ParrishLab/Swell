#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

unset MallocStackLogging MallocStackLoggingNoCompact MallocStackLoggingDirectory

PYTHON_BIN="python3"
if [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
  PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
fi

exec "$PYTHON_BIN" -m swell.main "$@"
