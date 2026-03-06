#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

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

if [[ -f "requirements.txt" ]]; then
  echo "Installing/updating dependencies..."
  python -m pip install --upgrade pip
  pip install -r requirements.txt
fi

echo "Launching GUI..."
python main.py
