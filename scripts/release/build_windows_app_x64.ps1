Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "../..")
$PythonBin = if ($env:PYTHON_BIN) { $env:PYTHON_BIN } else { "python" }

$SpecPath = Join-Path $RepoRoot "packaging/windows/sdapp_windows.spec"
$DistRoot = Join-Path $RepoRoot "dist"
$ArchDist = Join-Path $DistRoot "windows-x64"
$WorkPath = Join-Path $RepoRoot "build/pyinstaller-windows-x64"
$ZipOut = Join-Path $DistRoot "sdapp-windows-x64.zip"

& $PythonBin -m PyInstaller --version | Out-Null
& $PythonBin "$RepoRoot/scripts/release/validate_model_runtime.py"

if (Test-Path $ArchDist) { Remove-Item -Recurse -Force $ArchDist }
if (Test-Path $WorkPath) { Remove-Item -Recurse -Force $WorkPath }
if (Test-Path $ZipOut) { Remove-Item -Force $ZipOut }
New-Item -ItemType Directory -Force -Path $ArchDist | Out-Null

& $PythonBin -m PyInstaller $SpecPath --noconfirm --clean --distpath $ArchDist --workpath $WorkPath

$AppDir = Join-Path $ArchDist "SDApp"
if (!(Test-Path $AppDir)) {
  throw "[release] ERROR: expected app directory not found: $AppDir"
}

Compress-Archive -Path $AppDir -DestinationPath $ZipOut -CompressionLevel Optimal -Force

Write-Host "[release] Windows x64 bundle ready: $AppDir"
Write-Host "[release] Archive: $ZipOut"
