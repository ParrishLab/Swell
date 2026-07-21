from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import cv2
import numpy as np

MAX_PERCENTILE_SAMPLE_PIXELS_PER_FRAME = 262_144


@dataclass
class VisualizationStats:
    frame_count: int
    frame_shape: tuple[int, int]
    baseline_frames: int
    apply_horizontal_bar_denoise: bool
    apply_smoothing: bool
    apply_baseline_subtraction: bool
    apply_global_normalization: bool
    apply_stabilization: bool = False
    stabilization_reference_index: int = 0
    stabilization_offsets_px: np.ndarray | None = None
    stabilization_fallback_frame_indices: list[int] | None = None
    baseline: np.ndarray | None = None
    p1: float | None = None
    p99: float | None = None


class VisualizationCancelled(RuntimeError):
    """Raised when visualization preprocessing is canceled by the caller."""


def _frame_to_uint8(frame: np.ndarray) -> np.ndarray:
    arr = np.asarray(frame, dtype=np.float32)
    if arr.size == 0:
        return np.zeros((0, 0), dtype=np.uint8)
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return np.zeros(arr.shape, dtype=np.uint8)
    lo = float(np.min(finite))
    hi = float(np.max(finite))
    denom = hi - lo
    if denom <= 0:
        return np.zeros(arr.shape, dtype=np.uint8)
    safe = np.where(np.isfinite(arr), arr, lo)
    norm = (safe - lo) / denom
    result = np.clip(norm * 255.0, 0.0, 255.0).astype(np.uint8)
    result[~np.isfinite(arr)] = 0
    return result


def normalize_visual_frame(frame: np.ndarray, *, p1: float | None = None, p99: float | None = None) -> np.ndarray:
    arr = np.asarray(frame, dtype=np.float32)
    if arr.size == 0:
        return np.zeros((0, 0), dtype=np.uint8)
    if p1 is None or p99 is None:
        return _frame_to_uint8(arr)
    lo = float(p1)
    hi = float(p99)
    if not np.isfinite(lo) or not np.isfinite(hi):
        return _frame_to_uint8(arr)
    denom = hi - lo
    if denom <= 0:
        denom = 1e-8
    finite_mask = np.isfinite(arr)
    clipped = np.clip(np.where(finite_mask, arr, lo), lo, hi)
    result = (((clipped - lo) / denom) * 255.0).astype(np.uint8)
    result[~finite_mask] = 0
    return result


def _sample_percentile_pixels(frame: np.ndarray, max_pixels: int = MAX_PERCENTILE_SAMPLE_PIXELS_PER_FRAME) -> np.ndarray:
    flat = np.asarray(frame, dtype=np.float32).reshape(-1)
    flat = flat[np.isfinite(flat)]
    limit = max(1, int(max_pixels))
    if flat.size <= limit:
        return flat
    indices = np.linspace(0, flat.size - 1, num=limit, dtype=np.int64)
    return flat[indices]


def finite_percentile_bounds(
    values: np.ndarray,
    *,
    lower: float = 1.0,
    upper: float = 99.0,
    max_pixels: int = MAX_PERCENTILE_SAMPLE_PIXELS_PER_FRAME,
) -> tuple[float, float]:
    sample = _sample_percentile_pixels(values, max_pixels=max_pixels)
    if sample.size == 0:
        return 0.0, 1.0
    lo = float(np.percentile(sample, float(lower)))
    hi = float(np.percentile(sample, float(upper)))
    if not np.isfinite(lo) or not np.isfinite(hi):
        return 0.0, 1.0
    if hi <= lo:
        hi = lo + 1e-8
    return lo, hi


def sanitize_nonfinite_pixels(frame: np.ndarray) -> np.ndarray:
    arr = np.asarray(frame, dtype=np.float32)
    finite_mask = np.isfinite(arr)
    if np.all(finite_mask):
        return arr.astype(np.float32, copy=False)
    finite = arr[finite_mask]
    fill = float(np.median(finite)) if finite.size > 0 else 0.0
    return np.where(finite_mask, arr, fill).astype(np.float32, copy=False)


def _read_frame_float32(frame_source, idx: int) -> np.ndarray:
    raw = np.asarray(frame_source.get_raw_frame(int(idx)))
    if raw.ndim == 3 and raw.shape[2] in (3, 4):
        raw = raw[:, :, :3].mean(axis=2)
    return sanitize_nonfinite_pixels(raw)


def remove_horizontal_bar_artifacts(frame: np.ndarray) -> np.ndarray:
    arr = np.asarray(frame, dtype=np.float32)
    if arr.ndim != 2 or arr.size == 0:
        return arr.astype(np.float32, copy=False)
    row_bias = np.median(arr, axis=1, keepdims=True).astype(np.float32, copy=False)
    global_bias = float(np.median(row_bias))
    corrected = arr - (row_bias - global_bias)
    return corrected.astype(np.float32, copy=False)


def _gaussian_blur_2d(frame: np.ndarray, sigma: float = 0.5) -> np.ndarray:
    """2D Gaussian smoothing via OpenCV (SIMD-accelerated, far faster than scipy).

    BORDER_REFLECT matches scipy's default 'reflect' edge handling, and a zero
    ksize lets OpenCV derive the kernel size from sigma (radius 2 for sigma=0.5,
    same as scipy's default truncate=4.0).
    """
    arr = np.ascontiguousarray(frame, dtype=np.float32)
    return cv2.GaussianBlur(
        arr,
        (0, 0),
        sigmaX=float(sigma),
        sigmaY=float(sigma),
        borderType=cv2.BORDER_REFLECT,
    )


def _processed_frame(raw: np.ndarray, *, apply_horizontal_bar_denoise: bool, apply_smoothing: bool) -> np.ndarray:
    source = sanitize_nonfinite_pixels(raw)
    if bool(apply_horizontal_bar_denoise):
        source = remove_horizontal_bar_artifacts(source)
    if not bool(apply_smoothing):
        return source
    return _gaussian_blur_2d(source, 0.5)


def _processed_source_frame(
    frame_source,
    idx: int,
    *,
    apply_horizontal_bar_denoise: bool,
    apply_smoothing: bool,
) -> np.ndarray:
    raw = _read_frame_float32(frame_source, idx)
    return _processed_frame(
        raw,
        apply_horizontal_bar_denoise=bool(apply_horizontal_bar_denoise),
        apply_smoothing=bool(apply_smoothing),
    )


def _stabilize_frame(raw: np.ndarray, offset_xy: np.ndarray | tuple[float, float] | None) -> np.ndarray:
    arr = np.asarray(raw, dtype=np.float32)
    if arr.ndim != 2 or arr.size == 0:
        return arr.astype(np.float32, copy=False)
    dx = 0.0
    dy = 0.0
    if offset_xy is not None:
        try:
            dx = float(offset_xy[0])
            dy = float(offset_xy[1])
        except Exception:
            dx = 0.0
            dy = 0.0
    if abs(dx) < 1e-6 and abs(dy) < 1e-6:
        return arr.astype(np.float32, copy=False)
    h, w = arr.shape[:2]
    matrix = np.array([[1.0, 0.0, -dx], [0.0, 1.0, -dy]], dtype=np.float32)
    stabilized = cv2.warpAffine(
        arr,
        matrix,
        (int(w), int(h)),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return np.asarray(stabilized, dtype=np.float32)


def _compute_stabilization_offsets(
    frame_source,
    *,
    frame_count: int,
    apply_horizontal_bar_denoise: bool,
    apply_smoothing: bool,
    should_cancel: Callable[[], bool] | None = None,
    progress_callback=None,
) -> tuple[np.ndarray, list[int]]:
    offsets = np.zeros((max(0, int(frame_count)), 2), dtype=np.float32)
    if int(frame_count) <= 1:
        return offsets, []
    reference = _processed_source_frame(
        frame_source,
        0,
        apply_horizontal_bar_denoise=bool(apply_horizontal_bar_denoise),
        apply_smoothing=bool(apply_smoothing),
    )
    reference_std = float(np.std(reference)) if reference.size > 0 else 0.0
    last_valid = np.zeros((2,), dtype=np.float32)
    fallback_indices: list[int] = []
    total = max(1, int(frame_count) - 1)
    for idx in range(1, int(frame_count)):
        _raise_if_cancelled(should_cancel)
        frame = _processed_source_frame(
            frame_source,
            idx,
            apply_horizontal_bar_denoise=bool(apply_horizontal_bar_denoise),
            apply_smoothing=bool(apply_smoothing),
        )
        candidate = None
        try:
            if (
                reference.shape == frame.shape
                and reference.size > 0
                and reference_std > 1e-6
                and float(np.std(frame)) > 1e-6
            ):
                shift, response = cv2.phaseCorrelate(
                    np.asarray(reference, dtype=np.float32),
                    np.asarray(frame, dtype=np.float32),
                )
                dx = float(shift[0])
                dy = float(shift[1])
                if np.isfinite(dx) and np.isfinite(dy) and np.isfinite(float(response)) and float(response) > 1e-3:
                    candidate = np.array([dx, dy], dtype=np.float32)
        except Exception:
            candidate = None
        if candidate is None:
            candidate = last_valid.copy()
            fallback_indices.append(int(idx))
        else:
            last_valid = candidate
        offsets[idx] = candidate
        _emit_stats_progress(progress_callback, stage="stabilize", current=idx, total=total)
    return offsets, fallback_indices


def _raise_if_cancelled(should_cancel: Callable[[], bool] | None) -> None:
    if callable(should_cancel) and bool(should_cancel()):
        raise VisualizationCancelled("Visualization preparation canceled.")


def _emit_stats_progress(
    progress_callback,
    *,
    stage: str,
    current: int,
    total: int,
) -> None:
    if not callable(progress_callback):
        return
    progress_callback(
        {
            "stage": str(stage),
            "current": int(current),
            "total": int(total),
        }
    )


def _stats_sample_indices(frame_count: int) -> list[int]:
    count = max(0, int(frame_count))
    if count <= 0:
        return []
    return list(range(0, count, 5)) or [0]


def _prepare_stats_frame_cache(
    frame_source,
    *,
    frame_count: int,
    baseline_count: int,
    apply_horizontal_bar_denoise: bool,
    apply_smoothing: bool,
    first_frame: np.ndarray,
    apply_baseline_subtraction: bool,
    apply_global_normalization: bool,
    stabilization_offsets: np.ndarray | None = None,
    should_cancel: Callable[[], bool] | None = None,
    progress_callback=None,
) -> tuple[dict[int, np.ndarray], list[int]]:
    raw_cache: dict[int, np.ndarray] = {0: np.asarray(first_frame, dtype=np.float32)}
    processed_cache: dict[int, np.ndarray] = {}
    sample_indices = _stats_sample_indices(frame_count) if bool(apply_global_normalization) else []
    work_indices: list[int] = []
    seen: set[int] = set()
    if bool(apply_baseline_subtraction):
        for idx in range(int(baseline_count)):
            if idx not in seen:
                work_indices.append(int(idx))
                seen.add(int(idx))
    for idx in sample_indices:
        if idx not in seen:
            work_indices.append(int(idx))
            seen.add(int(idx))
    total = max(0, len(work_indices))
    for current, idx in enumerate(work_indices, start=1):
        _raise_if_cancelled(should_cancel)
        raw = raw_cache.get(int(idx))
        if raw is None:
            raw = _read_frame_float32(frame_source, idx)
            raw_cache[int(idx)] = raw
        processed_cache[int(idx)] = _processed_frame(
            _stabilize_frame(
                raw,
                stabilization_offsets[int(idx)] if stabilization_offsets is not None and int(idx) < len(stabilization_offsets) else None,
            ),
            apply_horizontal_bar_denoise=bool(apply_horizontal_bar_denoise),
            apply_smoothing=bool(apply_smoothing),
        )
        _emit_stats_progress(progress_callback, stage="prepare", current=current, total=total)
    return processed_cache, sample_indices


def compute_visualization_stats(
    frame_source,
    *,
    baseline_frames: int = 30,
    apply_horizontal_bar_denoise: bool = False,
    apply_smoothing: bool = True,
    apply_baseline_subtraction: bool = True,
    apply_global_normalization: bool = True,
    apply_stabilization: bool = False,
    should_cancel: Callable[[], bool] | None = None,
    progress_callback=None,
) -> VisualizationStats:
    frame_count = int(getattr(frame_source, "frame_count", 0) or 0)
    if frame_count <= 0:
        return VisualizationStats(
            frame_count=0,
            frame_shape=(0, 0),
            baseline_frames=0,
            apply_horizontal_bar_denoise=bool(apply_horizontal_bar_denoise),
            apply_smoothing=bool(apply_smoothing),
            apply_baseline_subtraction=bool(apply_baseline_subtraction),
            apply_global_normalization=bool(apply_global_normalization),
            apply_stabilization=bool(apply_stabilization),
        )

    first_frame = _read_frame_float32(frame_source, 0)
    frame_shape = tuple(int(v) for v in first_frame.shape[:2])
    baseline_count = max(0, min(int(baseline_frames), frame_count))
    stabilization_offsets = None
    stabilization_fallback_frame_indices: list[int] = []
    if bool(apply_stabilization):
        stabilization_offsets, stabilization_fallback_frame_indices = _compute_stabilization_offsets(
            frame_source,
            frame_count=frame_count,
            apply_horizontal_bar_denoise=bool(apply_horizontal_bar_denoise),
            apply_smoothing=bool(apply_smoothing),
            should_cancel=should_cancel,
            progress_callback=progress_callback,
        )
    processed_cache, sample_indices = _prepare_stats_frame_cache(
        frame_source,
        frame_count=frame_count,
        baseline_count=baseline_count,
        apply_horizontal_bar_denoise=bool(apply_horizontal_bar_denoise),
        apply_smoothing=bool(apply_smoothing),
        first_frame=first_frame,
        apply_baseline_subtraction=bool(apply_baseline_subtraction),
        apply_global_normalization=bool(apply_global_normalization),
        stabilization_offsets=stabilization_offsets,
        should_cancel=should_cancel,
        progress_callback=progress_callback,
    )
    baseline = None
    if bool(apply_baseline_subtraction) and baseline_count > 0:
        baseline_parts = [np.asarray(processed_cache[int(idx)], dtype=np.float32) for idx in range(baseline_count)]
        baseline = np.median(np.stack(baseline_parts, axis=0), axis=0).astype(np.float32, copy=False)

    p1 = None
    p99 = None
    if bool(apply_global_normalization):
        sampled_parts: list[np.ndarray] = []
        for idx in sample_indices:
            _raise_if_cancelled(should_cancel)
            source = np.asarray(processed_cache[int(idx)], dtype=np.float32)
            if baseline is not None:
                source = source - baseline
            sampled_parts.append(_sample_percentile_pixels(source))
        _raise_if_cancelled(should_cancel)
        sampled = np.concatenate(sampled_parts, axis=0) if sampled_parts else np.zeros((0,), dtype=np.float32)
        p1, p99 = finite_percentile_bounds(sampled)

    return VisualizationStats(
        frame_count=frame_count,
        frame_shape=frame_shape,
        baseline_frames=baseline_count,
        apply_horizontal_bar_denoise=bool(apply_horizontal_bar_denoise),
        apply_smoothing=bool(apply_smoothing),
        apply_baseline_subtraction=bool(apply_baseline_subtraction),
        apply_global_normalization=bool(apply_global_normalization),
        apply_stabilization=bool(apply_stabilization),
        stabilization_reference_index=0,
        stabilization_offsets_px=None if stabilization_offsets is None else np.asarray(stabilization_offsets, dtype=np.float32),
        stabilization_fallback_frame_indices=list(stabilization_fallback_frame_indices),
        baseline=baseline,
        p1=p1,
        p99=p99,
    )


def compute_visualization_stats_for_preview(
    frame_source,
    *,
    preview_scale: float = 0.25,
    baseline_frames: int = 30,
    apply_horizontal_bar_denoise: bool = False,
    apply_smoothing: bool = True,
    apply_baseline_subtraction: bool = True,
    apply_global_normalization: bool = True,
    apply_stabilization: bool = False,
    should_cancel=None,
    progress_callback=None,
) -> VisualizationStats:
    """Like compute_visualization_stats but operates at reduced resolution for speed.

    Stats are computed on a downsampled copy of the source for display previews.
    They remain approximate and must not be reused as canonical model input.
    Returned arrays and offsets are converted to the original pixel space.
    """
    from swell.shared.frame_source.downsampled import DownsampledFrameSource

    scale = max(0.01, min(1.0, float(preview_scale)))
    original_shape = tuple(int(v) for v in tuple(getattr(frame_source, "frame_shape", (0, 0)))[:2])

    if scale >= 1.0 or original_shape[0] <= 0 or original_shape[1] <= 0:
        return compute_visualization_stats(
            frame_source,
            baseline_frames=baseline_frames,
            apply_horizontal_bar_denoise=apply_horizontal_bar_denoise,
            apply_smoothing=apply_smoothing,
            apply_baseline_subtraction=apply_baseline_subtraction,
            apply_global_normalization=apply_global_normalization,
            apply_stabilization=apply_stabilization,
            should_cancel=should_cancel,
            progress_callback=progress_callback,
        )

    downsampled = DownsampledFrameSource(frame_source, scale=scale)
    stats = compute_visualization_stats(
        downsampled,
        baseline_frames=baseline_frames,
        apply_horizontal_bar_denoise=apply_horizontal_bar_denoise,
        apply_smoothing=apply_smoothing,
        apply_baseline_subtraction=apply_baseline_subtraction,
        apply_global_normalization=apply_global_normalization,
        apply_stabilization=apply_stabilization,
        should_cancel=should_cancel,
        progress_callback=progress_callback,
    )

    # Upsample baseline back to original resolution so the stats are usable for
    # full-res frame rendering without shape mismatches.
    if stats.baseline is not None:
        oh, ow = original_shape
        stats.baseline = cv2.resize(
            np.asarray(stats.baseline, dtype=np.float32),
            (ow, oh),
            interpolation=cv2.INTER_LINEAR,
        ).astype(np.float32)
    if stats.stabilization_offsets_px is not None:
        # Registration was measured in downsampled pixels. Convert offsets to
        # the original frame's coordinate system before returning the stats.
        stats.stabilization_offsets_px = (
            np.asarray(stats.stabilization_offsets_px, dtype=np.float32) / float(scale)
        )
    stats.frame_shape = original_shape
    return stats


def render_visualization_frame(
    frame_source,
    frame_idx: int,
    *,
    stats: VisualizationStats | None = None,
    baseline_frames: int = 30,
    apply_horizontal_bar_denoise: bool = False,
    apply_smoothing: bool = True,
    apply_baseline_subtraction: bool = True,
    apply_global_normalization: bool = True,
    apply_stabilization: bool = False,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    resolved_stats = stats
    if resolved_stats is None:
        resolved_stats = compute_visualization_stats(
            frame_source,
            baseline_frames=baseline_frames,
            apply_horizontal_bar_denoise=apply_horizontal_bar_denoise,
            apply_smoothing=apply_smoothing,
            apply_baseline_subtraction=apply_baseline_subtraction,
            apply_global_normalization=apply_global_normalization,
            apply_stabilization=apply_stabilization,
        )
    idx = max(0, min(int(frame_idx), max(0, int(resolved_stats.frame_count) - 1)))
    raw = _read_frame_float32(frame_source, idx)
    offsets = getattr(resolved_stats, "stabilization_offsets_px", None)
    stabilized_raw = _stabilize_frame(
        raw,
        offsets[idx] if bool(getattr(resolved_stats, "apply_stabilization", False)) and offsets is not None and idx < len(offsets) else None,
    )
    source = _processed_frame(
        stabilized_raw,
        apply_horizontal_bar_denoise=bool(getattr(resolved_stats, "apply_horizontal_bar_denoise", False)),
        apply_smoothing=bool(resolved_stats.apply_smoothing),
    )
    if bool(resolved_stats.apply_baseline_subtraction) and resolved_stats.baseline is not None:
        subtracted = (source - resolved_stats.baseline).astype(np.float32, copy=False)
    else:
        subtracted = source.astype(np.float32, copy=False)

    if bool(resolved_stats.apply_global_normalization):
        visual = normalize_visual_frame(
            subtracted,
            p1=float(resolved_stats.p1 if resolved_stats.p1 is not None else 0.0),
            p99=float(resolved_stats.p99 if resolved_stats.p99 is not None else 1.0),
        )
    else:
        visual = normalize_visual_frame(subtracted)
    return stabilized_raw.astype(np.float32, copy=False), subtracted, visual


def build_visualization_stack(
    frame_source,
    *,
    baseline_frames: int = 30,
    apply_horizontal_bar_denoise: bool = False,
    apply_smoothing: bool = True,
    apply_baseline_subtraction: bool = True,
    apply_global_normalization: bool = True,
    apply_stabilization: bool = False,
    stats: VisualizationStats | None = None,
    progress_callback=None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Create raw/subtracted/visual stacks from a frame source using shared normalization."""
    frame_count = int(getattr(frame_source, "frame_count", 0) or 0)
    if frame_count <= 0:
        return (
            np.zeros((0, 0, 0), dtype=np.float32),
            np.zeros((0, 0, 0), dtype=np.float32),
            np.zeros((0, 0, 0), dtype=np.uint8),
        )

    first_raw = _read_frame_float32(frame_source, 0)
    frame_shape = tuple(int(v) for v in first_raw.shape[:2])
    raw_frames = np.empty((frame_count, frame_shape[0], frame_shape[1]), dtype=np.float32)
    raw_frames[0] = first_raw
    total_progress_steps = max(1, frame_count * 3)

    for i in range(1, frame_count):
        raw_frames[i] = _read_frame_float32(frame_source, i)
        if callable(progress_callback):
            progress_callback({"stage": "read", "current": int(i + 1), "total": int(total_progress_steps)})

    resolved_stats = stats
    if resolved_stats is None:
        class _RawArrayFrameSource:
            def __init__(self, frames: np.ndarray) -> None:
                self._frames = frames
                self.frame_count = int(frames.shape[0])

            def get_raw_frame(self, idx: int) -> np.ndarray:
                return self._frames[int(idx)]

        resolved_stats = compute_visualization_stats(
            _RawArrayFrameSource(raw_frames),
            baseline_frames=baseline_frames,
            apply_horizontal_bar_denoise=apply_horizontal_bar_denoise,
            apply_smoothing=apply_smoothing,
            apply_baseline_subtraction=apply_baseline_subtraction,
            apply_global_normalization=apply_global_normalization,
            apply_stabilization=apply_stabilization,
        )

    offsets = getattr(resolved_stats, "stabilization_offsets_px", None)
    do_stabilize = bool(getattr(resolved_stats, "apply_stabilization", False)) and offsets is not None

    if do_stabilize:
        stabilized_raw_frames = np.empty_like(raw_frames)
        for i in range(frame_count):
            stabilized_raw_frames[i] = _stabilize_frame(raw_frames[i], offsets[i] if i < len(offsets) else None)
        if callable(progress_callback):
            progress_callback({"stage": "preprocess", "current": int(frame_count * 2), "total": int(total_progress_steps)})
    else:
        stabilized_raw_frames = raw_frames

    # Vectorize denoising and smoothing over the whole stack at once — far faster than N per-frame calls.
    source_for_sub: np.ndarray = stabilized_raw_frames
    if bool(apply_horizontal_bar_denoise):
        row_bias = np.median(source_for_sub, axis=2, keepdims=True).astype(np.float32)
        global_bias = np.median(row_bias, axis=1, keepdims=True).astype(np.float32)
        source_for_sub = (source_for_sub - (row_bias - global_bias)).astype(np.float32)
    if bool(apply_smoothing):
        # Per-frame OpenCV blur. Identical result to the per-frame render path
        # (_processed_frame), which the prepared/stack equivalence tests rely on.
        smoothed = np.empty_like(source_for_sub, dtype=np.float32)
        for i in range(source_for_sub.shape[0]):
            smoothed[i] = _gaussian_blur_2d(source_for_sub[i], 0.5)
        source_for_sub = smoothed
    if callable(progress_callback):
        progress_callback({"stage": "preprocess", "current": int(frame_count * 2), "total": int(total_progress_steps)})

    if bool(apply_baseline_subtraction) and int(baseline_frames) > 0:
        baseline_count = min(int(baseline_frames), source_for_sub.shape[0])
        if (
            resolved_stats is not None
            and bool(resolved_stats.apply_baseline_subtraction)
            and resolved_stats.baseline is not None
            and tuple(int(v) for v in resolved_stats.frame_shape[:2]) == tuple(int(v) for v in source_for_sub.shape[1:3])
        ):
            baseline = np.asarray(resolved_stats.baseline, dtype=np.float32)
        else:
            baseline = np.median(source_for_sub[:baseline_count], axis=0).astype(np.float32, copy=False)
        frames_sub = (source_for_sub - baseline).astype(np.float32)
    else:
        frames_sub = source_for_sub.astype(np.float32, copy=False)

    frames_viz = np.empty((frame_count, frame_shape[0], frame_shape[1]), dtype=np.uint8)
    if bool(apply_global_normalization):
        subsample = frames_sub[::5] if frames_sub.shape[0] > 0 else frames_sub
        if resolved_stats is not None and bool(resolved_stats.apply_global_normalization):
            p1 = float(resolved_stats.p1 if resolved_stats.p1 is not None else 0.0)
            p99 = float(resolved_stats.p99 if resolved_stats.p99 is not None else 1.0)
        else:
            p1, p99 = finite_percentile_bounds(subsample)
        denom = p99 - p1
        if denom <= 0:
            denom = 1e-8
        frames_viz[:] = np.clip((np.clip(frames_sub, p1, p99) - p1) / denom * 255.0, 0.0, 255.0).astype(np.uint8)
    else:
        # Per-frame local normalization (each frame scaled to its own min/max).
        lo = frames_sub.min(axis=(1, 2), keepdims=True).astype(np.float32)
        hi = frames_sub.max(axis=(1, 2), keepdims=True).astype(np.float32)
        denom_arr = np.where(hi - lo > 0, hi - lo, np.float32(1e-8))
        frames_viz[:] = np.clip((frames_sub - lo) / denom_arr * 255.0, 0.0, 255.0).astype(np.uint8)
    if callable(progress_callback):
        progress_callback({"stage": "visualize", "current": int(frame_count * 3), "total": int(total_progress_steps)})

    return (
        stabilized_raw_frames.astype(np.float32, copy=False),
        frames_sub,
        frames_viz,
    )
