from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_macos_spec_registers_sdproj_document_type() -> None:
    spec = (ROOT / "packaging" / "sdapp.spec").read_text(encoding="utf-8")
    assert "CFBundleDocumentTypes" in spec
    assert "UTExportedTypeDeclarations" in spec
    assert "com.sdapp.project" in spec
    assert "sdproj_doc_icon.icns" in spec
    assert "public.filename-extension" in spec
    assert "sdproj" in spec


def test_windows_installer_writes_sdproj_association() -> None:
    script = (ROOT / "packaging" / "windows" / "sdapp_installer.nsi").read_text(encoding="utf-8")
    assert "Software\\\\Classes\\\\.sdproj" in script
    assert "Software\\\\Classes\\\\${APP_PROG_ID}\\\\DefaultIcon" in script
    assert '\"$INSTDIR\\\\${APP_EXE}\" \"%1\"' in script
