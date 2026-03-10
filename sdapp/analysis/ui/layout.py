import tkinter as tk
from tkinter import ttk
import sys

from sdapp.analysis.ui.widgets import build_preview_overlay


class LayoutBuilder:
    def setup_ui(self):
        # 1. Top Control Panel
        control_frame = ttk.LabelFrame(self.root, text="Configuration", padding=10)
        control_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(control_frame, text="Input:").grid(row=0, column=0, sticky="e")
        self.entry_input = tk.Entry(control_frame, width=40)
        self.entry_input.grid(row=0, column=1, padx=5)
        self.btn_browse_menu = ttk.Menubutton(control_frame, text="Browse", direction="below")
        self.btn_browse_menu.grid(row=0, column=2, padx=5, sticky="w")
        self.browse_menu = tk.Menu(self.btn_browse_menu, tearoff=False)
        self.browse_menu.add_command(label="Browse Folder...", command=self.on_browse_select_folder)
        self.browse_menu.add_command(label="Browse Files...", command=self.on_browse_select_files)
        self.btn_browse_menu["menu"] = self.browse_menu

        ttk.Label(control_frame, text="Output:").grid(row=1, column=0, sticky="e")
        self.entry_output = tk.Entry(control_frame, width=40)
        self.entry_output.grid(row=1, column=1, padx=5)
        self.entry_output.insert(0, str(self.config.output_path()))
        ttk.Button(control_frame, text="Browse", command=self.browse_output).grid(row=1, column=2, padx=5)

        self.entry_model = tk.Entry(control_frame, width=35)
        self.entry_model.insert(0, str(self.config.model_path()))

        ttk.Label(control_frame, text="Baseline Frames:").grid(row=1, column=3, sticky="e")
        self.spin_baseline = tk.Spinbox(control_frame, from_=1, to=100, width=5)
        self.spin_baseline.grid(row=1, column=4, sticky="w", padx=5)
        self._set_spinbox_value(self.spin_baseline, self.config.default_baseline)

        self.btn_import = ttk.Button(control_frame, text="Import Images", command=self._start_import)
        self.btn_import.grid(row=1, column=5, padx=10, sticky="w")

        self.lbl_status = ttk.Label(
            control_frame,
            text="Status: Idle",
            foreground="gray",
            justify="left",
            wraplength=320,
        )
        self.lbl_status.grid(row=0, column=6, padx=10, sticky="w")

        # 2. Visualization Area
        viz_frame = ttk.Frame(self.root)
        viz_frame.pack(fill="both", expand=True, padx=10, pady=5)

        # Left Panel
        self.panel_left = ttk.LabelFrame(viz_frame, text="Interactive Selection (Global Norm)", padding=5)
        self.panel_left.pack(side="left", fill="both", expand=True)
        self.canvas_left = tk.Canvas(self.panel_left, bg="#222", cursor="cross")
        self.canvas_left.pack(fill="both", expand=True)

        # Mouse Bindings
        self.canvas_left.bind("<Button-1>", self.on_mouse_down)
        self.canvas_left.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas_left.bind("<ButtonRelease-1>", self.on_mouse_up)
        # Cursor Tracking
        self.canvas_left.bind("<Motion>", self.on_mouse_move)
        self.canvas_left.bind("<Leave>", self.on_mouse_leave)

        # Preview Window (Top Right Overlay)
        self.preview_frame, self.canvas_preview, self.lbl_grip = build_preview_overlay(
            self.canvas_left, self.start_resize_preview, self.do_resize_preview, self.stop_resize_preview
        )

        # Right Panel
        self.panel_right = ttk.LabelFrame(viz_frame, text="Reference View", padding=5)
        self.panel_right.pack(side="right", fill="both", expand=True)
        self.canvas_right = tk.Canvas(self.panel_right, bg="#222")
        self.canvas_right.pack(fill="both", expand=True)
        self.canvas_right.bind("<Button-1>", self.on_right_canvas_click)
        self.canvas_right.bind("<Double-Button-1>", self.on_right_canvas_double_click)

        # 3. Action Bar
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
            bg="#2a2b2f",
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

        # Toolbar
        btn_box = ttk.Frame(action_frame)
        btn_box.pack(fill="x", pady=5)

        self.tool_mode = tk.StringVar(value="select")

        # Tool: Points
        self.frame_tools = ttk.LabelFrame(btn_box, text="Tools")
        self.frame_tools.pack(side="left", padx=5)

        # Row 1: Point Tools
        row1 = ttk.Frame(self.frame_tools)
        row1.pack(side="top", fill="x", anchor="w")
        ttk.Radiobutton(row1, text="Select", variable=self.tool_mode, value="select").pack(side="left", padx=5)
        ttk.Radiobutton(row1, text="Point (+)", variable=self.tool_mode, value="point_pos").pack(side="left", padx=5)
        ttk.Radiobutton(row1, text="Point (-)", variable=self.tool_mode, value="point_neg").pack(side="left", padx=5)

        # Sensitivity
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

        # Row 2: Paint Tools & Brush Slider
        row2 = ttk.Frame(self.frame_tools)
        row2.pack(side="top", fill="x", anchor="w", pady=2)
        ttk.Radiobutton(row2, text="Brush (+)", variable=self.tool_mode, value="brush").pack(side="left", padx=5)
        ttk.Radiobutton(row2, text="Eraser (-)", variable=self.tool_mode, value="eraser").pack(side="left", padx=5)

        # Brush Size
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

        # Propagation Controls
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

        ttk.Button(self.frame_prop, text="Run", width=5, command=self._trigger_background_propagation).pack(
            side="left", padx=5
        )

        self.right_controls = ttk.Frame(btn_box)
        self.right_controls.pack(side="right", padx=8, pady=2)

        analysis_section = ttk.LabelFrame(self.right_controls, text="Analysis")
        analysis_section.pack(side="left", padx=(0, 6))
        self.btn_analysis_toggle = ttk.Button(
            analysis_section,
            text="Analysis ▸",
            width=16,
            command=self._toggle_analysis_panel,
        )
        self.btn_analysis_toggle.pack(fill="x", padx=4, pady=(4, 2))
        self.frame_analysis_body = ttk.Frame(analysis_section)
        analysis_row1 = ttk.Frame(self.frame_analysis_body)
        analysis_row1.pack(side="top", fill="x", pady=1)
        analysis_row2 = ttk.Frame(self.frame_analysis_body)
        analysis_row2.pack(side="top", fill="x", pady=1)

        ttk.Label(analysis_row1, text="Sec/Frame:").pack(side="left", padx=2)
        self.seconds_per_frame_var = tk.DoubleVar(value=1.0)
        self.entry_seconds_per_frame = tk.Entry(analysis_row1, textvariable=self.seconds_per_frame_var, width=6)
        self.entry_seconds_per_frame.pack(side="left", padx=2)
        self.btn_set_scale = ttk.Button(analysis_row1, text="Set Scale", command=self.start_scale_selection)
        self.btn_set_scale.pack(side="left", padx=3)

        self.btn_draw_roi = ttk.Button(analysis_row2, text="Draw ROI", command=self.start_roi_selection)
        self.btn_draw_roi.pack(side="left", padx=3)
        ttk.Label(analysis_row2, text="Start:").pack(side="left", padx=(8, 2))
        self.spin_analysis_start = tk.Spinbox(analysis_row2, from_=1, to=10000, width=5)
        self.spin_analysis_start.pack(side="left", padx=2)
        self._set_spinbox_value(self.spin_analysis_start, 1)
        for event_name in ("<KeyRelease>", "<<Increment>>", "<<Decrement>>", "<MouseWheel>", "<ButtonRelease-1>"):
            self.spin_analysis_start.bind(event_name, self._on_analysis_range_user_edit)
        ttk.Label(analysis_row2, text="End:").pack(side="left", padx=2)
        self.spin_analysis_end = tk.Spinbox(analysis_row2, from_=1, to=10000, width=5)
        self.spin_analysis_end.pack(side="left", padx=2)
        self._set_spinbox_value(self.spin_analysis_end, 100)
        for event_name in ("<KeyRelease>", "<<Increment>>", "<<Decrement>>", "<MouseWheel>", "<ButtonRelease-1>"):
            self.spin_analysis_end.bind(event_name, self._on_analysis_range_user_edit)
        self.btn_run_metrics = ttk.Button(analysis_row2, text="Run Metrics", command=self.run_metrics_analysis)
        self.btn_run_metrics.pack(side="left", padx=3)

        export_section = ttk.LabelFrame(self.right_controls, text="Export")
        export_section.pack(side="left")
        self.btn_export_toggle = ttk.Button(export_section, text="Export ▸", width=16, command=self._toggle_export_panel)
        self.btn_export_toggle.pack(fill="x", padx=4, pady=(4, 2))
        self.frame_export_body = ttk.Frame(export_section)
        export_row = ttk.Frame(self.frame_export_body)
        export_row.pack(fill="x")
        ttk.Label(export_row, text="Start:").pack(side="left", padx=2)
        self.spin_export_start = tk.Spinbox(export_row, from_=1, to=10000, width=5)
        self.spin_export_start.pack(side="left", padx=2)
        self._set_spinbox_value(self.spin_export_start, 1)
        for event_name in ("<KeyRelease>", "<<Increment>>", "<<Decrement>>", "<MouseWheel>", "<ButtonRelease-1>"):
            self.spin_export_start.bind(event_name, self._on_export_range_user_edit)
        ttk.Label(export_row, text="End:").pack(side="left", padx=2)
        self.spin_export_end = tk.Spinbox(export_row, from_=1, to=10000, width=5)
        self.spin_export_end.pack(side="left", padx=2)
        self._set_spinbox_value(self.spin_export_end, 100)
        for event_name in ("<KeyRelease>", "<<Increment>>", "<<Decrement>>", "<MouseWheel>", "<ButtonRelease-1>"):
            self.spin_export_end.bind(event_name, self._on_export_range_user_edit)
        self.btn_run = ttk.Button(export_row, text="\U0001F4BE EXPORT", width=10, command=self.export_results)
        self.btn_run.pack(side="left", padx=5)

        self._set_export_panel(False)
        self._set_analysis_panel(False)

        # 4. Logs
        log_frame = ttk.LabelFrame(self.root, text="Logs", height=100)
        log_frame.pack(fill="x", padx=10, pady=5)
        self.log_text = tk.Text(
            log_frame,
            height=6,
            state="disabled",
            bg="#000000",
            fg="#FFFFFF",
            font=("Consolas", 9),
        )
        self.log_text.pack(fill="both", expand=True)

        # Ensure a visible blinking text cursor in ttk Entry/Spinbox controls.
        for text_widget in [
            self.entry_input,
            self.entry_output,
            self.entry_model,
            self.spin_baseline,
            self.spin_prop_start,
            self.spin_prop_end,
            self.spin_export_start,
            self.spin_export_end,
            self.spin_analysis_start,
            self.spin_analysis_end,
            self.entry_seconds_per_frame,
        ]:
            try:
                text_widget.configure(insertbackground="#ffffff", insertwidth=2, insertontime=600, insertofftime=300)
            except Exception:
                try:
                    text_widget.configure(insertcolor="#ffffff", insertwidth=2, insertontime=600, insertofftime=300)
                except Exception:
                    pass

        # 5. Key Bindings
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
