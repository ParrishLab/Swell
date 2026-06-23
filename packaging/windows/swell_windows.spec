# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

_spec_path = Path(globals().get("__file__", "packaging/windows/swell_windows.spec")).resolve()
ROOT = _spec_path.parents[2]
doc_icon_ico = ROOT / "swell" / "resources" / "assets" / "swell_doc_icon.ico"

datas = [
    entry
    for entry in collect_data_files("swell")
    if "resources/updater/" not in entry[0]
]
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

for pkg in ("sam2", "hydra", "hydra_plugins", "omegaconf", "openpyxl"):
    hiddenimports += collect_submodules(pkg)

for pkg in ("sam2", "hydra", "omegaconf", "openpyxl"):
    datas += collect_data_files(pkg)

binaries += collect_dynamic_libs("torch")

a = Analysis(
    [str(ROOT / "swell" / "main.py")],
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
    name="Swell",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(ROOT / "swell" / "resources" / "assets" / "app_icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Swell",
)
