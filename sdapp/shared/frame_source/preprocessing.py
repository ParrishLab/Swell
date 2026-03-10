from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter


def build_visualization_stack(frame_source, *, baseline_frames: int = 30) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
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

    denoised = np.asarray([gaussian_filter(frame, sigma=0.5) for frame in raw_frames], dtype=np.float32)
    baseline_count = max(1, min(int(baseline_frames), int(denoised.shape[0])))
    baseline = np.median(denoised[:baseline_count], axis=0)
    frames_sub = denoised - baseline

    subsample = frames_sub[::5] if frames_sub.shape[0] > 0 else frames_sub
    p1 = float(np.percentile(subsample, 1)) if subsample.size > 0 else 0.0
    p99 = float(np.percentile(subsample, 99)) if subsample.size > 0 else 1.0
    denom = p99 - p1
    if denom == 0:
        denom = 1e-8
    frames_viz = []
    for frame in frames_sub:
        clipped = np.clip(frame, p1, p99)
        norm = (clipped - p1) / denom
        frames_viz.append((norm * 255).astype(np.uint8))

    return np.asarray(raw_frames, dtype=np.float32), np.asarray(frames_sub, dtype=np.float32), np.asarray(frames_viz, dtype=np.uint8)
