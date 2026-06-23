from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import tempfile
import threading
import time

import cv2
import numpy as np


def _safe_tuple(values) -> tuple[int, ...]:
    try:
        return tuple(int(v) for v in tuple(values or ()))
    except Exception:
        return ()


def _stable_source_identity(frame_source, *, frame_count: int, frame_shape: tuple[int, int]) -> str:
    source_paths = [str(p) for p in list(getattr(frame_source, "source_paths", []) or [])]
    frame_names = [str(n) for n in list(getattr(frame_source, "frame_names", []) or [])]
    payload = {
        "type": type(frame_source).__name__,
        "frame_count": int(frame_count),
        "frame_shape": list(_safe_tuple(frame_shape)),
        "source_paths_digest": sha256(repr(source_paths).encode("utf-8")).hexdigest(),
        "frame_names_digest": sha256(repr(frame_names).encode("utf-8")).hexdigest(),
        "first_source_paths": source_paths[:3],
        "last_source_paths": source_paths[-3:],
        "first_frame_names": frame_names[:3],
        "last_frame_names": frame_names[-3:],
    }
    return sha256(repr(payload).encode("utf-8")).hexdigest()[:24]


def build_sam2_frame_cache_key(
    *,
    frame_source,
    frame_count: int,
    frame_shape: tuple[int, int],
    baseline_frames: int,
    apply_horizontal_bar_denoise: bool,
    apply_smoothing: bool,
    apply_baseline_subtraction: bool,
    apply_global_normalization: bool,
    apply_stabilization: bool,
    stats,
) -> str:
    baseline_shape = None
    if stats is not None and getattr(stats, "baseline", None) is not None:
        baseline_shape = _safe_tuple(getattr(stats.baseline, "shape", ()))
    payload = {
        "source": _stable_source_identity(frame_source, frame_count=frame_count, frame_shape=frame_shape),
        "frame_count": int(frame_count),
        "frame_shape": list(_safe_tuple(frame_shape)),
        "baseline_frames": int(baseline_frames),
        "apply_horizontal_bar_denoise": bool(apply_horizontal_bar_denoise),
        "apply_smoothing": bool(apply_smoothing),
        "apply_baseline_subtraction": bool(apply_baseline_subtraction),
        "apply_global_normalization": bool(apply_global_normalization),
        "apply_stabilization": bool(apply_stabilization),
        "stats": {
            "frame_count": int(getattr(stats, "frame_count", 0) or 0),
            "frame_shape": list(_safe_tuple(getattr(stats, "frame_shape", ()))),
            "baseline_frames": int(getattr(stats, "baseline_frames", 0) or 0),
            "apply_horizontal_bar_denoise": bool(
                getattr(stats, "apply_horizontal_bar_denoise", apply_horizontal_bar_denoise)
            ),
            "apply_smoothing": bool(getattr(stats, "apply_smoothing", apply_smoothing)),
            "apply_baseline_subtraction": bool(
                getattr(stats, "apply_baseline_subtraction", apply_baseline_subtraction)
            ),
            "apply_global_normalization": bool(
                getattr(stats, "apply_global_normalization", apply_global_normalization)
            ),
            "apply_stabilization": bool(
                getattr(stats, "apply_stabilization", apply_stabilization)
            ),
            "p1": None if getattr(stats, "p1", None) is None else round(float(stats.p1), 6),
            "p99": None if getattr(stats, "p99", None) is None else round(float(stats.p99), 6),
            "baseline_shape": list(baseline_shape or ()),
        },
    }
    return sha256(repr(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SAM2FrameExportResult:
    cache_dir: str
    cache_key: str
    reused: bool
    exported_count: int
    expected_count: int


class SAM2FrameCache:
    def __init__(self, *, cache_root: str | None = None, ttl_sec: float = 3 * 24 * 60 * 60) -> None:
        base_root = cache_root or os.path.join(tempfile.gettempdir(), "swell_sam2_frame_cache")
        self.cache_root = str(Path(base_root).expanduser())
        self.ttl_sec = max(3600.0, float(ttl_sec))
        self._lock = threading.Lock()
        self._active_dirs: set[str] = set()
        os.makedirs(self.cache_root, exist_ok=True)

    def mark_active(self, cache_dir: str | None) -> None:
        if not cache_dir:
            return
        with self._lock:
            self._active_dirs.add(str(cache_dir))

    def release(self, cache_dir: str | None) -> None:
        if not cache_dir:
            return
        with self._lock:
            self._active_dirs.discard(str(cache_dir))

    def _cache_dir(self, cache_key: str) -> str:
        return str(Path(self.cache_root) / cache_key)

    def _frame_path(self, cache_dir: str, idx: int) -> str:
        return os.path.join(cache_dir, f"{int(idx):05d}.jpg")

    @staticmethod
    def _expected_frame_names(expected_count: int) -> set[str]:
        return {f"{idx:05d}.jpg" for idx in range(int(expected_count))}

    def _cache_file_names(self, cache_dir: str) -> set[str] | None:
        try:
            return set(os.listdir(cache_dir))
        except OSError:
            return None

    def is_complete(self, cache_dir: str, expected_count: int) -> bool:
        if int(expected_count) <= 0 or not os.path.isdir(cache_dir):
            return False
        names = self._cache_file_names(cache_dir)
        if names is None:
            return False
        return self._expected_frame_names(expected_count).issubset(names)

    def export_frames(
        self,
        *,
        frame_source,
        frames_viz,
        cache_key: str,
        logger,
        worker_count: int | None = None,
    ) -> SAM2FrameExportResult:
        arr = np.asarray(frames_viz, dtype=np.uint8)
        expected_count = int(arr.shape[0]) if arr.ndim >= 3 else 0
        cache_dir = self._cache_dir(cache_key)
        os.makedirs(cache_dir, exist_ok=True)
        self.mark_active(cache_dir)

        if self.is_complete(cache_dir, expected_count):
            logger("Perf", f"SAM frame export cache hit dir={Path(cache_dir).name} frames={expected_count}")
            return SAM2FrameExportResult(
                cache_dir=cache_dir,
                cache_key=cache_key,
                reused=True,
                exported_count=0,
                expected_count=expected_count,
            )

        names = self._cache_file_names(cache_dir) or set()
        missing = [idx for idx in range(expected_count) if f"{idx:05d}.jpg" not in names]
        if not missing:
            missing = list(range(expected_count))
        default_workers = min(int(os.cpu_count() or 1), 8)
        workers = max(1, int(worker_count if worker_count is not None else default_workers))

        def _write(idx: int) -> None:
            frame = np.asarray(arr[idx], dtype=np.uint8)
            path = self._frame_path(cache_dir, idx)
            ok = cv2.imwrite(path, frame)
            if not ok:
                raise RuntimeError(f"Failed to write SAM frame export: {path}")

        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_write, idx) for idx in missing]
            for fut in futures:
                fut.result()
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        logger(
            "Perf",
            f"SAM frame export {'partial' if len(missing) < expected_count else 'full'} "
            f"dir={Path(cache_dir).name} exported={len(missing)}/{expected_count} elapsed={elapsed_ms:.1f}ms",
        )
        return SAM2FrameExportResult(
            cache_dir=cache_dir,
            cache_key=cache_key,
            reused=False,
            exported_count=len(missing),
            expected_count=expected_count,
        )

    def prune_expired(self) -> None:
        now = time.time()
        with self._lock:
            active_dirs = set(self._active_dirs)
        root = Path(self.cache_root)
        if not root.exists():
            return
        for entry in root.iterdir():
            if not entry.is_dir():
                continue
            path_str = str(entry)
            if path_str in active_dirs:
                continue
            try:
                age = now - float(entry.stat().st_mtime)
            except Exception:
                continue
            if age < self.ttl_sec:
                continue
            try:
                for child in entry.iterdir():
                    child.unlink(missing_ok=True)
                entry.rmdir()
            except Exception:
                continue
