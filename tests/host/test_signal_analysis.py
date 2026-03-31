from __future__ import annotations

import numpy as np

from sdapp.host.config import EventCandidate
from sdapp.host.signal_analysis import compute_trace, event_to_dict


class DummyReader:
    def __init__(self, frames: list[np.ndarray]):
        self._frames = frames
        self.use_cache_calls: list[bool] = []

    def get_frame_count(self) -> int:
        return len(self._frames)

    def read_frame(self, frame_idx: int, use_cache: bool = True) -> np.ndarray:
        self.use_cache_calls.append(bool(use_cache))
        return self._frames[frame_idx]


def test_compute_trace_stats_and_default_time_none() -> None:
    frames = [
        np.array([[0, 2], [2, 4]], dtype=np.uint8),
        np.array([[1, 1], [1, 5]], dtype=np.uint8),
    ]
    trace = compute_trace(DummyReader(frames))

    assert trace.frame_indices == [0, 1]
    assert trace.time_sec == [None, None]
    assert trace.mean == [2.0, 2.0]
    assert trace.median == [2.0, 1.0]
    assert trace.std[0] == np.std(frames[0])
    assert trace.std[1] == np.std(frames[1])


def test_compute_trace_generates_time_when_seconds_per_frame_positive() -> None:
    frames = [np.zeros((2, 2), dtype=np.uint8) for _ in range(3)]
    trace = compute_trace(DummyReader(frames), seconds_per_frame=0.5)
    assert trace.time_sec == [0.0, 0.5, 1.0]


def test_compute_trace_ignores_nonpositive_seconds_per_frame() -> None:
    frames = [np.zeros((2, 2), dtype=np.uint8) for _ in range(2)]
    trace_zero = compute_trace(DummyReader(frames), seconds_per_frame=0)
    trace_neg = compute_trace(DummyReader(frames), seconds_per_frame=-1.0)
    assert trace_zero.time_sec == [None, None]
    assert trace_neg.time_sec == [None, None]


def test_compute_trace_progress_callback_frequency() -> None:
    frames = [np.zeros((2, 2), dtype=np.uint8) for _ in range(120)]
    calls: list[tuple[int, int]] = []

    compute_trace(DummyReader(frames), progress_callback=lambda cur, total: calls.append((cur, total)))

    assert calls == [(1, 120), (51, 120), (101, 120), (120, 120)]


def test_compute_trace_uses_cache_aware_reads_and_preserves_values() -> None:
    frames = [np.arange(16, dtype=np.uint8).reshape(4, 4) + idx for idx in range(20)]
    reader = DummyReader(frames)

    trace = compute_trace(reader)

    assert all(reader.use_cache_calls)
    assert trace.mean[0] == float(np.mean(frames[0]))
    assert trace.median[10] == float(np.median(frames[10]))
    assert trace.std[-1] == float(np.std(frames[-1]))


def test_event_to_dict_matches_event_candidate_fields() -> None:
    event = EventCandidate(
        event_id="event_0007",
        start_idx=10,
        end_idx=15,
        duration_frames=6,
        duration_sec=None,
    )
    out = event_to_dict(event)

    assert out == {
        "event_id": "event_0007",
        "start_idx": 10,
        "end_idx": 15,
        "duration_frames": 6,
        "duration_sec": None,
    }


def test_event_to_dict_includes_flags_only_when_present() -> None:
    event = EventCandidate(
        event_id="event_0008",
        start_idx=20,
        end_idx=25,
        duration_frames=6,
        duration_sec=3.0,
        flags={"baseline_pre_frames": 30},
    )

    assert event_to_dict(event) == {
        "event_id": "event_0008",
        "start_idx": 20,
        "end_idx": 25,
        "duration_frames": 6,
        "duration_sec": 3.0,
        "flags": {"baseline_pre_frames": 30},
    }
