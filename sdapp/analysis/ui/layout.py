from __future__ import annotations

import sys
import tkinter as tk

from sdapp.analysis.ui.theme import CANVAS_BACKGROUND, SLIDER_OVERLAY_BACKGROUND, SPACING, apply_theme
from sdapp.analysis.ui.widgets import build_preview_overlay
from sdapp.shared.ui.bootstrap import semantic_button_options, ttk


class LayoutBuilder:
    def setup_ui(self):
        apply_theme(self.root)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        shell = ttk.Frame(self.root, padding=SPACING.outer, style="AppShell.TFrame")
        shell.grid(row=0, column=0, sticky="nsew")
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(1, weight=1)
        self.frame_status_var = tk.StringVar(value="Frame 0 / 0")
        self.frame_meta_var = tk.StringVar(value="No file loaded")

        self._build_status_row(shell)

        content = ttk.Frame(shell, style="AppShell.TFrame")
        content.grid(row=1, column=0, sticky="nsew", pady=(0, SPACING.inner))
        content.columnconfigure(0, weight=1, uniform="viewer")
        content.columnconfigure(1, weight=1, uniform="viewer")
        content.rowconfigure(0, weight=1)

        self.build_left_panel(content)
        self.build_right_panel(content)

        controls = ttk.Frame(shell, style="AppShell.TFrame")
        controls.grid(row=2, column=0, sticky="ew")
        controls.columnconfigure(0, weight=1)

        self.build_controls(controls)
        self._disable_button_focus(shell)
        self._bind_clicks_to_clear_text_focus(shell)
        self._configure_text_cursor()
        self._bind_shortcuts()

    def _build_status_row(self, parent):
        status_row = ttk.Frame(parent, style="AppShell.TFrame")
        status_row.grid(row=0, column=0, sticky="ew", pady=(0, SPACING.inner))
        status_row.columnconfigure(0, weight=1)
        status_row.columnconfigure(1, weight=1)

        self.lbl_status = ttk.Label(status_row, text="Status: Idle", style="AppMeta.TLabel", justify="left", wraplength=480)
        self.lbl_status.grid(row=0, column=0, sticky="w")

        self.loading_status_var = tk.StringVar(value="Idle")
        self.loading_status_label = ttk.Label(
            status_row,
            textvariable=self.loading_status_var,
            style="AppMeta.TLabel",
            justify="right",
            anchor="e",
            wraplength=420,
        )
        self.loading_status_label.grid(row=0, column=1, sticky="e")

        self.loading_bar = ttk.Progressbar(status_row, mode="indeterminate", style="AppLoading.Horizontal.TProgressbar")
        self.loading_bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(SPACING.gap, 0))
        self.loading_bar.grid_remove()

    def build_left_panel(self, parent):
        self.panel_left, body = self._create_view_panel(parent, row=0, column=0, title="Interactive Selection", padx=(0, SPACING.gap))
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)

        self.canvas_left = tk.Canvas(body, bg=CANVAS_BACKGROUND, cursor="cross", highlightthickness=0, bd=0)
        self.canvas_left.grid(row=0, column=0, sticky="nsew")

        self.canvas_left.bind("<Button-1>", self.on_mouse_down)
        self.canvas_left.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas_left.bind("<ButtonRelease-1>", self.on_mouse_up)
        self.canvas_left.bind("<Motion>", self.on_mouse_move)
        self.canvas_left.bind("<Leave>", self.on_mouse_leave)
        self.canvas_left.bind("<Configure>", self._on_viewport_canvas_configure, add="+")
        self.canvas_left.bind("<MouseWheel>", self._on_canvas_mouse_wheel, add="+")
        self.canvas_left.bind("<Button-4>", self._on_canvas_mouse_wheel, add="+")
        self.canvas_left.bind("<Button-5>", self._on_canvas_mouse_wheel, add="+")

        self.preview_frame, self.canvas_preview, self.lbl_grip = build_preview_overlay(
            self.canvas_left,
            self.start_resize_preview,
            self.do_resize_preview,
            self.stop_resize_preview,
            dark_theme=True,
        )
        self.canvas_preview.bind("<Button-1>", lambda event: self._start_canvas_pan(self.canvas_preview, event), add="+")
        self.canvas_preview.bind("<B1-Motion>", lambda event: self._drag_canvas_pan(self.canvas_preview, event), add="+")
        self.canvas_preview.bind("<ButtonRelease-1>", lambda event: self._stop_canvas_pan(self.canvas_preview, event), add="+")
        self.canvas_preview.bind("<Configure>", self._on_viewport_canvas_configure, add="+")
        self.canvas_preview.bind("<MouseWheel>", self._on_canvas_mouse_wheel, add="+")
        self.canvas_preview.bind("<Button-4>", self._on_canvas_mouse_wheel, add="+")
        self.canvas_preview.bind("<Button-5>", self._on_canvas_mouse_wheel, add="+")

    def build_right_panel(self, parent):
        self.panel_right, body = self._create_view_panel(parent, row=0, column=1, title="Reference View", padx=(SPACING.gap, 0))
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)

        self.canvas_right = tk.Canvas(body, bg=CANVAS_BACKGROUND, highlightthickness=0, bd=0)
        self.canvas_right.grid(row=0, column=0, sticky="nsew")
        self.reference_overlay = self._create_frame_overlay(body)
        self.reference_overlay.lift()
        self.canvas_right.bind("<Button-1>", self.on_right_canvas_click)
        self.canvas_right.bind("<Double-Button-1>", self.on_right_canvas_double_click)
        self.canvas_right.bind("<Button-1>", lambda event: self._start_canvas_pan(self.canvas_right, event), add="+")
        self.canvas_right.bind("<B1-Motion>", lambda event: self._drag_canvas_pan(self.canvas_right, event), add="+")
        self.canvas_right.bind("<ButtonRelease-1>", lambda event: self._stop_canvas_pan(self.canvas_right, event), add="+")
        self.canvas_right.bind("<Configure>", self._on_viewport_canvas_configure, add="+")
        self.canvas_right.bind("<MouseWheel>", self._on_canvas_mouse_wheel, add="+")
        self.canvas_right.bind("<Button-4>", self._on_canvas_mouse_wheel, add="+")
        self.canvas_right.bind("<Button-5>", self._on_canvas_mouse_wheel, add="+")

    def build_controls(self, parent):
        parent.rowconfigure(1, weight=1)
        parent.columnconfigure(0, weight=1)

        self._build_timeline_band(parent)
        self._build_control_strip(parent)

    def _build_timeline_band(self, parent):
        timeline = ttk.Frame(parent, padding=(SPACING.card, SPACING.card, SPACING.card, SPACING.card), style="AppStrip.TFrame")
        timeline.grid(row=0, column=0, sticky="ew")
        timeline.columnconfigure(0, weight=1)

        ttk.Label(timeline, text="Timeline", style="AppStripTitle.TLabel").grid(row=0, column=0, sticky="w")

        slider_row = ttk.Frame(timeline, style="AppStrip.TFrame")
        slider_row.grid(row=1, column=0, sticky="ew", pady=(SPACING.inner, 0))
        slider_row.columnconfigure(0, weight=1)

        self.slider_overlay = tk.Canvas(
            slider_row,
            height=18,
            bg=SLIDER_OVERLAY_BACKGROUND,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.slider_overlay.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self.slider_overlay.bind("<Button-1>", self._on_slider_overlay_click)
        self.slider_overlay.bind("<Configure>", lambda _event: self._redraw_slider_overlay())

        self.slider = ttk.Scale(
            slider_row,
            from_=0,
            to=100,
            orient="horizontal",
            command=self.on_slider_move,
            style="AppFlat.Horizontal.TScale",
            takefocus=False,
        )
        self.slider.grid(row=1, column=0, sticky="ew")
        self.slider.bind("<Left>", self.on_nav_left)
        self.slider.bind("<Right>", self.on_nav_right)

    def _build_control_strip(self, parent):
        strip = ttk.Frame(parent, padding=(SPACING.card, SPACING.inner, SPACING.card, SPACING.card), style="AppStrip.TFrame")
        strip.grid(row=1, column=0, sticky="ew", pady=(SPACING.gap, 0))
        for column, weight in enumerate((5, 4, 3)):
            strip.columnconfigure(column * 2, weight=weight)
        self.frame_tools = self._build_tools_group(strip, 0)
        self._add_strip_separator(strip, 1)
        self.frame_prop = self._build_propagation_group(strip, 2)
        self._add_strip_separator(strip, 3)
        self.right_controls = self._build_metrics_masks_group(strip, 4)

    def _build_tools_group(self, parent, column):
        frame = ttk.Frame(parent, padding=(SPACING.card, SPACING.gap, SPACING.card, SPACING.card), style="AppSubpanel.TFrame")
        frame.grid(row=0, column=column, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(2, weight=1)
        self.tool_mode = tk.StringVar(value="select")
        self.tool_mode.trace_add("write", lambda *_args: self._sync_tool_mode_buttons())

        ttk.Label(frame, text="Tools", style="AppSubpanelTitle.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, SPACING.gap))
        segmented = ttk.Frame(frame, style="AppSubpanel.TFrame")
        segmented.grid(row=1, column=0, columnspan=3, sticky="ew")
        for seg_col in range(3):
            segmented.columnconfigure(seg_col, weight=1)
        self.btn_tool_select = ttk.Button(segmented, text="Select", command=lambda: self._set_tool_mode("select"), style="AppSegmentedActive.TButton")
        self.btn_tool_select.grid(row=0, column=0, sticky="ew")
        self.btn_tool_point_pos = ttk.Button(segmented, text="Point (+)", command=lambda: self._set_tool_mode("point_pos"), style="AppSegmented.TButton")
        self.btn_tool_point_pos.grid(row=0, column=1, sticky="ew", padx=(1, 1))
        self.btn_tool_point_neg = ttk.Button(segmented, text="Point (-)", command=lambda: self._set_tool_mode("point_neg"), style="AppSegmented.TButton")
        self.btn_tool_point_neg.grid(row=0, column=2, sticky="ew")

        sensitivity_row = ttk.Frame(frame, style="AppSubpanel.TFrame")
        sensitivity_row.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(SPACING.gap, 0))
        sensitivity_row.columnconfigure(1, weight=1)

        ttk.Label(sensitivity_row, text="Sensitivity", style="AppSubpanelMeta.TLabel").grid(row=0, column=0, sticky="w")
        self.sensitivity = tk.DoubleVar(value=0.0)
        ttk.Scale(
            sensitivity_row,
            from_=-3.0,
            to=3.0,
            variable=self.sensitivity,
            orient="horizontal",
            command=self.on_sensitivity_change,
            style="AppFlat.Horizontal.TScale",
        ).grid(row=0, column=1, sticky="ew", padx=(SPACING.gap, SPACING.gap))
        self.lbl_sens = ttk.Label(sensitivity_row, text="0.0", style="AppSubpanelMeta.TLabel", width=5)
        self.lbl_sens.grid(row=0, column=2, sticky="w")

        brush_row = ttk.Frame(frame, style="AppSubpanel.TFrame")
        brush_row.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(SPACING.inner, 0))
        brush_row.columnconfigure(0, weight=1)
        brush_row.columnconfigure(1, weight=1)
        self.btn_tool_brush = ttk.Button(brush_row, text="Brush (+)", command=lambda: self._set_tool_mode("brush"), style="AppSegmented.TButton")
        self.btn_tool_brush.grid(row=0, column=0, sticky="ew", padx=(0, 1))
        self.btn_tool_eraser = ttk.Button(brush_row, text="Eraser (-)", command=lambda: self._set_tool_mode("eraser"), style="AppSegmented.TButton")
        self.btn_tool_eraser.grid(row=0, column=1, sticky="ew")

        brush_size_row = ttk.Frame(frame, style="AppSubpanel.TFrame")
        brush_size_row.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(SPACING.inner, 0))
        brush_size_row.columnconfigure(1, weight=1)

        ttk.Label(brush_size_row, text="Brush", style="AppSubpanelMeta.TLabel").grid(row=0, column=0, sticky="w")
        self.brush_size = tk.DoubleVar(value=10.0)
        self.scale_brush = ttk.Scale(
            brush_size_row,
            from_=1,
            to=50,
            variable=self.brush_size,
            orient="horizontal",
            command=self.on_brush_size_change,
            style="AppFlat.Horizontal.TScale",
        )
        self.scale_brush.grid(row=0, column=1, sticky="ew", padx=(SPACING.gap, SPACING.gap))
        self.lbl_brush_val = ttk.Label(brush_size_row, text="10 px", style="AppSubpanelMeta.TLabel", width=7)
        self.lbl_brush_val.grid(row=0, column=2, sticky="w")

        ttk.Button(frame, text="Clear Frame", command=self.clear_current_frame_data, **semantic_button_options("secondary")).grid(
            row=5,
            column=2,
            sticky="e",
            pady=(SPACING.inner, 0),
        )
        self._sync_tool_mode_buttons()
        return frame

    def _build_propagation_group(self, parent, column):
        frame = ttk.Frame(parent, padding=(SPACING.card, SPACING.gap, SPACING.card, SPACING.card), style="AppSubpanel.TFrame")
        frame.grid(row=0, column=column, sticky="nsew")
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(3, weight=1)

        ttk.Label(frame, text="Propagation", style="AppSubpanelTitle.TLabel").grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, SPACING.gap))
        self.propagation_range_canvas = tk.Canvas(frame, height=16, bg=SLIDER_OVERLAY_BACKGROUND, highlightthickness=0, bd=0)
        self.propagation_range_canvas.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(0, SPACING.gap))
        ttk.Label(frame, text="Start", style="AppSubpanelMeta.TLabel").grid(row=2, column=0, sticky="w")
        self.spin_prop_start = ttk.Entry(frame, width=5, style="AppCompact.TEntry")
        self.spin_prop_start.grid(row=2, column=1, sticky="ew", padx=(SPACING.gap, SPACING.inner))
        self._set_spinbox_value(self.spin_prop_start, 1)
        self.spin_prop_start.bind("<KeyRelease>", lambda _event: self._redraw_propagation_range_bar(), add="+")
        self.spin_prop_start.bind("<FocusOut>", lambda _event: self._redraw_propagation_range_bar(), add="+")

        ttk.Label(frame, text="End", style="AppSubpanelMeta.TLabel").grid(row=2, column=2, sticky="w")
        self.spin_prop_end = ttk.Entry(frame, width=5, style="AppCompact.TEntry")
        self.spin_prop_end.grid(row=2, column=3, sticky="ew", padx=(SPACING.gap, 0))
        self._set_spinbox_value(self.spin_prop_end, 100)
        self.spin_prop_end.bind("<KeyRelease>", lambda _event: self._redraw_propagation_range_bar(), add="+")
        self.spin_prop_end.bind("<FocusOut>", lambda _event: self._redraw_propagation_range_bar(), add="+")

        self.btn_run_propagation = ttk.Button(frame, text="Run Propagation", command=self._trigger_background_propagation, **semantic_button_options("success"))
        self.btn_run_propagation.grid(
            row=3,
            column=0,
            columnspan=4,
            sticky="ew",
            pady=(SPACING.inner, 0),
        )
        self.propagation_range_canvas.bind("<Configure>", lambda _event: self._redraw_propagation_range_bar(), add="+")
        self._redraw_propagation_range_bar()
        return frame

    def _build_metrics_group(self, parent, column):
        frame = ttk.Frame(parent, style="AppSubpanel.TFrame")
        frame.grid(row=0, column=column, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        self.frame_metrics = frame

        ttk.Label(frame, text="Metrics", style="AppSubpanelTitle.TLabel").grid(row=0, column=0, sticky="w")
        self.btn_analysis_toggle = ttk.Button(frame, text="Adjust Metrics", width=18, command=self._toggle_analysis_panel, **semantic_button_options("secondary"))
        self.btn_analysis_toggle.grid(row=1, column=0, sticky="ew", pady=(SPACING.gap, 0))

        self.frame_analysis_body = ttk.Frame(frame, style="AppSubpanel.TFrame")
        self.frame_analysis_body.grid(row=2, column=0, sticky="ew", pady=(SPACING.inner, 0))
        self.frame_analysis_body.columnconfigure(1, weight=1)

        ttk.Label(self.frame_analysis_body, text="Frames/sec", style="AppSubpanelMeta.TLabel").grid(row=0, column=0, sticky="w")
        self.frames_per_sec_var = tk.DoubleVar(value=1.0)
        self.entry_frames_per_sec = ttk.Entry(self.frame_analysis_body, textvariable=self.frames_per_sec_var, width=7, style="AppCompact.TEntry")
        self.entry_frames_per_sec.grid(row=0, column=1, sticky="ew", padx=(SPACING.gap, 0))

        metrics_actions = ttk.Frame(self.frame_analysis_body, style="AppSubpanel.TFrame")
        metrics_actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(SPACING.inner, 0))
        metrics_actions.columnconfigure(0, weight=1)
        metrics_actions.columnconfigure(1, weight=1)
        metrics_actions.columnconfigure(2, weight=1)

        self.btn_set_scale = ttk.Button(metrics_actions, text="Set Scale", command=self.start_scale_selection, **semantic_button_options("secondary"))
        self.btn_set_scale.grid(row=0, column=0, sticky="ew", padx=(0, SPACING.gap))
        self.btn_draw_roi = ttk.Button(metrics_actions, text="Draw ROI", command=self.start_roi_selection, **semantic_button_options("secondary"))
        self.btn_draw_roi.grid(row=0, column=1, sticky="ew", padx=(0, SPACING.gap))
        self.btn_preview_metrics = ttk.Button(metrics_actions, text="Preview", command=self.compute_metrics_preview, **semantic_button_options("secondary"))
        self.btn_preview_metrics.grid(row=0, column=2, sticky="ew")

        self.metrics_fps_status_var = tk.StringVar(value="Frames/sec: 1 (Current)")
        self.metrics_scale_status_var = tk.StringVar(value="Scale: Not set (Current)")
        self.metrics_roi_status_var = tk.StringVar(value="ROI: Not set (Current)")
        self.metrics_preview_var = tk.StringVar(value="Preview: Click 'Preview' to compute")
        ttk.Label(self.frame_analysis_body, textvariable=self.metrics_fps_status_var, style="AppSubpanelMeta.TLabel").grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(SPACING.inner, 0)
        )
        ttk.Label(self.frame_analysis_body, textvariable=self.metrics_scale_status_var, style="AppSubpanelMeta.TLabel").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(2, 0)
        )
        ttk.Label(self.frame_analysis_body, textvariable=self.metrics_roi_status_var, style="AppSubpanelMeta.TLabel").grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(2, 0)
        )
        ttk.Label(self.frame_analysis_body, textvariable=self.metrics_preview_var, style="AppSubpanelMeta.TLabel").grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )

        self._stabilize_metrics_group_width()
        self._set_analysis_panel(False)

    def _stabilize_metrics_group_width(self):
        frame = getattr(self, "frame_metrics", None)
        body = getattr(self, "frame_analysis_body", None)
        toggle = getattr(self, "btn_analysis_toggle", None)
        if frame is None or body is None or toggle is None:
            return
        try:
            frame.update_idletasks()
            stable_width = max(int(toggle.winfo_reqwidth()), int(body.winfo_reqwidth()))
            frame.columnconfigure(0, minsize=stable_width)
        except Exception:
            return

    def _build_masks_group(self, parent, column):
        frame = ttk.Frame(parent, style="AppSubpanel.TFrame")
        frame.grid(row=0, column=column, sticky="ne", padx=(SPACING.inner * 2, 0))

        ttk.Label(frame, text="Masks", style="AppSubpanelTitle.TLabel").grid(row=0, column=0, sticky="w")
        self.btn_save_masks = ttk.Button(frame, text="Save Current Masks", command=self.save_current_masks, **semantic_button_options("secondary"))
        self.btn_save_masks.grid(row=1, column=0, sticky="w", pady=(SPACING.gap, 0))

    def _build_metrics_masks_group(self, parent, column):
        frame = ttk.Frame(parent, padding=(SPACING.card, SPACING.gap, SPACING.card, SPACING.card), style="AppSubpanel.TFrame")
        frame.grid(row=0, column=column, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=0)

        self._build_metrics_group(frame, 0)
        self._build_masks_group(frame, 1)
        return frame

    def _create_view_panel(self, parent, *, row, column, title, padx=(0, 0)):
        panel = ttk.Frame(parent, padding=(SPACING.card, SPACING.card, SPACING.card, SPACING.card), style="AppSurface.TFrame")
        panel.grid(row=row, column=column, sticky="nsew", padx=padx)
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(1, weight=1)

        ttk.Label(panel, text=title, style="AppSectionTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0, SPACING.inner))

        body = ttk.Frame(panel, style="AppInset.TFrame")
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        return panel, body

    def _create_frame_overlay(self, parent):
        overlay = ttk.Frame(parent, padding=(8, 6), style="AppOverlay.TFrame")
        overlay.place(relx=0.0, rely=1.0, anchor="sw", x=10, y=-10)
        overlay.columnconfigure(0, weight=1)
        ttk.Label(overlay, textvariable=self.frame_status_var, style="AppOverlayValue.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(overlay, textvariable=self.frame_meta_var, style="AppOverlayMeta.TLabel").grid(row=1, column=0, sticky="w")
        return overlay

    def _set_tool_mode(self, mode):
        self.tool_mode.set(str(mode))

    def _sync_tool_mode_buttons(self):
        current = str(self.tool_mode.get())
        mapping = {
            getattr(self, "btn_tool_select", None): "select",
            getattr(self, "btn_tool_point_pos", None): "point_pos",
            getattr(self, "btn_tool_point_neg", None): "point_neg",
            getattr(self, "btn_tool_brush", None): "brush",
            getattr(self, "btn_tool_eraser", None): "eraser",
        }
        for button, mode in mapping.items():
            if button is None:
                continue
            button.configure(style="AppSegmentedActive.TButton" if current == mode else "AppSegmented.TButton")

    def _parse_entry_frame_range(self):
        total = int(self._get_frame_count()) if hasattr(self, "_get_frame_count") else 0
        if total <= 0:
            return 0, 0, 0
        try:
            start_idx = max(0, min(total - 1, int(float(self.spin_prop_start.get())) - 1))
        except Exception:
            start_idx = 0
        try:
            end_idx = max(0, min(total - 1, int(float(self.spin_prop_end.get())) - 1))
        except Exception:
            end_idx = total - 1
        if end_idx < start_idx:
            start_idx, end_idx = end_idx, start_idx
        return total, start_idx, end_idx

    def _redraw_propagation_range_bar(self):
        canvas = getattr(self, "propagation_range_canvas", None)
        if canvas is None:
            return
        canvas.delete("all")
        width = max(1, int(canvas.winfo_width()))
        height = max(1, int(canvas.winfo_height()))
        canvas.create_rectangle(0, 0, width, height, fill=SLIDER_OVERLAY_BACKGROUND, outline="")
        total, start_idx, end_idx = self._parse_entry_frame_range()
        if total <= 0:
            return
        left = int((start_idx / max(1, total - 1)) * (width - 1))
        right = int((end_idx / max(1, total - 1)) * (width - 1))
        if right <= left:
            right = min(width, left + 3)
        canvas.create_rectangle(left, 3, right, height - 3, fill="#1b75bc", outline="")
        canvas.create_rectangle(max(0, left - 1), 1, min(width, left + 2), height - 1, fill="#00d26a", outline="")
        canvas.create_rectangle(max(0, right - 2), 1, min(width, right + 1), height - 1, fill="#ff5c5c", outline="")

    def _ensure_overlay_tooltip(self):
        tip = getattr(self, "_overlay_tooltip", None)
        if tip is not None:
            return tip
        tip = tk.Toplevel(self.root)
        tip.withdraw()
        tip.overrideredirect(True)
        frame = ttk.Frame(tip, padding=(8, 5), style="AppOverlay.TFrame")
        frame.grid(row=0, column=0, sticky="nsew")
        label = ttk.Label(frame, text="", style="AppOverlayMeta.TLabel")
        label.grid(row=0, column=0, sticky="w")
        self._overlay_tooltip = tip
        self._overlay_tooltip_label = label
        return tip

    def _show_overlay_tooltip(self, event, text):
        if not text:
            self._hide_overlay_tooltip()
            return
        tip = self._ensure_overlay_tooltip()
        self._overlay_tooltip_label.configure(text=str(text))
        x = int(event.x_root) + 12
        y = int(event.y_root) + 12
        tip.geometry(f"+{x}+{y}")
        tip.deiconify()
        tip.lift()

    def _hide_overlay_tooltip(self, _event=None):
        tip = getattr(self, "_overlay_tooltip", None)
        if tip is None:
            return
        try:
            tip.withdraw()
        except Exception:
            pass

    def _on_slider_overlay_motion(self, event):
        regions = list(getattr(self, "_slider_overlay_regions", []))
        for left, right, text in regions:
            if float(left) <= float(event.x) <= float(right):
                self._show_overlay_tooltip(event, text)
                return
        self._hide_overlay_tooltip()

    def _add_strip_separator(self, parent, column, *, vertical=True):
        separator = ttk.Separator(parent, orient="vertical" if vertical else "horizontal")
        if vertical:
            separator.grid(row=0, column=column, sticky="ns", padx=SPACING.inner)
        else:
            separator.grid(row=0, column=column, sticky="ns", padx=SPACING.inner)

    def _configure_text_cursor(self):
        insert_cursor = "#edf1f3"
        for text_widget in [getattr(self, "spin_prop_start", None), getattr(self, "spin_prop_end", None), getattr(self, "entry_frames_per_sec", None)]:
            if text_widget is None:
                continue
            try:
                text_widget.configure(insertbackground=insert_cursor, insertwidth=2, insertontime=600, insertofftime=300)
            except Exception:
                try:
                    text_widget.configure(insertcolor=insert_cursor, insertwidth=2, insertontime=600, insertofftime=300)
                except Exception:
                    pass

    def _disable_button_focus(self, parent):
        for widget in parent.winfo_children():
            try:
                if str(widget.winfo_class()) in {"TButton", "Button"}:
                    widget.configure(takefocus=False)
            except Exception:
                pass
            self._disable_button_focus(widget)

    def _bind_clicks_to_clear_text_focus(self, parent):
        text_classes = {"TEntry", "Entry", "TSpinbox", "Spinbox", "Text", "TCombobox", "Combobox"}
        skip_classes = {"Treeview"}
        for widget in parent.winfo_children():
            try:
                widget_class = str(widget.winfo_class())
            except Exception:
                widget_class = ""
            if widget_class not in text_classes | skip_classes:
                try:
                    widget.bind("<Button-1>", self._focus_clicked_widget, add="+")
                except Exception:
                    pass
            self._bind_clicks_to_clear_text_focus(widget)

    def _focus_clicked_widget(self, event):
        widget = getattr(event, "widget", None)
        if widget is None:
            return None
        try:
            widget.focus_set()
        except Exception:
            try:
                self.root.focus_set()
            except Exception:
                return None
        return None

    def _bind_shortcuts(self):
        is_mac = sys.platform == "darwin"
        mod_key = "Command" if is_mac else "Control"

        self.root.bind(f"<{mod_key}-z>", self.on_undo)
        self.root.bind(f"<{mod_key}-Z>", self.on_redo)
        self.root.bind(f"<{mod_key}-Shift-z>", self.on_redo)
        self.root.bind("<Left>", self.on_nav_left)
        self.root.bind("<Right>", self.on_nav_right)
        self.root.bind("<Delete>", self.delete_selected_point)
        self.root.bind("<BackSpace>", self.delete_selected_point)
        self.root.bind("<b>", self._set_tool_brush_hotkey)
        self.root.bind("<B>", self._set_tool_brush_hotkey)
        self.root.bind("<e>", self._set_tool_eraser_hotkey)
        self.root.bind("<E>", self._set_tool_eraser_hotkey)
        self.root.bind("<v>", self._set_tool_select_hotkey)
        self.root.bind("<V>", self._set_tool_select_hotkey)
        self.root.bind("<KeyPress-space>", self._set_space_pan_active, add="+")
        self.root.bind("<KeyRelease-space>", self._clear_space_pan_active, add="+")
        self.root.bind("<Key-plus>", self._set_tool_point_pos_hotkey, add="+")
        self.root.bind("<Key-equal>", self._set_tool_point_pos_hotkey, add="+")
        self.root.bind("<Key-minus>", self._set_tool_point_neg_hotkey, add="+")
        self.root.bind("<Key-underscore>", self._set_tool_point_neg_hotkey, add="+")
        self.root.bind(f"<{mod_key}-plus>", self._zoom_in_hotkey, add="+")
        self.root.bind(f"<{mod_key}-equal>", self._zoom_in_hotkey, add="+")
        self.root.bind(f"<{mod_key}-minus>", self._zoom_out_hotkey, add="+")
        self.root.bind(f"<{mod_key}-underscore>", self._zoom_out_hotkey, add="+")
        self.root.bind("<Key-0>", self._reset_zoom_hotkey, add="+")
