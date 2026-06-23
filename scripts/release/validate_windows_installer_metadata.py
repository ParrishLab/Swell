#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import re
import tomllib


APP_VERSION_RE = re.compile(r'(?m)^!define\s+APP_VERSION\s+"([^"]+)"\s*$')


def _load_project_version(pyproject_path: Path) -> str:
    with pyproject_path.open("rb") as f:
        payload = tomllib.load(f)
    project = dict(payload.get("project", {}))
    return str(project.get("version", "")).strip()


def _load_installer_version(installer_text: str) -> str:
    match = APP_VERSION_RE.search(installer_text)
    if not match:
        raise RuntimeError("Unable to find !define APP_VERSION in NSIS installer script.")
    return str(match.group(1)).strip()


def validate_installer_metadata(*, repo_root: Path, installer_path: Path, pyproject_path: Path) -> None:
    project_version = _load_project_version(pyproject_path)
    if not project_version:
        raise RuntimeError("Project version is missing in pyproject.toml.")

    script = installer_path.read_text(encoding="utf-8")
    installer_version = _load_installer_version(script)
    if installer_version != project_version:
        raise RuntimeError(
            f"Windows installer APP_VERSION mismatch: installer={installer_version} pyproject={project_version}."
        )

    payload_line = 'File /r "dist\\\\windows-x64\\\\Swell\\\\*.*"'
    if payload_line not in script:
        raise RuntimeError("Windows installer payload line is missing or changed unexpectedly.")
    if f"; {payload_line}" in script:
        raise RuntimeError("Windows installer payload line is commented out.")

    for required in (
        'IfFileExists "$INSTDIR\\\\${APP_EXE}"',
        'IfFileExists "$INSTDIR\\\\swell_doc_icon.ico"',
    ):
        if required not in script:
            raise RuntimeError(f"Windows installer runtime payload guard is missing: {required}")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Windows NSIS installer metadata and payload guards.")
    parser.add_argument("--repo-root", default=None, help="Repository root path.")
    parser.add_argument("--installer", default="packaging/windows/swell_installer.nsi", help="NSIS script path.")
    parser.add_argument("--pyproject", default="pyproject.toml", help="pyproject.toml path.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = Path(args.repo_root).expanduser().resolve() if args.repo_root else Path(__file__).resolve().parents[2]
    installer_path = (repo_root / str(args.installer)).resolve()
    pyproject_path = (repo_root / str(args.pyproject)).resolve()
    validate_installer_metadata(
        repo_root=repo_root,
        installer_path=installer_path,
        pyproject_path=pyproject_path,
    )
    print("WINDOWS_INSTALLER_VALIDATION:PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
