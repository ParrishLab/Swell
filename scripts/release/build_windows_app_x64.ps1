Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "../..")
$PythonBin = if ($env:PYTHON_BIN) { $env:PYTHON_BIN } else { "python" }

$SpecPath = Join-Path $RepoRoot "packaging/windows/sdapp_windows.spec"
$InstallerScript = Join-Path $RepoRoot "packaging/windows/sdapp_installer.nsi"
$DistRoot = Join-Path $RepoRoot "dist"
$ArchDist = Join-Path $DistRoot "windows-x64"
$WorkPath = Join-Path $RepoRoot "build/pyinstaller-windows-x64"
$ZipOut = Join-Path $DistRoot "sdapp-windows-x64.zip"
$InstallerFlag = if ($null -ne $env:SDAPP_BUILD_INSTALLER) { "$env:SDAPP_BUILD_INSTALLER" } else { "" }
$BuildInstaller = @("1", "true", "yes") -contains $InstallerFlag.ToLowerInvariant()

& $PythonBin -m PyInstaller --version | Out-Null
& $PythonBin "$RepoRoot/scripts/release/validate_model_runtime.py"
& $PythonBin "$RepoRoot/scripts/release/validate_windows_installer_metadata.py" --repo-root "$RepoRoot"

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

if ($BuildInstaller) {
  $makensis = Get-Command "makensis" -ErrorAction SilentlyContinue
  if (-not $makensis) {
    throw "[release] ERROR: SDAPP_BUILD_INSTALLER is enabled but makensis was not found on PATH."
  }
  Push-Location $RepoRoot
  try {
    & $makensis.Path $InstallerScript
  }
  finally {
    Pop-Location
  }
  Write-Host "[release] Windows installer build complete (NSIS)."
}
else {
  Write-Host "[release] Windows installer build skipped (set SDAPP_BUILD_INSTALLER=1 to enable)."
}
