import pytest
from unittest.mock import patch, MagicMock

from sdapp.shared.errors import DataCorruptionError, ProjectLoadError, InferenceRuntimeError
from sdapp.host.exporter import _resolve_roi_mask, _apply_propagation_gap_policy
from sdapp.shared.persistence.unified_project_store import _coerce_stack_ref, _coerce_events
from sdapp.analysis.core.inference_manager import InferenceManager

def test_project_load_validation_stack_ref():
    with pytest.raises(ProjectLoadError):
        _coerce_stack_ref({"input_dir": "test"})  # missing frame_count

    with pytest.raises(ProjectLoadError):
        _coerce_stack_ref(123)  # not a dict

def test_project_load_validation_events():
    with pytest.raises(ProjectLoadError):
        _coerce_events([{"id": "test"}])  # missing start/end

    with pytest.raises(ProjectLoadError):
        _coerce_events("not a list")

@patch('sdapp.host.exporter.MetricsSettingsResolver.normalize')
@patch('sdapp.host.exporter.roi_mask_from_points')
def test_exporter_roi_mask_failure(mock_roi_mask, mock_normalize):
    mock_roi_mask.side_effect = Exception("Mocked SAM-2 failure")
    mock_normalize.return_value = {"roi_points": [{"x": 10, "y": 20}]}
    
    settings = {}
    
    with pytest.raises(DataCorruptionError) as exc_info:
        _resolve_roi_mask(settings, (100, 100))
        
    assert "Failed to generate ROI mask" in str(exc_info.value)

@patch('sdapp.analysis.core.inference_manager.messagebox.showerror')
def test_inference_failure_propagation_single_frame(mock_showerror):
    # Construct InferenceManager with dummy arguments
    manager = InferenceManager(
        root=MagicMock(),
        state=MagicMock(),
        get_frame_count=MagicMock(),
        get_current_frame_idx=MagicMock(),
        get_frame_shape=MagicMock(),
        get_sensitivity=MagicMock(),
        set_slider_frame=MagicMock(),
        set_status=MagicMock(),
        set_propagated_frames=MagicMock(),
        recompute_markers=MagicMock(),
        update_display=MagicMock(),
        prop_log_start=MagicMock(),
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
    
    # Force an exception during inference
    manager.predictor.add_new_points_or_box.side_effect = Exception("Simulated GPU initialization failure")
    
    # Attempt to run frame inference
    manager._run_single_frame_inference_core(0, 1)
    
    # Verify the messagebox was called with InferenceRuntimeError message
    assert mock_showerror.called
    args, kwargs = mock_showerror.call_args
    assert "Inference Error" in args[0]
    assert "Simulated GPU initialization failure" in args[1]
