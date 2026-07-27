from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Dict


def _sampled_hash(
    path: Path,
    *,
    size: int,
    sample_size: int,
    legacy_mtime: float | None = None,
) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        head = f.read(sample_size)
        h.update(head)
        if size > sample_size:
            try:
                f.seek(max(0, size - sample_size), os.SEEK_SET)
                h.update(f.read(sample_size))
            except OSError:
                pass
    h.update(str(size).encode("utf-8"))
    if legacy_mtime is not None:
        h.update(str(float(legacy_mtime)).encode("utf-8"))
    return h.hexdigest()


def compute_file_fingerprint(path: str | Path, sample_size: int = 64 * 1024) -> Dict[str, object]:
    p = Path(path)
    stat = p.stat()
    size = int(stat.st_size)
    mtime = float(stat.st_mtime)

    return {
        "version": 2,
        "size": size,
        "mtime": mtime,
        "sample_size": int(sample_size),
        "sha256_sampled": _sampled_hash(
            p,
            size=size,
            sample_size=int(sample_size),
        ),
    }


def fingerprints_match(path: str | Path, expected: Dict[str, object]) -> bool:
    try:
        p = Path(path)
        sample_size = int(expected.get("sample_size", 64 * 1024))
        size = int(p.stat().st_size)
        if int(expected.get("version", 1) or 1) >= 2:
            actual_hash = _sampled_hash(
                p,
                size=size,
                sample_size=sample_size,
            )
        else:
            actual_hash = _sampled_hash(
                p,
                size=size,
                sample_size=sample_size,
                legacy_mtime=float(expected.get("mtime", 0.0)),
            )
    except Exception:
        return False
    return (
        size == int(expected.get("size", -1))
        and str(actual_hash) == str(expected.get("sha256_sampled", ""))
    )
