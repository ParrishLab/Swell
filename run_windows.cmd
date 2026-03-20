@echo off
setlocal

cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m sdapp.main %*
) else (
  python -m sdapp.main %*
)
