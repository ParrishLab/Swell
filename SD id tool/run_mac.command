#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

if [[ ! -x "$(command -v python3)" ]]; then
  echo "Error: python3 was not found in PATH."
  exit 1
fi

if [[ ! -f ".venv/bin/activate" ]]; then
  if [[ -d ".venv" ]]; then
    echo "Found incomplete .venv (missing bin/activate). Rebuilding..."
    rm -rf .venv
  else
    echo "Creating virtual environment..."
  fi
  python3 -m venv .venv
fi

source .venv/bin/activate

if [[ -f "requirements.merged.txt" ]]; then
  echo "Installing/updating dependencies..."
  python -m pip install --upgrade pip
  pip install -r requirements.merged.txt
fi

echo "Launching GUI..."
python "SD id tool/main.py"
