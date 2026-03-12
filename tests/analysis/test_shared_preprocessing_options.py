from __future__ import annotations

import numpy as np

from sdapp.shared.frame_source.preprocessing import build_visualization_stack


class _Source:
    def __init__(self, frames: list[np.ndarray]) -> None:
        self._frames = [np.asarray(f, dtype=np.float32) for f in frames]
        self.frame_count = len(self._frames)

    def get_raw_frame(self, idx: int) -> np.ndarray:
        return self._frames[int(idx)]


def test_preprocessing_options_disable_all_stages() -> None:
    frames = [
        np.array([[0, 10], [20, 30]], dtype=np.float32),
        np.array([[40, 50], [60, 70]], dtype=np.float32),
    ]
    source = _Source(frames)
    raw, sub, viz = build_visualization_stack(
        source,
        baseline_frames=2,
        apply_smoothing=False,
        apply_baseline_subtraction=False,
        apply_global_normalization=False,
    )
    assert raw.shape == (2, 2, 2)
    assert np.allclose(raw, sub)
    assert viz.dtype == np.uint8
    assert viz.shape == (2, 2, 2)


def test_preprocessing_options_apply_baseline_without_normalization() -> None:
    frames = [
        np.array([[1, 1], [1, 1]], dtype=np.float32),
        np.array([[2, 2], [2, 2]], dtype=np.float32),
    ]
    source = _Source(frames)
    _raw, sub, viz = build_visualization_stack(
        source,
        baseline_frames=1,
        apply_smoothing=False,
        apply_baseline_subtraction=True,
        apply_global_normalization=False,
    )
    assert np.allclose(sub[0], np.zeros((2, 2), dtype=np.float32))
    assert np.allclose(sub[1], np.ones((2, 2), dtype=np.float32))
    assert viz.dtype == np.uint8
