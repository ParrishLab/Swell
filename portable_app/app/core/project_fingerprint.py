from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Dict


def compute_file_fingerprint(path: str | Path, sample_size: int = 64 * 1024) -> Dict[str, object]:
    p = Path(path)
    stat = p.stat()
    size = int(stat.st_size)
    mtime = float(stat.st_mtime)

    h = hashlib.sha256()
    with p.open("rb") as f:
        head = f.read(sample_size)
        h.update(head)
        if size > sample_size:
            try:
                f.seek(max(0, size - sample_size), os.SEEK_SET)
                tail = f.read(sample_size)
                h.update(tail)
            except OSError:
                pass
    h.update(str(size).encode("utf-8"))
    h.update(str(mtime).encode("utf-8"))

    return {
        "size": size,
        "mtime": mtime,
        "sample_size": int(sample_size),
        "sha256_sampled": h.hexdigest(),
    }


def fingerprints_match(path: str | Path, expected: Dict[str, object]) -> bool:
    try:
        actual = compute_file_fingerprint(path, sample_size=int(expected.get("sample_size", 64 * 1024)))
    except Exception:
        return False
    return (
        int(actual["size"]) == int(expected.get("size", -1))
        and str(actual["sha256_sampled"]) == str(expected.get("sha256_sampled", ""))
    )

