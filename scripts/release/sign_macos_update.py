#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


SIGNATURE_RE = re.compile(r'sparkle:edSignature="([^"]+)"\s+length="(\d+)"')
LEGACY_SIGNATURE_RE = re.compile(r"edSignature:\s*([A-Za-z0-9+/=:_-]+)")


def _default_sign_update(repo_root: Path) -> Path:
    return repo_root / "sdapp" / "resources" / "updater" / "macos" / "bin" / "sign_update"


def _build_command(sign_update_path: Path, archive_path: Path, private_key_file: Path | None) -> list[str]:
    cmd = [str(sign_update_path)]
    if private_key_file is not None:
        cmd.extend(["--ed-key-file", str(private_key_file)])
    cmd.append(str(archive_path))
    return cmd


def _parse_signature(output: str, archive_path: Path) -> dict[str, object]:
    match = SIGNATURE_RE.search(output)
    if match:
        return {
            "archive": archive_path.name,
            "length": int(match.group(2)),
            "ed_signature": match.group(1),
        }
    legacy = LEGACY_SIGNATURE_RE.search(output)
    if legacy:
        return {
            "archive": archive_path.name,
            "length": int(archive_path.stat().st_size),
            "ed_signature": legacy.group(1),
        }
    raise RuntimeError(f"Unable to parse Sparkle signature output:\n{output}")


def sign_archive(
    *,
    archive_path: Path,
    output_path: Path,
    sign_update_path: Path,
    private_key_file: Path | None = None,
) -> Path:
    if not archive_path.exists():
        raise RuntimeError(f"Archive not found: {archive_path}")
    if not sign_update_path.exists():
        raise RuntimeError(f"Sparkle sign_update binary not found: {sign_update_path}")

    proc = subprocess.run(
        _build_command(sign_update_path, archive_path, private_key_file),
        capture_output=True,
        text=True,
        check=False,
    )
    combined = "\n".join(part for part in (proc.stdout, proc.stderr) if part).strip()
    if proc.returncode != 0:
        raise RuntimeError(combined or f"sign_update failed with exit code {proc.returncode}")

    payload = _parse_signature(combined, archive_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return output_path


def _resolve_private_key(env_value: str | None) -> Path | None:
    if not env_value:
        return None
    candidate = Path(env_value).expanduser()
    if candidate.exists():
        return candidate.resolve()
    temp_dir = Path(tempfile.mkdtemp(prefix="sparkle-key-"))
    key_path = temp_dir / "sparkle_private_key.txt"
    key_path.write_text(env_value, encoding="utf-8")
    os.chmod(key_path, 0o600)
    return key_path


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sign a macOS Sparkle update archive and emit signature metadata.")
    parser.add_argument("--repo-root", default=None, help="Repository root path.")
    parser.add_argument("--archive", required=True, help="Path to the update archive to sign.")
    parser.add_argument("--output", required=True, help="Path to write signature metadata JSON.")
    parser.add_argument("--sign-update", default=None, help="Path to Sparkle's sign_update binary.")
    parser.add_argument("--private-key-file", default=None, help="Path to Sparkle private Ed25519 key file.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = Path(args.repo_root).expanduser().resolve() if args.repo_root else Path(__file__).resolve().parents[2]
    private_key = Path(args.private_key_file).expanduser().resolve() if args.private_key_file else None
    if private_key is None:
        private_key = _resolve_private_key(os.environ.get("SPARKLE_PRIVATE_KEY_FILE") or os.environ.get("SPARKLE_PRIVATE_KEY"))
    output = sign_archive(
        archive_path=(repo_root / str(args.archive)).resolve() if not Path(str(args.archive)).is_absolute() else Path(str(args.archive)).resolve(),
        output_path=(repo_root / str(args.output)).resolve() if not Path(str(args.output)).is_absolute() else Path(str(args.output)).resolve(),
        sign_update_path=(
            Path(args.sign_update).expanduser().resolve()
            if args.sign_update
            else _default_sign_update(repo_root).resolve()
        ),
        private_key_file=private_key,
    )
    print(f"SPARKLE_SIGNATURE_WRITTEN:{output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
