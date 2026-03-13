from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest

from sdapp.host.config import EventCandidate, FrameRef, TraceResult
from sdapp.host.exporter import export_analysis


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


def _load_manifest_rows(csv_path: Path) -> list[dict]:
    with csv_path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _event(event_id: str, start: int, end: int) -> EventCandidate:
    return EventCandidate(
        event_id=event_id,
        start_idx=start,
        end_idx=end,
        duration_frames=end - start + 1,
        duration_sec=None,
    )


def test_export_without_trace_skips_trace_artifacts(tmp_path: Path) -> None:
    frames = [np.full((8, 8), i, dtype=np.uint8) for i in range(5)]
    reader = FakeReader(frames)
    events = [_event("event_0001", 1, 3)]

    result = export_analysis(
        reader=reader,
        events=events,
        output_dir=tmp_path,
        baseline_pre_frames=30,
        trace=None,
    )

    assert result["events_exported"] == 1
    assert result["frames_exported"] == 4  # baseline frame 0 + event frames 1,2,3
    assert not (tmp_path / "trace_data.csv").exists()
    assert not (tmp_path / "trace_plot.png").exists()
    assert (tmp_path / "events_manifest.csv").exists()
    assert (tmp_path / "events_manifest.json").exists()


def test_export_with_trace_writes_trace_files(tmp_path: Path) -> None:
    frames = [np.full((8, 8), i, dtype=np.uint8) for i in range(4)]
    reader = FakeReader(frames)
    events = [_event("event_0001", 1, 2)]
    trace = TraceResult(
        frame_indices=[0, 1, 2, 3],
        time_sec=[0.0, 1.0, 2.0, 3.0],
        mean=[10.0, 11.0, 12.0, 13.0],
        median=[9.0, 10.0, 11.0, 12.0],
        std=[1.0, 1.1, 1.2, 1.3],
    )

    export_analysis(
        reader=reader,
        events=events,
        output_dir=tmp_path,
        baseline_pre_frames=30,
        trace=trace,
    )

    assert (tmp_path / "trace_data.csv").exists()
    assert (tmp_path / "trace_plot.png").exists()


def test_export_selected_event_ids_filters_output(tmp_path: Path) -> None:
    frames = [np.full((8, 8), i, dtype=np.uint8) for i in range(10)]
    reader = FakeReader(frames)
    events = [_event("event_0001", 2, 3), _event("event_0002", 7, 8)]

    result = export_analysis(
        reader=reader,
        events=events,
        output_dir=tmp_path,
        baseline_pre_frames=2,
        selected_event_ids=["event_0002"],
    )

    assert result["events_exported"] == 1
    assert (tmp_path / "event_0002").exists()
    assert not (tmp_path / "event_0001").exists()

    rows = _load_manifest_rows(tmp_path / "events_manifest.csv")
    event_ids = {row["event_id"] for row in rows}
    assert event_ids == {"event_0002"}


def test_export_event_starting_at_zero_has_no_baseline_frames(tmp_path: Path) -> None:
    frames = [np.full((8, 8), i, dtype=np.uint8) for i in range(4)]
    reader = FakeReader(frames)
    events = [_event("event_0001", 0, 1)]

    result = export_analysis(
        reader=reader,
        events=events,
        output_dir=tmp_path,
        baseline_pre_frames=30,
        trace=None,
    )

    assert result["events_exported"] == 1
    assert result["frames_exported"] == 2

    rows = _load_manifest_rows(tmp_path / "events_manifest.csv")
    assert len(rows) == 2
    assert {row["role"] for row in rows} == {"event"}
    assert {int(row["frame_idx"]) for row in rows} == {0, 1}

    summary = json.loads((tmp_path / "event_0001" / "event_summary.json").read_text(encoding="utf-8"))
    assert summary["baseline_start_idx"] is None
    assert summary["baseline_end_idx"] is None


def test_export_baseline_pre_frames_limits_baseline_window(tmp_path: Path) -> None:
    frames = [np.full((8, 8), i, dtype=np.uint8) for i in range(20)]
    reader = FakeReader(frames)
    events = [_event("event_0001", 10, 10)]

    export_analysis(
        reader=reader,
        events=events,
        output_dir=tmp_path,
        baseline_pre_frames=3,
    )

    rows = _load_manifest_rows(tmp_path / "events_manifest.csv")
    baseline_rows = [r for r in rows if r["role"] == "baseline"]
    assert [int(r["frame_idx"]) for r in baseline_rows] == [7, 8, 9]


def test_export_uses_tiff_for_float_frames_even_if_source_png(tmp_path: Path) -> None:
    frames = [np.full((5, 5), 0.25, dtype=np.float32), np.full((5, 5), 0.5, dtype=np.float32)]
    reader = FakeReader(frames, source_ext=".png")
    events = [_event("event_0001", 0, 1)]

    export_analysis(reader=reader, events=events, output_dir=tmp_path, baseline_pre_frames=0)

    rows = _load_manifest_rows(tmp_path / "events_manifest.csv")
    assert len(rows) == 2
    for row in rows:
        assert row["output_path"].endswith(".tiff")


def test_export_manifest_timestamps_follow_trace_time_sec(tmp_path: Path) -> None:
    frames = [np.full((5, 5), i, dtype=np.uint8) for i in range(4)]
    reader = FakeReader(frames)
    events = [_event("event_0001", 1, 2)]
    trace = TraceResult(
        frame_indices=[0, 1, 2, 3],
        time_sec=[None, 1.5],
        mean=[],
        median=[],
        std=[],
    )

    export_analysis(
        reader=reader,
        events=events,
        output_dir=tmp_path,
        baseline_pre_frames=1,
        trace=trace,
    )

    rows = _load_manifest_rows(tmp_path / "events_manifest.csv")
    by_idx = {int(r["frame_idx"]): r for r in rows}

    assert by_idx[0]["timestamp_sec"] == ""
    assert by_idx[1]["timestamp_sec"] == "1.5"
    assert by_idx[2]["timestamp_sec"] == ""


def test_export_options_allow_event_only_or_baseline_only(tmp_path: Path) -> None:
    frames = [np.full((8, 8), i, dtype=np.uint8) for i in range(12)]
    reader = FakeReader(frames)
    events = [_event("event_0001", 5, 7)]

    event_only = tmp_path / "event_only"
    baseline_only = tmp_path / "baseline_only"

    result_event_only = export_analysis(
        reader=reader,
        events=events,
        output_dir=event_only,
        baseline_pre_frames=3,
        include_event_images=True,
        include_baseline_images=False,
    )
    rows_event_only = _load_manifest_rows(event_only / "events_manifest.csv")
    assert result_event_only["frames_exported"] == 3
    assert {row["role"] for row in rows_event_only} == {"event"}
    assert not (event_only / "event_0001" / "baseline").exists()

    result_baseline_only = export_analysis(
        reader=reader,
        events=events,
        output_dir=baseline_only,
        baseline_pre_frames=3,
        include_event_images=False,
        include_baseline_images=True,
    )
    rows_baseline_only = _load_manifest_rows(baseline_only / "events_manifest.csv")
    assert result_baseline_only["frames_exported"] == 3
    assert {row["role"] for row in rows_baseline_only} == {"baseline"}
    assert not (baseline_only / "event_0001" / "event_extent").exists()


def test_export_options_require_at_least_one_image_group(tmp_path: Path) -> None:
    frames = [np.full((8, 8), i, dtype=np.uint8) for i in range(6)]
    reader = FakeReader(frames)
    events = [_event("event_0001", 2, 4)]
    with pytest.raises(ValueError):
        export_analysis(
            reader=reader,
            events=events,
            output_dir=tmp_path,
            baseline_pre_frames=2,
            include_event_images=False,
            include_baseline_images=False,
        )


def test_export_metrics_only_writes_per_event_metrics_outputs(tmp_path: Path) -> None:
    frames = [np.full((8, 8), i, dtype=np.uint8) for i in range(10)]
    reader = FakeReader(frames)
    events = [_event("event_0001", 2, 5)]

    masks = np.zeros((10, 8, 8), dtype=np.uint8)
    masks[2, 2:4, 2:4] = 1
    masks[3, 2:5, 2:5] = 1
    masks[4, 1:5, 1:5] = 1
    masks[5, 1:6, 1:6] = 1

    result = export_analysis(
        reader=reader,
        events=events,
        output_dir=tmp_path,
        baseline_pre_frames=2,
        include_event_images=False,
        include_baseline_images=False,
        include_metric_propagation_speed=True,
        include_metric_area_recruited=True,
        include_metric_relative_area_recruited=True,
        analysis_sidecar={
            "event_0001": {
                "masks_committed": masks,
                "metrics_settings": {
                    "frames_per_sec": 2.0,
                    "scale_px_per_mm": 4.0,
                    "roi_mask": np.ones((8, 8), dtype=bool),
                },
            }
        },
    )

    metrics_dir = tmp_path / "event_0001" / "metrics"
    assert result["frames_exported"] == 0
    assert int(result["metrics_files_exported"]) >= 7
    assert (metrics_dir / "propagation_speed.csv").exists()
    assert (metrics_dir / "propagation_speed.png").exists()
    assert (metrics_dir / "area_recruited.csv").exists()
    assert (metrics_dir / "area_recruited.png").exists()
    assert (metrics_dir / "relative_area_recruited.csv").exists()
    assert (metrics_dir / "relative_area_recruited.png").exists()
    assert (metrics_dir / "metrics_summary.json").exists()


def test_export_metrics_respects_selection_flags(tmp_path: Path) -> None:
    frames = [np.full((8, 8), i, dtype=np.uint8) for i in range(8)]
    reader = FakeReader(frames)
    events = [_event("event_0001", 1, 3)]
    masks = np.zeros((8, 8, 8), dtype=np.uint8)
    masks[1, 2:4, 2:4] = 1
    masks[2, 2:5, 2:5] = 1
    masks[3, 1:5, 1:5] = 1

    export_analysis(
        reader=reader,
        events=events,
        output_dir=tmp_path,
        baseline_pre_frames=2,
        include_event_images=True,
        include_baseline_images=False,
        include_metric_propagation_speed=True,
        include_metric_area_recruited=False,
        include_metric_relative_area_recruited=False,
        analysis_sidecar={
            "event_0001": {
                "masks_committed": masks,
                "metrics_settings": {
                    "frames_per_sec": 1.0,
                    "scale_px_per_mm": 3.0,
                    "roi_points": [[1.0, 1.0], [6.0, 1.0], [6.0, 6.0], [1.0, 6.0]],
                },
            }
        },
    )

    metrics_dir = tmp_path / "event_0001" / "metrics"
    assert (metrics_dir / "propagation_speed.csv").exists()
    assert not (metrics_dir / "area_recruited.csv").exists()
    assert not (metrics_dir / "relative_area_recruited.csv").exists()


def test_export_binary_masks_writes_mask_images_when_available(tmp_path: Path) -> None:
    frames = [np.full((8, 8), i, dtype=np.uint8) for i in range(10)]
    reader = FakeReader(frames)
    events = [_event("event_0001", 4, 6)]
    masks = np.zeros((10, 8, 8), dtype=np.uint8)
    masks[3, 2:6, 2:6] = 1  # baseline frame
    masks[5, 1:4, 1:4] = 1  # event frame

    result = export_analysis(
        reader=reader,
        events=events,
        output_dir=tmp_path,
        baseline_pre_frames=2,
        include_binary_masks=True,
        analysis_sidecar={"event_0001": {"masks_committed": masks}},
    )
    masks_dir = tmp_path / "event_0001" / "binary_masks"
    assert masks_dir.exists()
    exported_masks = sorted(p.name for p in masks_dir.glob("*.tiff"))
    assert exported_masks == ["000003_baseline_mask.tiff", "000005_event_mask.tiff"]
    assert result["masks_exported"] == 2
