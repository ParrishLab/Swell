from __future__ import annotations

import numpy as np

from sdapp.host.processing_engine import PopupProcessRequest, PopupProcessingEngine


class CountingReader:
    def __init__(self, frames: list[np.ndarray]):
        self.frames = frames
        self.read_calls: dict[int, int] = {}

    def read_frame(self, frame_idx: int, use_cache: bool = True) -> np.ndarray:  # noqa: ARG002
        self.read_calls[frame_idx] = self.read_calls.get(frame_idx, 0) + 1
        return self.frames[frame_idx]


def test_smoothed_cache_reduces_repeat_reads() -> None:
    frames = [np.full((16, 16), i, dtype=np.uint8) for i in range(40)]
    reader = CountingReader(frames)
    engine = PopupProcessingEngine(smoothed_cache_max=128)
    engine.set_reader(reader)  # type: ignore[arg-type]

    req = PopupProcessRequest(
        job_id=1,
        range_start=5,
        range_end=25,
        baseline_count=10,
        baseline_end=14,
        current_idx=15,
        warm_radius=3,
    )
    result1 = engine.run_popup_sync(req)
    assert result1 is not None
    reads_after_first = sum(reader.read_calls.values())

    # Same request should heavily reuse smoothed/baseline/norm caches.
    result2 = engine.run_popup_sync(req)
    assert result2 is not None
    reads_after_second = sum(reader.read_calls.values())

    assert reads_after_second - reads_after_first <= 2


def test_baseline_cache_key_changes_when_count_or_end_changes() -> None:
    frames = [np.full((8, 8), i, dtype=np.uint8) for i in range(30)]
    reader = CountingReader(frames)
    engine = PopupProcessingEngine(smoothed_cache_max=128)
    engine.set_reader(reader)  # type: ignore[arg-type]

    r1 = engine.run_popup_sync(PopupProcessRequest(1, 10, 20, 5, 12, 13))
    r2 = engine.run_popup_sync(PopupProcessRequest(2, 10, 20, 6, 12, 13))
    r3 = engine.run_popup_sync(PopupProcessRequest(3, 10, 20, 5, 13, 13))

    assert r1 is not None and r2 is not None and r3 is not None
    assert np.any(r1.baseline_frame != r2.baseline_frame)
    assert np.any(r1.baseline_frame != r3.baseline_frame)


def test_sampled_diff_cache_respects_byte_budget() -> None:
    frames = [np.full((64, 64), i, dtype=np.uint8) for i in range(80)]
    reader = CountingReader(frames)
    engine = PopupProcessingEngine(smoothed_cache_max=128)
    engine.set_reader(reader)  # type: ignore[arg-type]

    engine._sampled_diff_cache_max_bytes = 64 * 1024  # type: ignore[attr-defined]
    req = PopupProcessRequest(
        job_id=1,
        range_start=0,
        range_end=79,
        baseline_count=10,
        baseline_end=20,
        current_idx=40,
        warm_radius=0,
        sample_stride=1,
    )
    result = engine.run_popup_sync(req)
    assert result is not None

    assert engine._sampled_diff_cache_bytes <= engine._sampled_diff_cache_max_bytes  # type: ignore[attr-defined]


def test_collect_garbage_aggressive_clears_engine_caches() -> None:
    frames = [np.full((32, 32), i, dtype=np.uint8) for i in range(40)]
    reader = CountingReader(frames)
    engine = PopupProcessingEngine(smoothed_cache_max=128)
    engine.set_reader(reader)  # type: ignore[arg-type]
    req = PopupProcessRequest(1, 5, 30, 10, 20, 18)
    assert engine.run_popup_sync(req) is not None

    engine.collect_garbage(aggressive=True)

    assert len(engine._smoothed_cache) == 0  # type: ignore[attr-defined]
    assert len(engine._baseline_cache) == 0  # type: ignore[attr-defined]
    assert len(engine._norm_cache) == 0  # type: ignore[attr-defined]
    assert len(engine._sampled_diff_cache) == 0  # type: ignore[attr-defined]
