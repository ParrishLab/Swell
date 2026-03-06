from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from config import EventCandidate, FrameRef
from exporter import export_analysis


class FakeReader:
    def __init__(self, frames: list[np.ndarray], source_ext: str = ".tif"):
        self._frames = frames
        self._refs: list[FrameRef] = []
        for idx in range(len(frames)):
            self._refs.append(
                FrameRef(
                    frame_idx=idx,
                    source_path=Path(f"/fake/frame_{idx:04d}{source_ext}"),
                    page_index=None,
                    source_ext=source_ext,
                    frame_name=f"frame_{idx:04d}{source_ext}",
                )
            )

    def read_frame(self, frame_idx: int, use_cache: bool = True) -> np.ndarray:  # noqa: ARG002
        return self._frames[frame_idx]

    def get_frame_ref(self, frame_idx: int) -> FrameRef:
        return self._refs[frame_idx]


def _rows(path: Path) -> list[dict]:
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_export_parallel_manifest_order_is_deterministic(tmp_path: Path) -> None:
    frames = [np.full((8, 8), i, dtype=np.uint8) for i in range(40)]
    reader = FakeReader(frames)
    events = [
        EventCandidate("event_0001", start_idx=10, end_idx=12, duration_frames=3, duration_sec=None),
        EventCandidate("event_0002", start_idx=20, end_idx=22, duration_frames=3, duration_sec=None),
    ]

    export_analysis(reader=reader, events=events, output_dir=tmp_path, baseline_pre_frames=3)
    records = _rows(tmp_path / "events_manifest.csv")

    by_event: dict[str, list[dict]] = {}
    for r in records:
        by_event.setdefault(r["event_id"], []).append(r)

    for ev in events:
        ev_rows = by_event[ev.event_id]
        roles = [r["role"] for r in ev_rows]
        idxs = [int(r["frame_idx"]) for r in ev_rows]

        # baseline first in ascending order, then event ascending order
        baseline_end = ev.start_idx - 1
        baseline_start = max(0, baseline_end - 3 + 1) if baseline_end >= 0 else None
        expected_baseline = [] if baseline_start is None else list(range(baseline_start, baseline_end + 1))
        expected_event = list(range(ev.start_idx, ev.end_idx + 1))
        expected_idxs = expected_baseline + expected_event

        assert idxs == expected_idxs
        assert roles == (["baseline"] * len(expected_baseline) + ["event"] * len(expected_event))
