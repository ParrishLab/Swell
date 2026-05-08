from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from sdapp.host.auto_detect_window import AutoDetectWindow
from sdapp.host.sd_detection import detector
from sdapp.host.sd_detection.traces import extract_lower_median_traces


@pytest.fixture()
def tk_root():
    import tkinter as tk

    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk unavailable: {exc}")
    root.withdraw()
    try:
        yield root
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass


class _Reader:
    def read_frame(self, _idx: int, *, use_cache: bool = False) -> np.ndarray:
        return np.zeros((8, 8), dtype=np.float32)


def _app(root):
    return SimpleNamespace(
        root=root,
        reader=_Reader(),
        current_frame_idx=0,
        stack_info=SimpleNamespace(frame_count=5, frame_height=8, frame_width=8),
        browser_controller=SimpleNamespace(get_global_metrics_defaults=lambda: {}),
    )


def test_auto_detect_review_populates_and_selects_first_candidate(tk_root) -> None:
    window = AutoDetectWindow(_app(tk_root))
    window.open()
    try:
        window._review_candidates = [
            {"start_frame": 1, "end_frame": 3, "peak_frame": 2, "lag1_corr": 0.9},
        ]

        window._show_review_phase()

        assert window._tree.get_children() == ("cand_0",)
        assert window._current_idx == 0
        assert window._start_entry.get() == "1"
        assert window._end_entry.get() == "3"
    finally:
        window._on_close()


def test_auto_detect_completion_callbacks_ignore_closed_window(tk_root) -> None:
    window = AutoDetectWindow(_app(tk_root))
    window.open()
    window._on_close()

    window._review_candidates = []
    window._finalize_run()
    window._on_run_error(RuntimeError("ignored"))
    window._report("ignored")

    assert not window._is_open()


def test_auto_detect_wrong_shape_roi_falls_back_to_full_frame(tk_root) -> None:
    window = AutoDetectWindow(_app(tk_root))
    window._roi_mask = np.ones((4, 4), dtype=bool)
    window._roi_points = [(0, 0)]

    roi = window._get_effective_roi()

    assert roi.shape == (8, 8)
    assert np.all(roi)
    assert window._roi_mask is None
    assert window._roi_points is None


def test_auto_detect_stale_selection_is_ignored(tk_root) -> None:
    window = AutoDetectWindow(_app(tk_root))
    window.open()
    try:
        window._review_candidates = []
        window._current_idx = 3

        window._on_update_bounds()
        window._on_delete()
        window._on_accept_one()

        assert window._current_idx is None
    finally:
        window._on_close()


def test_detector_rejects_mismatched_frame_indices() -> None:
    traces = np.zeros((2, 4), dtype=np.float32)

    with pytest.raises(ValueError, match="frame_indices length"):
        detector.find_candidates(traces, np.arange(3))


def test_detector_returns_no_candidates_for_too_short_trace_stack() -> None:
    traces = np.zeros((2, 1), dtype=np.float32)

    assert detector.find_candidates(traces, np.arange(1)) == []


def test_trace_extraction_rejects_invalid_frame_count() -> None:
    with pytest.raises(ValueError, match="frame_count"):
        extract_lower_median_traces(
            reader=object(),
            cell_masks=[np.ones((2, 2), dtype=bool)],
            geometry=SimpleNamespace(),
            frame_count=0,
        )
