#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sdapp.shared.release_governance import validate_release_metadata


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate release tag/version/changelog contract.")
    parser.add_argument("--tag", required=True, help="Release tag (vMAJOR.MINOR.PATCH or vMAJOR.MINOR.PATCH-rc.N).")
    parser.add_argument("--repo-root", default=None, help="Repository root path.")
    parser.add_argument("--changelog", default=None, help="Optional changelog path.")
    parser.add_argument(
        "--github-output",
        default=None,
        help="Optional path to append GitHub Actions outputs (release_tag, release_version, is_prerelease).",
    )
    return parser.parse_args(argv)


def _write_github_output(path: Path, *, release_tag: str, release_version: str, is_prerelease: bool) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(f"release_tag={release_tag}\n")
        f.write(f"release_version={release_version}\n")
        f.write(f"is_prerelease={'true' if is_prerelease else 'false'}\n")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(args.repo_root).expanduser().resolve() if args.repo_root else Path(__file__).resolve().parents[2]
    changelog = Path(args.changelog).expanduser().resolve() if args.changelog else None

    result = validate_release_metadata(repo_root=repo_root, tag=args.tag, changelog_path=changelog)

    if args.github_output:
        _write_github_output(
            Path(args.github_output).expanduser().resolve(),
            release_tag=result.tag_info.tag,
            release_version=result.tag_info.version,
            is_prerelease=result.tag_info.is_prerelease,
        )

    print(
        "VALID_RELEASE:"
        f"tag={result.tag_info.tag};"
        f"version={result.tag_info.version};"
        f"is_prerelease={'true' if result.tag_info.is_prerelease else 'false'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
