#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f ".venv/bin/activate" ]; then
  source ".venv/bin/activate"
fi

unset MallocStackLogging MallocStackLoggingNoCompact MallocStackLoggingDirectory

python3 -m swell.main "$@"
