from __future__ import annotations

import io
import json
import os
import time
import zipfile
from pathlib import Path
from typing import Any

import numpy as np


def write_json(zf: zipfile.ZipFile, arcname: str, payload: Any) -> None:
    zf.writestr(arcname, json.dumps(payload, indent=2))


def read_json(zf: zipfile.ZipFile, arcname: str, default: Any = None) -> Any:
    try:
        with zf.open(arcname, "r") as f:
            return json.loads(f.read().decode("utf-8"))
    except KeyError:
        if isinstance(default, dict):
            return dict(default)
        if isinstance(default, list):
            return list(default)
        return default


def write_npz_bytes(array: Any, *, key: str = "masks", dtype=np.uint8) -> bytes:
    arr = np.asarray(array, dtype=dtype)
    mem = io.BytesIO()
    np.savez_compressed(mem, **{key: arr})
    return mem.getvalue()


def read_npz_bytes(blob: bytes, *, key: str = "masks") -> np.ndarray:
    with np.load(io.BytesIO(blob)) as npz:
        return np.array(npz[key])


def write_npz(zf: zipfile.ZipFile, arcname: str, array: Any, *, key: str = "masks", dtype=np.uint8) -> None:
    zf.writestr(arcname, write_npz_bytes(array, key=key, dtype=dtype))


def read_npz(zf: zipfile.ZipFile, arcname: str, *, key: str = "masks") -> np.ndarray | None:
    try:
        with zf.open(arcname, "r") as f:
            return read_npz_bytes(f.read(), key=key)
    except Exception:
        return None


def cleanup_stale_temp_files(
    directory: str | Path,
    pattern: str = "*.sdproj.tmp",
    older_than_sec: float = 86400,
) -> int:
    base = Path(directory)
    if not base.exists() or not base.is_dir():
        return 0
    cutoff = time.time() - max(0.0, float(older_than_sec))
    removed = 0
    for p in base.glob(pattern):
        try:
            if not p.is_file():
                continue
            if p.stat().st_mtime > cutoff:
                continue
            p.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def fsync_parent_directory(target: Path) -> None:
    dir_fd = None
    try:
        dir_fd = os.open(str(target.parent), os.O_RDONLY)
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        if dir_fd is not None:
            try:
                os.close(dir_fd)
            except OSError:
                pass
