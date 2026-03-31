# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

_spec_path = Path(globals().get("__file__", "packaging/sdapp.spec")).resolve()
ROOT = _spec_path.parents[1]
doc_icon_icns = ROOT / "sdapp" / "resources" / "assets" / "sdproj_doc_icon.icns"

datas = collect_data_files("sdapp")
binaries = []
hiddenimports = []

if not doc_icon_icns.exists():
    raise FileNotFoundError(f"Missing macOS document icon asset: {doc_icon_icns}")

# Finder resolves document icons from the bundle resources root.
datas.append((str(doc_icon_icns), "."))

for pkg in ("sam2", "hydra", "hydra_plugins", "omegaconf"):
    hiddenimports += collect_submodules(pkg)

# SAM2/Hydra resolution in frozen apps can require package data files.
for pkg in ("sam2", "hydra", "omegaconf"):
    datas += collect_data_files(pkg)

# Torch runtime libraries are needed for model-backed segmentation.
binaries += collect_dynamic_libs("torch")

sparkle_framework = ROOT / "sdapp" / "resources" / "updater" / "macos" / "Sparkle.framework"
if sparkle_framework.exists():
    datas.append((str(sparkle_framework), "updater/macos/Sparkle.framework"))

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
    a.binaries,
    a.datas,
    [],
    name="SDApp",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    icon=str(ROOT / "sdapp" / "resources" / "assets" / "app_icon.icns"),
)

app = BUNDLE(
    exe,
    name="SDApp.app",
    icon=str(ROOT / "sdapp" / "resources" / "assets" / "app_icon.icns"),
    bundle_identifier="com.sdapp.desktop",
    info_plist={
        "SUFeedURL": "https://github.com/ClayDunford/Combined-tool-test/releases/latest/download/appcast-macos.xml",
        "SUPublicEDKey": "FuPzG0WpV5ajjd1Po8ycim/o/aWs74j0wrGTd9+MrY4=",
        "SUEnableAutomaticChecks": True,
        "SUAllowsAutomaticUpdates": True,
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName": "SDApp Project",
                "CFBundleTypeRole": "Editor",
                "LSHandlerRank": "Owner",
                "LSItemContentTypes": ["com.sdapp.project"],
                "CFBundleTypeIconFile": "sdproj_doc_icon.icns",
            }
        ],
        "UTExportedTypeDeclarations": [
            {
                "UTTypeIdentifier": "com.sdapp.project",
                "UTTypeDescription": "SDApp Project",
                "UTTypeConformsTo": ["public.data"],
                "UTTypeTagSpecification": {
                    "public.filename-extension": ["sdproj"],
                    "public.mime-type": "application/x-sdproj",
                },
            }
        ],
    },
)
