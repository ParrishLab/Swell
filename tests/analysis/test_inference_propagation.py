import types
import pytest
from unittest.mock import patch, MagicMock
import numpy as np

from swell.analysis.app import SwellAnalysisApp
from swell.analysis.core.inference_manager import InferenceManager
from swell.analysis.core.propagation_progress import PropagationProgressLogger

@patch('swell.analysis.core.inference_manager.messagebox.showerror')
def test_inference_propagation_logic_and_cache_coherency(mock_showerror):
    manager = InferenceManager(
        root=MagicMock(),
        state=MagicMock(),
        get_frame_count=MagicMock(return_value=10),
        get_current_frame_idx=MagicMock(return_value=0),
        get_frame_shape=MagicMock(return_value=(100, 100)),
        get_sensitivity=MagicMock(return_value=0.5),
        set_slider_frame=MagicMock(),
        set_status=MagicMock(),
        set_propagated_frames=MagicMock(),
        recompute_markers=MagicMock(),
        update_display=MagicMock(),
        prop_log_start=MagicMock(return_value=1),
        prop_log_tick=MagicMock(),
        prop_log_finish=MagicMock(),
        on_propagation_status=MagicMock(),
        on_device_oom=MagicMock(),
        log=MagicMock(),
        is_ui_alive=MagicMock(return_value=True),
        predictor_lock=MagicMock()
    )

    def mock_after(ms, func, *args):
        func(*args)

    manager.root.after.side_effect = mock_after
    manager.model_ready = True
    manager.predictor = MagicMock()
    manager.inference_state = MagicMock()

    # Deterministic point-prompt seed path: frame 0 is the sole anchor.
    manager.state.get_valid_point_frames.return_value = {0}
    manager.state.get_valid_box_frames.return_value = set()
    manager.state.get_prompt_anchor_frames.return_value = {0}
    manager.state.has_nonempty_paint.return_value = False
    manager.state.is_ground_truth_frame.return_value = False
    manager.state.points = {0: [{"x": 10, "y": 20, "label": 1}]}

    # set_mask writes into a real dict so we can assert what propagation wrote.
    masks_cache = {}
    manager.state.masks_cache = masks_cache
    manager.state.set_mask.side_effect = lambda idx, m, threshold=None: masks_cache.__setitem__(int(idx), np.asarray(m))

    # Frame 1 logit is above threshold (True mask), frame 2 is below (empty).
    frames = [
        (0, [0], [_FakeLogit(np.zeros((100, 100)))]),
        (1, [0], [_FakeLogit(np.ones((100, 100)))]),
        (2, [0], [_FakeLogit(np.zeros((100, 100)))]),
    ]
    manager.predictor.propagate_in_video.side_effect = lambda *a, **k: list(frames)

    manager._run_background_propagation(
        manager._active_propagation_generation, prop_start=0, prop_end=2, anchor_frame=0
    )

    # The run completed (not "failed"): finish + status both report "complete".
    manager.prop_log_finish.assert_any_call("complete", run_id=1)
    manager.on_propagation_status.assert_any_call("complete", 0, 2)
    assert manager.prop_log_start.called

    # Seed frame 0 is protected from overwrite; frames 1 and 2 were propagated.
    assert 0 not in masks_cache
    assert masks_cache[1].dtype == bool and masks_cache[1].all()
    # Thresholding is honored end-to-end: a below-threshold logit yields an
    # empty mask rather than being written as all-True.
    assert masks_cache[2].dtype == bool and not masks_cache[2].any()


class _FakeMask:
    """Stand-in for a torch tensor mask: supports .cpu().numpy().squeeze()."""

    def __init__(self, arr):
        self._arr = arr

    def cpu(self):
        return self

    def numpy(self):
        return self._arr


class _FakeLogit:
    """Stand-in for a torch logit tensor: `logit > thresh` yields a _FakeMask."""

    def __init__(self, arr):
        self._arr = np.asarray(arr)

    def __gt__(self, thresh):
        return _FakeMask(self._arr > thresh)


def _make_real_progress_wrappers():
    """Bind the *real* SwellAnalysisApp progress wrappers to a lightweight stub.

    Using the actual app methods (rather than MagicMocks) means any signature
    drift between InferenceManager's calls and the app wrappers -- e.g. the
    `_prop_log_tick(phase=...)` TypeError regression -- fails these tests
    instead of silently slipping through.
    """
    logger = PropagationProgressLogger(
        write_progress=MagicMock(),
        log_info=MagicMock(),
        log_success=MagicMock(),
        log_warn=MagicMock(),
        log_error=MagicMock(),
        on_update=MagicMock(),
    )
    app_stub = types.SimpleNamespace(progress_logger=logger)
    app_stub.prop_log_start = types.MethodType(SwellAnalysisApp._prop_log_start, app_stub)
    app_stub.prop_log_tick = types.MethodType(SwellAnalysisApp._prop_log_tick, app_stub)
    app_stub.prop_log_finish = types.MethodType(SwellAnalysisApp._prop_log_finish, app_stub)
    return logger, app_stub


def test_prop_log_tick_wrapper_forwards_phase_kwargs():
    """The app's _prop_log_tick must forward phase kwargs to the logger.

    Regression for the TypeError: _prop_log_tick() got an unexpected keyword
    argument 'phase'. InferenceManager calls prop_log_tick with phase/direction/
    phase_done/phase_total; a wrapper that only accepts (increment, run_id)
    raises here.
    """
    logger, app_stub = _make_real_progress_wrappers()
    run_id = app_stub.prop_log_start(4, "Propagation", prop_start=0, prop_end=3, anchor=0)

    app_stub.prop_log_tick(
        run_id=run_id,
        phase="forward",
        direction="forward",
        phase_done=1,
        phase_total=3,
    )

    assert logger.state.phase == "forward"
    assert logger.state.direction == "forward"
    assert logger.state.forward_total == 3
    assert logger.state.forward_done == 1
    app_stub.prop_log_finish("complete", run_id=run_id)
    assert logger.state.active is False


@patch('swell.analysis.core.inference_manager.messagebox.showerror')
def test_propagation_runs_through_real_progress_wrappers(mock_showerror):
    """Drive a full propagation with the real app progress wrappers wired in.

    Exercises the start -> tick(phase=...) -> finish path end-to-end so that a
    signature mismatch in any wrapper surfaces as a failed run rather than a
    green suite.
    """
    logger, app_stub = _make_real_progress_wrappers()

    manager = InferenceManager(
        root=MagicMock(),
        state=MagicMock(),
        get_frame_count=MagicMock(return_value=10),
        get_current_frame_idx=MagicMock(return_value=0),
        get_frame_shape=MagicMock(return_value=(100, 100)),
        get_sensitivity=MagicMock(return_value=0.5),
        set_slider_frame=MagicMock(),
        set_status=MagicMock(),
        set_propagated_frames=MagicMock(),
        recompute_markers=MagicMock(),
        update_display=MagicMock(),
        prop_log_start=app_stub.prop_log_start,
        prop_log_tick=app_stub.prop_log_tick,
        prop_log_finish=app_stub.prop_log_finish,
        on_propagation_status=MagicMock(),
        on_device_oom=MagicMock(),
        log=MagicMock(),
        is_ui_alive=MagicMock(return_value=True),
        predictor_lock=MagicMock(),
    )

    def mock_after(ms, func, *args):
        func(*args)

    manager.root.after.side_effect = mock_after
    manager.model_ready = True
    manager.predictor = MagicMock()
    manager.inference_state = MagicMock()

    # Take the deterministic point-prompt seed path: frame 0 is the sole anchor,
    # no paint / ground-truth / box prompts.
    manager.state.get_valid_point_frames.return_value = {0}
    manager.state.get_valid_box_frames.return_value = set()
    manager.state.get_prompt_anchor_frames.return_value = {0}
    manager.state.has_nonempty_paint.return_value = False
    manager.state.is_ground_truth_frame.return_value = False
    manager.state.points = {0: [{"x": 10, "y": 20, "label": 1}]}
    manager.state.masks_cache = {}

    # Frames yielded by both the forward and reverse generators.
    frames = [
        (0, [0], [_FakeLogit(np.zeros((100, 100)))]),
        (1, [0], [_FakeLogit(np.ones((100, 100)))]),
        (2, [0], [_FakeLogit(np.ones((100, 100)))]),
    ]
    manager.predictor.propagate_in_video.side_effect = lambda *a, **k: list(frames)

    manager._run_background_propagation(
        manager._active_propagation_generation, prop_start=0, prop_end=2, anchor_frame=0
    )

    # forward_expected = prop_end - anchor + 1 = 3; backward_expected = 1.
    assert logger.state.forward_total == 3
    assert logger.state.forward_done == 3
    assert logger.state.backward_total == 1
    # A dropped-kwarg wrapper would route the run to "failed"; a complete run
    # logs success exactly once with this message.
    logger._log_success.assert_called_with("Propagation", "Propagation complete")
    manager.on_propagation_status.assert_any_call("complete", 0, 2)
