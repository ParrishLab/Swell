import pytest
from unittest.mock import patch, MagicMock
import numpy as np

from swell.analysis.core.inference_manager import InferenceManager

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
    manager.state = MagicMock()
    manager.state.get_valid_point_frames.return_value = {0}
    manager.state.points = {0: [{"x": 10, "y": 20, "label": 1}]}
    
    # Pre-populate masks_cache
    manager.state.masks_cache = {
        0: np.ones((100, 100), dtype=bool),
        1: np.ones((100, 100), dtype=bool),
        2: np.ones((100, 100), dtype=bool),
    }
    
    # Return dummy objects from propagation predictor
    manager.predictor.propagate_in_video.return_value = [
        (0, [0], [np.zeros((100, 100), dtype=bool)]),
        (1, [0], [np.zeros((100, 100), dtype=bool)]),
        (2, [0], [np.zeros((100, 100), dtype=bool)]),
    ]
    
    # Clear masks in range before prop starts
    def mock_clear_mask(idx):
        if idx in manager.state.masks_cache:
            del manager.state.masks_cache[idx]
    manager.state.clear_mask.side_effect = mock_clear_mask

    # Attempt to run propagation
    manager._run_background_propagation(manager._active_propagation_generation, prop_start=0, prop_end=2, anchor_frame=0)
    
    # Validate cache cleared and updated
    assert 0 in manager.state.masks_cache
    assert 1 in manager.state.masks_cache
    assert 2 in manager.state.masks_cache
    
    # Validation events were fired
    assert manager.on_propagation_status.called
    assert manager.prop_log_start.called
    assert manager.prop_log_finish.called
