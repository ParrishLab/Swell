import numpy as np

from swell.analysis.app import SwellAnalysisApp
from swell.analysis.core.leverage import compute_trouble
from swell.analysis.core.seg_state import SegmentationState


def _make_ground_truth_app():
    app = SwellAnalysisApp.__new__(SwellAnalysisApp)
    app.seg_state = SegmentationState()
    app.current_frame_idx = 2
    app.undo_stack = []
    app.redo_stack = []
    app.project_dirty = False
    app._calls = {"leverage": 0, "markers": 0, "display": 0}
    app._get_frame_shape_for_idx = lambda _idx: (4, 4)
    app._refresh_ground_truth_controls = lambda *a, **k: None
    app._recompute_slider_jump_markers = lambda: app._calls.__setitem__("markers", app._calls["markers"] + 1)
    app._schedule_leverage_recompute = lambda *a, **k: app._calls.__setitem__("leverage", app._calls["leverage"] + 1)
    app.update_display = lambda *a, **k: app._calls.__setitem__("display", app._calls["display"] + 1)
    app.log_info = lambda *a, **k: None
    return app


def test_toggle_ground_truth_recomputes_leverage_so_marker_does_not_stick():
    app = _make_ground_truth_app()
    app.seg_state.set_mask(2, np.ones((4, 4), dtype=bool))

    result = app.toggle_ground_truth_current_frame()

    assert result is True
    assert app.seg_state.is_ground_truth_frame(2)
    # Locking changes the prompt-anchor set that compute_trouble zeroes out, so a
    # leverage recompute must fire or the white "suggested correction" marker sticks.
    assert app._calls["leverage"] == 1
    assert app.project_dirty is True


def test_toggle_ground_truth_rejects_empty_mask_frame():
    app = _make_ground_truth_app()  # no mask on the current frame

    result = app.toggle_ground_truth_current_frame()

    assert result is False
    assert not app.seg_state.is_ground_truth_frame(2)
    assert app._calls["leverage"] == 0


def test_mouse_up_region_edit_recomputes_leverage_and_marks_dirty():
    app = SwellAnalysisApp.__new__(SwellAnalysisApp)
    calls = {"leverage": 0, "dirty": 0}
    app._stop_canvas_pan = lambda _canvas, _event: None
    app.canvas_left = object()
    app.interaction_controller = type("Controller", (), {"on_mouse_up": lambda _self, _event: True})()
    app._schedule_leverage_recompute = lambda: calls.__setitem__("leverage", calls["leverage"] + 1)
    app._mark_project_dirty = lambda _reason: calls.__setitem__("dirty", calls["dirty"] + 1)

    app.on_mouse_up(object())

    assert calls == {"leverage": 1, "dirty": 1}


def test_compute_trouble_ignores_object_appearance_and_disappearance_edges():
    masks = {
        0: np.zeros((8, 8), dtype=bool),
        1: np.ones((8, 8), dtype=bool),
        2: np.zeros((8, 8), dtype=bool),
    }

    trouble = compute_trouble(masks, frame_count=3, frame_shape=(8, 8), user_frames=set())

    assert trouble == {}


def test_compute_trouble_scores_internal_instability_inside_object_span():
    left = np.zeros((8, 8), dtype=bool)
    left[:, :4] = True
    right = np.zeros((8, 8), dtype=bool)
    right[:, 4:] = True
    masks = {
        0: np.zeros((8, 8), dtype=bool),
        1: left,
        2: right,
        3: np.zeros((8, 8), dtype=bool),
    }

    trouble = compute_trouble(masks, frame_count=4, frame_shape=(8, 8), user_frames=set())

    assert trouble[1] > 0.0
    assert trouble[2] > 0.0
    assert 0 not in trouble
    assert 3 not in trouble


def test_sharp_jump_produces_visible_above_floor_leverage():
    """A single-frame discontinuity must read as a high-leverage correction site."""
    from swell.analysis.core.leverage import compute_leverage, LEVERAGE_FLOOR

    def blob(cx):
        m = np.zeros((64, 64), dtype=bool)
        yy, xx = np.ogrid[:64, :64]
        m[(xx - cx) ** 2 + (yy - 32) ** 2 <= 81] = True
        return m

    masks = {f: (blob(18) if f < 15 else blob(46)) for f in range(30)}
    trouble = compute_trouble(masks, 30, (64, 64), set())
    leverage, suggested = compute_leverage(trouble, 30)

    assert suggested is not None
    assert max(leverage.values()) >= LEVERAGE_FLOOR


def test_recompute_leverage_uses_composed_final_masks_from_paint_layers(monkeypatch):
    app = SwellAnalysisApp.__new__(SwellAnalysisApp)
    app.seg_state = SegmentationState()
    app._get_frame_count = lambda: 3
    app._get_frame_shape = lambda: (5, 5)
    app.seg_state.set_mask(1, np.zeros((5, 5), dtype=bool))
    plus = np.zeros((5, 5), dtype=bool)
    plus[1:4, 1:4] = True
    minus = np.zeros((5, 5), dtype=bool)
    app.seg_state.set_paint_layer(1, plus, minus)
    captured = {}

    def fake_compute_trouble(masks, frame_count, frame_shape, user_frames):
        captured["masks"] = masks
        captured["frame_count"] = frame_count
        captured["frame_shape"] = frame_shape
        captured["user_frames"] = user_frames
        return {1: 0.5}

    monkeypatch.setattr("swell.analysis.core.leverage.compute_trouble", fake_compute_trouble)
    monkeypatch.setattr("swell.analysis.core.leverage.compute_leverage", lambda trouble, frame_count: ({1: 0.4}, 1))

    app._recompute_leverage_map()

    assert captured["frame_count"] == 3
    assert captured["frame_shape"] == (5, 5)
    assert np.array_equal(captured["masks"][1], plus)
    assert app.seg_state.leverage_cache == {1: 0.4}
    assert app.seg_state.leverage_suggested_frame == 1


def test_set_propagated_frames_recomputes_leverage():
    """Ingesting propagated masks must refresh leverage so the heatmap is current."""
    app = SwellAnalysisApp.__new__(SwellAnalysisApp)
    app.seg_state = SegmentationState()
    app._get_frame_count = lambda: 6
    app._propagated_history_indices = set()
    calls = {"leverage": 0, "markers": 0}
    app._recompute_leverage_map = lambda: calls.__setitem__("leverage", calls["leverage"] + 1)
    app._recompute_slider_jump_markers = lambda: calls.__setitem__("markers", calls["markers"] + 1)
    app.log_debug = lambda *a, **k: None
    app._mark_project_dirty = lambda *a, **k: None

    app._set_propagated_frames({1, 2, 3}, mark_dirty=False)

    assert calls["leverage"] == 1
