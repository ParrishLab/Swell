from __future__ import annotations

import threading

import numpy as np

from sdapp.analysis.core.inference_manager import InferenceManager
from sdapp.analysis.core.seg_state import SegmentationState


class _ImmediateRoot:
    def after(self, _delay_ms, callback):
        callback()
        return "after-id"

    def after_cancel(self, _job):
        return None


class _FakeMaskTensor:
    def __init__(self, value) -> None:
        self._value = np.asarray(value, dtype=np.float32)

    def __gt__(self, thresh):
        return _FakeMaskTensor(self._value > thresh)

    def cpu(self):
        return self

    def numpy(self):
        return self._value


class _FakePredictor:
    def reset_state(self, _state):
        return None

    def add_new_points_or_box(self, **_kwargs):
        return None, None, [_FakeMaskTensor([[1.0]])]


def test_pending_point_batch_recomputes_markers_once():
    seg_state = SegmentationState()
    seg_state.points = {
        1: [{"x": 1.0, "y": 1.0, "label": 1}],
        3: [{"x": 2.0, "y": 2.0, "label": 1}],
    }
    root = _ImmediateRoot()
    recompute_calls: list[str] = []
    update_calls: list[str] = []

    manager = InferenceManager(
        state=seg_state,
        root=root,
        predictor_lock=threading.Lock(),
        get_sensitivity=lambda: 0.5,
        get_current_frame_idx=lambda: 0,
        get_frames_raw=lambda: None,
        set_slider_frame=lambda _idx: None,
        update_display=lambda: update_calls.append("update"),
        recompute_markers=lambda: recompute_calls.append("recompute"),
        set_propagated_frames=lambda _frames: None,
        set_status=lambda _text, _color: None,
        prop_log_start=lambda _total, _label: 1,
        prop_log_tick=lambda **_kwargs: None,
        prop_log_finish=lambda _status, **_kwargs: None,
        on_propagation_status=None,
        log=lambda *_args: None,
        is_ui_alive=lambda: True,
    )
    manager.on_model_ready(_FakePredictor(), object())
    manager.start()
    try:
        manager.enqueue_pending_point_frames({1, 3})
        manager._infer_queue.join()
    finally:
        manager.stop()

    assert recompute_calls == ["recompute"]
    assert update_calls == ["update", "update"]
    assert set(seg_state.masks_cache.keys()) == {1, 3}
