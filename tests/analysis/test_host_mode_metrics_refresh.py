from __future__ import annotations

from swell.analysis.app import SwellAnalysisApp


def test_workspace_event_open_refreshes_host_metrics_for_new_event() -> None:
    app = SwellAnalysisApp.__new__(SwellAnalysisApp)
    applied: list[tuple[dict | None, dict | None]] = []
    app._host_mode = True
    app._host_context_provider = lambda event_id: {
        "metrics_settings": {"frames_per_sec": 1.0, "roi_points": [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0]]},
        "local_metrics_settings": {"roi_points": [[1.0, 1.0], [3.0, 1.0], [3.0, 3.0]]} if event_id == "event_0002" else {},
    }
    app._apply_host_metrics_settings = lambda metrics, local=None: applied.append((metrics, local))
    app._clear_propagation_overlay_state = lambda: None
    app._recompute_slider_jump_markers = lambda: None
    app._sync_saved_mask_overlay_state = lambda reset_history=False: None
    app._get_frame_count = lambda: 5
    app._get_frame_shape = lambda: (8, 8)
    app.log_debug = lambda *_args, **_kwargs: None
    app.log_warn = lambda *_args, **_kwargs: None

    app._on_workspace_event_opened("event_0002")

    assert len(applied) == 1
    assert applied[0][0] == {"frames_per_sec": 1.0, "roi_points": [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0]]}
    assert applied[0][1] == {"roi_points": [[1.0, 1.0], [3.0, 1.0], [3.0, 3.0]]}
