"""Auto-detect Workbench Window.

A unified 3-pane scientific workbench for intrinsic optical signal analysis:
  - Left Pane: Parameters & Algorithms
  - Center Pane: Data Viewer & 1D Temporal Trace Scrubber
  - Right Pane: Candidate Event List & Commit
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Any

import numpy as np
from PIL import Image, ImageTk
import cv2

from swell.host.analysis_payload_mapper import apply_analysis_scope_flags
from swell.host.auto_detect_helpers import (
    active_cells_for_frame,
    cell_border_rects_for_layout,
    frame_index_position,
    grid_bounds_for_layout,
    normalize_to_uint8,
    onset_active_window,
)
from swell.host.auto_detect_layout import AutoDetectLayoutBuilder
from swell.host.auto_detect_rendering import build_grid_overlay_image
from swell.host.auto_detect_timeline import AutoDetectTimelineController
from swell.host.config import DEFAULT_BASELINE_PRE_FRAMES
from swell.shared.ui import BackgroundTaskRunner
from swell.shared.ui.bootstrap import center_window_on_screen
from swell.shared.ui.theme import CANVAS_BACKGROUND, SPACING, apply_theme

# Colors drawn directly onto tk.Canvas — must stay in sync with theme.py palette.
_C_ACCENT      = "#1b75bc"
_C_BORDER      = "#2a3139"
_C_TEXT        = "#edf1f3"
_C_MUTED       = "#8d97a2"
_C_MUTED_SOFT  = "#aeb7bf"

from .event_detection import detector as _detector
from .event_detection import grid as _grid
from .event_detection import traces as _traces

_WINDOW_W = 1200
_WINDOW_H = 700
_ALGORITHM_RERUN_DEBOUNCE_MS = 350
_POLARITY_LABELS = {
    "positive": "Positive-going (default)",
    "negative": "Negative-going",
    "both": "Both polarities",
}
_POLARITY_VALUES_BY_LABEL = {label: value for value, label in _POLARITY_LABELS.items()}


def _to_uint8(frame: np.ndarray) -> np.ndarray:
    return normalize_to_uint8(frame)


class AutoDetectWindow:
    def __init__(self, app: Any) -> None:
        self.app = app
        self._roi_mask: np.ndarray | None = None
        self._roi_points: list | None = None
        self._roi_polygons: list | None = None
        self._n_grid: int = 40
        self._grid_opacity: float = 0.45
        self._params: dict = dict(_detector.PRESET)

        self._cached_traces: np.ndarray | None = None
        self._cached_frame_indices: np.ndarray | None = None
        self._cached_detrended: np.ndarray | None = None
        self._cached_raw_candidates: list[dict] | None = None
        self._cached_grid_extraction: Any | None = None
        self._aggregated_trace: np.ndarray | None = None
        self._active_cell_cache: dict[tuple, tuple[int, int, np.ndarray]] = {}
        self._cell_border_cache_key: tuple | None = None
        self._cell_border_rects: list[tuple[int, int, int, int]] = []

        self._review_candidates: list[dict] = []
        self._current_idx: int | None = None

        self._dirty_traces: bool = True
        self._dirty_find: bool = False
        self._dirty_gate: bool = False

        self._popup: tk.Toplevel | None = None
        self._runner: BackgroundTaskRunner | None = None
        self._viewer_image: ImageTk.PhotoImage | None = None
        self._closed: bool = True
        
        self._trace_dragging: str | None = None
        self._trace_hover: str | None = None
        self._current_frame: int = 0

        self._detail_half_width: int = 200
        self._detail_min_half_width: int = 20
        self._detail_max_half_width: int = 5000
        self._detail_center_frame: int = 0

        self._overview_items: dict[str, int] = {}
        self._detail_items: dict[str, int] = {}
        self._candidate_bar_overview: list[int] = []
        self._candidate_bar_detail: list[int] = []

        self._pending_viewer_frame: int | None = None
        self._viewer_after_id: str | None = None

        self._run_generation: int = 0
        self._pending_algorithm_rerun: bool = False
        self._algorithm_rerun_after_id: str | None = None
        self._param_history: list[dict] = []
        self._param_history_idx: int = -1
        self._timeline = AutoDetectTimelineController(self)
        self._layout = AutoDetectLayoutBuilder(self, polarity_labels=_POLARITY_LABELS)
        self._push_history()

        self._load_project_roi()

    def open(self, *, show: bool = True) -> None:
        popup = tk.Toplevel(self.app.root)
        if not show:
            popup.withdraw()
        popup.title("Auto-detect SDs - Scientific Workbench")
        apply_theme(popup)
        popup.minsize(_WINDOW_W, _WINDOW_H)
        popup.protocol("WM_DELETE_WINDOW", self._on_close)
        self._popup = popup
        self._closed = False

        container = ttk.Frame(popup, style="AppSurface.TFrame")
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=0, minsize=300)
        container.columnconfigure(1, weight=1)
        container.columnconfigure(2, weight=0, minsize=320)
        container.rowconfigure(0, weight=1)

        self._layout.build_left_pane(container)
        self._layout.build_center_pane(container)
        self._layout.build_right_pane(container)

        self._update_setup_labels()
        self._update_roi_status()
        self._render_viewer_frame(0)

        if show:
            center_window_on_screen(popup, width=_WINDOW_W, height=_WINDOW_H)
            popup.after(0, lambda: (popup.lift(), popup.focus_force()))

    def _on_reset_defaults(self) -> None:
        self._params = dict(_detector.PRESET)
        self._n_grid = 40
        self._grid_opacity = 0.45
        self._grid_var.set(self._n_grid)
        self._grid_opacity_var.set(self._grid_opacity)
        self._sens_var.set(self._k_mad_to_sens(float(self._params["diff_k_mad"])))
        self._part_var.set(float(self._params["peak_height_fraction"]))
        self._coh_var.set(float(self._params["coherence_threshold"]))
        self._split_var.set(bool(self._params["split_broad_windows"]))
        self._polarity_var.set(self._polarity_label_for_param())
        self._grid_label_var.set(f"Grid density  ({self._n_grid}×{self._n_grid} cells)")
        self._grid_opacity_label_var.set(f"Grid opacity  ({int(round(self._grid_opacity * 100))}%)")
        self._update_setup_labels()
        self._invalidate_pipeline_results()
        self._push_history()
        self._refresh_after_pipeline_invalidation()

    def _push_history(self) -> None:
        state = {
            "params": dict(self._params),
            "n_grid": self._n_grid
        }
        if self._param_history and self._param_history[self._param_history_idx] == state:
            return
        self._param_history = self._param_history[:self._param_history_idx + 1]
        self._param_history.append(state)
        self._param_history_idx = len(self._param_history) - 1
        self._update_history_buttons()

    def _on_undo(self) -> None:
        if self._param_history_idx > 0:
            self._param_history_idx -= 1
            self._apply_history_state(self._param_history[self._param_history_idx])

    def _on_redo(self) -> None:
        if self._param_history_idx < len(self._param_history) - 1:
            self._param_history_idx += 1
            self._apply_history_state(self._param_history[self._param_history_idx])

    def _apply_history_state(self, state: dict) -> None:
        self._params = dict(state["params"])
        self._n_grid = int(state["n_grid"])
        self._grid_var.set(self._n_grid)
        self._sens_var.set(self._k_mad_to_sens(float(self._params["diff_k_mad"])))
        self._part_var.set(float(self._params["peak_height_fraction"]))
        self._coh_var.set(float(self._params["coherence_threshold"]))
        self._split_var.set(bool(self._params["split_broad_windows"]))
        self._polarity_var.set(self._polarity_label_for_param())
        self._grid_label_var.set(f"Grid density  ({self._n_grid}×{self._n_grid} cells)")
        self._update_setup_labels()
        self._invalidate_pipeline_results()
        self._update_history_buttons()
        self._refresh_after_pipeline_invalidation()

    def _update_history_buttons(self) -> None:
        if self._closed: return
        self._undo_btn.config(state="normal" if self._param_history_idx > 0 else "disabled")
        self._redo_btn.config(state="normal" if self._param_history_idx < len(self._param_history) - 1 else "disabled")

    def _on_cancel_run(self) -> None:
        self._run_generation += 1
        self._setup_status_var.set("Run cancelled.")
        self._cancel_btn.config(state="disabled")
        self._run_btn.config(state="normal")
        self._render_trace()

    def _on_draw_roi(self) -> None:
        from swell.analysis.ui.roi_dialog import open_roi_dialog
        fi = self._current_frame
        raw = self.app.reader.read_frame(fi, use_cache=True)
        img_u8 = _to_uint8(raw)

        def _pick_roi_image(parent=None):
            picker = getattr(self.app, "_pick_metrics_reference_image_u8", None)
            if callable(picker):
                res = picker(parent=parent or self._popup, purpose="ROI", force_picker=True)
                return res[0] if res else None
            return None

        # Try to get the filename for the current frame
        image_label = "Reference image"
        try:
            ref = self.app.reader.get_frame_ref(fi)
            source_path = Path(str(getattr(ref, "source_path", "") or "")).expanduser()
            if source_path.name:
                image_label = source_path.name
        except Exception:
            pass

        result = open_roi_dialog(
            self._popup,
            img_u8,
            initial_roi_points=self._roi_points,
            initial_roi_polygons=self._roi_polygons,
            allow_reset_local=False,
            pick_image_callback=_pick_roi_image,
            context="auto_detect",
            image_label=image_label,
        )
        if not isinstance(result, dict) or "roi_mask" not in result:
            return
        self._roi_mask = result.get("roi_mask")
        self._roi_points = result.get("roi_points")
        self._roi_polygons = result.get("roi_polygons")
        self._on_roi_changed()

    def _on_clear_roi(self) -> None:
        self._roi_mask = None
        self._roi_points = None
        self._roi_polygons = None
        self._on_roi_changed()

    def _on_roi_changed(self) -> None:
        self._invalidate_pipeline_results()
        self._update_roi_status()
        self._refresh_after_pipeline_invalidation()

    def _invalidate_pipeline_results(self) -> None:
        self._dirty_traces = True
        self._dirty_find = True
        self._dirty_gate = True
        self._cached_traces = None
        self._cached_frame_indices = None
        self._cached_detrended = None
        self._cached_raw_candidates = None
        self._cached_grid_extraction = None
        self._aggregated_trace = None
        self._clear_active_cell_overlay_cache()
        self._review_candidates = []
        self._current_idx = None

    def _refresh_after_pipeline_invalidation(self) -> None:
        if self._is_open():
            self._populate_tree()
            self._render_viewer_frame(self._current_frame)
            self._render_trace()

    def _on_grid_change(self, _val: str) -> None:
        raw = float(self._grid_var.get())
        n = max(10, min(80, int(round(raw / 10.0)) * 10))
        if n != self._n_grid:
            self._n_grid = n
            self._grid_label_var.set(f"Grid density  ({n}×{n} cells)")
            self._invalidate_pipeline_results()
            self._refresh_after_pipeline_invalidation()

    def _on_grid_opacity_change(self, _val: str) -> None:
        opacity = max(0.0, min(1.0, float(self._grid_opacity_var.get())))
        if abs(opacity - self._grid_opacity) >= 0.01:
            self._grid_opacity = opacity
            self._grid_opacity_label_var.set(f"Grid opacity  ({int(round(opacity * 100))}%)")
            self._render_viewer_frame(self._current_frame)

    def _on_sens_change(self, _val: str) -> None:
        sens = float(self._sens_var.get())
        k_mad = self._sens_to_k_mad(sens)
        if abs(k_mad - self._params["diff_k_mad"]) > 0.05:
            self._params["diff_k_mad"] = k_mad
            self._dirty_find = True
            self._update_setup_labels()
            self._schedule_algorithm_rerun()

    def _on_part_change(self, _val: str) -> None:
        v = float(self._part_var.get())
        if abs(v - self._params["peak_height_fraction"]) > 0.01:
            self._params["peak_height_fraction"] = v
            self._dirty_find = True
            self._update_setup_labels()
            self._schedule_algorithm_rerun()

    def _on_coh_change(self, _val: str) -> None:
        v = float(self._coh_var.get())
        if abs(v - self._params["coherence_threshold"]) > 0.01:
            self._params["coherence_threshold"] = v
            self._dirty_gate = True
            self._update_setup_labels()
            self._schedule_algorithm_rerun()

    def _on_split_change(self) -> None:
        self._params["split_broad_windows"] = bool(self._split_var.get())
        self._dirty_find = True

    def _on_polarity_change(self, _event=None) -> None:
        selected = _POLARITY_VALUES_BY_LABEL.get(str(self._polarity_var.get()), "positive")
        if selected == self._params.get("polarity", "positive"):
            return
        self._params["polarity"] = selected
        self._dirty_find = True
        self._dirty_gate = True
        self._clear_active_cell_overlay_cache()
        self._update_setup_labels()
        self._schedule_algorithm_rerun()

    def _polarity_label_for_param(self) -> str:
        return _POLARITY_LABELS.get(str(self._params.get("polarity", "positive")), _POLARITY_LABELS["positive"])

    def _schedule_algorithm_rerun(self) -> None:
        if not self._is_open():
            return
        if self._algorithm_rerun_after_id is not None and self._popup is not None:
            try:
                self._popup.after_cancel(self._algorithm_rerun_after_id)
            except Exception:
                pass
        self._algorithm_rerun_after_id = self._popup.after(_ALGORITHM_RERUN_DEBOUNCE_MS, self._flush_algorithm_rerun)

    def _flush_algorithm_rerun(self) -> None:
        self._algorithm_rerun_after_id = None
        self._rerun_cached_algorithm_stage()

    def _rerun_cached_algorithm_stage(self) -> None:
        if not self._is_open():
            return
        if self._is_pipeline_running():
            self._pending_algorithm_rerun = True
            return
        if not self._dirty_traces and self._cached_detrended is not None and self._cached_frame_indices is not None:
            if self._dirty_find or self._cached_raw_candidates is not None:
                self._on_run()

    def _on_run(self, push_history: bool = True) -> None:
        if not self._is_open():
            return
        if self._is_pipeline_running():
            self._pending_algorithm_rerun = True
            return
        if push_history:
            self._push_history()

        self._run_generation += 1
        gen = self._run_generation
        
        self._setup_status_var.set("Running detection...")
        for c in (getattr(self, "_overview_canvas", None), getattr(self, "_detail_canvas", None)):
            if c is not None:
                try:
                    c.itemconfig("scrubber", fill=_C_MUTED_SOFT)  # Muted while running
                except tk.TclError:
                    pass
        self._run_btn.config(state="disabled")
        self._cancel_btn.config(state="normal")
        
        if self._dirty_traces or self._cached_traces is None:
            self._run_full_pipeline(gen)
        elif self._dirty_find:
            self._run_find_and_gate(gen)
        elif self._dirty_gate:
            self._run_gate_only(gen)
        else:
            self._finalize_run(gen)

    def _run_full_pipeline(self, generation: int) -> None:
        app = self.app
        n_grid = self._n_grid
        roi_mask = self._get_effective_roi()
        params = dict(self._params)

        def worker():
            h = int(app.stack_info.frame_height)
            w = int(app.stack_info.frame_width)
            frame_count = int(app.stack_info.frame_count)
            self._report("Building grid...")
            extraction = _grid.build_detector_grid(roi_mask, (h, w), n_grid, n_grid)
            if not extraction.cell_masks:
                raise RuntimeError("Grid has no cells inside the ROI.")
            
            raw_traces = _traces.extract_lower_median_traces(
                app.reader,
                extraction.cell_masks,
                extraction.geometry,
                frame_count=frame_count,
                progress_callback=lambda frac, msg: self._report(f"Extracting: {int(frac*100)}%")
            )
            frame_indices = np.arange(frame_count, dtype=np.int64)
            detrended = _traces.detrend_traces(raw_traces)
            raw_cands = _find_with_params(detrended, frame_indices, params)
            accepted = _gate_with_params(raw_cands, detrended, frame_indices, params)
            
            # Aggregate for global trace
            agg = np.mean(detrended, axis=0) if detrended.shape[0] > 0 else np.zeros(frame_count)
            return extraction, raw_traces, frame_indices, detrended, raw_cands, accepted, agg

        def on_done(result):
            if generation != self._run_generation: return
            extraction, raw_traces, frame_indices, detrended, raw_cands, accepted, agg = result
            self._cached_grid_extraction = extraction
            self._cached_traces = raw_traces
            self._cached_frame_indices = frame_indices
            self._cached_detrended = detrended
            self._cached_raw_candidates = raw_cands
            self._review_candidates = accepted
            self._aggregated_trace = agg
            self._clear_active_cell_overlay_cache()
            self._dirty_traces = False
            if self._pending_algorithm_rerun:
                self._run_pending_algorithm_rerun(generation)
                return
            self._dirty_find = False
            self._dirty_gate = False
            self._finalize_run(generation)

        self._task_runner.start(target=worker, on_success=on_done, on_error=lambda e: self._on_run_error(e, generation), key="auto_detect", drop_if_running=True)

    def _run_find_and_gate(self, generation: int) -> None:
        detrended = self._cached_detrended
        frame_indices = self._cached_frame_indices
        if detrended is None or frame_indices is None:
            return self._run_full_pipeline(generation)
        params = dict(self._params)

        def worker():
            raw_cands = _find_with_params(detrended, frame_indices, params)
            return raw_cands, _gate_with_params(raw_cands, detrended, frame_indices, params)

        def on_done(result):
            if generation != self._run_generation: return
            raw_cands, accepted = result
            self._cached_raw_candidates = raw_cands
            self._review_candidates = accepted
            self._clear_active_cell_overlay_cache()
            if self._pending_algorithm_rerun:
                self._run_pending_algorithm_rerun(generation)
                return
            self._dirty_find = False
            self._dirty_gate = False
            self._finalize_run(generation)

        self._task_runner.start(target=worker, on_success=on_done, on_error=lambda e: self._on_run_error(e, generation), key="auto_detect", drop_if_running=True)

    def _run_gate_only(self, generation: int) -> None:
        raw_cands = self._cached_raw_candidates
        detrended = self._cached_detrended
        frame_indices = self._cached_frame_indices
        if raw_cands is None or detrended is None or frame_indices is None:
            return self._run_full_pipeline(generation)
        params = dict(self._params)

        def worker():
            return _gate_with_params(raw_cands, detrended, frame_indices, params)

        def on_done(accepted):
            if generation != self._run_generation: return
            self._review_candidates = accepted
            self._clear_active_cell_overlay_cache()
            if self._pending_algorithm_rerun:
                self._run_pending_algorithm_rerun(generation)
                return
            self._dirty_gate = False
            self._finalize_run(generation)

        self._task_runner.start(target=worker, on_success=on_done, on_error=lambda e: self._on_run_error(e, generation), key="auto_detect", drop_if_running=True)

    def _run_pending_algorithm_rerun(self, generation: int) -> None:
        if generation != self._run_generation or not self._is_open():
            return
        self._pending_algorithm_rerun = False
        if self._dirty_find or self._dirty_gate:
            self._popup.after(0, self._on_run)

    def _finalize_run(self, generation: int | None = None) -> None:
        if generation is None:
            generation = self._run_generation
        if not self._is_open() or generation != self._run_generation:
            return
        
        self._run_btn.config(state="normal")
        self._cancel_btn.config(state="disabled")
        
        n = len(self._review_candidates)
        self._setup_status_var.set(f"Ready: {n} event{'s' if n != 1 else ''} found")
        self._populate_tree()
        self._render_trace()
        if self._review_candidates:
            first_iid = self._tree.get_children()[0]
            self._tree.selection_set(first_iid)
            self._on_tree_select()

    def _on_run_error(self, exc: Exception, generation: int | None = None) -> None:
        if generation is None:
            generation = self._run_generation
        if not self._is_open() or generation != self._run_generation: 
            return
        self._run_btn.config(state="normal")
        self._cancel_btn.config(state="disabled")
        self._setup_status_var.set(f"Error: {exc}")
        self._render_trace()

    def _on_tree_select(self, _event=None) -> None:
        if not self._is_open(): return
        sel = self._tree.selection()
        if not sel: return
        idx = self._idx_for_iid(sel[0])
        if idx is None: return
        
        self._current_idx = idx
        cand = self._review_candidates[idx]
        self._start_entry.delete(0, "end")
        self._start_entry.insert(0, str(cand["start_frame"]))
        self._end_entry.delete(0, "end")
        self._end_entry.insert(0, str(cand["end_frame"]))
        
        peak = int(cand.get("peak_frame", cand["start_frame"]))
        self._current_frame = peak
        self._detail_center_frame = peak
        self._render_viewer_frame(peak)
        self._render_trace()

    def _on_step_frame(self, step: int) -> None:
        fc = int(self.app.stack_info.frame_count)
        self._current_frame = max(0, min(fc - 1, self._current_frame + step))
        self._detail_center_frame = self._current_frame
        self._render_viewer_frame(self._current_frame)
        self._render_trace()

    def _on_update_bounds(self) -> None:
        idx = self._selected_candidate_idx()
        if idx is None: return
        try:
            start = int(self._start_entry.get().strip())
            end = int(self._end_entry.get().strip())
            fc = int(self.app.stack_info.frame_count)
            start = max(0, min(start, fc - 1))
            end = max(start, min(end, fc - 1))
            cand = self._review_candidates[idx]
            cand["start_frame"] = start
            cand["end_frame"] = end
            self._refresh_tree_row(idx)
            self._render_trace()
        except ValueError:
            pass

    def _on_delete(self) -> None:
        idx = self._selected_candidate_idx()
        if idx is None: return
        iid = self._iid_for_idx(idx)
        if iid: self._tree.delete(iid)
        self._review_candidates.pop(idx)
        self._populate_tree()
        self._current_idx = None
        self._render_trace()

    def _on_accept_one(self) -> None:
        idx = self._selected_candidate_idx()
        if idx is None: return
        self._accept_candidate(self._review_candidates[idx])
        self._on_delete()

    def _on_accept_all(self) -> None:
        for cand in list(self._review_candidates):
            self._accept_candidate(cand)
        self._on_close()

    def _accept_candidate(self, cand: dict) -> None:
        flags = apply_analysis_scope_flags({}, event_start=int(cand["start_frame"]), event_end=int(cand["end_frame"]), baseline_pre_frames=DEFAULT_BASELINE_PRE_FRAMES)
        flags["source"] = "auto-detect"
        flags["diff_k_mad"] = float(self._params["diff_k_mad"])
        flags["coherence_threshold"] = float(self._params["coherence_threshold"])
        flags["grid_density"] = int(self._n_grid)
        flags["polarity"] = self._params.get("polarity", "positive")
        flags["persistence_frames"] = int(self._params.get("persistence_frames", 1))
        self.app.browser_controller.create_event(start_idx=int(cand["start_frame"]), end_idx=int(cand["end_frame"]), frame_count=int(self.app.stack_info.frame_count), flags=flags)
        self.app._sync_event_projections()

    def _render_viewer_frame(self, frame_idx: int) -> None:
        if self.app.reader is None: return
        try:
            raw = self.app.reader.read_frame(frame_idx, use_cache=True)
            img_u8 = _to_uint8(raw)
            cand = self._review_candidates[self._current_idx] if self._current_idx is not None else None
            pil = self._make_grid_overlay(img_u8, selected_cand=cand)
            self._viewer_image = ImageTk.PhotoImage(pil)
            self._viewer_canvas.delete("all")
            
            cw = self._viewer_canvas.winfo_width()
            ch = self._viewer_canvas.winfo_height()
            if cw <= 1: cw, ch = 480, 480
            
            self._viewer_canvas.create_image(cw // 2, ch // 2, anchor="center", image=self._viewer_image)
            self._viewer_frame_label_var.set(f"Frame {frame_idx}")
        except Exception:
            pass

    def _make_grid_overlay(self, img_u8: np.ndarray, *, selected_cand: dict | None) -> Image.Image:
        cw = max(1, self._viewer_canvas.winfo_width())
        ch = max(1, self._viewer_canvas.winfo_height())
        if cw <= 1: cw, ch = 480, 480

        h, w = img_u8.shape[:2]
        scale = min(cw / max(w, 1), ch / max(h, 1))
        dw, dh = max(1, int(w * scale)), max(1, int(h * scale))
        layout = (cw, ch, dw, dh, (cw - dw) // 2, (ch - dh) // 2)
        active_cells = self._active_cells_for_frame(selected_cand, self._current_frame)
        border_rects = self._cell_border_rects_for_layout(layout)
        return build_grid_overlay_image(
            img_u8,
            canvas_size=(cw, ch),
            grid_density=self._n_grid,
            grid_opacity=self._grid_opacity,
            roi_mask=self._roi_mask,
            extraction=self._cached_grid_extraction,
            active_cells=active_cells,
            border_rects=border_rects,
        )

    def _grid_bounds_for_layout(self, layout: tuple[int, int, int, int, int, int]) -> tuple[int, int, int, int] | None:
        return grid_bounds_for_layout(layout, self._cached_grid_extraction)

    def _clear_active_cell_overlay_cache(self) -> None:
        self._active_cell_cache.clear()
        self._cell_border_cache_key = None
        self._cell_border_rects = []

    def _active_cells_for_frame(self, selected_cand: dict | None, frame_idx: int) -> np.ndarray | None:
        return active_cells_for_frame(
            selected_cand=selected_cand,
            selected_index=self._current_idx,
            frame_idx=frame_idx,
            detrended=self._cached_detrended,
            frame_indices=self._cached_frame_indices,
            params=self._params,
            cache=self._active_cell_cache,
        )

    def _onset_active_window(self, detrended: np.ndarray, start_idx: int, end_idx: int) -> np.ndarray:
        return onset_active_window(detrended, start_idx, end_idx, self._params)

    @staticmethod
    def _frame_index_position(frame_indices: np.ndarray, frame: int) -> int | None:
        return frame_index_position(frame_indices, frame)

    def _draw_active_cell_borders(
        self,
        overlay: Image.Image,
        *,
        selected_cand: dict | None,
        frame_idx: int,
        layout: tuple[int, int, int, int, int, int],
    ) -> None:
        active_cells = self._active_cells_for_frame(selected_cand, frame_idx)
        if active_cells is None or not np.any(active_cells):
            return
        border_rects = self._cell_border_rects_for_layout(layout)
        if not border_rects:
            return
        # Kept as a compatibility path for callers that draw into an existing overlay.
        from PIL import ImageDraw

        draw = ImageDraw.Draw(overlay)
        for cell_idx in np.flatnonzero(active_cells):
            if int(cell_idx) >= len(border_rects):
                continue
            x0, y0, x1, y1 = border_rects[int(cell_idx)]
            draw.rectangle((x0, y0, x1, y1), outline=(27, 117, 188, 96), width=1)

    def _cell_border_rects_for_layout(self, layout: tuple[int, int, int, int, int, int]) -> list[tuple[int, int, int, int]]:
        extraction = self._cached_grid_extraction
        if extraction is None:
            return []
        cache_key = (id(extraction), layout)
        if self._cell_border_cache_key == cache_key:
            return self._cell_border_rects

        rects = cell_border_rects_for_layout(layout=layout, extraction=extraction, grid_density=self._n_grid)
        self._cell_border_cache_key = cache_key
        self._cell_border_rects = rects
        return rects

    def _render_trace(self) -> None:
        self._timeline.render_trace()

    def _render_overview(self) -> None:
        self._timeline.render_overview()

    def _update_overview_dynamic(self) -> None:
        self._timeline.update_overview_dynamic()

    def _detail_window_bounds(self) -> tuple[int, int]:
        return self._timeline.detail_window_bounds()

    def _render_detail(self) -> None:
        self._timeline.render_detail()

    def _frame_from_overview_x(self, x: float) -> int:
        return self._timeline.frame_from_overview_x(x)

    def _frame_from_detail_x(self, x: float) -> int:
        return self._timeline.frame_from_detail_x(x)

    def _detail_x_from_frame(self, frame: int) -> float | None:
        return self._timeline.detail_x_from_frame(frame)

    def _frame_from_x(self, x: float) -> int:
        return self._timeline.frame_from_x(x)

    def _x_from_frame(self, frame: int) -> float:
        return self._timeline.x_from_frame(frame)

    def _on_overview_click(self, event) -> None:
        self._timeline.on_overview_click(event)

    def _on_overview_drag(self, event) -> None:
        self._timeline.on_overview_drag(event)

    def _on_overview_release(self, _event) -> None:
        self._timeline.on_overview_release(_event)

    def _on_detail_motion(self, event) -> None:
        self._timeline.on_detail_motion(event)

    def _on_detail_click(self, event) -> None:
        self._timeline.on_detail_click(event)

    def _on_detail_drag(self, event) -> None:
        self._timeline.on_detail_drag(event)

    def _on_detail_release(self, _event) -> None:
        self._timeline.on_detail_release(_event)

    def _on_detail_wheel(self, event) -> None:
        self._timeline.on_detail_wheel(event)

    def _on_detail_wheel_linux(self, _event, direction: int) -> None:
        self._timeline.on_detail_wheel_linux(_event, direction)

    def _apply_detail_wheel(self, steps: int, *, shift: bool) -> None:
        self._timeline.apply_detail_wheel(steps, shift=shift)

    # ---------- Throttled viewer render ----------

    def _schedule_viewer_render(self, frame: int) -> None:
        self._pending_viewer_frame = int(frame)
        if self._viewer_after_id is None and self._popup is not None:
            self._viewer_after_id = self._popup.after(16, self._flush_viewer_render)

    def _flush_viewer_render(self) -> None:
        self._viewer_after_id = None
        if not self._is_open():
            return
        frame = self._pending_viewer_frame
        if frame is None:
            return
        self._render_viewer_frame(int(frame))

    def _populate_tree(self) -> None:
        self._current_idx = None
        self._tree.delete(*self._tree.get_children())
        for idx, cand in enumerate(self._review_candidates):
            dur = int(cand["end_frame"]) - int(cand["start_frame"])
            lag = cand.get("lag1_corr", float("nan"))
            lag_str = f"{lag:.3f}" if not np.isnan(lag) else "—"
            self._tree.insert("", "end", iid=f"cand_{idx}", values=(cand["start_frame"], cand["end_frame"], dur, lag_str))

    def _refresh_tree_row(self, idx: int) -> None:
        iid = f"cand_{idx}"
        if self._tree.exists(iid):
            cand = self._review_candidates[idx]
            dur = int(cand["end_frame"]) - int(cand["start_frame"])
            lag = cand.get("lag1_corr", float("nan"))
            lag_str = f"{lag:.3f}" if not np.isnan(lag) else "—"
            self._tree.item(iid, values=(cand["start_frame"], cand["end_frame"], dur, lag_str))

    def _iid_for_idx(self, idx: int) -> str | None:
        return f"cand_{idx}" if self._tree.exists(f"cand_{idx}") else None

    def _idx_for_iid(self, iid: str) -> int | None:
        try:
            return int(str(iid).split("_")[1])
        except Exception: return None

    def _selected_candidate_idx(self) -> int | None:
        if self._current_idx is not None and 0 <= self._current_idx < len(self._review_candidates):
            return self._current_idx
        self._current_idx = None
        return None

    def _load_project_roi(self) -> None:
        try:
            defaults = self.app.browser_controller.get_global_metrics_defaults()
            raw = defaults.get("roi_mask")
            if raw is not None:
                arr = np.asarray(raw, dtype=bool)
                if arr.ndim == 2 and np.any(arr):
                    self._roi_mask = arr
                    self._roi_points = defaults.get("roi_points")
                    self._roi_polygons = defaults.get("roi_polygons")
        except Exception: pass

    def _get_effective_roi(self) -> np.ndarray:
        h, w = int(self.app.stack_info.frame_height), int(self.app.stack_info.frame_width)
        if self._roi_mask is not None and self._roi_mask.shape == (h, w) and np.any(self._roi_mask):
            return np.asarray(self._roi_mask, dtype=bool)
        if self._roi_mask is not None:
            self._roi_mask = None
            self._roi_points = None
            self._roi_polygons = None
            if self._is_open():
                self._update_roi_status()
        return np.ones((h, w), dtype=bool)

    def _update_roi_status(self) -> None:
        self._roi_status_var.set(f"ROI set  ({int(np.sum(self._roi_mask)):,} px active)" if self._roi_mask is not None else "No ROI — using full frame")

    def _update_setup_labels(self) -> None:
        sens = self._k_mad_to_sens(float(self._params["diff_k_mad"]))
        self._sens_label_var.set(f"Sensitivity: {int(round(sens * 100))}%  (k_mad: {self._params['diff_k_mad']:.2f})")
        part = float(self._params["peak_height_fraction"])
        self._part_label_var.set(f"Min. participation: {int(round(part * 100))}%")
        coh = float(self._params["coherence_threshold"])
        self._coh_label_var.set(f"Coherence filter: {coh:.2f}")
        if hasattr(self, "_polarity_label_var"):
            self._polarity_label_var.set(f"Signal polarity: {self._polarity_label_for_param()}")

    def _report(self, msg: str) -> None:
        if not self._closed and self._popup:
            try: self._popup.after(0, lambda: self._setup_status_var.set(msg))
            except Exception: pass

    def _k_mad_to_sens(self, k_mad: float) -> float:
        return 1.0 - (k_mad - 1.5) / (5.0 - 1.5)

    def _sens_to_k_mad(self, sens: float) -> float:
        return 5.0 - sens * (5.0 - 1.5)

    def _on_close(self) -> None:
        self._closed = True
        if self._popup:
            try:
                if self._algorithm_rerun_after_id is not None:
                    self._popup.after_cancel(self._algorithm_rerun_after_id)
                    self._algorithm_rerun_after_id = None
                if self._viewer_after_id is not None:
                    self._popup.after_cancel(self._viewer_after_id)
                    self._viewer_after_id = None
                self._popup.grab_release()
                self._popup.destroy()
            except Exception: pass
        self._popup = None

    def _is_open(self) -> bool:
        return not self._closed and self._popup is not None and self._popup.winfo_exists()

    def _is_pipeline_running(self) -> bool:
        return bool(self._runner is not None and self._runner.is_running("auto_detect"))

    def _show_review_phase(self) -> None:
        self._finalize_run(self._run_generation)

    @property
    def _task_runner(self) -> BackgroundTaskRunner:
        if self._runner is None: self._runner = BackgroundTaskRunner(self.app.root)
        return self._runner


def _find_with_params(detrended: np.ndarray, frame_indices: np.ndarray, params: dict) -> list[dict]:
    return _detector.find_candidates(
        detrended,
        frame_indices,
        diff_k_mad=float(params["diff_k_mad"]),
        peak_height_fraction=float(params["peak_height_fraction"]),
        split_broad_windows=bool(params["split_broad_windows"]),
        polarity=params.get("polarity", "positive"),
        persistence_frames=int(params.get("persistence_frames", 1)),
    )

def _gate_with_params(candidates: list[dict], detrended: np.ndarray, frame_indices: np.ndarray, params: dict) -> list[dict]:
    return _detector.apply_coherence_gate(
        candidates,
        detrended,
        frame_indices,
        active_threshold_mad=float(params.get("coherence_active_threshold_mad", 10.0)),
        coherence_threshold=float(params.get("coherence_threshold", 0.8257435331730181)),
        quiet_pre_frames=int(params.get("quiet_pre_frames", 200)),
        polarity=params.get("polarity", "positive"),
    )
