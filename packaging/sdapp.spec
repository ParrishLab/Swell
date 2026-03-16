# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(__file__).resolve().parents[1]

datas = collect_data_files("sdapp")
hiddenimports = []

a = Analysis(
    [str(ROOT / "sdapp" / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
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
    upx=True,
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
