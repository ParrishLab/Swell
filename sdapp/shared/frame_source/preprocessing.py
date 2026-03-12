from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter


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


def build_visualization_stack(
    frame_source,
    *,
    baseline_frames: int = 30,
    apply_smoothing: bool = True,
    apply_baseline_subtraction: bool = True,
    apply_global_normalization: bool = True,
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
    for i in range(frame_count):
        raw = np.asarray(frame_source.get_raw_frame(i))
        if raw.ndim == 3 and raw.shape[2] in (3, 4):
            raw = raw[:, :, :3].mean(axis=2)
        raw_frames.append(raw.astype(np.float32))

    if bool(apply_smoothing):
        source_for_sub = np.asarray([gaussian_filter(frame, sigma=0.5) for frame in raw_frames], dtype=np.float32)
    else:
        source_for_sub = np.asarray(raw_frames, dtype=np.float32)

    if bool(apply_baseline_subtraction):
        baseline_count = max(1, min(int(baseline_frames), int(source_for_sub.shape[0])))
        baseline = np.median(source_for_sub[:baseline_count], axis=0)
        frames_sub = source_for_sub - baseline
    else:
        frames_sub = source_for_sub.copy()

    frames_viz: list[np.ndarray] = []
    if bool(apply_global_normalization):
        subsample = frames_sub[::5] if frames_sub.shape[0] > 0 else frames_sub
        p1 = float(np.percentile(subsample, 1)) if subsample.size > 0 else 0.0
        p99 = float(np.percentile(subsample, 99)) if subsample.size > 0 else 1.0
        denom = p99 - p1
        if denom == 0:
            denom = 1e-8
        for frame in frames_sub:
            clipped = np.clip(frame, p1, p99)
            norm = (clipped - p1) / denom
            frames_viz.append((norm * 255).astype(np.uint8))
    else:
        for frame in frames_sub:
            frames_viz.append(_frame_to_uint8(frame))

    return np.asarray(raw_frames, dtype=np.float32), np.asarray(frames_sub, dtype=np.float32), np.asarray(frames_viz, dtype=np.uint8)
