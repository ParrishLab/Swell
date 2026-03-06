@echo off
setlocal
cd /d %~dp0

if exist ".venv\Scripts\python.exe" (
  set "UPDATER_PY=.venv\Scripts\python.exe"
) else (
  set "UPDATER_PY=python"
)

"%UPDATER_PY%" tools\startup_update.py
if errorlevel 1 (
  echo [UPDATER] WARN: updater exited non-zero; continuing launch.
)

if exist "SD_Segmenter.exe" (
  "SD_Segmenter.exe"
) else if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m app.app
) else (
  python -m app.app
)
endlocal
