from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

import swell.host.auto_detect_helpers as auto_detect_helpers
from swell.host.auto_detect_window import AutoDetectWindow, _to_uint8
from swell.host.event_detection import detector
from swell.host.event_detection.grid import build_detector_grid
from swell.host.event_detection.traces import extract_lower_median_traces
from swell.shared.app_metadata import format_window_title


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


def _polarity_trace(sign: int) -> np.ndarray:
    traces = np.zeros((4, 120), dtype=np.float32)
    ramp = np.arange(61, dtype=np.float32) * int(sign)
    traces[:, 20:81] = ramp
    traces[:, 81:] = ramp[-1]
    return traces


def test_auto_detect_to_uint8_uses_sampled_percentiles(monkeypatch) -> None:
    frame = np.arange(10_000, dtype=np.float32).reshape(100, 100)
    sampled = np.asarray([0.0, 100.0, 200.0, 300.0], dtype=np.float32)
    calls: list[tuple[int, int]] = []

    def _sample(frame_arg):
        arr = np.asarray(frame_arg)
        calls.append(tuple(arr.shape))
        return sampled

    monkeypatch.setattr(auto_detect_helpers, "_sample_percentile_pixels", _sample)

    result = _to_uint8(frame)

    assert calls == [(100, 100)]
    assert result.shape == frame.shape
    assert result.dtype == np.uint8


def test_detector_grid_preserves_thin_roi_across_size_boundary() -> None:
    for width in (800, 801, 1600, 4000):
        roi = np.zeros((20, width), dtype=bool)
        roi[10, width // 2] = True

        extraction = build_detector_grid(roi, roi.shape, 1, 1)

        assert np.any(extraction.roi_analysis)
        assert max(extraction.geometry.resized_shape) <= 800


def test_auto_detect_timeline_coordinate_helpers_are_clamped() -> None:
    assert auto_detect_helpers.detail_window_bounds(100, 50, 10) == (40, 60)
    assert auto_detect_helpers.detail_window_bounds(1, 50, 10) == (0, 0)
    assert auto_detect_helpers.frame_from_overview_x(-10, canvas_width=200, frame_count=100) == 0
    assert auto_detect_helpers.frame_from_overview_x(250, canvas_width=200, frame_count=100) == 99
    assert auto_detect_helpers.frame_from_detail_x(50, canvas_width=100, window_bounds=(40, 60), frame_count=100) == 50
    assert auto_detect_helpers.detail_x_from_frame(50, canvas_width=100, window_bounds=(40, 60)) == 50.0
    assert auto_detect_helpers.detail_x_from_frame(70, canvas_width=100, window_bounds=(40, 60)) is None


def test_auto_detect_active_cell_helper_uses_cache() -> None:
    detrended = np.zeros((2, 8), dtype=np.float32)
    detrended[0, 3:6] = 100.0
    frame_indices = np.arange(8)
    params = {
        "coherence_active_threshold_mad": 10.0,
        "quiet_pre_frames": 2,
        "diff_k_mad": 2.5,
        "polarity": "positive",
        "persistence_frames": 1,
    }
    cache: dict[tuple, tuple[int, int, np.ndarray]] = {}
    cand = {"start_frame": 2, "end_frame": 5}

    active = auto_detect_helpers.active_cells_for_frame(
        selected_cand=cand,
        selected_index=0,
        frame_idx=3,
        detrended=detrended,
        frame_indices=frame_indices,
        params=params,
        cache=cache,
    )
    active_again = auto_detect_helpers.active_cells_for_frame(
        selected_cand=cand,
        selected_index=0,
        frame_idx=4,
        detrended=detrended,
        frame_indices=frame_indices,
        params=params,
        cache=cache,
    )

    assert active is not None
    assert bool(active[0]) is True
    assert active_again is not None
    assert len(cache) == 1


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


def test_auto_detect_window_title_matches_tool_style(tk_root) -> None:
    window = AutoDetectWindow(_app(tk_root))
    _open_hidden(window)
    try:
        assert window._popup is not None
        assert window._popup.title() == format_window_title("Swell Autodetect")
    finally:
        window._on_close()


def test_auto_detect_grid_density_label_uses_subsections(tk_root) -> None:
    window = AutoDetectWindow(_app(tk_root))
    _open_hidden(window)
    try:
        assert window._grid_label_var.get() == "Grid density  (40×40 subsections)"
        window._grid_var.set(20)

        window._on_grid_change("20")

        assert window._grid_label_var.get() == "Grid density  (20×20 subsections)"
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


def test_auto_detect_grid_has_contrast_on_dark_and_bright_frames(tk_root) -> None:
    class Canvas:
        def winfo_width(self) -> int:
            return 80

        def winfo_height(self) -> int:
            return 80

    window = AutoDetectWindow(_app(tk_root))
    window._viewer_canvas = Canvas()
    window._n_grid = 4
    window._roi_mask = None
    window._grid_opacity = 1.0

    dark = np.asarray(window._make_grid_overlay(np.zeros((8, 8), dtype=np.uint8), selected_cand=None))
    bright = np.asarray(window._make_grid_overlay(np.full((8, 8), 255, dtype=np.uint8), selected_cand=None))

    assert dark[40, 20].max() > 80
    assert np.abs(bright[40, 20].astype(int) - np.array([255, 255, 255])).max() > 30


def test_auto_detect_grid_lines_are_thicker_than_one_pixel(tk_root) -> None:
    class Canvas:
        def winfo_width(self) -> int:
            return 80

        def winfo_height(self) -> int:
            return 80

    window = AutoDetectWindow(_app(tk_root))
    window._viewer_canvas = Canvas()
    window._n_grid = 4
    window._roi_mask = None
    window._grid_opacity = 1.0

    rendered = np.asarray(window._make_grid_overlay(np.zeros((8, 8), dtype=np.uint8), selected_cand=None))
    affected_columns = [x for x in range(16, 25) if rendered[10, x].max() > 0]

    assert len(affected_columns) >= 2


def test_auto_detect_grid_lines_use_even_visual_weight(tk_root) -> None:
    class Canvas:
        def winfo_width(self) -> int:
            return 80

        def winfo_height(self) -> int:
            return 80

    window = AutoDetectWindow(_app(tk_root))
    window._viewer_canvas = Canvas()
    window._n_grid = 8
    window._roi_mask = None
    window._grid_opacity = 1.0

    rendered = np.asarray(window._make_grid_overlay(np.zeros((8, 8), dtype=np.uint8), selected_cand=None))

    assert np.array_equal(rendered[10, 10], rendered[10, 50])


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


def test_auto_detect_active_cells_clear_grid_for_scrubbed_frame(tk_root) -> None:
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

    assert frame_2[20, 20].max() > frame_2[20, 60].max()
    assert frame_3[20, 60].max() > frame_3[20, 20].max()


def test_auto_detect_active_cell_fills_without_border(tk_root) -> None:
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
    assert np.array_equal(rendered[0, 39], rendered[20, 20])


def test_auto_detect_adjacent_active_cells_do_not_draw_internal_seams(tk_root, monkeypatch) -> None:
    class Canvas:
        def winfo_width(self) -> int:
            return 80

        def winfo_height(self) -> int:
            return 80

    cells = []
    for row in range(2):
        for col in range(2):
            cell = np.zeros((8, 8), dtype=bool)
            cell[row * 4 : (row + 1) * 4, col * 4 : (col + 1) * 4] = True
            cells.append(cell)

    window = AutoDetectWindow(_app(tk_root))
    window._viewer_canvas = Canvas()
    window._n_grid = 2
    window._grid_opacity = 1.0
    window._roi_mask = np.ones((8, 8), dtype=bool)
    window._current_idx = 0
    window._review_candidates = [{"start_frame": 2, "end_frame": 4}]
    window._cached_grid_extraction = SimpleNamespace(
        cell_masks=cells,
        cell_row_cols=[(0, 0), (0, 1), (1, 0), (1, 1)],
        geometry=SimpleNamespace(resized_shape=(8, 8), crop_box=(0, 8, 0, 8)),
    )
    window._current_frame = 2
    monkeypatch.setattr(window, "_active_cells_for_frame", lambda _cand, _frame: np.array([True, True, True, True]))

    rendered = np.asarray(window._make_grid_overlay(np.zeros((8, 8), dtype=np.uint8), selected_cand=window._review_candidates[0]))

    assert rendered[20, 39].max() > 0
    assert np.array_equal(rendered[20, 39], rendered[20, 40])
    assert np.array_equal(rendered[39, 20], rendered[40, 20])


def test_auto_detect_active_cells_clear_detector_grid_extent_not_clipped_cell_mask(tk_root) -> None:
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
    assert np.array_equal(rendered[0, 39], rendered[20, 39])


def test_auto_detect_active_cell_fill_is_clipped_to_roi(tk_root) -> None:
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
    window._roi_mask = clipped_left_cell.copy()
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

    assert rendered[20, 10].max() > 0
    assert np.array_equal(rendered[20, 30], np.array([0, 0, 0], dtype=np.uint8))


def test_auto_detect_roi_change_repaints_grid_and_invalidates_cached_pipeline_without_rerun(tk_root, monkeypatch) -> None:
    from swell.analysis.ui import roi_dialog

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


def test_auto_detect_full_pipeline_reports_post_extraction_stages(tk_root, monkeypatch) -> None:
    window = AutoDetectWindow(_app(tk_root))
    _open_hidden(window)
    try:
        reports: list[str] = []
        extraction = SimpleNamespace(
            cell_masks=[np.ones((8, 8), dtype=bool)],
            geometry=SimpleNamespace(resized_shape=(8, 8), crop_box=(0, 8, 0, 8)),
        )

        def run_sync(target, *, on_success=None, on_error=None, **_kwargs):
            try:
                result = target()
            except Exception as exc:
                if on_error is not None:
                    on_error(exc)
            else:
                if on_success is not None:
                    on_success(result)
            return None

        window._runner = SimpleNamespace(start=run_sync)
        window._run_generation = 7
        monkeypatch.setattr(window, "_report", lambda msg: reports.append(msg))
        monkeypatch.setattr(window, "_finalize_run", lambda _generation=None: None)
        monkeypatch.setattr(window, "_clear_active_cell_overlay_cache", lambda: None)
        monkeypatch.setattr("swell.host.event_detection.grid.build_detector_grid", lambda *_args, **_kwargs: extraction)
        monkeypatch.setattr(
            "swell.host.event_detection.traces.extract_lower_median_traces",
            lambda *_args, progress_callback=None, **_kwargs: np.ones((1, 5), dtype=np.float32),
        )
        monkeypatch.setattr(
            "swell.host.event_detection.traces.detrend_traces",
            lambda traces: np.asarray(traces, dtype=np.float32),
        )
        monkeypatch.setattr("swell.host.auto_detect_window._find_with_params", lambda *_args, **_kwargs: [{"start_frame": 1, "end_frame": 3}])
        monkeypatch.setattr("swell.host.auto_detect_window._gate_with_params", lambda candidates, *_args, **_kwargs: list(candidates))

        window._run_full_pipeline(7)

        assert reports == [
            "Building grid...",
            "Detrending traces...",
            "Finding candidates...",
            "Applying coherence filter...",
            "Preparing review...",
        ]
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


def test_auto_detect_split_checkbox_schedules_cached_detection_rerun(tk_root, monkeypatch) -> None:
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
        window._flush_algorithm_rerun()
        assert runs == [True]
    finally:
        window._on_close()


def test_auto_detect_invalidation_during_running_pipeline_retires_stale_generation(tk_root) -> None:
    class Runner:
        def __init__(self) -> None:
            self.running = True
            self.starts = []

        def is_running(self, _key: str) -> bool:
            return self.running

        def start(self, **kwargs):
            self.starts.append(kwargs)
            return None

    window = AutoDetectWindow(_app(tk_root))
    _open_hidden(window)
    try:
        runner = Runner()
        window._runner = runner
        window._dirty_traces = False
        window._dirty_find = False
        window._dirty_gate = False
        old_generation = window._run_generation

        window._invalidate_pipeline_results()

        assert window._run_generation == old_generation + 1
        assert window._pending_algorithm_rerun is True
        assert window._dirty_traces is True
        runner.running = False
        window._run_pending_algorithm_rerun()
        tk_root.update()

        assert window._pending_algorithm_rerun is False
        assert len(runner.starts) == 1
    finally:
        window._on_close()


def test_auto_detect_history_restores_grid_opacity(tk_root) -> None:
    window = AutoDetectWindow(_app(tk_root))
    _open_hidden(window)
    try:
        window._grid_opacity = 0.2
        window._grid_opacity_var.set(0.2)
        window._push_history()

        window._on_reset_defaults()
        assert window._grid_opacity == 0.45

        window._on_undo()

        assert window._grid_opacity == 0.2
        assert float(window._grid_opacity_var.get()) == 0.2
        assert "20%" in window._grid_opacity_label_var.get()
    finally:
        window._on_close()


def test_auto_detect_polarity_defaults_to_positive_and_reset_restores_it(tk_root) -> None:
    window = AutoDetectWindow(_app(tk_root))
    _open_hidden(window)
    try:
        assert window._params["polarity"] == "positive"
        assert window._polarity_var.get() == "Positive-going (default)"

        window._polarity_var.set("Negative-going")
        window._on_polarity_change()

        assert window._params["polarity"] == "negative"

        window._on_reset_defaults()

        assert window._params["polarity"] == "positive"
        assert window._polarity_var.get() == "Positive-going (default)"
    finally:
        window._on_close()


def test_auto_detect_polarity_change_reruns_cached_detection_only(tk_root, monkeypatch) -> None:
    window = AutoDetectWindow(_app(tk_root))
    _open_hidden(window)
    try:
        window._dirty_traces = False
        window._dirty_find = False
        window._dirty_gate = False
        window._cached_traces = np.ones((1, 5), dtype=np.float32)
        window._cached_detrended = np.ones((1, 5), dtype=np.float32)
        window._cached_frame_indices = np.arange(5)
        window._active_cell_cache[("stale",)] = (0, 1, np.ones((1, 2), dtype=bool))
        runs = []
        monkeypatch.setattr(window, "_on_run", lambda *args, **kwargs: runs.append(True))

        window._polarity_var.set("Both polarities")
        window._on_polarity_change()

        assert window._params["polarity"] == "both"
        assert window._dirty_traces is False
        assert window._dirty_find is True
        assert window._dirty_gate is True
        assert window._active_cell_cache == {}
        assert window._algorithm_rerun_after_id is not None

        window._flush_algorithm_rerun()

        assert runs == [True]
    finally:
        window._on_close()


def test_auto_detect_accept_candidate_syncs_once_for_single_candidate(tk_root) -> None:
    created = []
    syncs = []
    app = _app(tk_root)
    app.browser_controller = SimpleNamespace(
        create_event=lambda **kwargs: created.append(dict(kwargs)),
        get_global_metrics_defaults=lambda: {},
    )
    app._sync_event_projections = lambda: syncs.append(True)
    window = AutoDetectWindow(app)

    window._accept_candidate({"start_frame": 1, "end_frame": 3})

    assert len(created) == 1
    assert len(syncs) == 1
    flags = created[0]["flags"]
    assert flags["source"] == "auto-detect"
    assert flags["grid_density"] == window._n_grid


def test_auto_detect_accept_all_batches_projection_sync(tk_root) -> None:
    created = []
    syncs = []
    app = _app(tk_root)
    app.browser_controller = SimpleNamespace(
        create_event=lambda **kwargs: created.append(dict(kwargs)),
        get_global_metrics_defaults=lambda: {},
    )
    app._sync_event_projections = lambda: syncs.append(True)
    window = AutoDetectWindow(app)
    window._review_candidates = [
        {"start_frame": 1, "end_frame": 3},
        {"start_frame": 4, "end_frame": 6},
        {"start_frame": 8, "end_frame": 9},
    ]

    window._on_accept_all()

    assert [(c["start_idx"], c["end_idx"]) for c in created] == [(1, 3), (4, 6), (8, 9)]
    assert len(syncs) == 1
    assert all(c["flags"]["source"] == "auto-detect" for c in created)


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


def test_detector_default_is_positive_only() -> None:
    frame_indices = np.arange(120)

    assert detector.PRESET["polarity"] == "positive"
    assert detector.find_candidates(_polarity_trace(+1), frame_indices)
    assert detector.find_candidates(_polarity_trace(-1), frame_indices) == []


def test_detector_negative_and_both_polarities_remain_available() -> None:
    frame_indices = np.arange(120)
    negative_trace = _polarity_trace(-1)

    assert detector.find_candidates(negative_trace, frame_indices, polarity="negative")
    assert detector.find_candidates(negative_trace, frame_indices, polarity="both")


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
