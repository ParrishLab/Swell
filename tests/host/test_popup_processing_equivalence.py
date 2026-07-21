from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter

from swell.host.processing_engine import PopupProcessRequest, PopupProcessingEngine


class Reader:
    def __init__(self, frames: list[np.ndarray]):
        self.frames = frames

    def read_frame(self, frame_idx: int, use_cache: bool = True) -> np.ndarray:  # noqa: ARG002
        return self.frames[frame_idx]


def legacy_compute(frames: list[np.ndarray], range_start: int, range_end: int, baseline_count: int, baseline_end: int):
    baseline_start = max(0, baseline_end - baseline_count + 1)
    bidx = list(range(baseline_start, baseline_end + 1))
    baseline_stack = [gaussian_filter(frames[i].astype(np.float32), sigma=0.5) for i in bidx]
    baseline = np.median(np.stack(baseline_stack, axis=0), axis=0).astype(np.float32, copy=False)

    sampled_indices = list(range(range_start, range_end + 1, 5))
    if (range_end - range_start) % 5 != 0:
        sampled_indices.append(range_end)
    sampled_diffs = [gaussian_filter(frames[i].astype(np.float32), sigma=0.5) - baseline for i in sampled_indices]
    sampled_stack = np.stack(sampled_diffs, axis=0)
    p1 = float(np.percentile(sampled_stack, 1))
    p99 = float(np.percentile(sampled_stack, 99))
    if p99 <= p1:
        p99 = p1 + 1e-8
    return baseline, p1, p99


def test_engine_matches_legacy_stats_within_tolerance() -> None:
    rng = np.random.default_rng(42)
    frames = [rng.integers(0, 255, size=(32, 32), dtype=np.uint8) for _ in range(80)]
    range_start, range_end = 10, 60
    baseline_count, baseline_end = 30, 20

    legacy_baseline, legacy_p1, legacy_p99 = legacy_compute(frames, range_start, range_end, baseline_count, baseline_end)

    engine = PopupProcessingEngine(smoothed_cache_max=128)
    engine.set_reader(Reader(frames))  # type: ignore[arg-type]
    result = engine.run_popup_sync(
        PopupProcessRequest(
            job_id=1,
            range_start=range_start,
            range_end=range_end,
            baseline_count=baseline_count,
            baseline_end=baseline_end,
            current_idx=30,
        )
    )
    assert result is not None

    assert np.allclose(result.baseline_frame, legacy_baseline, atol=1e-5)
    assert abs(result.p1 - legacy_p1) <= 1e-5
    assert abs(result.p99 - legacy_p99) <= 1e-5


def test_engine_sanitizes_nonfinite_frames_before_smoothing_and_stats() -> None:
    frames = [np.full((8, 8), idx, dtype=np.float32) for idx in range(12)]
    frames[2][0, 0] = np.nan
    frames[5][1, 1] = np.inf
    engine = PopupProcessingEngine(smoothed_cache_max=32)
    engine.set_reader(Reader(frames))  # type: ignore[arg-type]

    result = engine.run_popup_sync(PopupProcessRequest(1, 0, 11, 4, 3, 6))

    assert result is not None
    assert np.all(np.isfinite(result.baseline_frame))
    assert np.isfinite(result.p1)
    assert np.isfinite(result.p99)
    assert all(np.all(np.isfinite(frame)) for frame in result.warmed_frames.values())
