from __future__ import annotations

import unicodedata
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np


SOURCE_IDENTITY_VERSION = "v2"
DECODED_IDENTITY_VERSION = "v1"


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


def _legacy_source_identity(source: object) -> dict[str, str]:
    """Recreate the unversioned identity written by Swell 0.3.2."""

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


def _ordered_unique_paths(paths: list[str]) -> list[str]:
    unique_paths: list[str] = []
    seen: set[str] = set()
    for raw_path in paths:
        path_text = str(raw_path or "")
        if path_text in seen:
            continue
        seen.add(path_text)
        unique_paths.append(path_text)
    return unique_paths


def _update_file_signature(content, path_text: str) -> bool:
    if not path_text:
        content.update(b"no-path\0")
        return False
    try:
        source_path = Path(path_text)
        stat = source_path.stat()
        if not source_path.is_file():
            content.update(b"not-file\0")
            return False
        size = int(stat.st_size)
        content.update(b"file\0")
        content.update(str(size).encode("ascii"))
        content.update(b"\0")
        offsets = sorted({0, max(0, (size // 2) - 2048), max(0, size - 4096)})
        with source_path.open("rb") as handle:
            for offset in offsets:
                handle.seek(offset)
                block = handle.read(4096)
                content.update(str(offset).encode("ascii"))
                content.update(b":")
                content.update(str(len(block)).encode("ascii"))
                content.update(b":")
                content.update(block)
        return True
    except OSError:
        content.update(b"unreadable-path\0")
        return False


def source_identity(source: object) -> dict[str, str]:
    """Return a path- and decoder-independent identity for a stack source.

    Version 2 normalizes Unicode frame names and fingerprints source-file bytes
    without hashing decoded frames. The latter is important when the same TIFF
    stack is opened on another operating system or with a different optional
    image codec. Sources without file paths retain a decoded-frame fallback.
    """

    count = _frame_count(source)
    names = [
        unicodedata.normalize("NFC", _frame_name(source, idx))
        for idx in range(count)
    ]
    paths = [_source_path(source, idx) for idx in range(count)]
    names_hash = sha256(repr(names).encode("utf-8")).hexdigest()

    content = sha256()
    content.update(b"swell-source-identity-v2\0")
    content.update(str(count).encode("ascii"))
    content.update(b"\0")
    unique_paths = _ordered_unique_paths(paths)
    readable_file_count = 0
    content.update(str(len(unique_paths)).encode("ascii"))
    content.update(b"\0")
    for path_text in unique_paths:
        readable_file_count += int(_update_file_signature(content, path_text))

    if readable_file_count == 0:
        content.update(b"decoded-fallback\0")
        for idx in _sample_indices(count):
            frame = _raw_frame(source, idx)
            content.update(str(idx).encode("ascii"))
            content.update(b"\0")
            if frame is None:
                content.update(b"unreadable\0")
                continue
            arr = np.ascontiguousarray(frame)
            content.update(str(arr.dtype).encode("ascii"))
            content.update(b"\0")
            content.update(repr(tuple(int(v) for v in arr.shape)).encode("ascii"))
            content.update(b"\0")
            content.update(arr.tobytes(order="C"))

    return {
        "frame_names_digest": f"{SOURCE_IDENTITY_VERSION}:{names_hash}",
        "source_fingerprint": f"{SOURCE_IDENTITY_VERSION}:{content.hexdigest()}",
    }


def source_identity_for_saved_ref(source: object, source_fingerprint: object) -> dict[str, str]:
    """Compute the identity format used by an existing saved stack reference."""

    expected = str(source_fingerprint or "")
    if expected.startswith(f"{SOURCE_IDENTITY_VERSION}:"):
        return source_identity(source)
    return _legacy_source_identity(source)


def decoded_source_fingerprint(source: object) -> str:
    """Fingerprint sampled decoded frames independently from source-file identity."""

    count = _frame_count(source)
    digest = sha256()
    digest.update(b"swell-decoded-identity-v1\0")
    digest.update(str(count).encode("ascii"))
    digest.update(b"\0")
    for idx in _sample_indices(count):
        frame = _raw_frame(source, idx)
        digest.update(str(idx).encode("ascii"))
        digest.update(b"\0")
        if frame is None:
            digest.update(b"unreadable\0")
            continue
        arr = np.ascontiguousarray(frame)
        digest.update(str(arr.dtype).encode("ascii"))
        digest.update(b"\0")
        digest.update(repr(tuple(int(v) for v in arr.shape)).encode("ascii"))
        digest.update(b"\0")
        digest.update(arr.tobytes(order="C"))
    return f"{DECODED_IDENTITY_VERSION}:{digest.hexdigest()}"


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
