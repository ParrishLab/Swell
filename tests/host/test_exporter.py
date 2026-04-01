from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest
import tifffile

from sdapp.host.config import EventCandidate, FrameRef, TraceResult
from sdapp.host.exporter import _build_event_global_mask_map, analysis_image_cache_key, export_analysis
from sdapp.shared.frame_source import EventScopedFrameSource, SDStackFrameSource, build_visualization_stack
from sdapp.shared.persistence.event_path import allocate_event_path_segment


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

    def get_frame_count(self) -> int:
        return len(self._frames)

    def get_stack_info(self):
        frame = np.asarray(self._frames[0]) if self._frames else np.zeros((0, 0), dtype=np.uint8)

        class _Info:
            frame_height = int(frame.shape[0]) if frame.ndim >= 2 else 0
            frame_width = int(frame.shape[1]) if frame.ndim >= 2 else 0

        return _Info()

    def get_frame_ref(self, frame_idx: int) -> FrameRef:
        return self._refs[frame_idx]


def _load_manifest_rows(csv_path: Path) -> list[dict]:
    with csv_path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _event(
    event_id: str,
    start: int,
    end: int,
    *,
    flags: dict | None = None,
    label: str | None = None,
) -> EventCandidate:
    return EventCandidate(
        event_id=event_id,
        start_idx=start,
        end_idx=end,
        duration_frames=end - start + 1,
        duration_sec=None,
        flags=dict(flags or {}),
        label=label,
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
    assert (tmp_path / "events_manifest.md").exists()
    manifest_text = (tmp_path / "events_manifest.md").read_text(encoding="utf-8")
    assert "Events exported: 1" in manifest_text
    assert "### event_0001" in manifest_text


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


def test_export_sanitizes_event_output_directory_names(tmp_path: Path) -> None:
    frames = [np.full((8, 8), i, dtype=np.uint8) for i in range(10)]
    reader = FakeReader(frames)
    events = [
        _event("event_0001", 2, 3, label="A:B"),
        _event("event_0002", 7, 8, label="A?B"),
    ]

    export_analysis(
        reader=reader,
        events=events,
        output_dir=tmp_path,
        baseline_pre_frames=2,
    )

    used: set[str] = set()
    seg_a = allocate_event_path_segment("A:B", used)
    seg_b = allocate_event_path_segment("A?B", used)
    assert (tmp_path / seg_a).exists()
    assert (tmp_path / seg_b).exists()


def test_export_uses_visible_label_for_output_directory_names(tmp_path: Path) -> None:
    frames = [np.full((8, 8), i, dtype=np.uint8) for i in range(6)]
    reader = FakeReader(frames)
    events = [_event("event_0001", 1, 2, label="Renamed Event")]

    export_analysis(
        reader=reader,
        events=events,
        output_dir=tmp_path,
        baseline_pre_frames=1,
    )

    assert (tmp_path / "Renamed Event").exists()
    assert not (tmp_path / "event_0001").exists()


def test_export_disambiguates_duplicate_visible_labels(tmp_path: Path) -> None:
    frames = [np.full((8, 8), i, dtype=np.uint8) for i in range(8)]
    reader = FakeReader(frames)
    events = [
        _event("event_0001", 1, 2, label="Same Label"),
        _event("event_0002", 4, 5, label="Same Label"),
    ]

    export_analysis(
        reader=reader,
        events=events,
        output_dir=tmp_path,
        baseline_pre_frames=1,
    )

    used: set[str] = set()
    seg_a = allocate_event_path_segment("Same Label", used)
    seg_b = allocate_event_path_segment("Same Label", used)
    assert (tmp_path / seg_a).exists()
    assert (tmp_path / seg_b).exists()


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
    summary_text = (tmp_path / "event_0001" / "event_summary.md").read_text(encoding="utf-8")
    assert "Baseline start frame: n/a" in summary_text
    assert "Duration (frames): 2" in summary_text


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


def test_export_binary_masks_only_is_allowed(tmp_path: Path) -> None:
    frames = [np.full((8, 8), i, dtype=np.uint8) for i in range(8)]
    reader = FakeReader(frames)
    events = [_event("event_0001", 2, 4)]
    masks = np.zeros((8, 8, 8), dtype=np.uint8)
    masks[2, 1:4, 1:4] = 1

    result = export_analysis(
        reader=reader,
        events=events,
        output_dir=tmp_path,
        baseline_pre_frames=2,
        include_event_images=False,
        include_baseline_images=False,
        include_binary_masks=True,
        analysis_sidecar={"event_0001": {"masks_committed": masks}},
    )

    assert result["frames_exported"] == 0
    assert result["masks_exported"] == 1
    assert (tmp_path / "event_0001" / "binary_masks" / "000002_event_mask.tiff").exists()


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
    assert (metrics_dir / "metrics_summary.md").exists()
    summary = json.loads((metrics_dir / "metrics_summary.json").read_text(encoding="utf-8"))
    assert float(summary["event_start_time_sec"]) == 1.0
    assert float(summary["event_end_time_sec"]) == 2.5
    assert "overall_max_speed_um_per_sec" in summary
    metrics_text = (metrics_dir / "metrics_summary.md").read_text(encoding="utf-8")
    assert "Selected metrics: propagation_speed, area_recruited, relative_area_recruited" in metrics_text
    assert "Overall max speed (um/sec): " in metrics_text
    assert "ROI available: yes" in metrics_text


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


def test_build_event_global_mask_map_uses_analysis_scope_for_local_arrays() -> None:
    event = _event(
        "event_0001",
        12,
        15,
        flags={
            "baseline_pre_frames": 2,
            "analysis_scope_start_idx": 10,
            "analysis_scope_end_idx": 15,
            "analysis_local_event_start_idx": 2,
            "analysis_local_event_end_idx": 5,
        },
    )
    masks = np.zeros((6, 5, 5), dtype=np.uint8)
    masks[2, 1:3, 1:3] = 1
    masks[3, 1:4, 1:4] = 1
    masks[4, 0:4, 0:4] = 1
    masks[5, 0:5, 0:5] = 1

    mask_map = _build_event_global_mask_map(
        event=event,
        masks_payload=masks,
        baseline_pre_frames=0,
    )

    assert sorted(mask_map) == [10, 11, 12, 13, 14, 15]
    assert int(np.count_nonzero(mask_map[12])) == 4
    assert int(np.count_nonzero(mask_map[13])) == 9
    assert int(np.count_nonzero(mask_map[14])) == 16
    assert int(np.count_nonzero(mask_map[15])) == 25


def test_build_event_global_mask_map_uses_event_local_dict_indices_for_legacy_sidecars() -> None:
    event = _event(
        "event_0001",
        12,
        15,
        flags={
            "baseline_pre_frames": 2,
            "analysis_scope_start_idx": 10,
            "analysis_scope_end_idx": 15,
            "analysis_local_event_start_idx": 2,
            "analysis_local_event_end_idx": 5,
        },
    )
    mask_map = _build_event_global_mask_map(
        event=event,
        masks_payload={"0": np.ones((5, 5), dtype=np.uint8)},
        baseline_pre_frames=0,
    )

    assert sorted(mask_map) == [12]
    assert int(np.count_nonzero(mask_map[12])) == 25


def test_export_metrics_uses_analysis_scope_local_mask_arrays(tmp_path: Path) -> None:
    frames = [np.full((8, 8), i, dtype=np.uint8) for i in range(20)]
    reader = FakeReader(frames)
    event = _event(
        "event_0001",
        12,
        15,
        flags={
            "baseline_pre_frames": 2,
            "analysis_scope_start_idx": 10,
            "analysis_scope_end_idx": 15,
            "analysis_local_event_start_idx": 2,
            "analysis_local_event_end_idx": 5,
        },
    )
    masks = np.zeros((6, 8, 8), dtype=np.uint8)
    masks[2, 3:5, 3:5] = 1
    masks[3, 2:5, 2:5] = 1
    masks[4, 2:6, 2:6] = 1
    masks[5, 1:6, 1:6] = 1

    export_analysis(
        reader=reader,
        events=[event],
        output_dir=tmp_path,
        baseline_pre_frames=0,
        include_event_images=False,
        include_baseline_images=False,
        include_metric_area_recruited=True,
        include_metric_relative_area_recruited=True,
        analysis_sidecar={
            "event_0001": {
                "masks_committed": masks,
                "metrics_settings": {
                    "frames_per_sec": 1.0,
                    "scale_px_per_mm": 2.0,
                    "roi_mask": np.ones((8, 8), dtype=bool),
                },
            }
        },
    )

    metrics_dir = tmp_path / "event_0001" / "metrics"
    with (metrics_dir / "area_recruited.csv").open("r", newline="", encoding="utf-8") as f:
        area_rows = list(csv.DictReader(f))
    with (metrics_dir / "relative_area_recruited.csv").open("r", newline="", encoding="utf-8") as f:
        relative_rows = list(csv.DictReader(f))

    assert [int(row["frame_index"]) for row in area_rows] == [12, 13, 14, 15]
    assert [float(row["area_mm2"]) for row in area_rows] == [0.25, 1.0, 2.25, 4.0]
    assert [int(row["frame_index"]) for row in relative_rows] == [12, 13, 14, 15]
    assert [float(row["relative_area_pct"]) for row in relative_rows] == [1.5625, 6.25, 14.0625, 25.0]


def test_export_metrics_uses_legacy_event_local_mask_arrays(tmp_path: Path) -> None:
    frames = [np.full((8, 8), i, dtype=np.uint8) for i in range(20)]
    reader = FakeReader(frames)
    event = _event(
        "event_0001",
        12,
        15,
        flags={
            "baseline_pre_frames": 2,
            "analysis_scope_start_idx": 10,
            "analysis_scope_end_idx": 15,
            "analysis_local_event_start_idx": 2,
            "analysis_local_event_end_idx": 5,
        },
    )
    masks = np.zeros((4, 8, 8), dtype=np.uint8)
    masks[0, 3:5, 3:5] = 1
    masks[1, 2:5, 2:5] = 1
    masks[2, 2:6, 2:6] = 1
    masks[3, 1:6, 1:6] = 1

    export_analysis(
        reader=reader,
        events=[event],
        output_dir=tmp_path,
        baseline_pre_frames=0,
        include_event_images=False,
        include_baseline_images=False,
        include_metric_area_recruited=True,
        include_metric_relative_area_recruited=True,
        analysis_sidecar={
            "event_0001": {
                "masks_committed": masks,
                "masks_committed_frame_origin": "event_local",
                "metrics_settings": {
                    "frames_per_sec": 1.0,
                    "scale_px_per_mm": 2.0,
                    "roi_mask": np.ones((8, 8), dtype=bool),
                },
            }
        },
    )

    metrics_dir = tmp_path / "event_0001" / "metrics"
    with (metrics_dir / "area_recruited.csv").open("r", newline="", encoding="utf-8") as f:
        area_rows = list(csv.DictReader(f))

    assert [int(row["frame_index"]) for row in area_rows] == [12, 13, 14, 15]
    assert [float(row["area_mm2"]) for row in area_rows] == [0.25, 1.0, 2.25, 4.0]


def test_export_metrics_gap_warning_can_ignore(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    frames = [np.full((8, 8), i, dtype=np.uint8) for i in range(20)]
    reader = FakeReader(frames)
    event = _event("event_0001", 12, 15)
    masks = np.zeros((20, 8, 8), dtype=np.uint8)
    masks[12:16, 1:7, 1:7] = 1
    decisions: list[dict[str, object]] = []
    monkeypatch.setattr(
        "sdapp.host.exporter.compute_frame_metrics",
        lambda _boundaries, min_dist_px=2.0: {  # noqa: ARG005
            "avg_dist_px": np.asarray([np.nan, 6.0, np.nan, 10.0], dtype=np.float64),
            "areas_px": np.asarray([1.0, 1.0, 1.0, 1.0], dtype=np.float64),
        },
    )

    export_analysis(
        reader=reader,
        events=[event],
        output_dir=tmp_path,
        baseline_pre_frames=0,
        include_event_images=False,
        include_baseline_images=False,
        include_metric_propagation_speed=True,
        analysis_sidecar={
            "event_0001": {
                "masks_committed": masks,
                "metrics_settings": {
                    "frames_per_sec": 1.0,
                    "scale_px_per_mm": 2.0,
                    "roi_mask": np.ones((8, 8), dtype=bool),
                },
            }
        },
        propagation_gap_decision=lambda payload: decisions.append(dict(payload)) or "ignore",
    )

    metrics_dir = tmp_path / "event_0001" / "metrics"
    rows = list(csv.DictReader((metrics_dir / "propagation_speed.csv").open("r", newline="", encoding="utf-8")))
    warning = json.loads((metrics_dir / "propagation_speed_warning.json").read_text(encoding="utf-8"))

    assert decisions == [{"event_id": "event_0001", "gap_frame_runs": [[14, 14]], "metric": "propagation_speed"}]
    assert rows[2]["frame_index"] == "14"
    assert rows[2]["speed_um_per_sec"] == ""
    assert warning["action"] == "ignore"
    assert warning["frame_runs"] == [[14, 14]]
    summary = json.loads((metrics_dir / "metrics_summary.json").read_text(encoding="utf-8"))
    assert float(summary["overall_max_speed_um_per_sec"]) == 5000.0


def test_export_metrics_gap_warning_can_stop_at_gap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    frames = [np.full((8, 8), i, dtype=np.uint8) for i in range(20)]
    reader = FakeReader(frames)
    event = _event("event_0001", 12, 15)
    masks = np.zeros((20, 8, 8), dtype=np.uint8)
    masks[12:16, 1:7, 1:7] = 1
    monkeypatch.setattr(
        "sdapp.host.exporter.compute_frame_metrics",
        lambda _boundaries, min_dist_px=2.0: {  # noqa: ARG005
            "avg_dist_px": np.asarray([np.nan, 6.0, np.nan, 10.0], dtype=np.float64),
            "areas_px": np.asarray([1.0, 1.0, 1.0, 1.0], dtype=np.float64),
        },
    )

    export_analysis(
        reader=reader,
        events=[event],
        output_dir=tmp_path,
        baseline_pre_frames=0,
        include_event_images=False,
        include_baseline_images=False,
        include_metric_propagation_speed=True,
        analysis_sidecar={
            "event_0001": {
                "masks_committed": masks,
                "metrics_settings": {
                    "frames_per_sec": 1.0,
                    "scale_px_per_mm": 2.0,
                    "roi_mask": np.ones((8, 8), dtype=bool),
                },
            }
        },
        propagation_gap_decision=lambda _payload: "stop",
    )

    metrics_dir = tmp_path / "event_0001" / "metrics"
    rows = list(csv.DictReader((metrics_dir / "propagation_speed.csv").open("r", newline="", encoding="utf-8")))

    assert rows[1]["speed_um_per_sec"] != ""
    assert rows[2]["speed_um_per_sec"] == ""
    assert rows[3]["speed_um_per_sec"] == ""


def test_export_metrics_gap_warning_can_interpolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    frames = [np.full((8, 8), i, dtype=np.uint8) for i in range(20)]
    reader = FakeReader(frames)
    event = _event("event_0001", 12, 15)
    masks = np.zeros((20, 8, 8), dtype=np.uint8)
    masks[12:16, 1:7, 1:7] = 1
    monkeypatch.setattr(
        "sdapp.host.exporter.compute_frame_metrics",
        lambda _boundaries, min_dist_px=2.0: {  # noqa: ARG005
            "avg_dist_px": np.asarray([np.nan, 6.0, np.nan, 10.0], dtype=np.float64),
            "areas_px": np.asarray([1.0, 1.0, 1.0, 1.0], dtype=np.float64),
        },
    )

    export_analysis(
        reader=reader,
        events=[event],
        output_dir=tmp_path,
        baseline_pre_frames=0,
        include_event_images=False,
        include_baseline_images=False,
        include_metric_propagation_speed=True,
        analysis_sidecar={
            "event_0001": {
                "masks_committed": masks,
                "metrics_settings": {
                    "frames_per_sec": 1.0,
                    "scale_px_per_mm": 2.0,
                    "roi_mask": np.ones((8, 8), dtype=bool),
                },
            }
        },
        propagation_gap_decision=lambda _payload: "interpolate",
    )

    metrics_dir = tmp_path / "event_0001" / "metrics"
    rows = list(csv.DictReader((metrics_dir / "propagation_speed.csv").open("r", newline="", encoding="utf-8")))
    warning = json.loads((metrics_dir / "propagation_speed_warning.json").read_text(encoding="utf-8"))
    values = [row["speed_um_per_sec"] for row in rows]

    assert values[1] != ""
    assert values[2] != ""
    assert values[3] != ""
    assert float(values[2]) > 0.0
    assert warning["action"] == "interpolate"


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


def test_export_mask_overlay_images_match_analysis_overlay_tint(tmp_path: Path) -> None:
    frames = [np.full((6, 6), 100, dtype=np.uint8) for _ in range(8)]
    reader = FakeReader(frames)
    events = [_event("event_0001", 3, 4)]
    masks = np.zeros((8, 6, 6), dtype=np.uint8)
    masks[2, 1:5, 1:5] = 1  # baseline frame
    masks[4, 2:4, 2:4] = 1  # event frame

    result = export_analysis(
        reader=reader,
        events=events,
        output_dir=tmp_path,
        baseline_pre_frames=2,
        include_event_images=False,
        include_baseline_images=False,
        include_mask_overlay_images=True,
        analysis_sidecar={"event_0001": {"masks_committed": masks}},
    )

    overlays_dir = tmp_path / "event_0001" / "mask_overlays"
    exported = sorted(p.name for p in overlays_dir.glob("*"))
    assert exported == [
        "000002_baseline_overlay_frame_0002.tif",
        "000004_event_overlay_frame_0004.tif",
    ]
    baseline_overlay = tifffile.imread(str(overlays_dir / "000002_baseline_overlay_frame_0002.tif"))
    assert tuple(int(v) for v in baseline_overlay[0, 0]) == (100, 100, 100)
    assert tuple(int(v) for v in baseline_overlay[2, 2]) == (70, 146, 146)
    assert result["mask_overlay_images_exported"] == 2


def test_export_analysis_images_match_visualization_stack(tmp_path: Path) -> None:
    frames = [np.full((5, 5), i * 10, dtype=np.uint8) for i in range(7)]
    reader = FakeReader(frames)
    event = _event(
        "event_0001",
        3,
        4,
        flags={
            "baseline_pre_frames": 2,
            "analysis_processing": {
                "horizontal_bar_denoise": False,
                "smoothing": False,
                "baseline_subtraction": True,
                "global_normalization": False,
            },
            "analysis_scope_start_idx": 1,
            "analysis_scope_end_idx": 4,
        },
    )

    result = export_analysis(
        reader=reader,
        events=[event],
        output_dir=tmp_path,
        baseline_pre_frames=30,
        include_event_images=False,
        include_baseline_images=False,
        include_analysis_images=True,
    )

    analysis_dir = tmp_path / "event_0001" / "analysis_images"
    exported = sorted(p.name for p in analysis_dir.glob("*.tif"))
    assert exported == [
        "000001_baseline_frame_0001.tif",
        "000002_baseline_frame_0002.tif",
        "000003_event_frame_0003.tif",
        "000004_event_frame_0004.tif",
    ]
    scoped_source = EventScopedFrameSource(SDStackFrameSource(reader=reader), 1, 4)
    _raw, _sub, expected_viz = build_visualization_stack(
        scoped_source,
        baseline_frames=2,
        apply_smoothing=False,
        apply_baseline_subtraction=True,
        apply_global_normalization=False,
    )
    for local_idx, name in enumerate(exported):
        arr = tifffile.imread(str(analysis_dir / name))
        assert np.array_equal(arr, np.asarray(expected_viz[local_idx], dtype=np.uint8))
    assert result["analysis_images_exported"] == 4


def test_export_analysis_images_reuse_cache_when_available(tmp_path: Path) -> None:
    frames = [np.zeros((4, 4), dtype=np.uint8) for _ in range(6)]
    reader = FakeReader(frames)
    event = _event(
        "event_0001",
        2,
        3,
        flags={
            "baseline_pre_frames": 2,
            "analysis_processing": {"horizontal_bar_denoise": False},
            "analysis_scope_start_idx": 0,
            "analysis_scope_end_idx": 3,
        },
    )
    cached_stack = np.asarray(
        [
            np.full((4, 4), 11, dtype=np.uint8),
            np.full((4, 4), 22, dtype=np.uint8),
            np.full((4, 4), 33, dtype=np.uint8),
            np.full((4, 4), 44, dtype=np.uint8),
        ],
        dtype=np.uint8,
    )
    cache = {analysis_image_cache_key(event, default_baseline_pre_frames=30): cached_stack}

    export_analysis(
        reader=reader,
        events=[event],
        output_dir=tmp_path,
        baseline_pre_frames=30,
        include_event_images=False,
        include_baseline_images=False,
        include_analysis_images=True,
        analysis_image_cache=cache,
    )

    analysis_dir = tmp_path / "event_0001" / "analysis_images"
    arr = tifffile.imread(str(analysis_dir / "000002_event_frame_0002.tif"))
    assert np.array_equal(arr, cached_stack[2])


def test_export_analysis_images_reuse_cached_sequence_when_available(tmp_path: Path) -> None:
    class _Sequence:
        def __init__(self, frames: list[np.ndarray]) -> None:
            self._frames = [np.asarray(frame, dtype=np.uint8) for frame in frames]
            self.index_calls: list[int] = []

        def __len__(self) -> int:
            return len(self._frames)

        def __getitem__(self, idx: int) -> np.ndarray:
            self.index_calls.append(int(idx))
            return self._frames[int(idx)]

    frames = [np.zeros((4, 4), dtype=np.uint8) for _ in range(6)]
    reader = FakeReader(frames)
    event = _event(
        "event_0001",
        2,
        3,
        flags={
            "baseline_pre_frames": 2,
            "analysis_processing": {"horizontal_bar_denoise": False},
            "analysis_scope_start_idx": 0,
            "analysis_scope_end_idx": 3,
        },
    )
    cached_sequence = _Sequence(
        [
            np.full((4, 4), 11, dtype=np.uint8),
            np.full((4, 4), 22, dtype=np.uint8),
            np.full((4, 4), 33, dtype=np.uint8),
            np.full((4, 4), 44, dtype=np.uint8),
        ]
    )
    cache = {
        analysis_image_cache_key(event, default_baseline_pre_frames=30): {
            "frames_viz": cached_sequence,
            "frame_count": 4,
        }
    }

    export_analysis(
        reader=reader,
        events=[event],
        output_dir=tmp_path,
        baseline_pre_frames=30,
        include_event_images=False,
        include_baseline_images=False,
        include_analysis_images=True,
        analysis_image_cache=cache,
    )

    analysis_dir = tmp_path / "event_0001" / "analysis_images"
    arr = tifffile.imread(str(analysis_dir / "000002_event_frame_0002.tif"))
    assert np.array_equal(arr, np.full((4, 4), 33, dtype=np.uint8))
    assert cached_sequence.index_calls == [0, 1, 2, 3]


def test_export_analysis_images_emits_prepare_progress(tmp_path: Path) -> None:
    frames = [np.full((5, 5), i, dtype=np.uint8) for i in range(6)]
    reader = FakeReader(frames)
    event = _event(
        "event_0001",
        2,
        4,
        flags={
            "baseline_pre_frames": 2,
            "analysis_scope_start_idx": 0,
            "analysis_scope_end_idx": 4,
        },
    )
    progress: list[dict] = []

    export_analysis(
        reader=reader,
        events=[event],
        output_dir=tmp_path,
        baseline_pre_frames=30,
        include_event_images=False,
        include_baseline_images=False,
        include_analysis_images=True,
        progress_callback=lambda payload: progress.append(dict(payload)),
    )

    prepare_updates = [p for p in progress if p.get("phase") == "analysis_prepare"]
    assert prepare_updates
    assert prepare_updates[0]["event_id"] == "event_0001"
    assert prepare_updates[-1]["current"] == prepare_updates[-1]["total"]


def test_export_analysis_images_honors_horizontal_bar_denoise_flag(tmp_path: Path) -> None:
    striped = np.array(
        [
            [0, 0, 0, 0],
            [100, 100, 100, 100],
            [0, 0, 0, 0],
            [100, 100, 100, 100],
        ],
        dtype=np.uint8,
    )
    reader = FakeReader([striped, striped, striped])
    event = _event(
        "event_0001",
        1,
        2,
        flags={
            "baseline_pre_frames": 1,
            "analysis_processing": {
                "horizontal_bar_denoise": True,
                "smoothing": False,
                "baseline_subtraction": False,
                "global_normalization": False,
            },
            "analysis_scope_start_idx": 0,
            "analysis_scope_end_idx": 2,
        },
    )

    export_analysis(
        reader=reader,
        events=[event],
        output_dir=tmp_path,
        baseline_pre_frames=30,
        include_event_images=False,
        include_baseline_images=False,
        include_analysis_images=True,
    )

    arr = tifffile.imread(str(tmp_path / "event_0001" / "analysis_images" / "000001_event_frame_0001.tif"))
    assert np.all(arr == 0)
