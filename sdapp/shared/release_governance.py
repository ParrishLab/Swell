from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import tomllib


RELEASE_TAG_RE = re.compile(r"^v(?P<version>\d+\.\d+\.\d+)(?:-rc\.(?P<rc>[1-9]\d*))?$")
CHANGELOG_SECTION_RE = re.compile(r"^##\s+\[?v?(?P<version>\d+\.\d+\.\d+)\]?(?:\s+-\s+.*)?\s*$")
SUBHEADING_RE = re.compile(r"^###\s+(?P<title>.+?)\s*$")

REQUIRED_CHANGELOG_HEADINGS = (
    "Model/checkpoint compatibility",
    "Platform/backend limitations",
    ".sdproj/migration notes",
    "Known segmentation caveats/regressions",
)

_NORMALIZED_REQUIRED = {
    "modelcheckpointcompatibility": "Model/checkpoint compatibility",
    "platformbackendlimitations": "Platform/backend limitations",
    "sdprojmigrationnotes": ".sdproj/migration notes",
    "knownsegmentationcaveatsregressions": "Known segmentation caveats/regressions",
}


@dataclass(frozen=True)
class ReleaseTagInfo:
    tag: str
    version: str
    is_prerelease: bool
    prerelease_number: int | None


@dataclass(frozen=True)
class ReleaseValidationResult:
    tag_info: ReleaseTagInfo
    project_version: str
    changelog_section: str


def parse_release_tag(tag: str) -> ReleaseTagInfo:
    value = str(tag or "").strip()
    match = RELEASE_TAG_RE.fullmatch(value)
    if not match:
        raise ValueError(
            f"Invalid release tag '{value}'. Expected 'vMAJOR.MINOR.PATCH' or 'vMAJOR.MINOR.PATCH-rc.N'."
        )
    rc = match.group("rc")
    return ReleaseTagInfo(
        tag=value,
        version=match.group("version"),
        is_prerelease=rc is not None,
        prerelease_number=int(rc) if rc is not None else None,
    )


def read_project_version(repo_root: Path) -> str:
    pyproject_path = Path(repo_root) / "pyproject.toml"
    if not pyproject_path.exists():
        raise ValueError(f"Missing pyproject.toml at {pyproject_path}")
    with pyproject_path.open("rb") as f:
        data = tomllib.load(f)
    version = str(data.get("project", {}).get("version", "")).strip()
    if not version:
        raise ValueError(f"Missing [project].version in {pyproject_path}")
    return version


def _normalize_title(title: str) -> str:
    return "".join(ch.lower() for ch in title if ch.isalnum())


def extract_release_section(changelog_text: str, version: str) -> str:
    lines = changelog_text.splitlines()
    start_idx: int | None = None
    end_idx = len(lines)

    for idx, line in enumerate(lines):
        match = CHANGELOG_SECTION_RE.match(line)
        if not match:
            continue
        section_version = match.group("version")
        if start_idx is None and section_version == version:
            start_idx = idx
            continue
        if start_idx is not None:
            end_idx = idx
            break

    if start_idx is None:
        raise ValueError(f"CHANGELOG.md is missing a release section for version {version}.")

    section = "\n".join(lines[start_idx:end_idx]).strip()
    if not section:
        raise ValueError(f"CHANGELOG.md release section for version {version} is empty.")
    return section


def missing_required_headings(section_text: str) -> list[str]:
    found_normalized: set[str] = set()
    for line in section_text.splitlines():
        match = SUBHEADING_RE.match(line.strip())
        if not match:
            continue
        normalized = _normalize_title(match.group("title"))
        found_normalized.add(normalized)

    missing: list[str] = []
    for normalized, display in _NORMALIZED_REQUIRED.items():
        if normalized not in found_normalized:
            missing.append(display)
    return missing


def validate_release_metadata(repo_root: Path, tag: str, changelog_path: Path | None = None) -> ReleaseValidationResult:
    tag_info = parse_release_tag(tag)
    project_version = read_project_version(repo_root)
    if project_version != tag_info.version:
        raise ValueError(
            f"Version mismatch: tag '{tag_info.tag}' resolves to {tag_info.version}, "
            f"but pyproject.toml has {project_version}."
        )

    changelog = changelog_path or (Path(repo_root) / "CHANGELOG.md")
    if not changelog.exists():
        raise ValueError(f"Missing CHANGELOG.md at {changelog}")
    changelog_text = changelog.read_text(encoding="utf-8")
    section = extract_release_section(changelog_text, tag_info.version)
    missing = missing_required_headings(section)
    if missing:
        raise ValueError(
            "CHANGELOG.md release section is missing required headings: " + ", ".join(missing)
        )

    return ReleaseValidationResult(
        tag_info=tag_info,
        project_version=project_version,
        changelog_section=section,
    )
