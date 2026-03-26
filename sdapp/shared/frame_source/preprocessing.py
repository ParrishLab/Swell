from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
from scipy.ndimage import gaussian_filter


@dataclass
class VisualizationStats:
    frame_count: int
    frame_shape: tuple[int, int]
    baseline_frames: int
    apply_horizontal_bar_denoise: bool
    apply_smoothing: bool
    apply_baseline_subtraction: bool
    apply_global_normalization: bool
    baseline: np.ndarray | None = None
    p1: float | None = None
    p99: float | None = None


class VisualizationCancelled(RuntimeError):
    """Raised when visualization preprocessing is canceled by the caller."""


def _frame_to_uint8(frame: np.ndarray) -> np.ndarray:
    arr = np.asarray(frame, dtype=np.float32)
    if arr.size == 0:
        return np.zeros((0, 0), dtype=np.uint8)
    lo = float(np.min(arr))
    hi = float(np.max(arr))
    denom = hi - lo
    if denom <= 0:
        return np.zeros(arr.shape, dtype=np.uint8)
    norm = (arr - lo) / denom
    return np.clip(norm * 255.0, 0.0, 255.0).astype(np.uint8)


def normalize_visual_frame(frame: np.ndarray, *, p1: float | None = None, p99: float | None = None) -> np.ndarray:
    arr = np.asarray(frame, dtype=np.float32)
    if arr.size == 0:
        return np.zeros((0, 0), dtype=np.uint8)
    if p1 is None or p99 is None:
        return _frame_to_uint8(arr)
    lo = float(p1)
    hi = float(p99)
    denom = hi - lo
    if denom <= 0:
        denom = 1e-8
    clipped = np.clip(arr, lo, hi)
    return np.clip(((clipped - lo) / denom) * 255.0, 0.0, 255.0).astype(np.uint8)


def _read_frame_float32(frame_source, idx: int) -> np.ndarray:
    raw = np.asarray(frame_source.get_raw_frame(int(idx)))
    if raw.ndim == 3 and raw.shape[2] in (3, 4):
        raw = raw[:, :, :3].mean(axis=2)
    return raw.astype(np.float32, copy=False)


def remove_horizontal_bar_artifacts(frame: np.ndarray) -> np.ndarray:
    arr = np.asarray(frame, dtype=np.float32)
    if arr.ndim != 2 or arr.size == 0:
        return arr.astype(np.float32, copy=False)
    row_bias = np.median(arr, axis=1, keepdims=True).astype(np.float32, copy=False)
    global_bias = float(np.median(row_bias))
    corrected = arr - (row_bias - global_bias)
    return corrected.astype(np.float32, copy=False)


def _processed_frame(raw: np.ndarray, *, apply_horizontal_bar_denoise: bool, apply_smoothing: bool) -> np.ndarray:
    source = np.asarray(raw, dtype=np.float32, copy=False)
    if bool(apply_horizontal_bar_denoise):
        source = remove_horizontal_bar_artifacts(source)
    if not bool(apply_smoothing):
        return source
    return gaussian_filter(source, sigma=0.5)


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


def _raise_if_cancelled(should_cancel: Callable[[], bool] | None) -> None:
    if callable(should_cancel) and bool(should_cancel()):
        raise VisualizationCancelled("Visualization preparation canceled.")


def compute_visualization_stats(
    frame_source,
    *,
    baseline_frames: int = 30,
    apply_horizontal_bar_denoise: bool = False,
    apply_smoothing: bool = True,
    apply_baseline_subtraction: bool = True,
    apply_global_normalization: bool = True,
    should_cancel: Callable[[], bool] | None = None,
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
        )

    first_frame = _read_frame_float32(frame_source, 0)
    frame_shape = tuple(int(v) for v in first_frame.shape[:2])
    baseline_count = max(1, min(int(baseline_frames), frame_count))
    baseline = None
    if bool(apply_baseline_subtraction):
        baseline_parts = [
            (
                _raise_if_cancelled(should_cancel),
                _processed_source_frame(
                    frame_source,
                    idx,
                    apply_horizontal_bar_denoise=bool(apply_horizontal_bar_denoise),
                    apply_smoothing=bool(apply_smoothing),
                ),
            )[1]
            for idx in range(baseline_count)
        ]
        baseline = np.median(np.stack(baseline_parts, axis=0), axis=0).astype(np.float32, copy=False)

    p1 = None
    p99 = None
    if bool(apply_global_normalization):
        sampled_frames: list[np.ndarray] = []
        for idx in range(0, frame_count, 5):
            _raise_if_cancelled(should_cancel)
            source = _processed_source_frame(
                frame_source,
                idx,
                apply_horizontal_bar_denoise=bool(apply_horizontal_bar_denoise),
                apply_smoothing=bool(apply_smoothing),
            )
            if baseline is not None:
                source = source - baseline
            sampled_frames.append(source.astype(np.float32, copy=False))
        _raise_if_cancelled(should_cancel)
        sampled = np.stack(sampled_frames, axis=0) if sampled_frames else np.zeros((0,) + frame_shape, dtype=np.float32)
        p1 = float(np.percentile(sampled, 1)) if sampled.size > 0 else 0.0
        p99 = float(np.percentile(sampled, 99)) if sampled.size > 0 else 1.0

    return VisualizationStats(
        frame_count=frame_count,
        frame_shape=frame_shape,
        baseline_frames=baseline_count,
        apply_horizontal_bar_denoise=bool(apply_horizontal_bar_denoise),
        apply_smoothing=bool(apply_smoothing),
        apply_baseline_subtraction=bool(apply_baseline_subtraction),
        apply_global_normalization=bool(apply_global_normalization),
        baseline=baseline,
        p1=p1,
        p99=p99,
    )


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
        )
    idx = max(0, min(int(frame_idx), max(0, int(resolved_stats.frame_count) - 1)))
    raw = _read_frame_float32(frame_source, idx)
    source = _processed_frame(
        raw,
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
    return raw.astype(np.float32, copy=False), subtracted, visual


def build_visualization_stack(
    frame_source,
    *,
    baseline_frames: int = 30,
    apply_horizontal_bar_denoise: bool = False,
    apply_smoothing: bool = True,
    apply_baseline_subtraction: bool = True,
    apply_global_normalization: bool = True,
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

    raw_frames = []
    total_progress_steps = max(1, frame_count * 3)
    for i in range(frame_count):
        raw_frames.append(_read_frame_float32(frame_source, i))
        if callable(progress_callback):
            progress_callback(
                {
                    "stage": "read",
                    "current": int(i + 1),
                    "total": int(total_progress_steps),
                }
            )

    source_frames: list[np.ndarray] = []
    for i, frame in enumerate(raw_frames):
        source_frames.append(
            _processed_frame(
                frame,
                apply_horizontal_bar_denoise=bool(apply_horizontal_bar_denoise),
                apply_smoothing=bool(apply_smoothing),
            )
        )
        if callable(progress_callback):
            progress_callback(
                {
                    "stage": "preprocess",
                    "current": int(frame_count + i + 1),
                    "total": int(total_progress_steps),
                }
            )
    source_for_sub = np.asarray(source_frames, dtype=np.float32)

    baseline = None
    if bool(apply_baseline_subtraction):
        baseline_count = max(1, min(int(baseline_frames), int(source_for_sub.shape[0])))
        if (
            stats is not None
            and bool(stats.apply_baseline_subtraction)
            and stats.baseline is not None
            and tuple(int(v) for v in stats.frame_shape[:2]) == tuple(int(v) for v in source_for_sub.shape[1:3])
        ):
            baseline = np.asarray(stats.baseline, dtype=np.float32)
        else:
            baseline = np.median(source_for_sub[:baseline_count], axis=0).astype(np.float32, copy=False)
        frames_sub = source_for_sub - baseline
    else:
        frames_sub = source_for_sub.copy()

    frames_viz: list[np.ndarray] = []
    if bool(apply_global_normalization):
        subsample = frames_sub[::5] if frames_sub.shape[0] > 0 else frames_sub
        if stats is not None and bool(stats.apply_global_normalization):
            p1 = float(stats.p1 if stats.p1 is not None else 0.0)
            p99 = float(stats.p99 if stats.p99 is not None else 1.0)
        else:
            p1 = float(np.percentile(subsample, 1)) if subsample.size > 0 else 0.0
            p99 = float(np.percentile(subsample, 99)) if subsample.size > 0 else 1.0
        denom = p99 - p1
        if denom <= 0:
            denom = 1e-8
        for frame in frames_sub:
            clipped = np.clip(frame, p1, p99)
            norm = (clipped - p1) / denom
            frames_viz.append((norm * 255).astype(np.uint8))
            if callable(progress_callback):
                progress_callback(
                    {
                        "stage": "visualize",
                        "current": int((2 * frame_count) + len(frames_viz)),
                        "total": int(total_progress_steps),
                    }
                )
    else:
        for frame in frames_sub:
            frames_viz.append(_frame_to_uint8(frame))
            if callable(progress_callback):
                progress_callback(
                    {
                        "stage": "visualize",
                        "current": int((2 * frame_count) + len(frames_viz)),
                        "total": int(total_progress_steps),
                    }
                )

    return np.asarray(raw_frames, dtype=np.float32), np.asarray(frames_sub, dtype=np.float32), np.asarray(frames_viz, dtype=np.uint8)
