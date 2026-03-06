@echo off
setlocal
cd /d %~dp0

set APP_NAME=SD_Segmenter
set DIST_DIR=dist_app

echo [1/6] Checking Python availability...
python --version >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python is not available on PATH.
  exit /b 1
)

echo [2/6] Installing runtime dependencies...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo [3/6] Installing CPU-only Torch...
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu

echo [4/6] Installing build dependencies...
python -m pip install -r requirements-build.txt

echo [5/6] Building packaged app...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist %DIST_DIR% rmdir /s /q %DIST_DIR%

pyinstaller --name %APP_NAME% --windowed --icon assets\app_icon.ico --onedir --clean --hidden-import cv2 --collect-binaries cv2 --collect-submodules cv2 --add-data "config.json;." --add-data "configs;configs" app\app.py
if errorlevel 1 (
  echo ERROR: PyInstaller build failed.
  exit /b 1
)

mkdir %DIST_DIR%
xcopy /E /I /Y dist\%APP_NAME% %DIST_DIR%\%APP_NAME% >nul

mkdir %DIST_DIR%\%APP_NAME%\models 2>nul
xcopy /E /I /Y models\* %DIST_DIR%\%APP_NAME%\models\ >nul

mkdir %DIST_DIR%\%APP_NAME%\configs 2>nul
xcopy /E /I /Y configs\* %DIST_DIR%\%APP_NAME%\configs\ >nul

copy run_win.bat %DIST_DIR%\%APP_NAME%\run_win.bat >nul
copy run_mac.command %DIST_DIR%\%APP_NAME%\run_mac.command >nul

echo [6/6] Verifying packaged artifacts...
if not exist %DIST_DIR%\%APP_NAME%\%APP_NAME%.exe (
  echo ERROR: Missing executable: %DIST_DIR%\%APP_NAME%\%APP_NAME%.exe
  exit /b 1
)
if not exist %DIST_DIR%\%APP_NAME%\models\sam2.1_hiera_base_plus.pt (
  echo ERROR: Missing model file in package.
  exit /b 1
)
if not exist %DIST_DIR%\%APP_NAME%\configs\sam2.1\sam2.1_hiera_b+.yaml (
  echo ERROR: Missing SAM2 config file in package.
  exit /b 1
)
if not exist %DIST_DIR%\%APP_NAME%\config.json (
  echo ERROR: Missing config.json in package.
  exit /b 1
)

echo Build complete: %DIST_DIR%\%APP_NAME%
endlocal
