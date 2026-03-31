# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

_spec_path = Path(globals().get("__file__", "packaging/windows/sdapp_windows.spec")).resolve()
ROOT = _spec_path.parents[2]
doc_icon_ico = ROOT / "sdapp" / "resources" / "assets" / "sdproj_doc_icon.ico"

datas = collect_data_files("sdapp")
binaries = []
hiddenimports = []

if not doc_icon_ico.exists():
    raise FileNotFoundError(f"Missing Windows document icon asset: {doc_icon_ico}")

# The installer registers the document icon from the install root.
datas.append((str(doc_icon_ico), "."))

# TIFF decoding in frozen Windows builds may require optional image codec
# extension modules that PyInstaller does not always infer transitively.
hiddenimports += collect_submodules("imagecodecs")
hiddenimports += collect_submodules("PIL")
binaries += collect_dynamic_libs("imagecodecs")
binaries += collect_dynamic_libs("PIL")

for pkg in ("sam2", "hydra", "hydra_plugins", "omegaconf"):
    hiddenimports += collect_submodules(pkg)

for pkg in ("sam2", "hydra", "omegaconf"):
    datas += collect_data_files(pkg)

binaries += collect_dynamic_libs("torch")

winsparkle_dll = ROOT / "sdapp" / "resources" / "updater" / "windows" / "WinSparkle.dll"
if winsparkle_dll.exists():
    binaries.append((str(winsparkle_dll), "."))

a = Analysis(
    [str(ROOT / "sdapp" / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SDApp",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(ROOT / "sdapp" / "resources" / "assets" / "app_icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="SDApp",
)
