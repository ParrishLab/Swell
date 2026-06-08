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


def _open_hidden(window: AutoDetectWindow) -> None:
    window.open(show=False)


def test_auto_detect_review_populates_and_selects_first_candidate(tk_root) -> None:
    window = AutoDetectWindow(_app(tk_root))
    _open_hidden(window)
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
    _open_hidden(window)
    window._on_close()

    window._review_candidates = []
    window._finalize_run()
    window._on_run_error(RuntimeError("ignored"))
    window._report("ignored")

    assert not window._is_open()


def test_auto_detect_window_is_not_modal_or_transient(tk_root) -> None:
    window = AutoDetectWindow(_app(tk_root))
    _open_hidden(window)
    try:
        assert window._popup is not None
        assert window._popup.transient() == ""
        assert window._popup.grab_status() is None
    finally:
        window._on_close()


def test_auto_detect_wrong_shape_roi_falls_back_to_full_frame(tk_root) -> None:
    window = AutoDetectWindow(_app(tk_root))
    window._roi_mask = np.ones((4, 4), dtype=bool)
    window._roi_points = [(0, 0)]

    roi = window._get_effective_roi()

    assert roi.shape == (8, 8)
    assert np.all(roi)
    assert window._roi_mask is None
    assert window._roi_points is None


def test_auto_detect_grid_overlay_is_clipped_to_roi(tk_root) -> None:
    class Canvas:
        def winfo_width(self) -> int:
            return 80

        def winfo_height(self) -> int:
            return 80

    window = AutoDetectWindow(_app(tk_root))
    window._viewer_canvas = Canvas()
    window._n_grid = 4
    roi_mask = np.zeros((8, 8), dtype=bool)
    roi_mask[:, :4] = True
    window._roi_mask = roi_mask

    rendered = np.asarray(window._make_grid_overlay(np.zeros((8, 8), dtype=np.uint8), selected_cand=None))

    assert rendered[40, 20].max() > 0
    assert np.array_equal(rendered[40, 60], np.array([0, 0, 0], dtype=np.uint8))


def test_auto_detect_grid_opacity_changes_base_grid_strength(tk_root) -> None:
    class Canvas:
        def winfo_width(self) -> int:
            return 80

        def winfo_height(self) -> int:
            return 80

    window = AutoDetectWindow(_app(tk_root))
    window._viewer_canvas = Canvas()
    window._n_grid = 4
    window._roi_mask = None
    window._grid_opacity = 0.1
    faint = np.asarray(window._make_grid_overlay(np.zeros((8, 8), dtype=np.uint8), selected_cand=None))
    window._grid_opacity = 1.0
    strong = np.asarray(window._make_grid_overlay(np.zeros((8, 8), dtype=np.uint8), selected_cand=None))

    assert strong[40, 20].max() > faint[40, 20].max()


def test_auto_detect_active_cells_layer_participation_and_onset(tk_root) -> None:
    window = AutoDetectWindow(_app(tk_root))
    window._current_idx = 0
    window._review_candidates = [{"start_frame": 2, "end_frame": 4}]
    window._cached_frame_indices = np.arange(5)
    window._cached_detrended = np.asarray(
        [
            [0.0, 1.0, 8.0, 0.0, 0.0],
            [0.0, 1.0, 1.0, 8.0, 0.0],
            [0.0, 0.0, 0.0, 8.0, 8.0],
        ],
        dtype=np.float32,
    )

    frame_2 = window._active_cells_for_frame(window._review_candidates[0], 2)
    frame_3 = window._active_cells_for_frame(window._review_candidates[0], 3)

    assert np.array_equal(frame_2, np.array([True, False, False]))
    assert np.array_equal(frame_3, np.array([False, True, True]))
    assert len(window._active_cell_cache) == 1


def test_auto_detect_active_cell_borders_follow_scrubbed_frame(tk_root) -> None:
    class Canvas:
        def winfo_width(self) -> int:
            return 80

        def winfo_height(self) -> int:
            return 80

    left_cell = np.zeros((8, 8), dtype=bool)
    left_cell[:, :4] = True
    right_cell = np.zeros((8, 8), dtype=bool)
    right_cell[:, 4:] = True

    window = AutoDetectWindow(_app(tk_root))
    window._viewer_canvas = Canvas()
    window._n_grid = 2
    window._roi_mask = np.ones((8, 8), dtype=bool)
    window._current_idx = 0
    window._review_candidates = [{"start_frame": 2, "end_frame": 4}]
    window._cached_frame_indices = np.arange(5)
    window._cached_detrended = np.asarray(
        [
            [0.0, 1.0, 8.0, 0.0, 0.0],
            [0.0, 1.0, 1.0, 8.0, 0.0],
        ],
        dtype=np.float32,
    )
    window._cached_grid_extraction = SimpleNamespace(
        cell_masks=[left_cell, right_cell],
        cell_row_cols=[(0, 0), (0, 1)],
        geometry=SimpleNamespace(resized_shape=(8, 8), crop_box=(0, 8, 0, 8)),
    )

    window._current_frame = 2
    frame_2 = np.asarray(window._make_grid_overlay(np.zeros((8, 8), dtype=np.uint8), selected_cand=window._review_candidates[0]))
    window._current_frame = 3
    frame_3 = np.asarray(window._make_grid_overlay(np.zeros((8, 8), dtype=np.uint8), selected_cand=window._review_candidates[0]))

    assert frame_2[0, 20].max() > frame_2[0, 60].max()
    assert frame_3[0, 60].max() > frame_3[0, 20].max()


def test_auto_detect_active_cell_highlight_draws_border_not_fill(tk_root) -> None:
    class Canvas:
        def winfo_width(self) -> int:
            return 80

        def winfo_height(self) -> int:
            return 80

    cell = np.ones((8, 8), dtype=bool)
    window = AutoDetectWindow(_app(tk_root))
    window._viewer_canvas = Canvas()
    window._n_grid = 2
    window._grid_opacity = 0.0
    window._roi_mask = np.ones((8, 8), dtype=bool)
    window._current_idx = 0
    window._review_candidates = [{"start_frame": 2, "end_frame": 4}]
    window._cached_frame_indices = np.arange(5)
    window._cached_detrended = np.asarray([[0.0, 1.0, 8.0, 8.0, 8.0]], dtype=np.float32)
    window._cached_grid_extraction = SimpleNamespace(
        cell_masks=[cell],
        cell_row_cols=[(0, 0)],
        geometry=SimpleNamespace(resized_shape=(8, 8), crop_box=(0, 8, 0, 8)),
    )
    window._current_frame = 2

    rendered = np.asarray(window._make_grid_overlay(np.zeros((8, 8), dtype=np.uint8), selected_cand=window._review_candidates[0]))

    assert rendered[0, 39].max() > 0
    assert np.array_equal(rendered[40, 40], np.array([0, 0, 0], dtype=np.uint8))


def test_auto_detect_active_borders_align_to_detector_grid_not_clipped_cell_mask(tk_root) -> None:
    class Canvas:
        def winfo_width(self) -> int:
            return 80

        def winfo_height(self) -> int:
            return 80

    clipped_left_cell = np.zeros((8, 8), dtype=bool)
    clipped_left_cell[:, :2] = True
    window = AutoDetectWindow(_app(tk_root))
    window._viewer_canvas = Canvas()
    window._n_grid = 2
    window._grid_opacity = 1.0
    window._roi_mask = np.ones((8, 8), dtype=bool)
    window._current_idx = 0
    window._review_candidates = [{"start_frame": 2, "end_frame": 4}]
    window._cached_frame_indices = np.arange(5)
    window._cached_detrended = np.asarray([[0.0, 1.0, 8.0, 8.0, 8.0]], dtype=np.float32)
    window._cached_grid_extraction = SimpleNamespace(
        cell_masks=[clipped_left_cell],
        cell_row_cols=[(0, 0)],
        geometry=SimpleNamespace(resized_shape=(8, 8), crop_box=(0, 8, 0, 8)),
    )
    window._current_frame = 2

    rendered = np.asarray(window._make_grid_overlay(np.zeros((8, 8), dtype=np.uint8), selected_cand=window._review_candidates[0]))

    assert rendered[0, 39].max() > 0
    assert rendered[40, 39].max() > 0


def test_auto_detect_roi_change_repaints_grid_and_invalidates_cached_pipeline_without_rerun(tk_root, monkeypatch) -> None:
    from sdapp.analysis.ui import roi_dialog

    window = AutoDetectWindow(_app(tk_root))
    _open_hidden(window)
    try:
        new_roi = np.zeros((8, 8), dtype=bool)
        new_roi[:, :4] = True
        monkeypatch.setattr(
            roi_dialog,
            "open_roi_dialog",
            lambda *args, **kwargs: {
                "roi_mask": new_roi,
                "roi_points": [[0, 0], [3, 0], [3, 7]],
                "roi_polygons": [[[0, 0], [3, 0], [3, 7]]],
            },
        )
        window._cached_traces = np.ones((1, 5), dtype=np.float32)
        window._cached_frame_indices = np.arange(5)
        window._cached_detrended = np.ones((1, 5), dtype=np.float32)
        window._cached_raw_candidates = [{"start_frame": 0, "end_frame": 1}]
        window._review_candidates = [{"start_frame": 0, "end_frame": 1}]
        window._aggregated_trace = np.ones(5, dtype=np.float32)
        renders = []
        runs = []
        monkeypatch.setattr(window, "_render_viewer_frame", lambda frame_idx: renders.append(frame_idx))
        monkeypatch.setattr(window, "_on_run", lambda *args, **kwargs: runs.append(True))

        window._on_draw_roi()

        assert window._roi_mask is new_roi
        assert window._cached_traces is None
        assert window._cached_frame_indices is None
        assert window._cached_detrended is None
        assert window._cached_raw_candidates is None
        assert window._aggregated_trace is None
        assert window._review_candidates == []
        assert window._dirty_traces is True
        assert window._dirty_find is True
        assert window._dirty_gate is True
        assert renders == [window._current_frame]
        assert runs == []
    finally:
        window._on_close()


def test_auto_detect_grid_change_repaints_and_invalidates_without_rerun(tk_root, monkeypatch) -> None:
    window = AutoDetectWindow(_app(tk_root))
    _open_hidden(window)
    try:
        window._cached_traces = np.ones((1, 5), dtype=np.float32)
        window._cached_frame_indices = np.arange(5)
        window._cached_detrended = np.ones((1, 5), dtype=np.float32)
        window._cached_raw_candidates = [{"start_frame": 0, "end_frame": 1}]
        window._review_candidates = [{"start_frame": 0, "end_frame": 1}]
        renders = []
        runs = []
        monkeypatch.setattr(window, "_render_viewer_frame", lambda frame_idx: renders.append(frame_idx))
        monkeypatch.setattr(window, "_on_run", lambda *args, **kwargs: runs.append(True))
        window._grid_var.set(20)

        window._on_grid_change("20")

        assert window._n_grid == 20
        assert window._cached_traces is None
        assert window._cached_frame_indices is None
        assert window._cached_detrended is None
        assert window._cached_raw_candidates is None
        assert window._review_candidates == []
        assert window._dirty_traces is True
        assert renders == [window._current_frame]
        assert runs == []
    finally:
        window._on_close()


def test_auto_detect_algorithm_slider_does_not_run_without_cached_pipeline(tk_root, monkeypatch) -> None:
    window = AutoDetectWindow(_app(tk_root))
    _open_hidden(window)
    try:
        runs = []
        monkeypatch.setattr(window, "_on_run", lambda *args, **kwargs: runs.append(True))
        window._sens_var.set(0.2)

        window._on_sens_change("0.2")

        assert window._dirty_find is True
        assert runs == []
        window._flush_algorithm_rerun()
        assert runs == []
    finally:
        window._on_close()


def test_auto_detect_algorithm_slider_debounces_cached_find_stage(tk_root, monkeypatch) -> None:
    window = AutoDetectWindow(_app(tk_root))
    _open_hidden(window)
    try:
        window._dirty_traces = False
        window._cached_detrended = np.ones((1, 5), dtype=np.float32)
        window._cached_frame_indices = np.arange(5)
        runs = []
        monkeypatch.setattr(window, "_on_run", lambda *args, **kwargs: runs.append(True))
        window._part_var.set(0.08)

        window._on_part_change("0.08")

        assert window._dirty_find is True
        assert runs == []
        assert window._algorithm_rerun_after_id is not None
        window._flush_algorithm_rerun()
        assert runs == [True]
    finally:
        window._on_close()


def test_auto_detect_algorithm_slider_coalesces_while_pipeline_is_running(tk_root, monkeypatch) -> None:
    window = AutoDetectWindow(_app(tk_root))
    _open_hidden(window)
    try:
        window._runner = SimpleNamespace(is_running=lambda _key: True)
        window._dirty_traces = False
        window._cached_detrended = np.ones((1, 5), dtype=np.float32)
        window._cached_frame_indices = np.arange(5)
        runs = []
        monkeypatch.setattr(window, "_on_run", lambda *args, **kwargs: runs.append(True))
        window._part_var.set(0.08)

        window._on_part_change("0.08")

        assert window._dirty_find is True
        assert window._pending_algorithm_rerun is False
        window._flush_algorithm_rerun()
        assert window._pending_algorithm_rerun is True
        assert runs == []
    finally:
        window._on_close()


def test_auto_detect_coherence_slider_reruns_cached_gate_stage_only(tk_root, monkeypatch) -> None:
    window = AutoDetectWindow(_app(tk_root))
    _open_hidden(window)
    try:
        window._dirty_traces = False
        window._dirty_find = False
        window._cached_detrended = np.ones((1, 5), dtype=np.float32)
        window._cached_frame_indices = np.arange(5)
        window._cached_raw_candidates = [{"start_frame": 0, "end_frame": 1}]
        runs = []
        monkeypatch.setattr(window, "_on_run", lambda *args, **kwargs: runs.append(True))
        window._coh_var.set(0.1)

        window._on_coh_change("0.1")

        assert window._dirty_find is False
        assert window._dirty_gate is True
        assert runs == []
        window._flush_algorithm_rerun()
        assert runs == [True]
    finally:
        window._on_close()


def test_auto_detect_split_checkbox_marks_stale_without_rerun(tk_root, monkeypatch) -> None:
    window = AutoDetectWindow(_app(tk_root))
    _open_hidden(window)
    try:
        window._dirty_traces = False
        window._cached_detrended = np.ones((1, 5), dtype=np.float32)
        window._cached_frame_indices = np.arange(5)
        runs = []
        monkeypatch.setattr(window, "_on_run", lambda *args, **kwargs: runs.append(True))

        window._on_split_change()

        assert window._dirty_find is True
        assert runs == []
    finally:
        window._on_close()


def test_auto_detect_stale_selection_is_ignored(tk_root) -> None:
    window = AutoDetectWindow(_app(tk_root))
    _open_hidden(window)
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


def test_detail_window_clamps_at_stack_edges(tk_root) -> None:
    app = SimpleNamespace(
        root=tk_root,
        reader=_Reader(),
        current_frame_idx=0,
        stack_info=SimpleNamespace(frame_count=5000, frame_height=8, frame_width=8),
        browser_controller=SimpleNamespace(get_global_metrics_defaults=lambda: {}),
    )
    window = AutoDetectWindow(app)

    # Center at start
    window._detail_center_frame = 0
    window._detail_half_width = 200
    start, end = window._detail_window_bounds()
    assert start == 0
    assert end == 200

    # Center at end
    window._detail_center_frame = 4999
    start, end = window._detail_window_bounds()
    assert end == 4999
    assert start == 4999 - 200

    # Half-width larger than stack
    window._detail_center_frame = 2500
    window._detail_half_width = 10000
    start, end = window._detail_window_bounds()
    assert start == 0
    assert end == 4999


def test_detail_window_degenerate_for_single_frame_stack(tk_root) -> None:
    app = SimpleNamespace(
        root=tk_root,
        reader=_Reader(),
        current_frame_idx=0,
        stack_info=SimpleNamespace(frame_count=1, frame_height=8, frame_width=8),
        browser_controller=SimpleNamespace(get_global_metrics_defaults=lambda: {}),
    )
    window = AutoDetectWindow(app)

    start, end = window._detail_window_bounds()
    assert start == 0
    assert end == 0


def test_trace_extraction_rejects_invalid_frame_count() -> None:
    with pytest.raises(ValueError, match="frame_count"):
        extract_lower_median_traces(
            reader=object(),
            cell_masks=[np.ones((2, 2), dtype=bool)],
            geometry=SimpleNamespace(),
            frame_count=0,
        )
