import tkinter as tk
from tkinter import ttk
import sys

from sdapp.analysis.ui.widgets import build_preview_overlay


class LayoutBuilder:
    def setup_ui(self):
        canvas_bg = "#f1f1f1"
        slider_overlay_bg = "#d4d7db"
        insert_cursor = "#1f1f1f"

        # Hidden compatibility controls retained for state synchronization.
        self.entry_input = tk.Entry(self.root, width=40)
        self.entry_input.insert(0, "Host-provided SD event scope")

        self.entry_output = tk.Entry(self.root, width=40)
        self.entry_output.insert(0, str(self.config.output_path()))

        self.entry_model = tk.Entry(self.root, width=35)
        self.entry_model.insert(0, self.config.model_token())

        self.spin_baseline = tk.Spinbox(self.root, from_=1, to=100, width=5)
        self._set_spinbox_value(self.spin_baseline, self.config.default_baseline)

        self.lbl_status = ttk.Label(
            self.root,
            text="Status: Idle",
            foreground="gray",
            justify="left",
            wraplength=320,
        )

        viz_frame = ttk.Frame(self.root)
        viz_frame.pack(fill="both", expand=True, padx=10, pady=5)

        self.panel_left = ttk.LabelFrame(viz_frame, text="Interactive Selection (Global Norm)", padding=5)
        self.panel_left.pack(side="left", fill="both", expand=True)
        self.canvas_left = tk.Canvas(self.panel_left, bg=canvas_bg, cursor="cross")
        self.canvas_left.pack(fill="both", expand=True)

        self.canvas_left.bind("<Button-1>", self.on_mouse_down)
        self.canvas_left.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas_left.bind("<ButtonRelease-1>", self.on_mouse_up)
        self.canvas_left.bind("<Motion>", self.on_mouse_move)
        self.canvas_left.bind("<Leave>", self.on_mouse_leave)

        self.preview_frame, self.canvas_preview, self.lbl_grip = build_preview_overlay(
            self.canvas_left,
            self.start_resize_preview,
            self.do_resize_preview,
            self.stop_resize_preview,
            dark_theme=False,
        )

        self.panel_right = ttk.LabelFrame(viz_frame, text="Reference View", padding=5)
        self.panel_right.pack(side="right", fill="both", expand=True)
        self.canvas_right = tk.Canvas(self.panel_right, bg=canvas_bg)
        self.canvas_right.pack(fill="both", expand=True)
        self.canvas_right.bind("<Button-1>", self.on_right_canvas_click)
        self.canvas_right.bind("<Double-Button-1>", self.on_right_canvas_double_click)

        action_frame = ttk.Frame(self.root, padding=10)
        action_frame.pack(fill="x", padx=10)

        self.lbl_frame = ttk.Label(action_frame, text="Frame: 0 / 0")
        self.lbl_frame.pack(side="top", anchor="w")

        slider_row = ttk.Frame(action_frame)
        slider_row.pack(fill="x", pady=5)

        slider_wrap = ttk.Frame(slider_row)
        slider_wrap.pack(side="left", fill="x", expand=True)

        self.slider_overlay = tk.Canvas(
            slider_wrap,
            height=12,
            bg=slider_overlay_bg,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.slider_overlay.pack(fill="x", pady=(0, 2))
        self.slider_overlay.bind("<Button-1>", self._on_slider_overlay_click)
        self.slider_overlay.bind("<Configure>", lambda _e: self._redraw_slider_overlay())

        self.slider = ttk.Scale(slider_wrap, from_=0, to=100, orient="horizontal", command=self.on_slider_move)
        self.slider.pack(fill="x", expand=True)
        self.slider_value = tk.StringVar(value="1")
        self.lbl_slider_value = ttk.Label(slider_row, textvariable=self.slider_value, width=5)
        self.lbl_slider_value.pack(side="right", padx=6)

        btn_box = ttk.Frame(action_frame)
        btn_box.pack(fill="x", pady=5)

        self.tool_mode = tk.StringVar(value="select")

        self.frame_tools = ttk.LabelFrame(btn_box, text="Tools")
        self.frame_tools.pack(side="left", padx=5)

        row1 = ttk.Frame(self.frame_tools)
        row1.pack(side="top", fill="x", anchor="w")
        ttk.Radiobutton(row1, text="Select", variable=self.tool_mode, value="select").pack(side="left", padx=5)
        ttk.Radiobutton(row1, text="Point (+)", variable=self.tool_mode, value="point_pos").pack(side="left", padx=5)
        ttk.Radiobutton(row1, text="Point (-)", variable=self.tool_mode, value="point_neg").pack(side="left", padx=5)

        ttk.Label(row1, text="| Sens:").pack(side="left", padx=2)
        self.sensitivity = tk.DoubleVar(value=0.0)
        ttk.Scale(
            row1,
            from_=-3.0,
            to=3.0,
            variable=self.sensitivity,
            orient="horizontal",
            length=60,
            command=self.on_sensitivity_change,
        ).pack(side="left", padx=5)
        self.lbl_sens = ttk.Label(row1, text="0.0")
        self.lbl_sens.pack(side="left")
        ttk.Button(row1, text="Clear Frame", command=self.clear_current_frame_data).pack(side="right", padx=5)

        row2 = ttk.Frame(self.frame_tools)
        row2.pack(side="top", fill="x", anchor="w", pady=2)
        ttk.Radiobutton(row2, text="Brush (+)", variable=self.tool_mode, value="brush").pack(side="left", padx=5)
        ttk.Radiobutton(row2, text="Eraser (-)", variable=self.tool_mode, value="eraser").pack(side="left", padx=5)

        ttk.Label(row2, text="| Size:").pack(side="left", padx=2)
        self.brush_size = tk.DoubleVar(value=10.0)
        self.scale_brush = ttk.Scale(
            row2,
            from_=1,
            to=50,
            variable=self.brush_size,
            orient="horizontal",
            length=60,
            command=self.on_brush_size_change,
        )
        self.scale_brush.pack(side="left", padx=5)
        self.lbl_brush_val = ttk.Label(row2, text="10 px", width=5)
        self.lbl_brush_val.pack(side="left")

        self.frame_prop = ttk.LabelFrame(btn_box, text="Propagation")
        self.frame_prop.pack(side="left", padx=15, pady=2)

        ttk.Label(self.frame_prop, text="Start:").pack(side="left", padx=2)
        self.spin_prop_start = tk.Spinbox(self.frame_prop, from_=1, to=10000, width=5)
        self.spin_prop_start.pack(side="left", padx=2)
        self._set_spinbox_value(self.spin_prop_start, 1)

        ttk.Label(self.frame_prop, text="End:").pack(side="left", padx=2)
        self.spin_prop_end = tk.Spinbox(self.frame_prop, from_=1, to=10000, width=5)
        self.spin_prop_end.pack(side="left", padx=2)
        self._set_spinbox_value(self.spin_prop_end, 100)

        ttk.Button(self.frame_prop, text="Run Propagation", width=14, command=self._trigger_background_propagation).pack(
            side="left", padx=5
        )

        self.right_controls = ttk.Frame(btn_box)
        self.right_controls.pack(side="right", padx=8, pady=2)

        analysis_section = ttk.LabelFrame(self.right_controls, text="Metrics Settings")
        analysis_section.pack(side="left", padx=(0, 6))
        self.btn_analysis_toggle = ttk.Button(
            analysis_section,
            text="Metrics Settings ▸",
            width=16,
            command=self._toggle_analysis_panel,
        )
        self.btn_analysis_toggle.pack(fill="x", padx=4, pady=(4, 2))
        self.frame_analysis_body = ttk.Frame(analysis_section)
        analysis_row1 = ttk.Frame(self.frame_analysis_body)
        analysis_row1.pack(side="top", fill="x", pady=1)
        analysis_row2 = ttk.Frame(self.frame_analysis_body)
        analysis_row2.pack(side="top", fill="x", pady=1)

        ttk.Label(analysis_row1, text="Frames/sec:").pack(side="left", padx=2)
        self.frames_per_sec_var = tk.DoubleVar(value=1.0)
        self.entry_frames_per_sec = tk.Entry(analysis_row1, textvariable=self.frames_per_sec_var, width=6)
        self.entry_frames_per_sec.pack(side="left", padx=2)
        self.btn_set_scale = ttk.Button(analysis_row1, text="Set Scale", command=self.start_scale_selection)
        self.btn_set_scale.pack(side="left", padx=3)

        self.btn_draw_roi = ttk.Button(analysis_row2, text="Draw ROI", command=self.start_roi_selection)
        self.btn_draw_roi.pack(side="left", padx=3)

        export_section = ttk.LabelFrame(self.right_controls, text="Masks")
        export_section.pack(side="left")
        self.btn_save_masks = ttk.Button(
            export_section,
            text="Save Current Masks",
            width=18,
            command=self.save_current_masks,
        )
        self.btn_save_masks.pack(fill="x", padx=4, pady=(4, 4))

        self._set_analysis_panel(False)

        activity_frame = ttk.LabelFrame(self.root, text="Activity", height=64)
        activity_frame.pack(fill="x", padx=10, pady=5)
        self.loading_status_var = tk.StringVar(value="Idle")
        self.loading_status_label = ttk.Label(activity_frame, textvariable=self.loading_status_var, foreground="#4d6f8a")
        self.loading_status_label.pack(anchor="w", padx=6, pady=(2, 2))
        self.loading_bar = ttk.Progressbar(activity_frame, mode="indeterminate")

        # Ensure a visible blinking text cursor in ttk Entry/Spinbox controls.
        for text_widget in [
            self.entry_input,
            self.entry_output,
            self.entry_model,
            self.spin_baseline,
            self.spin_prop_start,
            self.spin_prop_end,
            self.entry_frames_per_sec,
        ]:
            try:
                text_widget.configure(insertbackground=insert_cursor, insertwidth=2, insertontime=600, insertofftime=300)
            except Exception:
                try:
                    text_widget.configure(insertcolor=insert_cursor, insertwidth=2, insertontime=600, insertofftime=300)
                except Exception:
                    pass

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
