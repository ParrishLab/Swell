#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import re
import subprocess
import sys
import tomllib


VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
CHANGELOG_SECTION_RE = re.compile(r"^##\s+\[(?P<version>\d+\.\d+\.\d+)\](?:\s+-\s+.*)?\s*$")
REQUIRED_HEADINGS = (
    "### Model/checkpoint compatibility",
    "### Platform/backend limitations",
    "### .sdproj/migration notes",
    "### Known segmentation caveats/regressions",
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bump project version and scaffold CHANGELOG release section.",
    )
    parser.add_argument(
        "target",
        help="One of: patch, minor, major, or explicit version (X.Y.Z).",
    )
    parser.add_argument(
        "--pyproject",
        default="pyproject.toml",
        help="Path to pyproject.toml (default: pyproject.toml).",
    )
    parser.add_argument(
        "--changelog",
        default="CHANGELOG.md",
        help="Path to CHANGELOG.md (default: CHANGELOG.md).",
    )
    parser.add_argument(
        "--windows-installer",
        default="packaging/windows/sdapp_installer.nsi",
        help="Path to Windows NSIS installer script (default: packaging/windows/sdapp_installer.nsi).",
    )
    parser.add_argument(
        "--date",
        dest="release_date",
        default=date.today().isoformat(),
        help="Release section date (YYYY-MM-DD). Defaults to today.",
    )
    parser.add_argument(
        "--tag",
        action="store_true",
        help="Create git tag v<new_version> after updating files.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print intended version change without writing files.",
    )
    return parser.parse_args()


def _read_project_version(pyproject_path: Path) -> str:
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    version = str(data.get("project", {}).get("version", "")).strip()
    if not VERSION_RE.fullmatch(version):
        raise ValueError(f"Unsupported or missing [project].version: {version!r}")
    return version


def _bump_semver(current: str, target: str) -> str:
    if VERSION_RE.fullmatch(target):
        return target

    major, minor, patch = [int(part) for part in current.split(".")]
    mode = str(target).strip().lower()
    if mode == "patch":
        return f"{major}.{minor}.{patch + 1}"
    if mode == "minor":
        return f"{major}.{minor + 1}.0"
    if mode == "major":
        return f"{major + 1}.0.0"
    raise ValueError("target must be patch, minor, major, or explicit X.Y.Z")


def _write_pyproject_version(pyproject_path: Path, new_version: str) -> None:
    text = pyproject_path.read_text(encoding="utf-8")
    pattern = re.compile(r'(?m)^version\s*=\s*"[^"]+"\s*$')
    updated, count = pattern.subn(f'version = "{new_version}"', text, count=1)
    if count != 1:
        raise RuntimeError(f"Unable to update version in {pyproject_path}")
    pyproject_path.write_text(updated, encoding="utf-8")


def _write_windows_installer_version(installer_path: Path, new_version: str) -> bool:
    if not installer_path.exists():
        return False
    text = installer_path.read_text(encoding="utf-8")
    pattern = re.compile(r'(?m)^!define\s+APP_VERSION\s+"[^"]+"\s*$')
    updated, count = pattern.subn(f'!define APP_VERSION "{new_version}"', text, count=1)
    if count != 1:
        raise RuntimeError(f"Unable to update APP_VERSION in {installer_path}")
    installer_path.write_text(updated, encoding="utf-8")
    return True


def _release_block(version: str, release_date: str) -> str:
    return (
        f"## [{version}] - {release_date}\n\n"
        "### Model/checkpoint compatibility\n"
        "- TBD\n\n"
        "### Platform/backend limitations\n"
        "- TBD\n\n"
        "### .sdproj/migration notes\n"
        "- TBD\n\n"
        "### Known segmentation caveats/regressions\n"
        "- TBD\n"
    )


def _insert_changelog_section(changelog_path: Path, version: str, release_date: str) -> bool:
    text = changelog_path.read_text(encoding="utf-8")
    if re.search(rf"(?m)^##\s+\[{re.escape(version)}\](?:\s+-\s+.*)?\s*$", text):
        return False

    lines = text.splitlines()
    insert_at = None
    unreleased_idx = None
    for idx, line in enumerate(lines):
        if re.match(r"^##\s+\[Unreleased\]\s*$", line):
            unreleased_idx = idx
            break

    if unreleased_idx is not None:
        for idx in range(unreleased_idx + 1, len(lines)):
            if lines[idx].startswith("## "):
                insert_at = idx
                break
        if insert_at is None:
            insert_at = len(lines)
    else:
        insert_at = len(lines)
        for idx, line in enumerate(lines):
            if line.startswith("## "):
                insert_at = idx
                break

    block = _release_block(version, release_date).rstrip("\n")
    prefix = lines[:insert_at]
    suffix = lines[insert_at:]

    while prefix and prefix[-1] == "":
        prefix.pop()
    new_lines = prefix + ["", block, ""] + suffix
    output = "\n".join(new_lines).rstrip() + "\n"
    changelog_path.write_text(output, encoding="utf-8")
    return True


def _create_git_tag(tag: str) -> None:
    existing = subprocess.run(
        ["git", "tag", "--list", tag],
        check=True,
        capture_output=True,
        text=True,
    )
    if existing.stdout.strip():
        raise RuntimeError(f"Tag already exists: {tag}")
    subprocess.run(["git", "tag", tag], check=True)


def main() -> int:
    args = _parse_args()
    repo_root = Path.cwd()
    pyproject_path = (repo_root / args.pyproject).resolve()
    changelog_path = (repo_root / args.changelog).resolve()
    windows_installer_path = (repo_root / args.windows_installer).resolve()

    if not pyproject_path.exists():
        raise FileNotFoundError(f"Missing pyproject.toml: {pyproject_path}")
    if not changelog_path.exists():
        raise FileNotFoundError(f"Missing CHANGELOG.md: {changelog_path}")

    current_version = _read_project_version(pyproject_path)
    new_version = _bump_semver(current_version, str(args.target).strip())

    if args.dry_run:
        print(f"BUMP_VERSION:DRY_RUN:old={current_version};new={new_version}")
        return 0

    _write_pyproject_version(pyproject_path, new_version)
    windows_installer_updated = _write_windows_installer_version(windows_installer_path, new_version)
    inserted = _insert_changelog_section(changelog_path, new_version, args.release_date)

    tag_name = f"v{new_version}"
    if args.tag:
        _create_git_tag(tag_name)

    print(
        f"BUMP_VERSION:OK:old={current_version};new={new_version};"
        f"windows_installer_updated={'true' if windows_installer_updated else 'false'};"
        f"changelog_inserted={'true' if inserted else 'false'};"
        f"tag_created={'true' if args.tag else 'false'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
