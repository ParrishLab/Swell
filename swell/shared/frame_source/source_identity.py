from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np


def canonical_dtype_name(value: object) -> str:
    try:
        return str(np.dtype(value).name)
    except Exception:
        return str(value or "").strip().lower()


def _frame_count(source: object) -> int:
    value = getattr(source, "frame_count", None)
    if value is not None:
        try:
            return max(0, int(value))
        except Exception:
            pass
    getter = getattr(source, "get_frame_count", None)
    if callable(getter):
        try:
            return max(0, int(getter()))
        except Exception:
            pass
    return 0


def _frame_name(source: object, idx: int) -> str:
    names = getattr(source, "frame_names", None)
    if isinstance(names, (list, tuple)) and 0 <= idx < len(names):
        return str(names[idx])
    getter = getattr(source, "get_frame_name", None)
    if callable(getter):
        try:
            return str(getter(idx))
        except Exception:
            pass
    return ""


def _source_path(source: object, idx: int) -> str:
    paths = getattr(source, "source_paths", None)
    if isinstance(paths, (list, tuple)) and 0 <= idx < len(paths):
        return str(paths[idx])
    getter = getattr(source, "get_frame_ref", None)
    if callable(getter):
        try:
            ref = getter(idx)
            return str(getattr(ref, "source_path", "") or "")
        except Exception:
            pass
    return ""


def _raw_frame(source: object, idx: int) -> np.ndarray | None:
    getter = getattr(source, "get_raw_frame", None)
    if callable(getter):
        try:
            return np.asarray(getter(idx))
        except Exception:
            return None
    reader = getattr(source, "read_frame", None)
    if callable(reader):
        try:
            return np.asarray(reader(idx, use_cache=True))
        except TypeError:
            try:
                return np.asarray(reader(idx))
            except Exception:
                return None
        except Exception:
            return None
    return None


def _sample_indices(count: int, limit: int = 9) -> list[int]:
    if count <= 0:
        return []
    if count <= limit:
        return list(range(count))
    return sorted({int(round(i * (count - 1) / float(limit - 1))) for i in range(limit)})


def source_identity(source: object) -> dict[str, str]:
    """Return stable ordered-name and content fingerprints for a stack source.

    File-size and boundary-byte signatures cover every source file, while sampled decoded
    frames protect against a different recording with matching dimensions and
    filenames. Legacy projects can omit these fields; newly bound stacks cannot.
    """

    count = _frame_count(source)
    names = [_frame_name(source, idx) for idx in range(count)]
    paths = [_source_path(source, idx) for idx in range(count)]
    names_digest = sha256(repr(names).encode("utf-8")).hexdigest()

    content = sha256()
    content.update(str(count).encode("ascii"))
    content.update(names_digest.encode("ascii"))
    unique_paths: list[str] = []
    seen: set[str] = set()
    for raw_path in paths:
        path_text = str(raw_path or "")
        if path_text in seen:
            continue
        seen.add(path_text)
        unique_paths.append(path_text)
    for path_text in unique_paths:
        if not path_text:
            continue
        try:
            source_path = Path(path_text)
            stat = source_path.stat()
            content.update(str(int(stat.st_size)).encode("ascii"))
            if source_path.is_file():
                with source_path.open("rb") as handle:
                    content.update(handle.read(4096))
                    if int(stat.st_size) > 4096:
                        handle.seek(max(0, int(stat.st_size) - 4096))
                        content.update(handle.read(4096))
        except OSError:
            content.update(b"missing")
    for idx in _sample_indices(count):
        frame = _raw_frame(source, idx)
        content.update(str(idx).encode("ascii"))
        if frame is None:
            content.update(b"unreadable")
            continue
        arr = np.ascontiguousarray(frame)
        content.update(str(arr.dtype).encode("ascii"))
        content.update(repr(tuple(int(v) for v in arr.shape)).encode("ascii"))
        content.update(arr.tobytes(order="C"))
    return {
        "frame_names_digest": names_digest,
        "source_fingerprint": content.hexdigest(),
    }


def visual_stack_digest(frames: Any) -> str:
    """Digest every visual frame through a bounded spatial sample."""

    arr = np.asarray(frames)
    digest = sha256()
    digest.update(str(arr.dtype).encode("ascii"))
    digest.update(repr(tuple(int(v) for v in arr.shape)).encode("ascii"))
    if arr.ndim < 3:
        digest.update(np.ascontiguousarray(arr).tobytes(order="C"))
        return digest.hexdigest()
    height = int(arr.shape[1])
    width = int(arr.shape[2])
    row_idx = np.linspace(0, max(0, height - 1), num=min(64, max(1, height)), dtype=int)
    col_idx = np.linspace(0, max(0, width - 1), num=min(64, max(1, width)), dtype=int)
    for idx in range(int(arr.shape[0])):
        frame = np.asarray(arr[idx])
        sampled = frame[row_idx[:, None], col_idx[None, :], ...]
        digest.update(np.ascontiguousarray(sampled).tobytes(order="C"))
    return digest.hexdigest()
