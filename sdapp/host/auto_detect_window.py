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
from sdapp.shared.ui.theme import CANVAS_BACKGROUND, SPACING, apply_theme

# Colors drawn directly onto tk.Canvas — must stay in sync with theme.py palette.
_C_ACCENT      = "#1b75bc"
_C_BORDER      = "#2a3139"
_C_CONTROL     = "#313842"
_C_TEXT        = "#edf1f3"
_C_MUTED       = "#8d97a2"
_C_MUTED_SOFT  = "#aeb7bf"

from .sd_detection import detector as _detector
from .sd_detection import grid as _grid
from .sd_detection import traces as _traces

_WINDOW_W = 1200
_WINDOW_H = 700
_ALGORITHM_RERUN_DEBOUNCE_MS = 350


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
        self._push_history()

        self._load_project_roi()

    def open(self) -> None:
        popup = tk.Toplevel(self.app.root)
        popup.title("Auto-detect SDs - Scientific Workbench")
        popup.geometry(f"{_WINDOW_W}x{_WINDOW_H}")
        popup.minsize(1000, 600)
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

        popup.after(0, lambda: (popup.lift(), popup.focus_force()))

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
        self._grid_scale.pack(fill="x", pady=(SPACING.gap, SPACING.inner))

        self._grid_opacity_label_var = tk.StringVar(value=f"Grid opacity  ({int(round(self._grid_opacity * 100))}%)")
        ttk.Label(left, textvariable=self._grid_opacity_label_var, style="AppMeta.TLabel").pack(anchor="w")
        self._grid_opacity_var = tk.DoubleVar(value=self._grid_opacity)
        self._grid_opacity_scale = ttk.Scale(left, from_=0.0, to=1.0, orient="horizontal", variable=self._grid_opacity_var, style="AppFlat.Horizontal.TScale")
        self._grid_opacity_scale.configure(command=self._on_grid_opacity_change)
        self._grid_opacity_scale.pack(fill="x", pady=(SPACING.gap, SPACING.inner))

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
        self._grid_opacity = 0.45
        self._grid_var.set(self._n_grid)
        self._grid_opacity_var.set(self._grid_opacity)
        self._sens_var.set(self._k_mad_to_sens(float(self._params["diff_k_mad"])))
        self._part_var.set(float(self._params["peak_height_fraction"]))
        self._coh_var.set(float(self._params["coherence_threshold"]))
        self._split_var.set(bool(self._params["split_broad_windows"]))
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

        self._overview_canvas = tk.Canvas(scrub_frame, height=28, bg=CANVAS_BACKGROUND, highlightthickness=0)
        self._overview_canvas.pack(fill="x", pady=(2, 0))
        self._overview_canvas.bind("<Configure>", lambda e: self._render_overview())
        self._overview_canvas.bind("<Button-1>", lambda e: self._on_overview_click(e))
        self._overview_canvas.bind("<B1-Motion>", lambda e: self._on_overview_drag(e))
        self._overview_canvas.bind("<ButtonRelease-1>", lambda e: self._on_overview_release(e))

        self._detail_canvas = tk.Canvas(scrub_frame, height=60, bg=CANVAS_BACKGROUND, highlightthickness=0)
        self._detail_canvas.pack(fill="x", pady=(2, 0))
        self._detail_canvas.bind("<Configure>", lambda e: self._render_detail())
        self._detail_canvas.bind("<Motion>", lambda e: self._on_detail_motion(e))
        self._detail_canvas.bind("<Button-1>", lambda e: self._on_detail_click(e))
        self._detail_canvas.bind("<B1-Motion>", lambda e: self._on_detail_drag(e))
        self._detail_canvas.bind("<ButtonRelease-1>", lambda e: self._on_detail_release(e))
        self._detail_canvas.bind("<MouseWheel>", lambda e: self._on_detail_wheel(e))
        self._detail_canvas.bind("<Button-4>", lambda e: self._on_detail_wheel_linux(e, +1))
        self._detail_canvas.bind("<Button-5>", lambda e: self._on_detail_wheel_linux(e, -1))

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

        minor_alpha = int(round(96 * self._grid_opacity))
        major_alpha = int(round(150 * self._grid_opacity))
        grid_bounds = self._grid_bounds_for_layout((cw, ch, dw, dh, ox, oy))
        if grid_bounds is not None:
            grid_x, grid_y, grid_w, grid_h = grid_bounds
            n = self._n_grid
            for i in range(1, n):
                x = grid_x + int(grid_w * i / n)
                alpha = major_alpha if i % 5 == 0 else minor_alpha
                draw.line([(x, grid_y), (x, grid_y + grid_h)], fill=(125, 175, 215, alpha), width=1)
            for i in range(1, n):
                y = grid_y + int(grid_h * i / n)
                alpha = major_alpha if i % 5 == 0 else minor_alpha
                draw.line([(grid_x, y), (grid_x + grid_w, y)], fill=(125, 175, 215, alpha), width=1)

        if self._roi_mask is not None:
            try:
                roi_small = Image.fromarray(self._roi_mask.astype(np.uint8) * 255).resize((dw, dh), Image.NEAREST)
                roi_mask_img = Image.new("L", (cw, ch), 0)
                roi_mask_img.paste(roi_small, (ox, oy))
                
                empty = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
                grid_overlay = Image.composite(grid_overlay, empty, roi_mask_img)
            except Exception: pass

        self._draw_active_cell_borders(grid_overlay, selected_cand=selected_cand, frame_idx=self._current_frame, layout=(cw, ch, dw, dh, ox, oy))
        return Image.alpha_composite(canvas_pil.convert("RGBA"), grid_overlay).convert("RGB")

    def _grid_bounds_for_layout(self, layout: tuple[int, int, int, int, int, int]) -> tuple[int, int, int, int] | None:
        _cw, _ch, dw, dh, ox, oy = layout
        extraction = self._cached_grid_extraction
        if extraction is None:
            return ox, oy, dw, dh
        geometry = extraction.geometry
        resized_h, resized_w = geometry.resized_shape
        if resized_h <= 0 or resized_w <= 0:
            return None
        crop_y0, crop_y1, crop_x0, crop_x1 = geometry.crop_box
        grid_x = ox + int(round(crop_x0 * dw / resized_w))
        grid_y = oy + int(round(crop_y0 * dh / resized_h))
        grid_w = max(1, int(round((crop_x1 - crop_x0) * dw / resized_w)))
        grid_h = max(1, int(round((crop_y1 - crop_y0) * dh / resized_h)))
        return grid_x, grid_y, grid_w, grid_h

    def _clear_active_cell_overlay_cache(self) -> None:
        self._active_cell_cache.clear()
        self._cell_border_cache_key = None
        self._cell_border_rects = []

    def _active_cells_for_frame(self, selected_cand: dict | None, frame_idx: int) -> np.ndarray | None:
        idx = self._current_idx
        detrended = self._cached_detrended
        frame_indices = self._cached_frame_indices
        if selected_cand is None or idx is None or detrended is None or frame_indices is None:
            return None
        if detrended.ndim != 2 or frame_indices.ndim != 1 or detrended.shape[1] != frame_indices.size:
            return None
        try:
            start_frame = int(selected_cand["start_frame"])
            end_frame = int(selected_cand["end_frame"])
        except Exception:
            return None

        frame_pos = self._frame_index_position(frame_indices, int(frame_idx))
        start_idx = self._frame_index_position(frame_indices, start_frame)
        end_idx = self._frame_index_position(frame_indices, end_frame)
        if frame_pos is None or start_idx is None or end_idx is None:
            return None
        if end_idx < start_idx:
            start_idx, end_idx = end_idx, start_idx
        if frame_pos < start_idx or frame_pos > end_idx:
            return None

        active_threshold = float(self._params.get("coherence_active_threshold_mad", 10.0))
        quiet_pre_frames = int(self._params.get("quiet_pre_frames", 200))
        cache_key = ("combined", int(idx), start_idx, end_idx, active_threshold, quiet_pre_frames, float(self._params.get("diff_k_mad", 2.5)), id(detrended), id(frame_indices))
        cached = self._active_cell_cache.get(cache_key)
        if cached is None:
            mad = _detector.quiet_mad(detrended, start_idx, quiet_pre_frames=quiet_pre_frames)
            norm = detrended[:, start_idx : end_idx + 1] / mad[:, np.newaxis]
            participation_window = norm > active_threshold
            onset_window = self._onset_active_window(detrended, start_idx, end_idx)
            active_window = participation_window | onset_window
            cached = (start_idx, end_idx, active_window)
            self._active_cell_cache[cache_key] = cached
        cached_start, cached_end, active_window = cached
        if frame_pos < cached_start or frame_pos > cached_end:
            return None
        return np.asarray(active_window[:, frame_pos - cached_start], dtype=bool)

    def _onset_active_window(self, detrended: np.ndarray, start_idx: int, end_idx: int) -> np.ndarray:
        window_len = max(0, int(end_idx) - int(start_idx) + 1)
        if window_len <= 0:
            return np.zeros((int(detrended.shape[0]), 0), dtype=bool)
        diffs = np.diff(np.asarray(detrended), axis=1)
        if diffs.shape[1] == 0:
            return np.zeros((int(detrended.shape[0]), window_len), dtype=bool)
        diff_center = np.nanmedian(diffs, axis=1, keepdims=True)
        mads = np.nanmedian(np.abs(diffs - diff_center), axis=1)
        active_diffs = diffs > (float(self._params.get("diff_k_mad", 2.5)) * mads[:, np.newaxis])
        active_window = np.zeros((int(detrended.shape[0]), window_len), dtype=bool)
        for out_idx, frame_pos in enumerate(range(int(start_idx), int(end_idx) + 1)):
            diff_idx = frame_pos - 1
            if 0 <= diff_idx < active_diffs.shape[1]:
                active_window[:, out_idx] = active_diffs[:, diff_idx]
        return active_window

    @staticmethod
    def _frame_index_position(frame_indices: np.ndarray, frame: int) -> int | None:
        matches = np.flatnonzero(np.asarray(frame_indices) == int(frame))
        if matches.size == 0:
            return None
        return int(matches[0])

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

        grid_bounds = self._grid_bounds_for_layout(layout)
        if grid_bounds is None:
            return []
        grid_x, grid_y, grid_w, grid_h = grid_bounds

        rects: list[tuple[int, int, int, int]] = []
        cell_row_cols = getattr(extraction, "cell_row_cols", None)
        if isinstance(cell_row_cols, list) and len(cell_row_cols) == len(extraction.cell_masks):
            n = self._n_grid
            for row, col in cell_row_cols:
                row_i = int(row)
                col_i = int(col)
                x0 = grid_x + int(grid_w * col_i / n)
                x1 = grid_x + int(grid_w * (col_i + 1) / n)
                y0 = grid_y + int(grid_h * row_i / n)
                y1 = grid_y + int(grid_h * (row_i + 1) / n)
                rects.append((x0, y0, max(x0, x1 - 1), max(y0, y1 - 1)))
        else:
            for cell_mask in extraction.cell_masks:
                mask = np.asarray(cell_mask, dtype=bool)
                if mask.ndim != 2 or not np.any(mask):
                    rects.append((grid_x, grid_y, grid_x, grid_y))
                    continue
                rows, cols = np.where(mask)
                r0, r1 = int(rows.min()), int(rows.max()) + 1
                c0, c1 = int(cols.min()), int(cols.max()) + 1
                mask_h, mask_w = mask.shape
                x0 = grid_x + int(np.floor(c0 * grid_w / max(1, mask_w)))
                x1 = grid_x + int(np.ceil(c1 * grid_w / max(1, mask_w)))
                y0 = grid_y + int(np.floor(r0 * grid_h / max(1, mask_h)))
                y1 = grid_y + int(np.ceil(r1 * grid_h / max(1, mask_h)))
                rects.append((x0, y0, max(x0, x1 - 1), max(y0, y1 - 1)))

        self._cell_border_cache_key = cache_key
        self._cell_border_rects = rects
        return rects

    def _render_trace(self) -> None:
        self._render_overview()
        self._render_detail()

    # ---------- Overview strip ----------

    def _render_overview(self) -> None:
        canvas = getattr(self, "_overview_canvas", None)
        if canvas is None:
            return
        cw = max(1, canvas.winfo_width())
        ch = max(1, canvas.winfo_height())
        fc = int(self.app.stack_info.frame_count)

        canvas.delete("all")
        self._overview_items.clear()
        self._candidate_bar_overview.clear()
        if cw <= 1 or fc <= 1:
            return

        # Candidate bars (slim, bottom 4px)
        for idx, cand in enumerate(self._review_candidates):
            s = int(cand["start_frame"])
            e = int(cand["end_frame"])
            x0 = (s / (fc - 1)) * cw
            x1 = (e / (fc - 1)) * cw
            color = _C_ACCENT if idx == self._current_idx else _C_BORDER
            bar = canvas.create_rectangle(x0, ch - 4, max(x1, x0 + 1), ch, fill=color, outline="")
            self._candidate_bar_overview.append(bar)

        # Viewport rect showing the detail window's coverage
        win_start, win_end = self._detail_window_bounds()
        vx0 = (win_start / (fc - 1)) * cw
        vx1 = (win_end / (fc - 1)) * cw
        self._overview_items["viewport"] = canvas.create_rectangle(
            vx0, 0, max(vx1, vx0 + 1), ch, outline=_C_BORDER, fill=_C_BORDER, stipple="gray25", width=1
        )

        # Playhead
        cx = (self._current_frame / (fc - 1)) * cw
        self._overview_items["scrubber"] = canvas.create_line(
            cx, 0, cx, ch, fill=_C_TEXT, width=1, tags="scrubber"
        )

    def _update_overview_dynamic(self) -> None:
        """Move playhead + viewport rect on the overview without rebuilding."""
        canvas = getattr(self, "_overview_canvas", None)
        if canvas is None:
            return
        cw = max(1, canvas.winfo_width())
        ch = max(1, canvas.winfo_height())
        fc = int(self.app.stack_info.frame_count)
        if cw <= 1 or fc <= 1:
            return
        cx = (self._current_frame / (fc - 1)) * cw
        if "scrubber" in self._overview_items:
            canvas.coords(self._overview_items["scrubber"], cx, 0, cx, ch)
        win_start, win_end = self._detail_window_bounds()
        vx0 = (win_start / (fc - 1)) * cw
        vx1 = (win_end / (fc - 1)) * cw
        if "viewport" in self._overview_items:
            canvas.coords(self._overview_items["viewport"], vx0, 0, max(vx1, vx0 + 1), ch)

    # ---------- Detail strip ----------

    def _detail_window_bounds(self) -> tuple[int, int]:
        fc = int(self.app.stack_info.frame_count)
        if fc <= 1:
            return 0, 0
        half = max(1, int(self._detail_half_width))
        center = int(self._detail_center_frame)
        start = max(0, center - half)
        end = min(fc - 1, center + half)
        if end - start < 1:
            end = min(fc - 1, start + 1)
            start = max(0, end - 1)
        return start, end

    def _render_detail(self) -> None:
        canvas = getattr(self, "_detail_canvas", None)
        if canvas is None:
            return
        cw = max(1, canvas.winfo_width())
        ch = max(1, canvas.winfo_height())
        fc = int(self.app.stack_info.frame_count)

        canvas.delete("all")
        self._detail_items.clear()
        self._candidate_bar_detail.clear()
        if cw <= 1 or fc <= 1:
            return

        win_start, win_end = self._detail_window_bounds()
        win_span = max(1, win_end - win_start)

        def _x(frame: float) -> float:
            return (float(frame) - win_start) / win_span * cw

        # Candidate bars within window
        for idx, cand in enumerate(self._review_candidates):
            s = int(cand["start_frame"])
            e = int(cand["end_frame"])
            if e < win_start or s > win_end:
                continue
            cs = max(s, win_start)
            ce = min(e, win_end)
            x0 = _x(cs)
            x1 = _x(ce)
            color = _C_ACCENT if idx == self._current_idx else _C_BORDER
            bar = canvas.create_rectangle(x0, ch - 10, max(x1, x0 + 1), ch - 2, fill=color, outline="")
            self._candidate_bar_detail.append(bar)

        # Selected candidate translucent overlay + handles
        sel_idx = self._selected_candidate_idx()
        if sel_idx is not None:
            cand = self._review_candidates[sel_idx]
            s, e = int(cand["start_frame"]), int(cand["end_frame"])
            if e >= win_start and s <= win_end:
                cs = max(s, win_start)
                ce = min(e, win_end)
                ox0 = _x(cs)
                ox1 = _x(ce)
                self._detail_items["overlay"] = canvas.create_rectangle(
                    ox0, 0, max(ox1, ox0 + 1), ch, fill=_C_ACCENT, stipple="gray25", outline=""
                )
            if win_start <= s <= win_end:
                hx = _x(s)
                h_color = _C_TEXT if self._trace_hover == "start" else _C_MUTED_SOFT
                self._detail_items["handle_start"] = canvas.create_rectangle(
                    hx - 3, 0, hx + 3, ch, fill=h_color, outline="", tags="handle_start"
                )
            if win_start <= e <= win_end:
                hx = _x(e)
                h_color = _C_TEXT if self._trace_hover == "end" else _C_MUTED_SOFT
                self._detail_items["handle_end"] = canvas.create_rectangle(
                    hx - 3, 0, hx + 3, ch, fill=h_color, outline="", tags="handle_end"
                )

        # Playhead
        if win_start <= self._current_frame <= win_end:
            cx = _x(self._current_frame)
            self._detail_items["scrubber"] = canvas.create_line(
                cx, 0, cx, ch, fill=_C_TEXT, width=1, tags="scrubber"
            )

        # Edge labels
        canvas.create_text(4, 2, anchor="nw", text=str(win_start), fill=_C_MUTED, font=("TkSmallCaptionFont",))
        canvas.create_text(cw - 4, 2, anchor="ne", text=str(win_end), fill=_C_MUTED, font=("TkSmallCaptionFont",))

    # ---------- Frame ↔ x mapping ----------

    def _frame_from_overview_x(self, x: float) -> int:
        canvas = self._overview_canvas
        cw = max(1, canvas.winfo_width())
        fc = int(self.app.stack_info.frame_count)
        if fc <= 1:
            return 0
        return int(max(0, min(fc - 1, round((x / cw) * (fc - 1)))))

    def _frame_from_detail_x(self, x: float) -> int:
        canvas = self._detail_canvas
        cw = max(1, canvas.winfo_width())
        fc = int(self.app.stack_info.frame_count)
        if fc <= 1:
            return 0
        win_start, win_end = self._detail_window_bounds()
        span = max(1, win_end - win_start)
        return int(max(win_start, min(win_end, round(win_start + (x / cw) * span))))

    def _detail_x_from_frame(self, frame: int) -> float | None:
        canvas = self._detail_canvas
        cw = max(1, canvas.winfo_width())
        win_start, win_end = self._detail_window_bounds()
        if frame < win_start or frame > win_end:
            return None
        span = max(1, win_end - win_start)
        return (float(frame) - win_start) / span * cw

    # Backward-compat shims (used elsewhere if anyone imported these)
    def _frame_from_x(self, x: float) -> int:
        return self._frame_from_overview_x(x)

    def _x_from_frame(self, frame: int) -> float:
        canvas = self._overview_canvas
        cw = max(1, canvas.winfo_width())
        fc = int(self.app.stack_info.frame_count)
        if fc <= 1:
            return 0.0
        return (frame / (fc - 1)) * cw

    # ---------- Event handlers (overview) ----------

    def _on_overview_click(self, event) -> None:
        frame = self._frame_from_overview_x(event.x)
        self._current_frame = frame
        self._detail_center_frame = frame
        self._schedule_viewer_render(frame)
        self._render_overview()
        self._render_detail()

    def _on_overview_drag(self, event) -> None:
        frame = self._frame_from_overview_x(event.x)
        self._current_frame = frame
        self._detail_center_frame = frame
        self._schedule_viewer_render(frame)
        self._update_overview_dynamic()
        self._render_detail()

    def _on_overview_release(self, _event) -> None:
        self._render_overview()

    # ---------- Event handlers (detail) ----------

    def _on_detail_motion(self, event) -> None:
        idx = self._selected_candidate_idx()
        hover = None
        if idx is not None:
            cand = self._review_candidates[idx]
            xs = self._detail_x_from_frame(int(cand["start_frame"]))
            xe = self._detail_x_from_frame(int(cand["end_frame"]))
            if xs is not None and abs(event.x - xs) < 6:
                hover = "start"
            elif xe is not None and abs(event.x - xe) < 6:
                hover = "end"

        if hover != self._trace_hover:
            self._trace_hover = hover
            self._render_detail()
            self._detail_canvas.config(cursor="sb_h_double_arrow" if hover else "")

    def _on_detail_click(self, event) -> None:
        if self._trace_hover:
            self._trace_dragging = self._trace_hover
            return
        frame = self._frame_from_detail_x(event.x)
        self._current_frame = frame
        self._schedule_viewer_render(frame)
        self._render_detail()
        self._update_overview_dynamic()

    def _on_detail_drag(self, event) -> None:
        if self._trace_dragging:
            idx = self._selected_candidate_idx()
            if idx is not None:
                cand = self._review_candidates[idx]
                f = self._frame_from_detail_x(event.x)
                if self._trace_dragging == "start":
                    cand["start_frame"] = min(f, int(cand["end_frame"]))
                else:
                    cand["end_frame"] = max(f, int(cand["start_frame"]))
                self._refresh_tree_row(idx)
                self._render_detail()
                self._render_overview()
            return
        frame = self._frame_from_detail_x(event.x)
        self._current_frame = frame
        self._schedule_viewer_render(frame)
        self._render_detail()
        self._update_overview_dynamic()

    def _on_detail_release(self, _event) -> None:
        if self._trace_dragging:
            idx = self._selected_candidate_idx()
            if idx is not None:
                cand = self._review_candidates[idx]
                self._start_entry.delete(0, "end")
                self._start_entry.insert(0, str(cand["start_frame"]))
                self._end_entry.delete(0, "end")
                self._end_entry.insert(0, str(cand["end_frame"]))
            self._trace_dragging = None
            self._render_detail()

    def _on_detail_wheel(self, event) -> None:
        # Windows / macOS deliver delta in event.delta. Negative = scroll down.
        steps = int(event.delta / 120) if abs(event.delta) >= 120 else (1 if event.delta > 0 else -1)
        self._apply_detail_wheel(steps, shift=bool(event.state & 0x0001))

    def _on_detail_wheel_linux(self, _event, direction: int) -> None:
        self._apply_detail_wheel(direction, shift=False)

    def _apply_detail_wheel(self, steps: int, *, shift: bool) -> None:
        if steps == 0:
            return
        fc = int(self.app.stack_info.frame_count)
        if fc <= 1:
            return
        if shift:
            # pan
            half = max(1, self._detail_half_width)
            self._detail_center_frame = int(max(0, min(fc - 1, self._detail_center_frame - steps * max(1, half // 4))))
        else:
            # zoom: positive = zoom in (smaller half_width)
            factor = 0.8 if steps > 0 else 1.25
            new_half = int(round(self._detail_half_width * factor))
            new_half = max(self._detail_min_half_width, min(self._detail_max_half_width, new_half))
            self._detail_half_width = new_half
        self._render_detail()
        self._update_overview_dynamic()

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
    return _detector.find_candidates(detrended, frame_indices, diff_k_mad=float(params["diff_k_mad"]), peak_height_fraction=float(params["peak_height_fraction"]), split_broad_windows=bool(params["split_broad_windows"]))

def _gate_with_params(candidates: list[dict], detrended: np.ndarray, frame_indices: np.ndarray, params: dict) -> list[dict]:
    return _detector.apply_coherence_gate(candidates, detrended, frame_indices, active_threshold_mad=float(params.get("coherence_active_threshold_mad", 10.0)), coherence_threshold=float(params.get("coherence_threshold", 0.8257435331730181)), quiet_pre_frames=int(params.get("quiet_pre_frames", 200)))
