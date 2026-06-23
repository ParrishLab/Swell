#!/bin/bash
# Bash port of scripts/release/build_windows_app_x64.ps1 for the tobix/pywine
# container (Wine + Windows Python under Linux). NSIS installer step is handled
# separately on the Linux side with makensis.
set -euo pipefail
export WINEDEBUG=-all
cd /src

PYR="wine python"

echo "[winbuild] pip/setup"
$PYR -m pip install --no-warn-script-location -q -U pip wheel setuptools

echo "[winbuild] installing pinned dependencies (minus sam-2 git ref)"
grep -v "^sam-2" requirements/release-py312-constraints.txt > /tmp/constraints_nosam.txt
$PYR -m pip install --no-warn-script-location -q -r /tmp/constraints_nosam.txt

echo "[winbuild] installing sam2 from local pinned checkout"
$PYR -m pip install --no-warn-script-location -q --no-build-isolation --no-deps ./tmp/sam2-src
$PYR -m pip install --no-warn-script-location -q iopath tqdm portalocker psutil

echo "[winbuild] installing swell (no deps)"
$PYR -m pip install --no-warn-script-location -q --no-deps .

echo "[winbuild] validators"
$PYR scripts/release/validate_model_runtime.py
$PYR scripts/release/validate_windows_installer_metadata.py --repo-root .

echo "[winbuild] cleaning previous outputs"
rm -rf dist/windows-x64 build/pyinstaller-windows-x64 dist/swell-windows-x64.zip
mkdir -p dist/windows-x64

echo "[winbuild] running PyInstaller"
$PYR -m PyInstaller packaging/windows/swell_windows.spec --noconfirm --clean \
  --distpath dist/windows-x64 --workpath build/pyinstaller-windows-x64 --log-level WARN

if [ ! -d dist/windows-x64/Swell ]; then
  echo "[winbuild] ERROR: expected app directory not found: dist/windows-x64/Swell" >&2
  exit 1
fi

echo "[winbuild] frozen-app smoke test"
wine dist/windows-x64/Swell/Swell.exe --smoke-test | tail -1

echo "[winbuild] zipping bundle"
cd dist/windows-x64 && zip -qr ../swell-windows-x64.zip Swell && cd /src
echo "[winbuild] DONE: dist/windows-x64/Swell and dist/swell-windows-x64.zip"
