from __future__ import annotations

from pathlib import Path
import re
import tomllib


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


def test_windows_installer_metadata_matches_project_version_and_includes_payload() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project_version = str(pyproject["project"]["version"])
    script = (ROOT / "packaging" / "windows" / "sdapp_installer.nsi").read_text(encoding="utf-8")

    match = re.search(r'(?m)^!define\s+APP_VERSION\s+"([^"]+)"\s*$', script)
    assert match is not None
    assert match.group(1) == project_version
    assert 'File /r "dist\\\\windows-x64\\\\SDApp\\\\*.*"' in script
    assert '; File /r "dist\\\\windows-x64\\\\SDApp\\\\*.*"' not in script
    assert 'IfFileExists "$INSTDIR\\\\${APP_EXE}"' in script
    assert 'IfFileExists "$INSTDIR\\\\sdproj_doc_icon.ico"' in script
