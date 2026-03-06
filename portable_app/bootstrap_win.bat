@echo off
setlocal
cd /d %~dp0

if not exist ".venv\Scripts\python.exe" (
  echo Creating venv...
  python -m venv --copies .venv
  if errorlevel 1 (
    echo Primary venv creation failed. Falling back to temp location...
    set "TMP_VENV=%TEMP%\portable_app_venv_%RANDOM%"
    python -m venv --copies "%TMP_VENV%"
    if exist "%TMP_VENV%\Scripts\python.exe" (
      move "%TMP_VENV%" ".venv" >nul
    ) else (
      echo Failed to create venv in temp location.
      exit /b 1
    )
  )
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip

echo Installing dependencies...
python -m pip install -r requirements.txt

echo Done. You can now run run_win.bat
endlocal
