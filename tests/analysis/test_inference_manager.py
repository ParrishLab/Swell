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
    def __init__(self) -> None:
        self.mask_frames: list[int] = []
        self.point_frames: list[int] = []

    def reset_state(self, _state):
        return None

    def add_new_points_or_box(self, **_kwargs):
        self.point_frames.append(int(_kwargs.get("frame_idx", -1)))
        return None, None, [_FakeMaskTensor([[1.0]])]

    def add_new_mask(self, **_kwargs):
        self.mask_frames.append(int(_kwargs.get("frame_idx", -1)))
        return _kwargs.get("frame_idx", 0), [1], [_FakeMaskTensor([[1.0]])]

    def propagate_in_video(self, _inference_state, *, start_frame_idx: int, reverse: bool):
        indices = range(int(start_frame_idx), -1, -1) if reverse else range(int(start_frame_idx), 5)
        for idx in indices:
            yield idx, [1], [_FakeMaskTensor([[1.0]])]


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
        get_frame_count=lambda: 5,
        get_frame_shape=lambda: (1, 1),
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


def _build_propagation_manager(seg_state, predictor, *, current_frame_idx=2, frame_count=5):
    root = _ImmediateRoot()
    status_events: list[tuple[str, int, int]] = []
    slider_frames: list[int] = []
    manager = InferenceManager(
        state=seg_state,
        root=root,
        predictor_lock=threading.Lock(),
        get_sensitivity=lambda: 0.5,
        get_current_frame_idx=lambda: current_frame_idx,
        get_frame_count=lambda: frame_count,
        get_frame_shape=lambda: (1, 1),
        set_slider_frame=lambda idx: slider_frames.append(int(idx)),
        update_display=lambda: None,
        recompute_markers=lambda: None,
        set_propagated_frames=lambda _frames: None,
        set_status=lambda _text, _color: None,
        prop_log_start=lambda _total, _label: 1,
        prop_log_tick=lambda **_kwargs: None,
        prop_log_finish=lambda _status, **_kwargs: None,
        on_propagation_status=lambda status, start, end: status_events.append((str(status), int(start), int(end))),
        log=lambda *_args: None,
        is_ui_alive=lambda: True,
    )
    manager.on_model_ready(predictor, object())
    manager._active_propagation_generation = 1
    return manager, status_events, slider_frames


def test_mask_only_propagation_uses_single_nearest_seed_frame():
    seg_state = SegmentationState()
    for frame_idx in (1, 2, 3, 4):
        seg_state.set_mask(frame_idx, np.array([[True]], dtype=bool))
    predictor = _FakePredictor()
    manager, status_events, slider_frames = _build_propagation_manager(seg_state, predictor, current_frame_idx=2, frame_count=5)

    manager._run_background_propagation(1, 1, 4, 2)

    assert predictor.mask_frames == [2]
    assert predictor.point_frames == []
    assert slider_frames == [2]
    assert ("started", 1, 4) in status_events
    assert ("complete", 1, 4) in status_events


def test_point_prompts_take_precedence_over_saved_masks_for_propagation():
    seg_state = SegmentationState()
    seg_state.set_points(1, [{"x": 1.0, "y": 1.0, "label": 1}])
    for frame_idx in (1, 2, 3, 4):
        seg_state.set_mask(frame_idx, np.array([[True]], dtype=bool))
    predictor = _FakePredictor()
    manager, _status_events, slider_frames = _build_propagation_manager(seg_state, predictor, current_frame_idx=2, frame_count=5)

    manager._run_background_propagation(1, 1, 4, 2)

    assert predictor.point_frames == [1]
    assert predictor.mask_frames == []
    assert slider_frames == [1]
