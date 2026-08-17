from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import tomllib

import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_macos_spec_registers_swell_document_type() -> None:
    spec = (ROOT / "packaging" / "swell.spec").read_text(encoding="utf-8")
    assert "CFBundleDocumentTypes" in spec
    assert "UTExportedTypeDeclarations" in spec
    assert "com.swell.project" in spec
    assert "swell_doc_icon.icns" in spec
    assert 'datas.append((str(doc_icon_icns), "."))' in spec
    assert "public.filename-extension" in spec
    assert "swell" in spec
    assert '"CFBundleShortVersionString": APP_VERSION' in spec
    assert '"CFBundleVersion": APP_VERSION' in spec
    assert '"openpyxl"' in spec
    assert '"resources/updater/" not in entry[0]' in spec


def test_repo_contains_updater_placeholders_and_public_key() -> None:
    assert (ROOT / "swell" / "resources" / "updater" / "macos" / "README.txt").exists()
    assert (ROOT / "swell" / "resources" / "updater" / "macos" / "public_ed25519_key.txt").exists()
    assert (ROOT / "swell" / "resources" / "updater" / "windows" / "README.txt").exists()


def test_windows_installer_writes_swell_association() -> None:
    script = (ROOT / "packaging" / "windows" / "swell_installer.nsi").read_text(encoding="utf-8")
    assert "Software\\\\Classes\\\\.swell" in script
    assert "Software\\\\Classes\\\\${APP_PROG_ID}\\\\DefaultIcon" in script
    assert '\"$INSTDIR\\\\${APP_EXE}\" \"%1\"' in script


def test_windows_installer_metadata_matches_project_version_and_includes_payload() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project_version = str(pyproject["project"]["version"])
    script = (ROOT / "packaging" / "windows" / "swell_installer.nsi").read_text(encoding="utf-8")

    match = re.search(r'(?m)^!define\s+APP_VERSION\s+"([^"]+)"\s*$', script)
    assert match is not None
    assert match.group(1) == project_version
    assert 'File /r "dist\\\\windows-x64\\\\Swell\\\\*.*"' in script
    assert '; File /r "dist\\\\windows-x64\\\\Swell\\\\*.*"' not in script
    assert 'IfFileExists "$INSTDIR\\\\${APP_EXE}"' in script
    assert 'IfFileExists "$INSTDIR\\\\swell_doc_icon.ico"' in script
    assert "WINSPARKLE_APPCAST_URL" not in script


def test_windows_spec_excludes_updater_runtime_from_package_data() -> None:
    spec = (ROOT / "packaging" / "windows" / "swell_windows.spec").read_text(encoding="utf-8")
    assert 'datas.append((str(doc_icon_ico), "."))' in spec
    assert '"openpyxl"' in spec
    assert 'collect_data_files("swell")' in spec
    assert '"resources/updater/" not in entry[0]' in spec


def test_dev_registration_script_builds_source_backed_macos_bundle() -> None:
    script = (ROOT / "scripts" / "dev" / "register_swell_dev_app.sh").read_text(encoding="utf-8")
    assert 'APP_BUNDLE="${APP_BUNDLE:-$REPO_ROOT/build/dev-macos/$APP_NAME.app}"' in script
    assert 'cp "$DOC_ICON_SRC" "$RESOURCES_DIR/swell_doc_icon.icns"' in script
    assert '<key>CFBundleDocumentTypes</key>' in script
    assert '<string>com.swell.project.dev</string>' in script
    assert 'exec "$LAUNCH_SCRIPT" "\\$@"' in script
    assert '"$LSREGISTER" -f "$APP_BUNDLE"' in script


def test_release_workflow_disables_updater_artifacts_by_default() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release_phase3_tag.yml").read_text(encoding="utf-8")
    assert 'SWELL_ENABLE_UPDATER_ARTIFACTS: "false"' in workflow
    assert "SWELL_SIGN_UPDATES" in workflow
    assert "SWELL_BUILD_INSTALLER" in workflow
    assert "if: env.SWELL_ENABLE_UPDATER_ARTIFACTS == 'true'" in workflow
    assert "dist/swell-macos-arm64.zip" in workflow
    assert "dist/swell-windows-x64.zip" in workflow
    assert "run_launch_probe.py" in workflow
    assert "requirements/release-py312-constraints.txt" in workflow
    assert "--bundle-path dist/macos-arm64/Swell.app" in workflow


def test_release_workflow_uses_draft_release_assets_instead_of_actions_storage() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release_phase3_tag.yml").read_text(encoding="utf-8")

    assert "actions/upload-artifact" not in workflow
    assert "actions/download-artifact" not in workflow
    assert "softprops/action-gh-release" not in workflow
    assert 'gh release create "$RELEASE_TAG"' in workflow
    assert 'gh release upload "$RELEASE_TAG" "${FILES[@]}" --clobber' in workflow
    assert 'gh release upload "$env:RELEASE_TAG" @files --clobber' in workflow
    assert 'gh release download "$RELEASE_TAG"' in workflow
    assert 'IS_DRAFT="$(gh release view "$RELEASE_TAG" --json isDraft --jq \'.isDraft\')"' in workflow
    assert "Release $RELEASE_TAG is already published" in workflow
    assert "publish-draft:" not in workflow


def test_release_workflow_names_download_archives_with_app_version() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release_phase3_tag.yml").read_text(encoding="utf-8")

    assert 'RELEASE_VERSION: ${{ needs.release-validate.outputs.release_version }}' in workflow
    assert 'VERSIONED_ZIP="dist/swell-${RELEASE_VERSION}-macos-arm64.zip"' in workflow
    assert '$versionedZip = "dist/swell-$env:RELEASE_VERSION-windows-x64.zip"' in workflow
    assert '--pattern "swell-${RELEASE_VERSION}-macos-arm64.zip"' in workflow
    assert '--pattern "swell-${RELEASE_VERSION}-windows-x64.zip"' in workflow


def test_release_workflow_explicit_bash_blocks_are_syntactically_valid() -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is not available")

    workflow = (ROOT / ".github" / "workflows" / "release_phase3_tag.yml").read_text(encoding="utf-8")
    lines = workflow.splitlines()
    checked = 0
    for index, line in enumerate(lines):
        if line.strip() != "shell: bash":
            continue
        run_line = lines[index + 1]
        assert run_line.strip() == "run: |"
        base_indent = len(run_line) - len(run_line.lstrip())
        body: list[str] = []
        for candidate in lines[index + 2 :]:
            candidate_indent = len(candidate) - len(candidate.lstrip())
            if candidate.strip() and candidate_indent <= base_indent:
                break
            body.append(candidate[base_indent + 2 :] if candidate.strip() else "")

        result = subprocess.run([bash, "-n"], input="\n".join(body), text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
        checked += 1

    assert checked >= 4


def test_validation_workflows_disable_optional_installer_and_updater_outputs() -> None:
    phase2 = (ROOT / ".github" / "workflows" / "release_phase2_pr.yml").read_text(encoding="utf-8")
    quick = (ROOT / ".github" / "workflows" / "windows_quick_package.yml").read_text(encoding="utf-8")
    assert "SWELL_SIGN_UPDATES=false" in phase2
    assert '$env:SWELL_BUILD_INSTALLER="false"' in phase2
    assert '$env:SWELL_BUILD_INSTALLER="false"' in quick
    assert "run_launch_probe.py" in phase2
    assert "requirements/release-py312-constraints.txt" in phase2
    assert "requirements/release-py312-constraints.txt" in quick
    assert "--bundle-path dist/macos-arm64/Swell.app" in phase2
