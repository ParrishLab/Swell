from __future__ import annotations

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def _write_fixture_repo(tmp_path: Path, version: str = "1.2.3") -> None:
    (tmp_path / "pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                'name = "swell"',
                f'version = "{version}"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    installer_dir = tmp_path / "packaging" / "windows"
    installer_dir.mkdir(parents=True, exist_ok=True)
    (installer_dir / "swell_installer.nsi").write_text(
        "\n".join(
            [
                'Unicode true',
                'RequestExecutionLevel user',
                '',
                '!define APP_NAME "Swell"',
                f'!define APP_VERSION "{version}"',
                '!define APP_EXE "Swell.exe"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "CHANGELOG.md").write_text(
        "\n".join(
            [
                "# Changelog",
                "",
                "## [Unreleased]",
                "",
                "### Model/checkpoint compatibility",
                "- TBD",
                "",
                "### Platform/backend limitations",
                "- TBD",
                "",
                "### .swell/migration notes",
                "- TBD",
                "",
                "### Known segmentation caveats/regressions",
                "- TBD",
                "",
                "## [1.2.3] - 2026-03-16",
                "",
                "### Model/checkpoint compatibility",
                "- old",
                "",
                "### Platform/backend limitations",
                "- old",
                "",
                "### .swell/migration notes",
                "- old",
                "",
                "### Known segmentation caveats/regressions",
                "- old",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_bump_version_patch_updates_pyproject_and_changelog(tmp_path: Path) -> None:
    _write_fixture_repo(tmp_path, version="1.2.3")
    script = ROOT / "scripts" / "release" / "bump_version.py"
    proc = subprocess.run(
        [sys.executable, str(script), "patch", "--date", "2026-03-17"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=True,
    )
    assert "BUMP_VERSION:OK:old=1.2.3;new=1.2.4;" in proc.stdout
    assert "windows_installer_updated=true" in proc.stdout
    pyproject = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "1.2.4"' in pyproject
    installer = (tmp_path / "packaging" / "windows" / "swell_installer.nsi").read_text(encoding="utf-8")
    assert '!define APP_VERSION "1.2.4"' in installer
    changelog = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [1.2.4] - 2026-03-17" in changelog
    assert "### Model/checkpoint compatibility" in changelog
    assert "### Platform/backend limitations" in changelog
    assert "### .swell/migration notes" in changelog
    assert "### Known segmentation caveats/regressions" in changelog


def test_bump_version_explicit_dry_run_makes_no_changes(tmp_path: Path) -> None:
    _write_fixture_repo(tmp_path, version="1.2.3")
    before_pyproject = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    before_changelog = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
    before_installer = (tmp_path / "packaging" / "windows" / "swell_installer.nsi").read_text(encoding="utf-8")
    script = ROOT / "scripts" / "release" / "bump_version.py"
    proc = subprocess.run(
        [sys.executable, str(script), "2.0.0", "--dry-run"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=True,
    )
    assert "BUMP_VERSION:DRY_RUN:old=1.2.3;new=2.0.0" in proc.stdout
    assert (tmp_path / "pyproject.toml").read_text(encoding="utf-8") == before_pyproject
    assert (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8") == before_changelog
    assert (tmp_path / "packaging" / "windows" / "swell_installer.nsi").read_text(encoding="utf-8") == before_installer
