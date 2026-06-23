# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import tomllib

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

_spec_path = Path(globals().get("__file__", "packaging/swell.spec")).resolve()
ROOT = _spec_path.parents[1]
doc_icon_icns = ROOT / "swell" / "resources" / "assets" / "swell_doc_icon.icns"
APP_VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]

datas = [
    entry
    for entry in collect_data_files("swell")
    if "resources/updater/" not in entry[0]
]
binaries = []
hiddenimports = []

if not doc_icon_icns.exists():
    raise FileNotFoundError(f"Missing macOS document icon asset: {doc_icon_icns}")

# Finder resolves document icons from the bundle resources root.
datas.append((str(doc_icon_icns), "."))

for pkg in ("sam2", "hydra", "hydra_plugins", "omegaconf", "openpyxl"):
    hiddenimports += collect_submodules(pkg)

# SAM2/Hydra resolution in frozen apps can require package data files.
for pkg in ("sam2", "hydra", "omegaconf", "openpyxl"):
    datas += collect_data_files(pkg)

# Torch runtime libraries are needed for model-backed segmentation.
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
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    icon=str(ROOT / "swell" / "resources" / "assets" / "app_icon.icns"),
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

app = BUNDLE(
    coll,
    name="Swell.app",
    icon=str(ROOT / "swell" / "resources" / "assets" / "app_icon.icns"),
    bundle_identifier="com.swell.desktop",
    info_plist={
        "CFBundleShortVersionString": APP_VERSION,
        "CFBundleVersion": APP_VERSION,
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName": "Swell Project",
                "CFBundleTypeRole": "Editor",
                "LSHandlerRank": "Owner",
                "LSItemContentTypes": ["com.swell.project", "com.sdapp.project"],
                "CFBundleTypeIconFile": "swell_doc_icon.icns",
            }
        ],
        "UTExportedTypeDeclarations": [
            {
                "UTTypeIdentifier": "com.sdapp.project",
                "UTTypeDescription": "Legacy Swell Project",
                "UTTypeConformsTo": ["public.data"],
                "UTTypeTagSpecification": {
                    "public.filename-extension": ["sdproj"],
                    "public.mime-type": "application/x-sdproj",
                },
            },
            {
                "UTTypeIdentifier": "com.swell.project",
                "UTTypeDescription": "Swell Project",
                "UTTypeConformsTo": ["public.data"],
                "UTTypeTagSpecification": {
                    "public.filename-extension": ["swell"],
                    "public.mime-type": "application/x-swell",
                },
            },
        ],
    },
)
