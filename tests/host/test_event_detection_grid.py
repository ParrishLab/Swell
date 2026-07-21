from __future__ import annotations

import numpy as np
import pytest

from swell.host.event_detection.grid import build_detector_grid
from swell.host.event_detection.traces import extract_lower_median_traces


@pytest.mark.parametrize("shape", [(801, 20), (20, 801), (4000, 12), (12, 4000)])
def test_sparse_border_and_disconnected_roi_survive_downsampling(shape: tuple[int, int]) -> None:
    height, width = shape
    roi = np.zeros(shape, dtype=bool)
    roi[0, 0] = True
    roi[-1, -1] = True
    roi[height // 2, width // 2] = True

    extraction = build_detector_grid(roi, shape, 2, 2)

    assert np.any(extraction.roi_analysis)
    assert max(extraction.geometry.resized_shape) <= 800
    assert extraction.geometry.crop_box[0] == 0
    assert extraction.geometry.crop_box[2] == 0


def test_downsampled_crop_box_tracks_source_rectangle() -> None:
    shape = (400, 1600)
    roi = np.zeros(shape, dtype=bool)
    roi[100:300, 200:1000] = True

    extraction = build_detector_grid(roi, shape, 2, 4)

    assert extraction.geometry.analysis_scale == pytest.approx(0.5)
    assert extraction.geometry.resized_shape == (200, 800)
    assert extraction.geometry.crop_box == (50, 150, 100, 500)
    assert extraction.geometry.cropped_roi_shape == (100, 400)


def test_grid_cells_partition_roi_without_overlap_and_preserve_hole() -> None:
    roi = np.zeros((1000, 1200), dtype=bool)
    roi[100:900, 100:1100] = True
    roi[400:600, 450:750] = False

    extraction = build_detector_grid(roi, roi.shape, 3, 4)
    coverage = np.zeros_like(extraction.roi_analysis, dtype=np.uint8)
    for cell in extraction.cell_masks:
        coverage += np.asarray(cell, dtype=np.uint8)

    assert np.array_equal(coverage > 0, extraction.roi_analysis)
    assert int(coverage.max()) == 1
    center_y = extraction.roi_analysis.shape[0] // 2
    center_x = extraction.roi_analysis.shape[1] // 2
    assert not bool(extraction.roi_analysis[center_y, center_x])


def test_explicit_downsample_scale_can_request_smaller_analysis_grid() -> None:
    roi = np.ones((500, 1000), dtype=bool)

    extraction = build_detector_grid(roi, roi.shape, 1, 1, downsample_scale=0.25)

    assert extraction.geometry.analysis_scale == pytest.approx(0.25)
    assert extraction.geometry.resized_shape == (125, 250)


def test_downsampled_trace_extraction_preserves_spatially_uniform_signal() -> None:
    shape = (40, 1600)
    roi = np.ones(shape, dtype=bool)
    extraction = build_detector_grid(roi, shape, 2, 4)
    frames = [np.full(shape, idx * 3.0, dtype=np.float32) for idx in range(6)]

    class _Reader:
        def read_frame(self, frame_idx: int, use_cache: bool = False) -> np.ndarray:
            del use_cache
            return frames[int(frame_idx)]

    traces = extract_lower_median_traces(
        _Reader(),
        extraction.cell_masks,
        extraction.geometry,
        frame_count=len(frames),
        backend="numpy",
        batch_size=3,
        intra_batch_workers=1,
    )

    expected = np.arange(len(frames), dtype=np.float32) * 3.0
    assert traces.shape == (len(extraction.cell_masks), len(frames))
    for trace in traces:
        np.testing.assert_allclose(trace, expected)
