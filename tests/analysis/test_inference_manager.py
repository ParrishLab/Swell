from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import numpy as np

from sdapp.analysis.core.inference_manager import InferenceManager
from sdapp.analysis.controllers.runtime_controller import AnalysisRuntimeController
from sdapp.analysis.core.project_session import ProjectSessionService
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


class _ControlledPropagationPredictor(_FakePredictor):
    def __init__(self) -> None:
        super().__init__()
        self.ready_for_second_frame = threading.Event()
        self.allow_second_frame = threading.Event()

    def propagate_in_video(self, _inference_state, *, start_frame_idx: int, reverse: bool):
        if reverse:
            yield 0, [1], [_FakeMaskTensor([[1.0]])]
            return
        yield 0, [1], [_FakeMaskTensor([[1.0]])]
        self.ready_for_second_frame.set()
        self.allow_second_frame.wait(timeout=2.0)
        yield 1, [1], [_FakeMaskTensor([[1.0]])]
        yield 2, [1], [_FakeMaskTensor([[1.0]])]


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


def test_pause_and_resume_continue_same_propagation_run():
    seg_state = SegmentationState()
    seg_state.set_points(0, [{"x": 1.0, "y": 1.0, "label": 1}])
    predictor = _ControlledPropagationPredictor()
    manager, status_events, _slider_frames = _build_propagation_manager(seg_state, predictor, current_frame_idx=1, frame_count=3)

    thread = threading.Thread(target=manager._run_background_propagation, args=(1, 0, 2, 0), daemon=True)
    manager.propagate_thread = thread
    thread.start()
    assert predictor.ready_for_second_frame.wait(timeout=2.0)
    assert manager.pause_propagation()
    predictor.allow_second_frame.set()
    time.sleep(0.1)

    assert manager.is_propagation_paused()
    assert 1 not in seg_state.masks_cache

    assert manager.resume_propagation()
    thread.join(timeout=2.0)

    assert not thread.is_alive()
    assert 1 in seg_state.masks_cache
    assert ("complete", 0, 2) in status_events


def test_stop_while_paused_unblocks_and_reports_preserve_status():
    seg_state = SegmentationState()
    seg_state.set_points(0, [{"x": 1.0, "y": 1.0, "label": 1}])
    predictor = _ControlledPropagationPredictor()
    manager, status_events, _slider_frames = _build_propagation_manager(seg_state, predictor, current_frame_idx=1, frame_count=3)
    manager.propagate_thread = threading.Thread(target=manager._run_background_propagation, args=(1, 0, 2, 0), daemon=True)
    manager.propagate_thread.start()
    assert predictor.ready_for_second_frame.wait(timeout=2.0)
    assert manager.pause_propagation()

    assert manager.request_stop_propagation(preserve_generated_masks=True)
    predictor.allow_second_frame.set()
    manager.propagate_thread.join(timeout=2.0)

    assert manager.propagate_thread is None
    assert ("stopped_preserve", 0, 2) in status_events


def test_project_session_preserved_stop_keeps_current_masks_incomplete():
    service = ProjectSessionService()
    records = {}
    current_masks = {1: np.ones((2, 2), dtype=bool)}

    transition = service.on_propagation_status(
        status="stopped_preserve",
        prop_start=0,
        prop_end=2,
        active_event_id="sd_event_001",
        event_records=records,
        current_masks=current_masks,
        committed_snapshot={0: np.zeros((2, 2), dtype=bool)},
    )

    assert transition.restored_masks is None
    assert not transition.event_record.metadata.propagation_completed
    assert 1 in transition.event_record.analysis.masks_committed
    assert transition.event_record.analysis.masks_draft is None


class _Button:
    def __init__(self) -> None:
        self.options = {}

    def configure(self, **kwargs):
        self.options.update(kwargs)


def test_runtime_controller_propagation_button_states():
    class _Manager:
        running = False
        paused = False

        def is_propagation_running(self):
            return self.running

        def is_propagation_paused(self):
            return self.paused

    manager = _Manager()
    app = SimpleNamespace(
        btn_run_propagation=_Button(),
        btn_pause_propagation=_Button(),
        btn_resume_propagation=_Button(),
        btn_stop_propagation=_Button(),
        inference_manager=manager,
        _has_loaded_stack=lambda: True,
    )
    controller = AnalysisRuntimeController(app)

    controller.sync_propagation_button_state()
    assert app.btn_run_propagation.options["state"] == "normal"
    assert app.btn_pause_propagation.options["state"] == "disabled"
    assert app.btn_resume_propagation.options["state"] == "disabled"
    assert app.btn_stop_propagation.options["state"] == "disabled"

    manager.running = True
    controller.sync_propagation_button_state()
    assert app.btn_run_propagation.options["state"] == "disabled"
    assert app.btn_pause_propagation.options["state"] == "normal"
    assert app.btn_resume_propagation.options["state"] == "disabled"
    assert app.btn_stop_propagation.options["state"] == "normal"

    manager.paused = True
    controller.sync_propagation_button_state()
    assert app.btn_pause_propagation.options["state"] == "disabled"
    assert app.btn_resume_propagation.options["state"] == "normal"
    assert app.btn_stop_propagation.options["state"] == "normal"
