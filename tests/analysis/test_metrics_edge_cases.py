import pytest
import numpy as np

from swell.analysis.core.metrics import compute_frame_metrics, compute_roi_metrics, compute_scale

def test_compute_frame_metrics_single_frame():
    # Single frame should still return valid arrays of length 1, but avg_dist_px will be NaN
    boundaries = [np.array([[10.0, 10.0], [20.0, 10.0], [20.0, 20.0], [10.0, 20.0]])]
    res = compute_frame_metrics(boundaries)
    
    assert len(res["areas_px"]) == 1
    assert np.isfinite(res["areas_px"][0])
    assert np.isnan(res["avg_dist_px"][0])
    assert not res["transition_valid"][0]

def test_compute_frame_metrics_missing_scale_handled_by_caller():
    # compute_frame_metrics returns pixel values, so missing scale is handled in the UI
    boundaries = [np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]])]
    res = compute_frame_metrics(boundaries)
    assert len(res["areas_px"]) == 1
    assert np.isfinite(res["areas_px"][0])

def test_compute_roi_metrics_zero_area_roi():
    # ROI with no True pixels
    roi_mask = np.zeros((100, 100), dtype=bool)
    areas_px = np.array([100.0, 200.0])
    avg_dist_px = np.array([np.nan, 5.0])
    px_per_mm = 10.0
    sec_per_frame = 1.0

    res = compute_roi_metrics(roi_mask, areas_px, avg_dist_px, px_per_mm, sec_per_frame)
    assert res["roi_pixels"] == 0
    assert res["roi_area_mm2"] == 0.0
    assert np.isnan(res["relative_area_pct"]) # Can't compute pct of 0
    
def test_compute_roi_metrics_nan_handling():
    roi_mask = np.zeros((10, 10), dtype=bool)
    roi_mask[0:5, 0:5] = True
    
    # All NaN areas
    areas_px = np.array([np.nan, np.nan])
    avg_dist_px = np.array([np.nan, np.nan])
    
    res = compute_roi_metrics(roi_mask, areas_px, avg_dist_px, 10.0, 1.0)
    assert np.isnan(res["overall_avg_speed_um_per_sec"])
    assert np.isnan(res["overall_max_speed_um_per_sec"])
    assert np.isnan(res["max_area_mm2"])
    assert np.isnan(res["relative_area_pct"])
