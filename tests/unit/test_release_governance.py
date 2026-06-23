from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

from swell.shared.release_governance import (
    extract_release_section,
    parse_release_tag,
    validate_release_metadata,
)


ROOT = Path(__file__).resolve().parents[2]


def _write_repo_fixture(
    tmp_path: Path,
    *,
    pyproject_version: str = "1.2.3",
    changelog_version: str = "1.2.3",
    include_required_headings: bool = True,
) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                'name = "swell"',
                f'version = "{pyproject_version}"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    heading_block = (
        "\n".join(
            [
                "### Model/checkpoint compatibility",
                "- ok",
                "",
                "### Platform/backend limitations",
                "- ok",
                "",
                "### .swell/migration notes",
                "- ok",
                "",
                "### Known segmentation caveats/regressions",
                "- ok",
            ]
        )
        if include_required_headings
        else "### Model/checkpoint compatibility\n- only one heading\n"
    )
    changelog = "\n".join(
        [
            "# Changelog",
            "",
            "## [Unreleased]",
            "",
            "### Model/checkpoint compatibility",
            "- pending",
            "",
            f"## [{changelog_version}] - 2026-03-16",
            "",
            heading_block,
            "",
        ]
    )
    (tmp_path / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    return tmp_path


def test_parse_release_tag_accepts_stable_and_rc() -> None:
    stable = parse_release_tag("v1.2.3")
    assert stable.version == "1.2.3"
    assert stable.is_prerelease is False

    rc = parse_release_tag("v1.2.3-rc.4")
    assert rc.version == "1.2.3"
    assert rc.is_prerelease is True
    assert rc.prerelease_number == 4


def test_parse_release_tag_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="Invalid release tag"):
        parse_release_tag("release-1.2.3")


def test_extract_release_section_returns_matching_version_block() -> None:
    changelog = "\n".join(
        [
            "# Changelog",
            "",
            "## [1.2.4] - 2026-03-17",
            "newer",
            "",
            "## [1.2.3] - 2026-03-16",
            "target",
            "",
            "## [1.2.2] - 2026-03-15",
            "older",
        ]
    )
    section = extract_release_section(changelog, "1.2.3")
    assert section.startswith("## [1.2.3]")
    assert "target" in section
    assert "older" not in section


def test_validate_release_metadata_rejects_version_mismatch(tmp_path: Path) -> None:
    repo_root = _write_repo_fixture(tmp_path, pyproject_version="1.2.4", changelog_version="1.2.4")
    with pytest.raises(ValueError, match="Version mismatch"):
        validate_release_metadata(repo_root=repo_root, tag="v1.2.3")


def test_validate_release_metadata_rejects_missing_required_headings(tmp_path: Path) -> None:
    repo_root = _write_repo_fixture(tmp_path, include_required_headings=False)
    with pytest.raises(ValueError, match="missing required headings"):
        validate_release_metadata(repo_root=repo_root, tag="v1.2.3")


def test_validate_release_inputs_script_writes_outputs(tmp_path: Path) -> None:
    repo_root = _write_repo_fixture(tmp_path)
    script = ROOT / "scripts" / "release" / "validate_release_inputs.py"
    output_file = tmp_path / "gha_output.txt"

    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--repo-root",
            str(repo_root),
            "--tag",
            "v1.2.3-rc.2",
            "--github-output",
            str(output_file),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=True,
    )

    assert "VALID_RELEASE:tag=v1.2.3-rc.2" in proc.stdout
    output_text = output_file.read_text(encoding="utf-8")
    assert "release_tag=v1.2.3-rc.2" in output_text
    assert "release_version=1.2.3" in output_text
    assert "is_prerelease=true" in output_text


def test_validate_release_inputs_script_fails_on_bad_tag(tmp_path: Path) -> None:
    repo_root = _write_repo_fixture(tmp_path)
    script = ROOT / "scripts" / "release" / "validate_release_inputs.py"

    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--repo-root",
            str(repo_root),
            "--tag",
            "bad-tag",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode != 0
    assert "Invalid release tag" in proc.stderr


def test_generate_release_notes_script_extracts_section(tmp_path: Path) -> None:
    repo_root = _write_repo_fixture(tmp_path)
    script = ROOT / "scripts" / "release" / "generate_release_notes.py"
    output = tmp_path / "release_notes.md"

    subprocess.run(
        [
            sys.executable,
            str(script),
            "--repo-root",
            str(repo_root),
            "--tag",
            "v1.2.3",
            "--output",
            str(output),
        ],
        cwd=str(ROOT),
        check=True,
    )

    notes = output.read_text(encoding="utf-8")
    assert notes.startswith("## [1.2.3]")
    assert "### Model/checkpoint compatibility" in notes
