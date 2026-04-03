from __future__ import annotations

from collections import OrderedDict
from types import SimpleNamespace

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
