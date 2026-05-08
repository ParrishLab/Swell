"""Auto-detect Workbench Window.

A unified 3-pane scientific workbench for intrinsic optical signal analysis:
  - Left Pane: Parameters & Algorithms
  - Center Pane: Data Viewer & 1D Temporal Trace Scrubber
  - Right Pane: Candidate Event List & Commit
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageTk
import cv2

from sdapp.host.analysis_payload_mapper import apply_analysis_scope_flags
from sdapp.host.config import DEFAULT_BASELINE_PRE_FRAMES
from sdapp.shared.frame_source import normalize_visual_frame
from sdapp.shared.ui import BackgroundTaskRunner
from sdapp.shared.ui.bootstrap import semantic_button_options
from sdapp.shared.ui.theme import SPACING, apply_theme

from .sd_detection import detector as _detector
from .sd_detection import grid as _grid
from .sd_detection import traces as _traces

_WINDOW_W = 1200
_WINDOW_H = 700


def _to_uint8(frame: np.ndarray) -> np.ndarray:
    arr = np.asarray(frame, dtype=np.float32)
    p1 = float(np.percentile(arr, 1))
    p99 = float(np.percentile(arr, 99))
    return normalize_visual_frame(arr, p1=p1, p99=p99)


class AutoDetectWindow:
    def __init__(self, app: Any) -> None:
        self.app = app
        self._roi_mask: np.ndarray | None = None
        self._roi_points: list | None = None
        self._roi_polygons: list | None = None
        self._n_grid: int = 40
        self._params: dict = dict(_detector.PRESET)

        self._cached_traces: np.ndarray | None = None
        self._cached_frame_indices: np.ndarray | None = None
        self._cached_detrended: np.ndarray | None = None
        self._cached_raw_candidates: list[dict] | None = None
        self._aggregated_trace: np.ndarray | None = None

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

        self._run_generation: int = 0
        self._param_history: list[dict] = []
        self._param_history_idx: int = -1
        self._push_history()

        self._load_project_roi()

    def open(self) -> None:
        popup = tk.Toplevel(self.app.root)
        popup.title("Auto-detect SDs - Scientific Workbench")
        popup.geometry(f"{_WINDOW_W}x{_WINDOW_H}")
        popup.minsize(1000, 600)
        popup.transient(self.app.root)
        apply_theme(popup)
        popup.protocol("WM_DELETE_WINDOW", self._on_close)
        self._popup = popup
        self._closed = False

        container = ttk.Frame(popup, style="AppSurface.TFrame")
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=0, minsize=300)
        container.columnconfigure(1, weight=1)
        container.columnconfigure(2, weight=0, minsize=320)
        container.rowconfigure(0, weight=1)

        self._build_left_pane(container)
        self._build_center_pane(container)
        self._build_right_pane(container)

        self._update_setup_labels()
        self._update_roi_status()
        self._render_viewer_frame(0)

        popup.grab_set()
        popup.focus_set()

    def _build_left_pane(self, parent: ttk.Frame) -> None:
        left = ttk.Frame(parent, padding=SPACING.outer, style="AppSidebar.TFrame")
        left.grid(row=0, column=0, sticky="nsew")

        ttk.Label(left, text="Region of Interest", style="AppSidebarTitle.TLabel").pack(anchor="w", pady=(0, SPACING.inner))
        self._roi_status_var = tk.StringVar(value="No ROI — using full frame")
        ttk.Label(left, textvariable=self._roi_status_var, style="AppMeta.TLabel").pack(anchor="w", pady=(0, SPACING.inner))
        
        btn_row = ttk.Frame(left, style="AppSidebar.TFrame")
        btn_row.pack(fill="x", pady=(0, SPACING.outer))
        ttk.Button(btn_row, text="Draw ROI", command=self._on_draw_roi, **semantic_button_options("secondary")).pack(side="left", padx=(0, SPACING.gap))
        ttk.Button(btn_row, text="Clear ROI", command=self._on_clear_roi, **semantic_button_options("secondary")).pack(side="left")

        ttk.Separator(left, orient="horizontal").pack(fill="x", pady=(SPACING.inner, SPACING.inner))
        self._grid_label_var = tk.StringVar(value=f"Grid density  ({self._n_grid}×{self._n_grid} cells)")
        ttk.Label(left, textvariable=self._grid_label_var, style="AppMeta.TLabel").pack(anchor="w")
        self._grid_var = tk.DoubleVar(value=self._n_grid)
        self._grid_scale = ttk.Scale(left, from_=10, to=80, orient="horizontal", variable=self._grid_var, style="AppFlat.Horizontal.TScale")
        self._grid_scale.configure(command=self._on_grid_change)
        self._grid_scale.pack(fill="x", pady=(SPACING.gap, SPACING.outer))

        ttk.Separator(left, orient="horizontal").pack(fill="x", pady=(SPACING.inner, SPACING.inner))
        ttk.Label(left, text="Detection Algorithms", style="AppSidebarTitle.TLabel").pack(anchor="w", pady=(0, SPACING.inner))

        self._sens_label_var = tk.StringVar()
        self._sens_scale, self._sens_var = self._add_slider(left, self._sens_label_var, 0.0, 1.0, self._k_mad_to_sens(float(self._params["diff_k_mad"])), self._on_sens_change)

        self._part_label_var = tk.StringVar()
        self._part_scale, self._part_var = self._add_slider(left, self._part_label_var, 0.01, 0.20, float(self._params["peak_height_fraction"]), self._on_part_change)

        self._coh_label_var = tk.StringVar()
        self._coh_scale, self._coh_var = self._add_slider(left, self._coh_label_var, 0.0, 1.00, float(self._params["coherence_threshold"]), self._on_coh_change)

        self._split_var = tk.BooleanVar(value=bool(self._params["split_broad_windows"]))
        ttk.Checkbutton(left, text="Split compound events", variable=self._split_var, command=self._on_split_change).pack(anchor="w", pady=(SPACING.inner, SPACING.outer))

        history_row = ttk.Frame(left, style="AppSidebar.TFrame")
        history_row.pack(fill="x", pady=(0, SPACING.inner))
        self._undo_btn = ttk.Button(history_row, text="⟲ Undo", command=self._on_undo, width=8, **semantic_button_options("secondary"))
        self._undo_btn.pack(side="left", padx=(0, SPACING.gap))
        self._redo_btn = ttk.Button(history_row, text="⟳ Redo", command=self._on_redo, width=8, **semantic_button_options("secondary"))
        self._redo_btn.pack(side="left", padx=(0, SPACING.gap))
        ttk.Button(history_row, text="Reset", command=self._on_reset_defaults, width=8, **semantic_button_options("secondary")).pack(side="left")

        action_btns = ttk.Frame(left, style="AppSidebar.TFrame")
        action_btns.pack(fill="x", pady=(SPACING.inner, SPACING.gap))
        
        self._run_btn = ttk.Button(action_btns, text="Run Detection", command=self._on_run, **semantic_button_options("primary"))
        self._run_btn.pack(side="left", expand=True, fill="x", padx=(0, SPACING.gap))
        self._cancel_btn = ttk.Button(action_btns, text="Cancel Run", command=self._on_cancel_run, **semantic_button_options("secondary"), state="disabled")
        self._cancel_btn.pack(side="left", expand=True, fill="x")

        self._setup_status_var = tk.StringVar(value="")
        ttk.Label(left, textvariable=self._setup_status_var, style="AppMeta.TLabel", wraplength=240).pack(anchor="w", pady=(0, 0))

    def _on_reset_defaults(self) -> None:
        self._params = dict(_detector.PRESET)
        self._n_grid = 40
        self._grid_var.set(self._n_grid)
        self._sens_var.set(self._k_mad_to_sens(float(self._params["diff_k_mad"])))
        self._part_var.set(float(self._params["peak_height_fraction"]))
        self._coh_var.set(float(self._params["coherence_threshold"]))
        self._split_var.set(bool(self._params["split_broad_windows"]))
        self._grid_label_var.set(f"Grid density  ({self._n_grid}×{self._n_grid} cells)")
        self._update_setup_labels()
        self._dirty_traces = True
        self._dirty_find = True
        self._dirty_gate = True
        self._push_history()
        self._on_run()

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
            self._on_run(push_history=False)

    def _on_redo(self) -> None:
        if self._param_history_idx < len(self._param_history) - 1:
            self._param_history_idx += 1
            self._apply_history_state(self._param_history[self._param_history_idx])
            self._on_run(push_history=False)

    def _apply_history_state(self, state: dict) -> None:
        self._params = dict(state["params"])
        self._n_grid = int(state["n_grid"])
        self._grid_var.set(self._n_grid)
        self._sens_var.set(self._k_mad_to_sens(float(self._params["diff_k_mad"])))
        self._part_var.set(float(self._params["peak_height_fraction"]))
        self._coh_var.set(float(self._params["coherence_threshold"]))
        self._split_var.set(bool(self._params["split_broad_windows"]))
        self._grid_label_var.set(f"Grid density  ({self._n_grid}×{self._n_grid} cells)")
        self._update_setup_labels()
        self._dirty_traces = True
        self._dirty_find = True
        self._dirty_gate = True
        self._update_history_buttons()

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

    def _build_center_pane(self, parent: ttk.Frame) -> None:
        center = ttk.Frame(parent, padding=SPACING.outer, style="AppSurface.TFrame")
        center.grid(row=0, column=1, sticky="nsew")
        center.rowconfigure(0, weight=1)
        center.columnconfigure(0, weight=1)

        canvas_frame = ttk.Frame(center, style="AppInset.TFrame")
        canvas_frame.grid(row=0, column=0, sticky="nsew")
        
        self._viewer_canvas = tk.Canvas(canvas_frame, bg="#1a1a1a", highlightthickness=0)
        self._viewer_canvas.pack(fill="both", expand=True)
        self._viewer_canvas.bind("<Configure>", lambda e: self._render_viewer_frame(self._current_frame))

        badge_frame = ttk.Frame(canvas_frame, style="AppOverlay.TFrame", padding=(4, 2))
        badge_frame.place(relx=0.02, rely=0.02, anchor="nw")
        ttk.Label(badge_frame, text="Display: 1-99% Stretch | Detection: Raw Float", style="AppSurfaceMicro.TLabel").pack()

        scrub_frame = ttk.Frame(center, style="AppSurface.TFrame")
        scrub_frame.grid(row=1, column=0, sticky="ew", pady=(SPACING.inner, 0))
        
        nav_row = ttk.Frame(scrub_frame, style="AppSurface.TFrame")
        nav_row.pack(fill="x", pady=(0, 2))
        self._viewer_frame_label_var = tk.StringVar(value="Frame 0")
        ttk.Label(nav_row, textvariable=self._viewer_frame_label_var, style="AppMeta.TLabel").pack(side="left")
        ttk.Button(nav_row, text=">", command=lambda: self._on_step_frame(1), width=2, **semantic_button_options("secondary")).pack(side="right")
        ttk.Button(nav_row, text="<", command=lambda: self._on_step_frame(-1), width=2, **semantic_button_options("secondary")).pack(side="right", padx=(0, 2))
        
        self._trace_canvas = tk.Canvas(scrub_frame, height=80, bg="#141517", highlightthickness=0)
        self._trace_canvas.pack(fill="x", pady=(2, 0))
        self._trace_canvas.bind("<Configure>", lambda e: self._render_trace())
        self._trace_canvas.bind("<Motion>", self._on_trace_motion)
        self._trace_canvas.bind("<Button-1>", self._on_trace_click)
        self._trace_canvas.bind("<B1-Motion>", self._on_trace_drag)
        self._trace_canvas.bind("<ButtonRelease-1>", self._on_trace_release)

    def _build_right_pane(self, parent: ttk.Frame) -> None:
        right = ttk.Frame(parent, padding=SPACING.outer, style="AppSurface.TFrame")
        right.grid(row=0, column=2, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        ttk.Label(right, text="Detected Candidates", style="AppSidebarTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0, SPACING.inner))

        tree_frame = ttk.Frame(right, style="AppInset.TFrame")
        tree_frame.grid(row=1, column=0, sticky="nsew")
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        cols = ("start", "end", "duration", "coherence")
        self._tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=8, selectmode="browse")
        self._tree.heading("start", text="Start")
        self._tree.heading("end", text="End")
        self._tree.heading("duration", text="Dur.")
        self._tree.heading("coherence", text="Coherence")
        for c in cols:
            self._tree.column(c, width=70, anchor="center")
        self._tree.grid(row=0, column=0, sticky="nsew")

        tree_sb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=tree_sb.set)
        tree_sb.grid(row=0, column=1, sticky="ns")
        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        bounds_row = ttk.Frame(right, style="AppSurface.TFrame")
        bounds_row.grid(row=2, column=0, sticky="ew", pady=(SPACING.inner, 0))
        ttk.Label(bounds_row, text="Start:", style="AppMeta.TLabel").pack(side="left")
        self._start_entry = ttk.Entry(bounds_row, width=6, style="AppCompact.TEntry")
        self._start_entry.pack(side="left", padx=(2, SPACING.gap))
        ttk.Label(bounds_row, text="End:", style="AppMeta.TLabel").pack(side="left")
        self._end_entry = ttk.Entry(bounds_row, width=6, style="AppCompact.TEntry")
        self._end_entry.pack(side="left", padx=(2, SPACING.gap))
        self._start_entry.bind("<FocusOut>", lambda e: self._on_update_bounds())
        self._start_entry.bind("<Return>", lambda e: self._on_update_bounds())
        self._end_entry.bind("<FocusOut>", lambda e: self._on_update_bounds())
        self._end_entry.bind("<Return>", lambda e: self._on_update_bounds())

        action_row = ttk.Frame(right, style="AppSurface.TFrame")
        action_row.grid(row=3, column=0, sticky="ew", pady=(SPACING.outer, 0))
        ttk.Button(action_row, text="Delete Event", command=self._on_delete, **semantic_button_options("danger")).pack(side="left", expand=True, fill="x", padx=(0, SPACING.gap))
        ttk.Button(action_row, text="Accept Event", command=self._on_accept_one, **semantic_button_options("secondary")).pack(side="left", expand=True, fill="x")

        ttk.Separator(right, orient="horizontal").grid(row=4, column=0, sticky="ew", pady=(SPACING.outer, SPACING.inner))

        ttk.Button(right, text="Commit & Proceed", command=self._on_accept_all, **semantic_button_options("primary")).grid(row=5, column=0, sticky="ew", pady=(0, SPACING.inner))
        ttk.Button(right, text="Cancel", command=self._on_close, **semantic_button_options("secondary")).grid(row=6, column=0, sticky="ew")

    def _add_slider(self, parent: ttk.Frame, label_var: tk.StringVar, from_: float, to: float, init: float, command) -> tuple[ttk.Scale, tk.DoubleVar]:
        ttk.Label(parent, textvariable=label_var, style="AppMeta.TLabel").pack(anchor="w", pady=(SPACING.inner, 0))
        var = tk.DoubleVar(value=init)
        scale = ttk.Scale(parent, from_=from_, to=to, orient="horizontal", variable=var, style="AppFlat.Horizontal.TScale")
        scale.configure(command=command)
        scale.pack(fill="x", pady=(0, 2))
        return scale, var

    def _on_draw_roi(self) -> None:
        from sdapp.analysis.ui.roi_dialog import open_roi_dialog
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
        self._dirty_traces = True
        self._update_roi_status()

    def _on_clear_roi(self) -> None:
        self._roi_mask = None
        self._roi_points = None
        self._roi_polygons = None
        self._dirty_traces = True
        self._update_roi_status()
        self._render_viewer_frame(self._current_frame)

    def _on_grid_change(self, _val: str) -> None:
        raw = float(self._grid_var.get())
        n = max(10, min(80, int(round(raw / 10.0)) * 10))
        if n != self._n_grid:
            self._n_grid = n
            self._dirty_traces = True
            self._grid_label_var.set(f"Grid density  ({n}×{n} cells)")
            self._render_viewer_frame(self._current_frame)
            self._on_run()

    def _on_sens_change(self, _val: str) -> None:
        sens = float(self._sens_var.get())
        k_mad = self._sens_to_k_mad(sens)
        if abs(k_mad - self._params["diff_k_mad"]) > 0.05:
            self._params["diff_k_mad"] = k_mad
            self._dirty_find = True
            self._update_setup_labels()
            self._on_run()

    def _on_part_change(self, _val: str) -> None:
        v = float(self._part_var.get())
        if abs(v - self._params["peak_height_fraction"]) > 0.01:
            self._params["peak_height_fraction"] = v
            self._dirty_find = True
            self._update_setup_labels()
            self._on_run()

    def _on_coh_change(self, _val: str) -> None:
        v = float(self._coh_var.get())
        if abs(v - self._params["coherence_threshold"]) > 0.01:
            self._params["coherence_threshold"] = v
            self._dirty_gate = True
            self._update_setup_labels()
            self._on_run()

    def _on_split_change(self) -> None:
        self._params["split_broad_windows"] = bool(self._split_var.get())
        self._dirty_find = True
        self._on_run()

    def _on_run(self, push_history: bool = True) -> None:
        if not self._is_open():
            return
        if push_history:
            self._push_history()

        self._run_generation += 1
        gen = self._run_generation
        
        self._setup_status_var.set("Running detection...")
        self._trace_canvas.itemconfig("scrubber", fill="#aeb7bf") # Muted while running
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
            return raw_traces, frame_indices, detrended, raw_cands, accepted, agg

        def on_done(result):
            if generation != self._run_generation: return
            raw_traces, frame_indices, detrended, raw_cands, accepted, agg = result
            self._cached_traces = raw_traces
            self._cached_frame_indices = frame_indices
            self._cached_detrended = detrended
            self._cached_raw_candidates = raw_cands
            self._review_candidates = accepted
            self._aggregated_trace = agg
            self._dirty_traces = False
            self._dirty_find = False
            self._dirty_gate = False
            self._finalize_run(generation)

        self._task_runner.start(target=worker, on_success=on_done, on_error=lambda e: self._on_run_error(e, generation), key="auto_detect")

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
            self._dirty_find = False
            self._dirty_gate = False
            self._finalize_run(generation)

        self._task_runner.start(target=worker, on_success=on_done, on_error=lambda e: self._on_run_error(e, generation), key="auto_detect")

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
            self._dirty_gate = False
            self._finalize_run(generation)

        self._task_runner.start(target=worker, on_success=on_done, on_error=lambda e: self._on_run_error(e, generation), key="auto_detect")

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
        self._render_viewer_frame(peak)
        self._render_trace()

    def _on_step_frame(self, step: int) -> None:
        fc = int(self.app.stack_info.frame_count)
        self._current_frame = max(0, min(fc - 1, self._current_frame + step))
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

        pil = Image.fromarray(img_u8).convert("RGB").resize((dw, dh), Image.LANCZOS)
        canvas_pil = Image.new("RGB", (cw, ch), (26, 26, 26))
        ox, oy = (cw - dw) // 2, (ch - dh) // 2
        canvas_pil.paste(pil, (ox, oy))

        grid_overlay = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        draw = ImageDraw.Draw(grid_overlay)

        n = self._n_grid
        for i in range(1, n):
            x = ox + int(dw * i / n)
            draw.line([(x, oy), (x, oy + dh)], fill=(255, 255, 255, 100), width=1)
        for i in range(1, n):
            y = oy + int(dh * i / n)
            draw.line([(ox, y), (ox + dw, y)], fill=(255, 255, 255, 100), width=1)

        if self._roi_mask is not None:
            try:
                roi_small = Image.fromarray(self._roi_mask.astype(np.uint8) * 255).resize((dw, dh), Image.NEAREST)
                roi_mask_img = Image.new("L", (cw, ch), 0)
                roi_mask_img.paste(roi_small, (ox, oy))
                
                empty = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
                grid_overlay = Image.composite(grid_overlay, empty, Image.fromarray(255 - np.array(roi_mask_img)))
            except Exception: pass

        return Image.alpha_composite(canvas_pil.convert("RGBA"), grid_overlay).convert("RGB")

    def _render_trace(self) -> None:
        self._trace_canvas.delete("all")
        cw = max(1, self._trace_canvas.winfo_width())
        ch = max(1, self._trace_canvas.winfo_height())
        if cw <= 1: return
        fc = int(self.app.stack_info.frame_count)
        if fc <= 1: return

        # Draw global trace if available
        if self._aggregated_trace is not None and len(self._aggregated_trace) == fc:
            tr = self._aggregated_trace
            t_min, t_max = np.min(tr), np.max(tr)
            rng = max(1e-9, t_max - t_min)
            pts = []
            for i in range(fc):
                x = int((i / (fc - 1)) * cw)
                y = int(ch - 5 - ((tr[i] - t_min) / rng) * (ch - 10))
                pts.extend([x, y])
            self._trace_canvas.create_line(pts, fill="#8d97a2", width=1, smooth=True)

        # Draw bounds of all candidates
        for idx, cand in enumerate(self._review_candidates):
            s = int(cand["start_frame"])
            e = int(cand["end_frame"])
            x0 = (s / (fc - 1)) * cw
            x1 = (e / (fc - 1)) * cw
            color = "#1b75bc" if idx == self._current_idx else "#313842"
            self._trace_canvas.create_rectangle(x0, ch - 8, x1, ch, fill=color, outline="")

        # Draw current frame scrubber
        cx = (self._current_frame / (fc - 1)) * cw
        self._trace_canvas.create_line(cx, 0, cx, ch, fill="#edf1f3", width=2, tags="scrubber")

        # Handles if a candidate is selected
        idx = self._selected_candidate_idx()
        if idx is not None:
            cand = self._review_candidates[idx]
            s, e = int(cand["start_frame"]), int(cand["end_frame"])
            x0 = (s / (fc - 1)) * cw
            x1 = (e / (fc - 1)) * cw
            # Draw semi-transparent overlay over the whole event in trace
            self._trace_canvas.create_rectangle(x0, 0, x1, ch, fill="#1b75bc", stipple="gray25", outline="")
            # Handles
            h_color = "#fff" if self._trace_hover == "start" else "#aeb7bf"
            self._trace_canvas.create_rectangle(x0 - 3, 0, x0 + 3, ch, fill=h_color, outline="", tags="handle_start")
            h_color = "#fff" if self._trace_hover == "end" else "#aeb7bf"
            self._trace_canvas.create_rectangle(x1 - 3, 0, x1 + 3, ch, fill=h_color, outline="", tags="handle_end")

        self._trace_canvas.tag_raise("scrubber")
        self._trace_canvas.tag_raise("handle_start")
        self._trace_canvas.tag_raise("handle_end")

    def _frame_from_x(self, x: float) -> int:
        cw = max(1, self._trace_canvas.winfo_width())
        fc = int(self.app.stack_info.frame_count)
        return int(max(0, min(fc - 1, round((x / cw) * (fc - 1)))))

    def _x_from_frame(self, frame: int) -> float:
        cw = max(1, self._trace_canvas.winfo_width())
        fc = int(self.app.stack_info.frame_count)
        return (frame / (fc - 1)) * cw

    def _on_trace_motion(self, event) -> None:
        idx = self._selected_candidate_idx()
        if idx is None:
            self._trace_canvas.config(cursor="")
            return
        cand = self._review_candidates[idx]
        x0 = self._x_from_frame(int(cand["start_frame"]))
        x1 = self._x_from_frame(int(cand["end_frame"]))
        
        hover = None
        if abs(event.x - x0) < 5: hover = "start"
        elif abs(event.x - x1) < 5: hover = "end"

        if hover != self._trace_hover:
            self._trace_hover = hover
            self._render_trace()
            self._trace_canvas.config(cursor="sb_h_double_arrow" if hover else "hand2")

    def _on_trace_click(self, event) -> None:
        if self._trace_hover:
            self._trace_dragging = self._trace_hover
        else:
            self._current_frame = self._frame_from_x(event.x)
            self._render_viewer_frame(self._current_frame)
            self._render_trace()

    def _on_trace_drag(self, event) -> None:
        if self._trace_dragging:
            idx = self._selected_candidate_idx()
            if idx is not None:
                cand = self._review_candidates[idx]
                f = self._frame_from_x(event.x)
                if self._trace_dragging == "start":
                    cand["start_frame"] = min(f, int(cand["end_frame"]))
                else:
                    cand["end_frame"] = max(f, int(cand["start_frame"]))
                self._refresh_tree_row(idx)
                self._render_trace()
        else:
            self._current_frame = self._frame_from_x(event.x)
            self._render_viewer_frame(self._current_frame)
            self._render_trace()

    def _on_trace_release(self, event) -> None:
        if self._trace_dragging:
            idx = self._selected_candidate_idx()
            if idx is not None:
                cand = self._review_candidates[idx]
                self._start_entry.delete(0, "end")
                self._start_entry.insert(0, str(cand["start_frame"]))
                self._end_entry.delete(0, "end")
                self._end_entry.insert(0, str(cand["end_frame"]))
            self._trace_dragging = None

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
                self._popup.grab_release()
                self._popup.destroy()
            except Exception: pass
        self._popup = None

    def _is_open(self) -> bool:
        return not self._closed and self._popup is not None and self._popup.winfo_exists()

    def _show_review_phase(self) -> None:
        self._finalize_run(self._run_generation)

    @property
    def _task_runner(self) -> BackgroundTaskRunner:
        if self._runner is None: self._runner = BackgroundTaskRunner(self.app.root)
        return self._runner


def _find_with_params(detrended: np.ndarray, frame_indices: np.ndarray, params: dict) -> list[dict]:
    return _detector.find_candidates(detrended, frame_indices, diff_k_mad=float(params["diff_k_mad"]), peak_height_fraction=float(params["peak_height_fraction"]), split_broad_windows=bool(params["split_broad_windows"]))

def _gate_with_params(candidates: list[dict], detrended: np.ndarray, frame_indices: np.ndarray, params: dict) -> list[dict]:
    return _detector.apply_coherence_gate(candidates, detrended, frame_indices, active_threshold_mad=float(params.get("coherence_active_threshold_mad", 10.0)), coherence_threshold=float(params.get("coherence_threshold", 0.8257435331730181)), quiet_pre_frames=int(params.get("quiet_pre_frames", 200)))
