from __future__ import annotations

from collections import OrderedDict
from types import SimpleNamespace
import importlib.util

import numpy as np

from sdapp.host.config import EventCandidate
from sdapp.host.controllers.host_window_controller import HostWindowController
from sdapp.host.exporter import analysis_image_cache_key


class _NonMaterializedFrames:
    def __len__(self) -> int:
        return 4

    def __getitem__(self, idx: int):
        raise AssertionError(f"should not materialize frame {idx}")


def test_seed_analysis_image_export_cache_keeps_live_sequence_without_materializing() -> None:
    frames_viz = _NonMaterializedFrames()
    event = EventCandidate(
        event_id="event_0001",
        start_idx=2,
        end_idx=3,
        duration_frames=2,
        duration_sec=None,
        flags={
            "baseline_pre_frames": 2,
            "analysis_scope_start_idx": 0,
            "analysis_scope_end_idx": 3,
        },
    )
    app = SimpleNamespace(
        _analysis_image_export_cache=OrderedDict(),
        analysis_window_manager=SimpleNamespace(
            get=lambda scope_id, event_id: (
                SimpleNamespace(app=SimpleNamespace(frames_sub_viz=frames_viz))
                if scope_id == "__project__" and event_id == "event_0001"
                else None
            )
        ),
    )
    controller = HostWindowController(app)

    cache = controller._seed_analysis_image_export_cache([event], baseline_pre_frames=30)

    cache_key = analysis_image_cache_key(event, default_baseline_pre_frames=30)
    entry = cache[cache_key]
    assert entry["frames_viz"] is frames_viz
    assert entry["frame_count"] == 4


def test_combined_metric_spreadsheet_requires_at_least_one_metric_selection() -> None:
    assert (
        HostWindowController._can_export_combined_metric_spreadsheet(
            include_metric_propagation_speed=False,
            include_metric_area_recruited=False,
            include_metric_relative_area_recruited=False,
        )
        is False
    )
    assert (
        HostWindowController._can_export_combined_metric_spreadsheet(
            include_metric_propagation_speed=True,
            include_metric_area_recruited=False,
            include_metric_relative_area_recruited=False,
        )
        is True
    )


def test_combined_metric_spreadsheet_requires_openpyxl(monkeypatch) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None if name == "openpyxl" else object())

    assert (
        HostWindowController._can_export_combined_metric_spreadsheet(
            include_metric_propagation_speed=True,
            include_metric_area_recruited=False,
            include_metric_relative_area_recruited=False,
        )
        is False
    )


def test_propagation_gap_event_name_prefers_label_from_payload() -> None:
    app = SimpleNamespace(browser_controller=SimpleNamespace(get_event=lambda _event_id: None))
    controller = HostWindowController(app)

    assert controller._propagation_gap_event_name({"event_id": "event_0001", "event_label": "Halo(Light Off) 1"}) == "Halo(Light Off) 1"


def test_propagation_gap_event_name_falls_back_to_browser_event_label() -> None:
    app = SimpleNamespace(browser_controller=SimpleNamespace(get_event=lambda _event_id: SimpleNamespace(label="Halo(Light Off) 1")))
    controller = HostWindowController(app)

    assert controller._propagation_gap_event_name({"event_id": "event_0001"}) == "Halo(Light Off) 1"


def test_propagation_action_specs_clarify_end_trace_here() -> None:
    specs = HostWindowController._propagation_action_specs("gap")

    assert [spec["label"] for spec in specs] == ["Leave Blank", "End Trace Here", "Average Between Frames"]
    assert "first affected frame onward" in specs[1]["description"]


def test_apply_preview_action_zero_and_stop() -> None:
    values = np.asarray([np.nan, 6.0, np.nan, 10.0], dtype=np.float64)
    runs = [(2, 2)]

    zeroed = HostWindowController._apply_preview_action(values, runs, "zero")
    stopped = HostWindowController._apply_preview_action(values, runs, "stop")

    assert float(zeroed[2]) == 0.0
    assert np.isnan(stopped[2])
    assert np.isnan(stopped[3])
