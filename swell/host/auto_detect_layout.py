from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from swell.shared.ui.bootstrap import semantic_button_options
from swell.shared.ui.theme import CANVAS_BACKGROUND, SPACING


class AutoDetectLayoutBuilder:
    """Build AutoDetectWindow widgets while leaving behavior on the window."""

    def __init__(self, window: Any, *, polarity_labels: dict[str, str]) -> None:
        self.window = window
        self.polarity_labels = polarity_labels

    def build_left_pane(self, parent: ttk.Frame) -> None:
        w = self.window
        left = ttk.Frame(parent, padding=SPACING.outer, style="AppSidebar.TFrame")
        left.grid(row=0, column=0, sticky="nsew")

        ttk.Label(left, text="Region of Interest", style="AppSidebarTitle.TLabel").pack(anchor="w", pady=(0, SPACING.inner))
        w._roi_status_var = tk.StringVar(value="No ROI — using full frame")
        ttk.Label(left, textvariable=w._roi_status_var, style="AppMeta.TLabel").pack(anchor="w", pady=(0, SPACING.inner))

        btn_row = ttk.Frame(left, style="AppSidebar.TFrame")
        btn_row.pack(fill="x", pady=(0, SPACING.outer))
        ttk.Button(btn_row, text="Draw ROI", command=w._on_draw_roi, **semantic_button_options("secondary")).pack(side="left", padx=(0, SPACING.gap))
        ttk.Button(btn_row, text="Clear ROI", command=w._on_clear_roi, **semantic_button_options("secondary")).pack(side="left")

        ttk.Separator(left, orient="horizontal").pack(fill="x", pady=(SPACING.inner, SPACING.inner))
        w._grid_label_var = tk.StringVar(value=f"Grid density  ({w._n_grid}×{w._n_grid} cells)")
        ttk.Label(left, textvariable=w._grid_label_var, style="AppMeta.TLabel").pack(anchor="w")
        w._grid_var = tk.DoubleVar(value=w._n_grid)
        w._grid_scale = ttk.Scale(left, from_=10, to=80, orient="horizontal", variable=w._grid_var, style="AppFlat.Horizontal.TScale")
        w._grid_scale.configure(command=w._on_grid_change)
        w._grid_scale.pack(fill="x", pady=(SPACING.gap, SPACING.inner))

        w._grid_opacity_label_var = tk.StringVar(value=f"Grid opacity  ({int(round(w._grid_opacity * 100))}%)")
        ttk.Label(left, textvariable=w._grid_opacity_label_var, style="AppMeta.TLabel").pack(anchor="w")
        w._grid_opacity_var = tk.DoubleVar(value=w._grid_opacity)
        w._grid_opacity_scale = ttk.Scale(left, from_=0.0, to=1.0, orient="horizontal", variable=w._grid_opacity_var, style="AppFlat.Horizontal.TScale")
        w._grid_opacity_scale.configure(command=w._on_grid_opacity_change)
        w._grid_opacity_scale.pack(fill="x", pady=(SPACING.gap, SPACING.inner))

        ttk.Separator(left, orient="horizontal").pack(fill="x", pady=(SPACING.inner, SPACING.inner))
        ttk.Label(left, text="Detection Algorithms", style="AppSidebarTitle.TLabel").pack(anchor="w", pady=(0, SPACING.inner))

        w._sens_label_var = tk.StringVar()
        w._sens_scale, w._sens_var = self.add_slider(left, w._sens_label_var, 0.0, 1.0, w._k_mad_to_sens(float(w._params["diff_k_mad"])), w._on_sens_change)

        w._part_label_var = tk.StringVar()
        w._part_scale, w._part_var = self.add_slider(left, w._part_label_var, 0.01, 0.20, float(w._params["peak_height_fraction"]), w._on_part_change)

        w._coh_label_var = tk.StringVar()
        w._coh_scale, w._coh_var = self.add_slider(left, w._coh_label_var, 0.0, 1.00, float(w._params["coherence_threshold"]), w._on_coh_change)

        w._split_var = tk.BooleanVar(value=bool(w._params["split_broad_windows"]))
        ttk.Checkbutton(left, text="Split compound events", variable=w._split_var, command=w._on_split_change).pack(anchor="w", pady=(SPACING.inner, SPACING.outer))

        w._polarity_label_var = tk.StringVar(value="Signal polarity")
        ttk.Label(left, textvariable=w._polarity_label_var, style="AppMeta.TLabel").pack(anchor="w")
        w._polarity_var = tk.StringVar(value=w._polarity_label_for_param())
        w._polarity_combo = ttk.Combobox(
            left,
            textvariable=w._polarity_var,
            values=list(self.polarity_labels.values()),
            state="readonly",
            width=26,
            style="AppCompact.TCombobox",
        )
        w._polarity_combo.pack(fill="x", pady=(SPACING.gap, SPACING.inner))
        w._polarity_combo.bind("<<ComboboxSelected>>", w._on_polarity_change, add="+")
        ttk.Label(
            left,
            text="Default detects brightening waves; negative and both remain available for dark-going recordings.",
            style="AppMeta.TLabel",
            wraplength=240,
        ).pack(anchor="w", pady=(0, SPACING.outer))

        history_row = ttk.Frame(left, style="AppSidebar.TFrame")
        history_row.pack(fill="x", pady=(0, SPACING.inner))
        w._undo_btn = ttk.Button(history_row, text="⟲ Undo", command=w._on_undo, width=8, **semantic_button_options("secondary"))
        w._undo_btn.pack(side="left", padx=(0, SPACING.gap))
        w._redo_btn = ttk.Button(history_row, text="⟳ Redo", command=w._on_redo, width=8, **semantic_button_options("secondary"))
        w._redo_btn.pack(side="left", padx=(0, SPACING.gap))
        ttk.Button(history_row, text="Reset", command=w._on_reset_defaults, width=8, **semantic_button_options("secondary")).pack(side="left")

        action_btns = ttk.Frame(left, style="AppSidebar.TFrame")
        action_btns.pack(fill="x", pady=(SPACING.inner, SPACING.gap))

        w._run_btn = ttk.Button(action_btns, text="Run Detection", command=w._on_run, **semantic_button_options("primary"))
        w._run_btn.pack(side="left", expand=True, fill="x", padx=(0, SPACING.gap))
        w._cancel_btn = ttk.Button(action_btns, text="Cancel Run", command=w._on_cancel_run, **semantic_button_options("secondary"), state="disabled")
        w._cancel_btn.pack(side="left", expand=True, fill="x")

        w._setup_status_var = tk.StringVar(value="")
        ttk.Label(left, textvariable=w._setup_status_var, style="AppMeta.TLabel", wraplength=240).pack(anchor="w", pady=(0, 0))

    def build_center_pane(self, parent: ttk.Frame) -> None:
        w = self.window
        center = ttk.Frame(parent, padding=SPACING.outer, style="AppSurface.TFrame")
        center.grid(row=0, column=1, sticky="nsew")
        center.rowconfigure(0, weight=1)
        center.columnconfigure(0, weight=1)

        canvas_frame = ttk.Frame(center, style="AppInset.TFrame")
        canvas_frame.grid(row=0, column=0, sticky="nsew")

        w._viewer_canvas = tk.Canvas(canvas_frame, bg="#1a1a1a", highlightthickness=0)
        w._viewer_canvas.pack(fill="both", expand=True)
        w._viewer_canvas.bind("<Configure>", lambda _e: w._render_viewer_frame(w._current_frame))

        badge_frame = ttk.Frame(canvas_frame, style="AppOverlay.TFrame", padding=(4, 2))
        badge_frame.place(relx=0.02, rely=0.02, anchor="nw")
        ttk.Label(badge_frame, text="Display: 1-99% Stretch | Detection: Raw Float", style="AppSurfaceMicro.TLabel").pack()

        scrub_frame = ttk.Frame(center, style="AppSurface.TFrame")
        scrub_frame.grid(row=1, column=0, sticky="ew", pady=(SPACING.inner, 0))

        nav_row = ttk.Frame(scrub_frame, style="AppSurface.TFrame")
        nav_row.pack(fill="x", pady=(0, 2))
        w._viewer_frame_label_var = tk.StringVar(value="Frame 0")
        ttk.Label(nav_row, textvariable=w._viewer_frame_label_var, style="AppMeta.TLabel").pack(side="left")
        ttk.Button(nav_row, text=">", command=lambda: w._on_step_frame(1), width=2, **semantic_button_options("secondary")).pack(side="right")
        ttk.Button(nav_row, text="<", command=lambda: w._on_step_frame(-1), width=2, **semantic_button_options("secondary")).pack(side="right", padx=(0, 2))

        w._overview_canvas = tk.Canvas(scrub_frame, height=28, bg=CANVAS_BACKGROUND, highlightthickness=0)
        w._overview_canvas.pack(fill="x", pady=(2, 0))
        w._overview_canvas.bind("<Configure>", lambda _e: w._timeline.render_overview())
        w._overview_canvas.bind("<Button-1>", w._timeline.on_overview_click)
        w._overview_canvas.bind("<B1-Motion>", w._timeline.on_overview_drag)
        w._overview_canvas.bind("<ButtonRelease-1>", w._timeline.on_overview_release)

        w._detail_canvas = tk.Canvas(scrub_frame, height=60, bg=CANVAS_BACKGROUND, highlightthickness=0)
        w._detail_canvas.pack(fill="x", pady=(2, 0))
        w._detail_canvas.bind("<Configure>", lambda _e: w._timeline.render_detail())
        w._detail_canvas.bind("<Motion>", w._timeline.on_detail_motion)
        w._detail_canvas.bind("<Button-1>", w._timeline.on_detail_click)
        w._detail_canvas.bind("<B1-Motion>", w._timeline.on_detail_drag)
        w._detail_canvas.bind("<ButtonRelease-1>", w._timeline.on_detail_release)
        w._detail_canvas.bind("<MouseWheel>", w._timeline.on_detail_wheel)
        w._detail_canvas.bind("<Button-4>", lambda e: w._timeline.on_detail_wheel_linux(e, +1))
        w._detail_canvas.bind("<Button-5>", lambda e: w._timeline.on_detail_wheel_linux(e, -1))

    def build_right_pane(self, parent: ttk.Frame) -> None:
        w = self.window
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
        w._tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=8, selectmode="browse")
        w._tree.heading("start", text="Start")
        w._tree.heading("end", text="End")
        w._tree.heading("duration", text="Dur.")
        w._tree.heading("coherence", text="Coherence")
        for c in cols:
            w._tree.column(c, width=70, anchor="center")
        w._tree.grid(row=0, column=0, sticky="nsew")

        tree_sb = ttk.Scrollbar(tree_frame, orient="vertical", command=w._tree.yview)
        w._tree.configure(yscrollcommand=tree_sb.set)
        tree_sb.grid(row=0, column=1, sticky="ns")
        w._tree.bind("<<TreeviewSelect>>", w._on_tree_select)

        bounds_row = ttk.Frame(right, style="AppSurface.TFrame")
        bounds_row.grid(row=2, column=0, sticky="ew", pady=(SPACING.inner, 0))
        ttk.Label(bounds_row, text="Start:", style="AppMeta.TLabel").pack(side="left")
        w._start_entry = ttk.Entry(bounds_row, width=6, style="AppCompact.TEntry")
        w._start_entry.pack(side="left", padx=(2, SPACING.gap))
        ttk.Label(bounds_row, text="End:", style="AppMeta.TLabel").pack(side="left")
        w._end_entry = ttk.Entry(bounds_row, width=6, style="AppCompact.TEntry")
        w._end_entry.pack(side="left", padx=(2, SPACING.gap))
        w._start_entry.bind("<FocusOut>", lambda _e: w._on_update_bounds())
        w._start_entry.bind("<Return>", lambda _e: w._on_update_bounds())
        w._end_entry.bind("<FocusOut>", lambda _e: w._on_update_bounds())
        w._end_entry.bind("<Return>", lambda _e: w._on_update_bounds())

        action_row = ttk.Frame(right, style="AppSurface.TFrame")
        action_row.grid(row=3, column=0, sticky="ew", pady=(SPACING.outer, 0))
        ttk.Button(action_row, text="Delete Event", command=w._on_delete, **semantic_button_options("danger")).pack(side="left", expand=True, fill="x", padx=(0, SPACING.gap))
        ttk.Button(action_row, text="Accept Event", command=w._on_accept_one, **semantic_button_options("secondary")).pack(side="left", expand=True, fill="x")

        ttk.Separator(right, orient="horizontal").grid(row=4, column=0, sticky="ew", pady=(SPACING.outer, SPACING.inner))

        ttk.Button(right, text="Commit & Proceed", command=w._on_accept_all, **semantic_button_options("primary")).grid(row=5, column=0, sticky="ew", pady=(0, SPACING.inner))
        ttk.Button(right, text="Cancel", command=w._on_close, **semantic_button_options("secondary")).grid(row=6, column=0, sticky="ew")

    def add_slider(
        self,
        parent: ttk.Frame,
        label_var: tk.StringVar,
        from_: float,
        to: float,
        init: float,
        command,
    ) -> tuple[ttk.Scale, tk.DoubleVar]:
        ttk.Label(parent, textvariable=label_var, style="AppMeta.TLabel").pack(anchor="w", pady=(SPACING.inner, 0))
        var = tk.DoubleVar(value=init)
        scale = ttk.Scale(parent, from_=from_, to=to, orient="horizontal", variable=var, style="AppFlat.Horizontal.TScale")
        scale.configure(command=command)
        scale.pack(fill="x", pady=(0, 2))
        return scale, var
