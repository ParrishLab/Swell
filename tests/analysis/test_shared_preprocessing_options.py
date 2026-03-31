from __future__ import annotations

import numpy as np

from sdapp.shared.frame_source.preprocessing import (
    VisualizationCancelled,
    build_visualization_stack,
    compute_visualization_stats,
    render_visualization_frame,
)


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


def test_horizontal_bar_denoise_reduces_row_banding() -> None:
    frames = [
        np.array(
            [
                [0, 0, 0, 0],
                [100, 100, 100, 100],
                [0, 0, 0, 0],
                [100, 100, 100, 100],
            ],
            dtype=np.float32,
        )
    ]
    source = _Source(frames)

    _raw, sub, _viz = build_visualization_stack(
        source,
        baseline_frames=1,
        apply_horizontal_bar_denoise=True,
        apply_smoothing=False,
        apply_baseline_subtraction=False,
        apply_global_normalization=False,
    )

    assert np.allclose(sub[0], np.full((4, 4), 50.0, dtype=np.float32))


def test_render_visualization_frame_matches_full_stack_exactly() -> None:
    frames = [
        np.array([[0, 5], [10, 15]], dtype=np.float32),
        np.array([[2, 7], [12, 17]], dtype=np.float32),
        np.array([[4, 9], [14, 19]], dtype=np.float32),
        np.array([[20, 25], [30, 35]], dtype=np.float32),
    ]
    source = _Source(frames)

    stats = compute_visualization_stats(
        source,
        baseline_frames=2,
        apply_smoothing=False,
        apply_baseline_subtraction=True,
        apply_global_normalization=True,
    )
    full_raw, full_sub, full_viz = build_visualization_stack(
        source,
        baseline_frames=2,
        apply_smoothing=False,
        apply_baseline_subtraction=True,
        apply_global_normalization=True,
        stats=stats,
    )
    raw, sub, viz = render_visualization_frame(source, 3, stats=stats)

    assert np.allclose(raw, full_raw[3])
    assert np.allclose(sub, full_sub[3])
    assert np.array_equal(viz, full_viz[3])


def test_compute_visualization_stats_honors_cancellation() -> None:
    frames = [np.full((4, 4), idx, dtype=np.float32) for idx in range(6)]
    source = _Source(frames)

    try:
        compute_visualization_stats(
            source,
            baseline_frames=3,
            apply_smoothing=False,
            apply_baseline_subtraction=True,
            apply_global_normalization=True,
            should_cancel=lambda: True,
        )
    except VisualizationCancelled:
        return

    raise AssertionError("Expected VisualizationCancelled")


def test_compute_visualization_stats_reuses_processed_frames_across_baseline_and_sampling() -> None:
    class _CountingSource(_Source):
        def __init__(self, frames: list[np.ndarray]) -> None:
            super().__init__(frames)
            self.calls: list[int] = []

        def get_raw_frame(self, idx: int) -> np.ndarray:
            self.calls.append(int(idx))
            return super().get_raw_frame(idx)

    frames = [np.full((4, 4), idx, dtype=np.float32) for idx in range(12)]
    source = _CountingSource(frames)

    stats = compute_visualization_stats(
        source,
        baseline_frames=3,
        apply_smoothing=False,
        apply_baseline_subtraction=True,
        apply_global_normalization=True,
    )

    assert stats.frame_count == 12
    assert source.calls == [0, 1, 2, 5, 10]
