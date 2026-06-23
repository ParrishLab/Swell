#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from swell.shared.release_governance import validate_release_metadata


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate release notes markdown from CHANGELOG.md.")
    parser.add_argument("--tag", required=True, help="Release tag (vMAJOR.MINOR.PATCH or vMAJOR.MINOR.PATCH-rc.N).")
    parser.add_argument("--repo-root", default=None, help="Repository root path.")
    parser.add_argument("--changelog", default=None, help="Optional changelog path.")
    parser.add_argument("--output", required=True, help="Output markdown file path.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(args.repo_root).expanduser().resolve() if args.repo_root else Path(__file__).resolve().parents[2]
    changelog = Path(args.changelog).expanduser().resolve() if args.changelog else None
    output = Path(args.output).expanduser().resolve()

    result = validate_release_metadata(repo_root=repo_root, tag=args.tag, changelog_path=changelog)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(result.changelog_section.strip() + "\n", encoding="utf-8")

    print(f"Wrote release notes: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
