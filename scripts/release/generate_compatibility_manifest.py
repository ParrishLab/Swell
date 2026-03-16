#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import tomllib


def _load_pyproject(pyproject_path: Path) -> dict:
    with pyproject_path.open("rb") as f:
        return tomllib.load(f)


def _load_policy(policy_path: Path) -> dict:
    with policy_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def build_manifest(*, pyproject_path: Path, policy_path: Path) -> dict:
    project = _load_pyproject(pyproject_path).get("project", {})
    policy = _load_policy(policy_path)

    manifest = {
        "manifest_version": int(policy.get("manifest_version", 1)),
        "app_name": str(project.get("name", "sdapp")),
        "app_version": str(project.get("version", "0.0.0")),
        "python_requires": str(project.get("requires-python", "")),
        "sam2_reference": str(policy.get("sam2_reference", "")),
        "torch_range": str(policy.get("torch_range", "")),
        "supported_checkpoints": list(policy.get("supported_checkpoints", [])),
        "supported_platforms": list(policy.get("supported_platforms", [])),
        "runtime_policy": dict(policy.get("runtime_policy", {})),
    }
    return manifest


def write_manifest(manifest: dict, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate release compatibility manifest.")
    parser.add_argument("--repo-root", default=None, help="Repository root (defaults to script-relative root).")
    parser.add_argument("--policy", default=None, help="Policy JSON path (defaults to packaging/compatibility_policy.json).")
    parser.add_argument("--output", default=None, help="Output JSON path (defaults to dist/compatibility.json).")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = (
        Path(args.repo_root).expanduser().resolve()
        if args.repo_root
        else Path(__file__).resolve().parents[2]
    )
    policy_path = (
        Path(args.policy).expanduser().resolve()
        if args.policy
        else repo_root / "packaging" / "compatibility_policy.json"
    )
    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else repo_root / "dist" / "compatibility.json"
    )
    pyproject_path = repo_root / "pyproject.toml"

    manifest = build_manifest(pyproject_path=pyproject_path, policy_path=policy_path)
    write_manifest(manifest, output_path)
    print(f"Wrote compatibility manifest: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
