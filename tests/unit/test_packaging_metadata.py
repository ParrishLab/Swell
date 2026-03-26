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
    assert "SUFeedURL" in spec
    assert "SUPublicEDKey" in spec
    assert 'updater/macos/Sparkle.framework' in spec


def test_repo_contains_sparkle_signing_tool_and_public_key() -> None:
    assert (ROOT / "sdapp" / "resources" / "updater" / "macos" / "bin" / "sign_update").exists()
    assert (ROOT / "sdapp" / "resources" / "updater" / "macos" / "public_ed25519_key.txt").exists()


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
    assert '!define WINSPARKLE_APPCAST_URL "https://github.com/ClayDunford/Combined-tool-test/releases/latest/download/appcast-windows.xml"' in script


def test_windows_spec_bundles_winsparkle_runtime() -> None:
    spec = (ROOT / "packaging" / "windows" / "sdapp_windows.spec").read_text(encoding="utf-8")
    assert 'WinSparkle.dll' in spec
    assert 'binaries.append((str(winsparkle_dll), "."))' in spec


def test_release_workflow_disables_updater_artifacts_by_default() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release_phase3_tag.yml").read_text(encoding="utf-8")
    assert 'SDAPP_ENABLE_UPDATER_ARTIFACTS: "false"' in workflow
    assert "SDAPP_SIGN_UPDATES" in workflow
    assert "SDAPP_BUILD_INSTALLER" in workflow
    assert "if: env.SDAPP_ENABLE_UPDATER_ARTIFACTS == 'true'" in workflow
    assert "dist/sdapp-macos-arm64.zip" in workflow
    assert "dist/sdapp-windows-x64.zip" in workflow
