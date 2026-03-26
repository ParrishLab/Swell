from __future__ import annotations

from unittest.mock import patch

import numpy as np

from sdapp.analysis.core.analysis_controller import AnalysisController


def _make_controller():
    state = {
        "scale": None,
        "scale_points": [],
        "roi_points": [],
        "roi_mask": None,
        "scale_local": False,
        "roi_local": False,
        "metrics_changed": [],
        "global_updates": [],
        "updated": 0,
    }

    controller = AnalysisController(
        root=None,
        app_root=".",
        get_frame_count=lambda: 1,
        get_raw_frame=lambda _idx: np.zeros((8, 8), dtype=np.uint8),
        get_masks_cache=lambda: {},
        get_paint_layers=lambda: {},
        get_points=lambda: {},
        get_frame_names=lambda: [],
        get_import_source_hint=lambda: "",
        get_current_image_source_paths=lambda: [],
        get_compose_final_mask_for_frame=lambda _idx: None,
        get_nonempty_final_mask_frames=lambda: set(),
        get_frames_per_sec=lambda: 1.0,
        get_scale_px_per_mm=lambda: state["scale"],
        set_scale_px_per_mm=lambda v: state.__setitem__("scale", v),
        get_scale_points=lambda: list(state["scale_points"]),
        set_scale_points=lambda v: state.__setitem__("scale_points", list(v)),
        get_last_scale_image_path=lambda: "",
        set_last_scale_image_path=lambda _v: None,
        get_roi_mask=lambda: state["roi_mask"],
        set_roi_mask=lambda v: state.__setitem__("roi_mask", v),
        get_roi_points=lambda: list(state["roi_points"]),
        set_roi_points=lambda v: state.__setitem__("roi_points", list(v)),
        update_display=lambda: state.__setitem__("updated", state["updated"] + 1),
        log_info=lambda *_args: None,
        log_success=lambda *_args: None,
        on_metrics_settings_changed=lambda reason: state["metrics_changed"].append(str(reason)),
        emit_host_global_metrics_update=lambda reason, payload: state["global_updates"].append((str(reason), dict(payload))) or {"ok": True},
        get_scale_is_local_override=lambda: bool(state["scale_local"]),
        set_scale_is_local_override=lambda v: state.__setitem__("scale_local", bool(v)),
        get_roi_is_local_override=lambda: bool(state["roi_local"]),
        set_roi_is_local_override=lambda v: state.__setitem__("roi_local", bool(v)),
    )
    return controller, state


def test_local_scale_selection_updates_local_state() -> None:
    controller, state = _make_controller()
    controller._capture_scale_selection = lambda: {
        "px_per_mm": 5.0,
        "scale_points": [(1.0, 1.0), (5.0, 1.0)],
        "fallback": False,
        "refined_ok": True,
        "axis_mode": "horizontal",
    }
    with patch("sdapp.analysis.core.analysis_controller.messagebox.showinfo"):
        controller.start_local_scale_selection()

    assert float(state["scale"]) == 5.0
    assert state["scale_local"] is True
    assert state["metrics_changed"] == ["scale"]


def test_global_scale_selection_emits_global_update_and_preserves_existing_local_override() -> None:
    controller, state = _make_controller()
    state["scale"] = 9.0
    state["scale_points"] = [(2.0, 2.0), (6.0, 2.0)]
    state["scale_local"] = True
    controller._capture_scale_selection = lambda: {
        "px_per_mm": 5.0,
        "scale_points": [(1.0, 1.0), (5.0, 1.0)],
        "fallback": False,
        "refined_ok": True,
        "axis_mode": "horizontal",
    }
    with patch("sdapp.analysis.core.analysis_controller.messagebox.showinfo"):
        controller.start_global_scale_selection()

    assert float(state["scale"]) == 9.0
    assert state["scale_local"] is True
    assert state["global_updates"][0][0] == "global_scale"
    assert float(state["global_updates"][0][1]["scale_px_per_mm"]) == 5.0


def test_global_roi_selection_updates_visible_state_when_no_local_override() -> None:
    controller, state = _make_controller()
    roi_mask = np.ones((4, 4), dtype=bool)
    controller._capture_roi_selection = lambda: {
        "roi_points": [[1.0, 1.0], [3.0, 1.0], [3.0, 3.0]],
        "roi_mask": roi_mask,
    }
    with patch("sdapp.analysis.core.analysis_controller.messagebox.showinfo"):
        controller.start_global_roi_selection()

    assert state["roi_local"] is False
    assert len(state["roi_points"]) == 3
    assert np.array_equal(np.asarray(state["roi_mask"], dtype=bool), roi_mask)
    assert state["updated"] == 1
