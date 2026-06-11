from __future__ import annotations

from unittest.mock import patch

import numpy as np

from sdapp.analysis.core.analysis_controller import AnalysisController
from sdapp.analysis.core.analysis_context import AnalysisContext
from sdapp.analysis.controllers.window_controller import AnalysisWindowController


def _make_controller():
    state = {
        "scale": None,
        "scale_points": [],
        "scale_axis_lock": True,
        "scale_image_path": "",
        "roi_points": [],
        "roi_polygons": [],
        "roi_mask": None,
        "scale_local": False,
        "roi_local": False,
        "metrics_changed": [],
        "global_updates": [],
        "cleared_local": [],
        "autosaves": [],
        "updated": 0,
    }

    controller = AnalysisController(
        root=None,
        app_root=".",
        ctx=AnalysisContext(
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
            get_scale_axis_lock=lambda: bool(state["scale_axis_lock"]),
            set_scale_axis_lock=lambda v: state.__setitem__("scale_axis_lock", bool(v)),
            get_last_scale_image_path=lambda: "",
            set_last_scale_image_path=lambda v: state.__setitem__("scale_image_path", str(v or "")),
            get_roi_mask=lambda: state["roi_mask"],
            set_roi_mask=lambda v: state.__setitem__("roi_mask", v),
            get_roi_points=lambda: list(state["roi_points"]),
            set_roi_points=lambda v: state.__setitem__("roi_points", list(v)),
            get_roi_polygons=lambda: list(state["roi_polygons"]),
            set_roi_polygons=lambda v: state.__setitem__("roi_polygons", list(v)),
            update_display=lambda: state.__setitem__("updated", state["updated"] + 1),
            log_info=lambda *_args: None,
            log_success=lambda *_args: None,
            on_metrics_settings_changed=lambda reason: state["metrics_changed"].append(str(reason)),
            emit_host_global_metrics_update=lambda reason, payload: state["global_updates"].append((str(reason), dict(payload))) or {"ok": True},
            clear_local_metrics_override=lambda reason, keys: state["cleared_local"].append((str(reason), list(keys))) or {"ok": True, "metrics_settings": {"frames_per_sec": 1.0}, "local_metrics_settings": {}},
            autosave_project_after_metrics_commit=lambda reason: state["autosaves"].append(str(reason)) or {"ok": True},
            get_scale_is_local_override=lambda: bool(state["scale_local"]),
            set_scale_is_local_override=lambda v: state.__setitem__("scale_local", bool(v)),
            get_roi_is_local_override=lambda: bool(state["roi_local"]),
            set_roi_is_local_override=lambda v: state.__setitem__("roi_local", bool(v)),
        ),
    )
    return controller, state


def test_local_scale_selection_updates_local_state() -> None:
    controller, state = _make_controller()
    controller._capture_scale_selection = lambda: {
        "px_per_mm": 5.0,
        "scale_points": [(1.0, 1.0), (5.0, 1.0)],
        "image_path": "/tmp/local-scale.png",
        "fallback": False,
        "refined_ok": True,
        "axis_mode": "horizontal",
        "axis_lock": True,
    }
    with patch("sdapp.analysis.core.analysis_controller.messagebox.showinfo"):
        controller.start_local_scale_selection()

    assert float(state["scale"]) == 5.0
    assert state["scale_axis_lock"] is True
    assert state["scale_image_path"] == "/tmp/local-scale.png"
    assert state["scale_local"] is True
    assert state["metrics_changed"] == ["scale"]
    assert state["autosaves"] == ["local_scale"]


def test_global_scale_selection_emits_global_update_and_preserves_existing_local_override() -> None:
    controller, state = _make_controller()
    state["scale"] = 9.0
    state["scale_points"] = [(2.0, 2.0), (6.0, 2.0)]
    state["scale_local"] = True
    controller._capture_scale_selection = lambda: {
        "px_per_mm": 5.0,
        "scale_points": [(1.0, 1.0), (5.0, 1.0)],
        "image_path": "/tmp/global-scale.png",
        "fallback": False,
        "refined_ok": True,
        "axis_mode": "horizontal",
        "axis_lock": False,
    }
    with patch("sdapp.analysis.core.analysis_controller.messagebox.showinfo"):
        controller.start_global_scale_selection()

    assert float(state["scale"]) == 9.0
    assert state["scale_local"] is True
    assert state["global_updates"][0][0] == "global_scale"
    assert float(state["global_updates"][0][1]["scale_px_per_mm"]) == 5.0
    assert state["global_updates"][0][1]["scale_axis_lock"] is False
    assert state["global_updates"][0][1]["scale_image_path"] == "/tmp/global-scale.png"
    assert state["autosaves"] == ["global_scale"]


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
    assert state["autosaves"] == ["global_roi"]


def test_global_and_local_roi_selection_updates_both_scopes() -> None:
    controller, state = _make_controller()
    roi_mask = np.ones((4, 4), dtype=bool)
    polygons = [[[1.0, 1.0], [3.0, 1.0], [3.0, 3.0]]]
    controller._capture_roi_selection = lambda: {
        "target_scope": "global_and_local",
        "roi_points": polygons[0],
        "roi_polygons": polygons,
        "roi_mask": roi_mask,
    }

    with patch("sdapp.analysis.core.analysis_controller.messagebox.showinfo"):
        controller.start_roi_selection()

    assert state["roi_local"] is True
    assert state["roi_points"] == polygons[0]
    assert state["roi_polygons"] == polygons
    assert state["global_updates"][0][0] == "global_roi"
    assert state["global_updates"][0][1]["roi_polygons"] == polygons
    assert state["autosaves"] == ["global_and_local_roi"]


def test_reset_local_scale_override_clears_event_local_keys() -> None:
    controller, state = _make_controller()
    state["scale_local"] = True
    with patch("sdapp.analysis.core.analysis_controller.messagebox.showinfo"):
        controller.reset_local_scale_override()

    assert state["cleared_local"] == [
        ("reset_local_scale", ["scale_px_per_mm", "scale_unit", "scale_source", "scale_points", "scale_axis_lock", "scale_image_path"])
    ]
    assert state["autosaves"] == ["reset_local_scale"]


def test_reset_local_roi_override_clears_event_local_keys() -> None:
    controller, state = _make_controller()
    state["roi_local"] = True
    with patch("sdapp.analysis.core.analysis_controller.messagebox.showinfo"):
        controller.reset_local_roi_override()

    assert state["cleared_local"] == [("reset_local_roi", ["roi_points", "roi_polygons", "roi_mask"])]
    assert state["autosaves"] == ["reset_local_roi"]


class _Var:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def _make_metrics_preview_window_controller(*, frame_count=1, raw_masks=None, composed_masks=None, include_compose=True):
    app = type("App", (), {})()
    app.metrics_preview_var = _Var("")
    app.frames_per_sec_var = _Var(1.0)
    app.scale_px_per_mm = None
    app.roi_mask = None
    app.masks_cache = dict(raw_masks or {})
    app._ui_alive = lambda: False
    app._get_frame_count = lambda: int(frame_count)
    if include_compose:
        masks = dict(composed_masks or {})
        app._compose_final_mask_for_frame = lambda idx: masks.get(int(idx))
    return AnalysisWindowController(app), app


def _capture_boundary(captured):
    def _extract(mask):
        captured["mask"] = np.asarray(mask, dtype=bool).copy()
        return np.array([[0.0, 0.0]])

    return _extract


def test_metrics_preview_uses_composed_final_masks_for_region_only_preview(monkeypatch) -> None:
    region_only = np.zeros((6, 6), dtype=bool)
    region_only[1:5, 1:5] = True
    controller, app = _make_metrics_preview_window_controller(
        raw_masks={},
        composed_masks={0: region_only},
    )
    captured = {}

    monkeypatch.setattr(
        "sdapp.analysis.core.metrics.extract_primary_boundary",
        _capture_boundary(captured),
    )
    monkeypatch.setattr(
        "sdapp.analysis.core.metrics.compute_frame_metrics",
        lambda boundaries: {"areas_px": np.array([float(np.count_nonzero(captured["mask"]))]), "avg_dist_px": np.array([])},
    )

    controller.compute_metrics_preview()

    assert np.array_equal(captured["mask"], region_only)
    assert app.metrics_preview_var.get() == "Max Area: 16 px"


def test_metrics_preview_uses_composed_final_masks_for_paint_only_preview(monkeypatch) -> None:
    paint_only = np.zeros((6, 6), dtype=bool)
    paint_only[2:4, 2:5] = True
    controller, app = _make_metrics_preview_window_controller(
        raw_masks={},
        composed_masks={0: paint_only},
    )
    captured = {}

    monkeypatch.setattr(
        "sdapp.analysis.core.metrics.extract_primary_boundary",
        _capture_boundary(captured),
    )
    monkeypatch.setattr(
        "sdapp.analysis.core.metrics.compute_frame_metrics",
        lambda boundaries: {"areas_px": np.array([float(np.count_nonzero(captured["mask"]))]), "avg_dist_px": np.array([])},
    )

    controller.compute_metrics_preview()

    assert np.array_equal(captured["mask"], paint_only)
    assert app.metrics_preview_var.get() == "Max Area: 6 px"


def test_metrics_preview_reports_no_masks_when_composed_masks_are_empty() -> None:
    empty = np.zeros((6, 6), dtype=bool)
    controller, app = _make_metrics_preview_window_controller(
        raw_masks={0: np.ones((6, 6), dtype=bool)},
        composed_masks={0: empty},
    )

    controller.compute_metrics_preview()

    assert app.metrics_preview_var.get() == "Preview: No active masks to measure."


def test_metrics_preview_falls_back_to_raw_masks_without_compose_helper(monkeypatch) -> None:
    raw = np.zeros((6, 6), dtype=bool)
    raw[1:3, 1:4] = True
    controller, app = _make_metrics_preview_window_controller(
        raw_masks={0: raw},
        include_compose=False,
    )
    captured = {}

    monkeypatch.setattr(
        "sdapp.analysis.core.metrics.extract_primary_boundary",
        _capture_boundary(captured),
    )
    monkeypatch.setattr(
        "sdapp.analysis.core.metrics.compute_frame_metrics",
        lambda boundaries: {"areas_px": np.array([float(np.count_nonzero(captured["mask"]))]), "avg_dist_px": np.array([])},
    )

    controller.compute_metrics_preview()

    assert np.array_equal(captured["mask"], raw)
    assert app.metrics_preview_var.get() == "Max Area: 6 px"
