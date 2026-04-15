from __future__ import annotations

from collections import OrderedDict
import gc
import sys
import threading
from datetime import datetime
from pathlib import Path
from time import perf_counter
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import numpy as np
from PIL import Image, ImageTk

from sdapp.analysis.ui.theme import CANVAS_BACKGROUND, SLIDER_OVERLAY_BACKGROUND, SPACING
from sdapp.analysis.core.state import AppConfig
from .browser_controller import BrowserController
from .config import APP_TITLE, DEFAULT_BASELINE_PRE_FRAMES, TraceResult
from .controllers import (
    AnalysisLaunchController,
    HostDCTraceController,
    HostModelSetupController,
    HostProjectLifecycleController,
    HostWindowController,
)
from .mark_popup_controller import MarkPopupController
from .processing_engine import PopupProcessRequest, PopupProcessResult, PopupProcessingEngine
from .preview_controller import HostPreviewController
from .stack_reader import StackReader
from .ui_geometry import (
    adjust_baseline_end_for_start,
    clamp_popup_range,
    linear_value_to_x,
    linear_x_to_value,
)

from sdapp.shared.services import AnalysisWindowManager, CheckpointRuntimeService, SingleInstanceBridge
from sdapp.shared.menu.factory import build_shared_menu
from sdapp.shared.app_metadata import format_window_title
from sdapp.shared.frame_source import normalize_visual_frame
from sdapp.shared.ui.bootstrap import center_window_on_screen, semantic_button_options


class SDAnalyzerApp:
    def __init__(
        self,
        root: tk.Tk,
        *,
        initial_project_path: str | None = None,
        instance_bridge: SingleInstanceBridge | None = None,
    ):
        self.root = root
        self.root.title(format_window_title(APP_TITLE))
        self.root.geometry("1400x900")
        center_window_on_screen(self.root, width=1400, height=900)
        self._app_icon_image: ImageTk.PhotoImage | None = None
        self._apply_runtime_icon()
        self._instance_bridge = instance_bridge

        self.reader: StackReader | None = None
        self.stack_info = None
        self.trace: TraceResult | None = None
        self.browser_controller = BrowserController()
        self.preview_controller = HostPreviewController(self)
        self.window_controller = HostWindowController(self)
        self.project_controller = HostProjectLifecycleController(self)
        self.analysis_launch_controller = AnalysisLaunchController(self)
        self.checkpoint_runtime = CheckpointRuntimeService()
        self.model_setup_controller = HostModelSetupController(self)
        self.dc_trace_controller = HostDCTraceController(self)
        self.config = AppConfig.load()
        self.current_event_id: str | None = None
        self.current_frame_idx = 0
        self.current_project_path: str | None = None
        self.popup_controller = MarkPopupController(self)
        self.baseline_pre_frames = DEFAULT_BASELINE_PRE_FRAMES
        default_descriptor = self.checkpoint_runtime.default_descriptor()
        self._active_model_token = f"managed://{default_descriptor.checkpoint_id}" if default_descriptor else ""
        self._manual_model_override: str | None = None
        self._active_model_path: str | None = None
        self._active_checkpoint_id: str | None = None
        self._active_model_metadata: dict[str, object] | None = None
        self._model_setup_ready = False
        self._model_setup_disabled = False
        self._model_setup_reason = "Model setup required."
        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar(value=str(Path.cwd() / "output"))

        self.tk_preview_image: ImageTk.PhotoImage | None = None
        self.max_log_lines = 500
        self._load_progress_bucket = -1
        self._export_progress_bucket = -1

        self._mark_popup: tk.Toplevel | None = None
        self._mark_popup_mode: str | None = None
        self._mark_popup_event_id: str | None = None
        self._mark_popup_anchor_idx = 0
        self._mark_popup_current_idx = 0
        self._mark_popup_local_start = 0
        self._mark_popup_local_end = 0
        self._mark_popup_image: ImageTk.PhotoImage | None = None
        self._mark_popup_mini_image: ImageTk.PhotoImage | None = None
        self._mark_start_var: tk.StringVar | None = None
        self._mark_end_var: tk.StringVar | None = None
        self._mark_baseline_count_var: tk.StringVar | None = None
        self._mark_baseline_end_var: tk.StringVar | None = None
        self._mark_contrast_var: tk.DoubleVar | None = None
        self._mark_contrast_label_var: tk.StringVar | None = None
        self._mark_frame_info_var: tk.StringVar | None = None
        self._mark_window_info_var: tk.StringVar | None = None
        self._mark_scale: tk.Scale | None = None
        self._mark_preview_label: ttk.Label | None = None
        self._mark_overlay: tk.Canvas | None = None
        self._mark_range_canvas: tk.Canvas | None = None
        self._mark_range_active_handle: str | None = None
        self._mark_range_start_idx = 0
        self._mark_range_end_idx = 0
        self._mark_last_full_refresh_note: str = ""
        self._mark_loading_var: tk.StringVar | None = None
        self._mark_loading_label: ttk.Label | None = None
        self._mark_loading_bar: ttk.Progressbar | None = None
        self._mark_main_view_shell: ttk.Frame | None = None
        self._mark_mini_frame: ttk.Frame | None = None
        self._mark_mini_canvas: tk.Canvas | None = None
        self._mark_mini_grip: tk.Label | None = None
        self._mark_resize_start_x: int | None = None
        self._mark_resize_start_y: int | None = None
        self._mark_resize_start_w: int | None = None
        self._mark_resize_start_h: int | None = None
        self._mark_recompute_after_id: str | None = None
        self._mark_recompute_show_errors = False
        self._mark_baseline_frame: np.ndarray | None = None
        self._mark_norm_p1: float = 0.0
        self._mark_norm_p99: float = 1.0
        self._mark_processed_cache: OrderedDict[int, np.ndarray] = OrderedDict()
        self._mark_processed_cache_max = 32
        self._popup_job_seq = 0
        self._popup_active_job_id = 0
        self._popup_engine = PopupProcessingEngine(smoothed_cache_max=64, baseline_cache_max=16, norm_cache_max=32)
        self.preview_overlay: tk.Canvas | None = None
        self._main_render_cache: OrderedDict[tuple[int, int, int], ImageTk.PhotoImage] = OrderedDict()
        self._main_render_cache_max = 24
        self._normalized_frame_u8_cache: OrderedDict[tuple[int, str], np.ndarray] = OrderedDict()
        self._normalized_frame_u8_cache_max = 64
        self._pending_main_frame_idx: int | None = None
        self._pending_main_after_id: str | None = None
        self._pending_popup_frame_idx: int | None = None
        self._pending_popup_after_id: str | None = None
        self._last_log_msg: str = ""
        self._last_log_time: float = 0.0
        self._cache_gc_after_id: str | None = None
        self._mark_processed_cache_max_bytes = 220 * 1024 * 1024
        self._normalized_frame_u8_cache_max_bytes = 160 * 1024 * 1024
        self._analysis_windows: list[tuple[tk.Toplevel, object]] = []
        self.analysis_window_manager = AnalysisWindowManager()
        self._analysis_options_preview_image: ImageTk.PhotoImage | None = None
        self._analysis_preview_cache: OrderedDict[tuple, dict[str, object]] = OrderedDict()
        self._analysis_app_class_cache = None
        self._analysis_app_import_started = False
        self._last_scale_image_path = ""
        self._logs_expanded = False
        self._main_overlay_regions: list[tuple[float, float, str]] = []
        self._log_summary_var = tk.StringVar(value="Ready")
        self.preview_label_meta = tk.StringVar(value="")

        self._build_ui()
        self._refresh_model_gate_ui()
        self._build_menu()
        self.root.protocol("WM_DELETE_WINDOW", self._on_root_close)
        self._register_platform_open_handlers()
        self._start_instance_listener()
        if initial_project_path:
            self.root.after(0, lambda p=str(initial_project_path): self.open_project_request(p))
        self._schedule_periodic_cache_gc()
        self.root.after(0, self._run_model_startup_preflight)

    def _resource_root(self) -> Path:
        return Path(__file__).resolve().parents[1] / "resources"

    def _apply_runtime_icon(self) -> None:
        try:
            icon_path = self._resource_root() / "assets" / "app_icon_runtime.png"
            if not icon_path.exists():
                return
            icon_image = tk.PhotoImage(file=str(icon_path))
            self.root.iconphoto(True, icon_image)
            # Keep a strong reference so Tk doesn't release the icon image.
            self._app_icon_image = icon_image
        except Exception:
            # Icon failures should never block app startup.
            return

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        main = ttk.Frame(self.root, padding=SPACING.outer, style="AppShell.TFrame")
        main.grid(row=0, column=0, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)

        self.status_var = tk.StringVar(value="Idle")
        ttk.Label(main, textvariable=self.status_var, style="AppMeta.TLabel").grid(row=0, column=0, sticky="w", pady=(0, SPACING.inner))

        body = ttk.Panedwindow(main, orient="horizontal")
        body.grid(row=1, column=0, sticky="nsew")
        self.body_split = body

        left = ttk.Frame(body, style="AppShell.TFrame")
        right = ttk.Frame(body, style="AppSidebar.TFrame")
        body.add(left, weight=6)
        body.add(right, weight=2)

        viewer_card = ttk.Frame(left, padding=(SPACING.card, SPACING.card, SPACING.card, SPACING.card), style="AppSurface.TFrame")
        viewer_card.grid(row=0, column=0, sticky="nsew", padx=(0, SPACING.inner))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        viewer_card.columnconfigure(0, weight=1)
        viewer_card.rowconfigure(1, weight=1)

        ttk.Label(viewer_card, text="Frame Viewer", style="AppSectionTitle.TLabel").grid(row=0, column=0, sticky="w")

        viewer_shell = ttk.Frame(viewer_card, padding=(0, SPACING.inner, 0, 0), style="AppSurface.TFrame")
        viewer_shell.grid(row=1, column=0, sticky="nsew")
        viewer_shell.columnconfigure(0, weight=1)
        viewer_shell.rowconfigure(0, weight=1)

        canvas_shell = ttk.Frame(viewer_shell, style="AppInset.TFrame")
        canvas_shell.grid(row=0, column=0, sticky="nsew")
        canvas_shell.columnconfigure(0, weight=1)
        canvas_shell.rowconfigure(0, weight=1)

        self.preview_label = ttk.Label(canvas_shell, anchor="center")
        self.preview_label.grid(row=0, column=0, sticky="nsew", padx=SPACING.gap, pady=SPACING.gap)

        self.preview_label_info = tk.StringVar(value="Frame -")
        preview_overlay_frame = ttk.Frame(canvas_shell, padding=(8, 6), style="AppOverlay.TFrame")
        preview_overlay_frame.place(relx=0.0, rely=1.0, anchor="sw", x=10, y=-10)
        ttk.Label(preview_overlay_frame, textvariable=self.preview_label_info, style="AppOverlayValue.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(preview_overlay_frame, textvariable=self.preview_label_meta, style="AppOverlayMeta.TLabel").grid(row=1, column=0, sticky="w")

        self.preview_overlay = tk.Canvas(
            viewer_shell,
            height=18,
            bg=SLIDER_OVERLAY_BACKGROUND,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.preview_overlay.grid(row=1, column=0, sticky="ew", pady=(SPACING.inner, 4))
        self.preview_overlay.bind("<Configure>", lambda _e: self._redraw_main_overlay())
        self.preview_overlay.bind("<Button-1>", self._on_main_overlay_click)
        self.preview_overlay.bind("<Motion>", self._on_main_overlay_motion, add="+")
        self.preview_overlay.bind("<Leave>", self._hide_main_overlay_tooltip, add="+")

        self.preview_scale = ttk.Scale(
            viewer_shell,
            from_=0,
            to=1,
            orient="horizontal",
            command=self._on_preview_slide,
            style="AppFlat.Horizontal.TScale",
        )
        self.preview_scale.grid(row=2, column=0, sticky="ew", pady=(0, SPACING.inner))

        nav_row = ttk.Frame(viewer_shell, style="AppSurface.TFrame")
        nav_row.grid(row=3, column=0, sticky="ew")
        for column in range(3):
            nav_row.columnconfigure(column, weight=1)
        ttk.Button(nav_row, text="Prev", command=lambda: self._step_preview(-1), **semantic_button_options("secondary")).grid(
            row=0,
            column=0,
            sticky="ew",
        )
        ttk.Button(nav_row, text="Mark SD", command=self._mark_sd, **semantic_button_options("primary")).grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(SPACING.gap, SPACING.gap),
        )
        ttk.Button(nav_row, text="Next", command=lambda: self._step_preview(1), **semantic_button_options("secondary")).grid(
            row=0,
            column=2,
            sticky="ew",
        )

        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        right.rowconfigure(1, weight=0)
        right_top = ttk.Frame(right, style="AppSidebar.TFrame")
        right_top.grid(row=0, column=0, sticky="nsew")
        right_bottom = ttk.Frame(right, style="AppSidebar.TFrame")
        right_bottom.grid(row=1, column=0, sticky="ew", pady=(SPACING.gap, 0))

        right_top.columnconfigure(0, weight=1)
        right_top.rowconfigure(0, weight=1)
        right_top.rowconfigure(1, weight=0)
        right_bottom.columnconfigure(0, weight=1)
        right_bottom.rowconfigure(0, weight=0)

        table_frame = ttk.Frame(right_top, padding=(SPACING.card, SPACING.card, SPACING.card, SPACING.gap), style="AppSidebar.TFrame")
        table_frame.grid(row=0, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(1, weight=1)
        ttk.Label(table_frame, text="Marked SD Events", style="AppSidebarTitle.TLabel").grid(row=0, column=0, sticky="w")

        table_shell = ttk.Frame(table_frame, padding=(0, SPACING.inner, 0, 0), style="AppSidebar.TFrame")
        table_shell.grid(row=1, column=0, sticky="nsew")
        table_shell.columnconfigure(0, weight=1)
        table_shell.rowconfigure(0, weight=1)
        table_inset = ttk.Frame(table_shell, style="AppInset.TFrame")
        table_inset.grid(row=0, column=0, sticky="nsew")
        table_inset.columnconfigure(0, weight=1)
        table_inset.rowconfigure(0, weight=1)

        columns = ("id", "start", "end", "duration")
        self.tree = ttk.Treeview(table_inset, columns=columns, show="headings", height=12, selectmode="extended")
        for col, width in [("id", 160), ("start", 75), ("end", 75), ("duration", 95)]:
            heading_text = "NAME" if col == "id" else col.upper()
            self.tree.heading(col, text=heading_text)
            self.tree.column(col, width=width, anchor="center")
        self.tree.grid(row=0, column=0, sticky="nsew", padx=SPACING.gap, pady=SPACING.gap)
        self.tree.bind("<<TreeviewSelect>>", self._on_event_select)
        self.tree.bind("<Button-2>", self._on_event_tree_context_menu)
        self.tree.bind("<Button-3>", self._on_event_tree_context_menu)

        ttk.Separator(right_top, orient="horizontal").grid(row=1, column=0, sticky="ew", pady=(0, SPACING.gap))

        action_frame = ttk.Frame(right_top, padding=(SPACING.card, SPACING.gap, SPACING.card, SPACING.card), style="AppSidebar.TFrame")
        action_frame.grid(row=2, column=0, sticky="ew")
        action_frame.columnconfigure(0, weight=1)
        action_frame.columnconfigure(1, weight=1)
        ttk.Label(action_frame, text="Event Actions", style="AppSidebarTitle.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Button(action_frame, text="Edit Selected", command=self._edit_selected, **semantic_button_options("secondary")).grid(
            row=1, column=0, sticky="ew", pady=(SPACING.inner, SPACING.gap)
        )
        ttk.Button(
            action_frame,
            text="Delete Selected",
            command=self._delete_selected_events,
            **semantic_button_options("danger"),
        ).grid(row=1, column=1, sticky="ew", padx=(SPACING.gap, 0), pady=(SPACING.inner, SPACING.gap))
        self.btn_open_analysis = ttk.Button(
            action_frame,
            text="Open Analysis...",
            command=self._analyze_selected_event,
            **semantic_button_options("secondary"),
        )
        self.btn_open_analysis.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, SPACING.gap))
        ttk.Button(
            action_frame,
            text="Open Metrics...",
            command=self._open_generate_metrics_popup,
            **semantic_button_options("secondary"),
        ).grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, SPACING.gap))
        ttk.Button(action_frame, text="Export Selected", command=self._export_selected, **semantic_button_options("secondary")).grid(
            row=4, column=0, sticky="ew"
        )
        ttk.Button(action_frame, text="Export All", command=self._export_all, **semantic_button_options("secondary")).grid(
            row=4, column=1, sticky="ew", padx=(SPACING.gap, 0)
        )

        logs_frame = ttk.Frame(right_bottom, padding=(SPACING.card, SPACING.gap, SPACING.card, SPACING.gap), style="AppSidebar.TFrame")
        logs_frame.grid(row=0, column=0, sticky="nsew")
        logs_frame.columnconfigure(0, weight=1)
        logs_frame.rowconfigure(1, weight=1)

        logs_header = ttk.Frame(logs_frame, style="AppSidebar.TFrame")
        logs_header.grid(row=0, column=0, sticky="ew")
        logs_header.columnconfigure(0, weight=1)
        self.lbl_log_summary = ttk.Label(logs_header, textvariable=self._log_summary_var, style="AppMeta.TLabel", cursor="hand2")
        self.lbl_log_summary.grid(row=0, column=0, sticky="ew")
        self.lbl_log_summary.bind("<Button-1>", lambda _event: self._toggle_logs_expanded())
        self.btn_toggle_logs = ttk.Button(logs_header, text="Show Logs", command=self._toggle_logs_expanded, **semantic_button_options("secondary"))
        self.btn_toggle_logs.grid(
            row=0,
            column=1,
            sticky="e",
        )
        self.btn_clear_logs = ttk.Button(logs_header, text="Clear", command=self._clear_logs, **semantic_button_options("secondary"))
        self.btn_clear_logs.grid(row=0, column=2, sticky="e", padx=(SPACING.gap, 0))

        log_shell = ttk.Frame(logs_frame, style="AppInset.TFrame")
        log_shell.grid(row=1, column=0, sticky="nsew", pady=(SPACING.inner, 0))
        log_shell.columnconfigure(0, weight=1)
        log_shell.rowconfigure(0, weight=1)
        self.log_shell = log_shell
        self.log_text = tk.Text(
            log_shell,
            height=5,
            wrap="word",
            state="disabled",
            bg=CANVAS_BACKGROUND,
            fg="#c4cdd6",
            insertbackground="#c4cdd6",
            relief="flat",
            highlightthickness=0,
            bd=0,
            padx=8,
            pady=8,
        )
        log_scroll = ttk.Scrollbar(log_shell, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=(SPACING.gap, 0), pady=SPACING.gap)
        log_scroll.grid(row=0, column=1, sticky="ns", padx=(0, SPACING.gap), pady=SPACING.gap)
        self._set_logs_expanded(False)

        self.root.after(150, self._reset_main_layout)
        self._bind_main_keys()
        self._log_info("Application started in manual SD marking mode.")

    def _build_menu(self) -> None:
        build_shared_menu(self.root, self, mode="host", host_mode=False)

    def _register_platform_open_handlers(self) -> None:
        if sys.platform != "darwin":
            return
        try:
            self.root.createcommand("::tk::mac::OpenDocument", self._on_mac_open_document)
        except Exception:
            return

    def _on_mac_open_document(self, *paths: str) -> None:
        for path in paths:
            candidate = str(path or "").strip()
            if candidate:
                self.open_project_request(candidate)

    def _start_instance_listener(self) -> None:
        bridge = self._instance_bridge
        if bridge is None:
            return

        def _on_open_path(path: str) -> None:
            self.root.after(0, lambda p=str(path): self.open_project_request(p))

        started = bridge.start_listener(_on_open_path)
        if not started:
            self._log_warn("Single-instance listener unavailable; external .sdproj forwarding is disabled.")

    def _set_status(self, text: str) -> None:
        self.status_var.set(text)

    def _clear_logs(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self._log_info("Logs cleared.")

    def _set_logs_expanded(self, expanded: bool) -> None:
        self._logs_expanded = bool(expanded)
        shell = getattr(self, "log_shell", None)
        if shell is not None:
            if self._logs_expanded:
                shell.grid()
            else:
                shell.grid_remove()
        if hasattr(self, "btn_toggle_logs"):
            self.btn_toggle_logs.configure(text="Hide" if self._logs_expanded else "Logs")
        if hasattr(self, "btn_clear_logs"):
            if self._logs_expanded:
                self.btn_clear_logs.grid()
                self.btn_clear_logs.configure(state="normal")
            else:
                self.btn_clear_logs.grid_remove()

    def _toggle_logs_expanded(self) -> None:
        self._set_logs_expanded(not bool(getattr(self, "_logs_expanded", False)))

    def _reset_main_layout(self) -> None:
        if not hasattr(self, "body_split"):
            return
        total = max(self.body_split.winfo_width(), self.root.winfo_width())
        target = int(total * 0.74)
        try:
            self.body_split.sashpos(0, target)
        except Exception:
            pass

    def _focus_is_entry(self, event_widget) -> bool:
        if event_widget is None:
            return False
        klass = str(getattr(event_widget, "winfo_class", lambda: "")())
        return "Entry" in klass

    def _bind_main_keys(self) -> None:
        self.root.bind("<Left>", lambda e: self._handle_main_key(e, -1))
        self.root.bind("<Right>", lambda e: self._handle_main_key(e, 1))
        self.root.bind("<Shift-Left>", lambda e: self._handle_main_key(e, -10))
        self.root.bind("<Shift-Right>", lambda e: self._handle_main_key(e, 10))
        self.root.bind("<Up>", lambda e: self._handle_main_key(e, 10))
        self.root.bind("<Down>", lambda e: self._handle_main_key(e, -10))

    def _bind_popup_keys(self, popup: tk.Toplevel) -> None:
        popup.bind("<Left>", lambda e: self._handle_popup_key(e, -1))
        popup.bind("<Right>", lambda e: self._handle_popup_key(e, 1))
        popup.bind("<Shift-Left>", lambda e: self._handle_popup_key(e, -10))
        popup.bind("<Shift-Right>", lambda e: self._handle_popup_key(e, 10))
        popup.bind("<Up>", lambda e: self._handle_popup_key(e, 10))
        popup.bind("<Down>", lambda e: self._handle_popup_key(e, -10))

    def _handle_main_key(self, event, step: int):
        if self.stack_info is None:
            return None
        if self._focus_is_entry(getattr(event, "widget", None)):
            return None
        if self._mark_popup is not None and self._mark_popup.winfo_exists():
            return None
        self._step_preview(step)
        return "break"

    def _handle_popup_key(self, event, step: int):
        if self._focus_is_entry(getattr(event, "widget", None)):
            return None
        self._popup_step(step)
        return "break"

    def _log(self, level: str, message: str) -> None:
        now = perf_counter()
        if level == "INFO" and message == self._last_log_msg and (now - self._last_log_time) < 0.3:
            return
        self._last_log_msg = message
        self._last_log_time = now
        prefix = "" if level == "INFO" else f"{level} "
        line = f"{datetime.now().strftime('%H:%M:%S')} {prefix}{message}\n"
        if threading.current_thread() is threading.main_thread():
            self._append_log_line(line)
        else:
            self.root.after(0, lambda: self._append_log_line(line))

    def _append_log_line(self, line: str) -> None:
        clean = str(line).strip()
        if clean:
            self._log_summary_var.set(self._summarize_log_line(clean))
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line)
        total_lines = int(float(self.log_text.index("end-1c").split(".")[0]))
        if total_lines > self.max_log_lines:
            remove_count = total_lines - self.max_log_lines
            self.log_text.delete("1.0", f"{remove_count + 1}.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    @staticmethod
    def _summarize_log_line(line: str, *, max_length: int = 44) -> str:
        text = " ".join(str(line or "").split())
        if len(text) <= int(max_length):
            return text
        return text[: max(1, int(max_length) - 1)].rstrip() + "…"

    def _log_info(self, message: str) -> None:
        self._log("INFO", message)

    def _log_warn(self, message: str) -> None:
        self._log("WARN", message)

    def _log_error(self, message: str) -> None:
        self._log("ERROR", message)

    @property
    def events(self):
        return self.browser_controller.list_events()

    def _active_event_id(self) -> str | None:
        return self.browser_controller.get_active_event_id()

    def _set_active_event_id(self, event_id: str | None) -> None:
        self.browser_controller.set_active_event(event_id)
        self.current_event_id = self.browser_controller.get_active_event_id()

    def _sync_event_projections(self) -> None:
        self.refresh_event_table(self.events)
        self.refresh_timeline_overlays(self.events, self._active_event_id())

    def refresh_event_table(self, events) -> None:
        selected = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        for event in events:
            display_name = str(getattr(event, "label", "") or "").strip() or str(event.event_id)
            values = (display_name, event.start_idx, event.end_idx, event.duration_frames)
            self.tree.insert("", "end", iid=event.event_id, values=values)
        for event_id in list(selected):
            if self.tree.exists(event_id):
                self.tree.selection_add(event_id)
        self._refresh_model_gate_ui()

    def refresh_timeline_overlays(self, _events, _active_event_id: str | None) -> None:
        self._redraw_main_overlay()
        self.dc_trace_controller.on_events_changed()

    def _show_warning(self, title: str, text: str) -> None:
        messagebox.showwarning(title, text, parent=self.root)

    def _ensure_main_overlay_tooltip(self):
        tip = getattr(self, "_main_overlay_tooltip", None)
        if tip is not None:
            return tip
        tip = tk.Toplevel(self.root)
        tip.withdraw()
        tip.overrideredirect(True)
        frame = ttk.Frame(tip, padding=(8, 5), style="AppOverlay.TFrame")
        frame.grid(row=0, column=0, sticky="nsew")
        label = ttk.Label(frame, text="", style="AppOverlayMeta.TLabel")
        label.grid(row=0, column=0, sticky="w")
        self._main_overlay_tooltip = tip
        self._main_overlay_tooltip_label = label
        return tip

    def _show_main_overlay_tooltip(self, event, text: str) -> None:
        if not text:
            self._hide_main_overlay_tooltip()
            return
        tip = self._ensure_main_overlay_tooltip()
        self._main_overlay_tooltip_label.configure(text=str(text))
        tip.geometry(f"+{int(event.x_root) + 12}+{int(event.y_root) + 12}")
        tip.deiconify()
        tip.lift()

    def _hide_main_overlay_tooltip(self, _event=None) -> None:
        tip = getattr(self, "_main_overlay_tooltip", None)
        if tip is None:
            return
        try:
            tip.withdraw()
        except Exception:
            pass

    def _on_main_overlay_motion(self, event) -> None:
        for left, right, text in list(getattr(self, "_main_overlay_regions", [])):
            if float(left) <= float(event.x) <= float(right):
                self._show_main_overlay_tooltip(event, text)
                return
        self._hide_main_overlay_tooltip()

    def save_host_session(self, path: str | None = None):
        return self.browser_controller.save_session(path)

    def _new_project(self) -> None:
        self._get_project_controller().new_project()

    def _save_project(self) -> None:
        self._get_project_controller().save_project()

    def _save_project_as(self) -> None:
        self._get_project_controller().save_project_as()

    def update_project_model_to_active(self) -> None:
        self.model_setup_controller.update_project_model_to_active()

    def on_browse_model(self) -> None:
        self.model_setup_controller.on_browse_model()

    def load_model_from_menu(self) -> None:
        self.model_setup_controller.load_model()

    def validate_assets_from_menu(self) -> None:
        self.model_setup_controller.validate_assets()

    def _open_project_dialog(self) -> None:
        self._get_project_controller().open_project_dialog()

    def _open_project(self, path: str) -> None:
        self._get_project_controller().open_project(path)

    def open_project_request(self, path: str) -> bool:
        return self._get_project_controller().open_project_request(path)

    def _import_dc_trace(self) -> None:
        self.dc_trace_controller.import_dc_trace()

    def import_dc_trace(self) -> None:
        self._import_dc_trace()

    def _remove_dc_trace(self) -> None:
        self.dc_trace_controller.remove_dc_trace()

    def remove_dc_trace(self) -> None:
        self._remove_dc_trace()

    def _restore_dc_trace_from_project(self) -> None:
        self.dc_trace_controller.restore_from_project_metadata()

    def get_trace_time_for_frame(self, frame_idx: int) -> float | None:
        return self.dc_trace_controller.get_trace_time_for_frame(frame_idx)

    def get_frame_for_trace_time(self, t_s: float) -> int | None:
        return self.dc_trace_controller.get_frame_for_trace_time(t_s)

    def get_trace_value_at_frame(self, frame_idx: int) -> float | None:
        return self.dc_trace_controller.get_trace_value_at_frame(frame_idx)

    def get_trace_window(self, t0_s: float, t1_s: float) -> np.ndarray:
        return self.dc_trace_controller.get_trace_window(t0_s, t1_s)

    def get_analysis_handoff_payload(self) -> dict | None:
        return self.browser_controller.handoff.selected_event_payload()

    def _on_analysis_sync(self, payload: dict) -> None:
        self._get_project_controller().on_analysis_sync(payload)

    def _on_analysis_state_update(self, payload: dict) -> dict:
        return self._get_project_controller().on_analysis_state_update(payload)

    def _on_analysis_metrics_update(self, payload: dict) -> dict:
        return self._get_project_controller().on_analysis_metrics_update(payload)

    def _on_analysis_global_metrics_update(self, payload: dict) -> dict:
        return self._get_project_controller().on_analysis_global_metrics_update(payload)

    def _on_analysis_checkpoint_update(self, payload: dict) -> dict:
        return self._get_project_controller().on_analysis_checkpoint_update(payload)

    def _on_analysis_sync_result(self, result: dict) -> None:
        self._get_project_controller().on_analysis_sync_result(result)

    def _on_analysis_log_message(self, level: str, context: str, message: str) -> None:
        self._get_project_controller().on_analysis_log_message(level, context, message)

    def _on_analysis_project_saved(self, project_path: str) -> None:
        self._get_project_controller().on_analysis_project_saved(project_path)

    def _save_project_from_analysis(self, project_path: str) -> dict:
        return self._get_project_controller().save_project_from_analysis(project_path)

    def open_model_manager(self) -> None:
        self._get_model_setup_controller().open_model_manager(required=False)

    def open_checkpoint_manager(self) -> None:
        # Backward-compatible alias for older callbacks.
        self.open_model_manager()

    def close_analysis_windows_with_prompt(self) -> dict:
        return self._get_project_controller().close_analysis_windows_with_prompt()

    def prepare_context_switch(self) -> bool:
        return self._get_project_controller().prepare_context_switch()

    def _load_analysis_app_class(self):
        return self._get_analysis_launch_controller().load_analysis_app_class()

    @staticmethod
    def _preview_to_u8(frame: np.ndarray) -> np.ndarray:
        arr = np.asarray(frame, dtype=np.float32)
        if arr.ndim == 3 and arr.shape[2] in (3, 4):
            arr = arr[:, :, :3].mean(axis=2)
        return normalize_visual_frame(arr)

    def _get_first_frame_original_u8(self) -> np.ndarray | None:
        if self.reader is None:
            return None
        try:
            frame = self.reader.read_frame(0, use_cache=True)
        except TypeError:
            frame = self.reader.read_frame(0)
        except Exception:
            return None
        arr = np.asarray(frame, dtype=np.float32)
        if arr.ndim == 3 and arr.shape[2] in (3, 4):
            arr = arr[:, :, :3].mean(axis=2)
        if arr.ndim != 2:
            return None
        return self._preview_to_u8(arr)

    def _metrics_picker_initial_dir(self) -> str:
        raw = ""
        input_var = getattr(self, "input_var", None)
        if input_var is not None and hasattr(input_var, "get"):
            try:
                raw = str(input_var.get() or "").strip()
            except Exception:
                raw = ""
        if raw:
            candidate = Path(raw).expanduser()
            if candidate.is_dir():
                return str(candidate.resolve())
        stack_info = getattr(self, "stack_info", None)
        if stack_info is not None:
            stack_dir = Path(str(getattr(stack_info, "input_dir", "") or "")).expanduser()
            if stack_dir.is_dir():
                return str(stack_dir.resolve())
        return str(Path.cwd())

    def _metrics_picker_initial_file(self) -> str:
        reader = getattr(self, "reader", None)
        if reader is None:
            return ""
        try:
            frame_count = int(reader.get_frame_count())
        except Exception:
            return ""
        if frame_count <= 0:
            return ""
        try:
            idx = int(getattr(self, "current_frame_idx", 0))
        except Exception:
            idx = 0
        idx = max(0, min(idx, frame_count - 1))
        try:
            ref = reader.get_frame_ref(idx)
            source_path = Path(str(getattr(ref, "source_path", "") or "")).expanduser()
            name = source_path.name
            return str(name or "")
        except Exception:
            return ""

    def _load_metrics_reference_image_u8(self, image_path: str | Path) -> np.ndarray | None:
        path = Path(image_path).expanduser().resolve()
        if not path.exists() or not path.is_file():
            return None

        # Prefer stack reader decoding so multipage TIFF selections map to the loaded stack format.
        reader = getattr(self, "reader", None)
        if reader is not None:
            try:
                frame_count = int(reader.get_frame_count())
            except Exception:
                frame_count = 0
            if frame_count > 0:
                for idx in range(frame_count):
                    try:
                        ref = reader.get_frame_ref(idx)
                        ref_path = Path(str(getattr(ref, "source_path", "") or "")).expanduser().resolve()
                    except Exception:
                        continue
                    if ref_path != path:
                        continue
                    try:
                        frame = reader.read_frame(int(idx), use_cache=True)
                    except TypeError:
                        frame = reader.read_frame(int(idx))
                    except Exception:
                        break
                    arr = np.asarray(frame, dtype=np.float32)
                    if arr.ndim == 3 and arr.shape[2] in (3, 4):
                        arr = arr[:, :, :3].mean(axis=2)
                    if arr.ndim != 2:
                        return None
                    return self._preview_to_u8(arr)

        # Fallback loader for paths outside the active stack.
        try:
            if path.suffix.lower() in {".tif", ".tiff"}:
                import tifffile

                raw = np.asarray(tifffile.imread(str(path)))
                if raw.ndim == 3 and raw.shape[2] not in (3, 4):
                    raw = raw[0]
            else:
                with Image.open(path) as image:
                    raw = np.asarray(image)
        except Exception:
            return None

        arr = np.asarray(raw, dtype=np.float32)
        if arr.ndim == 3 and arr.shape[2] in (3, 4):
            arr = arr[:, :, :3].mean(axis=2)
        elif arr.ndim > 2:
            arr = np.asarray(arr).squeeze()
            if arr.ndim == 3 and arr.shape[2] in (3, 4):
                arr = arr[:, :, :3].mean(axis=2)
        if arr.ndim != 2:
            return None
        return self._preview_to_u8(arr)

    def _pick_metrics_reference_image_u8(
        self,
        *,
        parent,
        purpose: str,
    ) -> np.ndarray | None:
        selected = ""
        if str(purpose or "").lower() == "scale":
            last_scale_image_path = str(getattr(self, "_last_scale_image_path", "") or "").strip()
            if last_scale_image_path and Path(last_scale_image_path).is_file():
                selected = last_scale_image_path
        if not selected:
            initialdir = self._metrics_picker_initial_dir()
            initialfile = self._metrics_picker_initial_file()
            selected = filedialog.askopenfilename(
                parent=parent,
                title=f"Select Image for {purpose}",
                initialdir=initialdir,
                initialfile=initialfile,
                filetypes=[
                    ("Image files", "*.tif *.tiff *.png *.jpg *.jpeg *.bmp"),
                    ("TIFF files", "*.tif *.tiff"),
                    ("All files", "*.*"),
                ],
            )
            if not selected:
                return None
            if str(purpose or "").lower() == "scale":
                self._last_scale_image_path = str(selected)
        img_u8 = self._load_metrics_reference_image_u8(selected)
        if img_u8 is None:
            self._show_warning(
                purpose,
                "Unable to load the selected image. Please choose a readable image file from the input stack.",
            )
            return None

        stack_info = getattr(self, "stack_info", None)
        if stack_info is not None:
            expected_h = int(getattr(stack_info, "frame_height", 0) or 0)
            expected_w = int(getattr(stack_info, "frame_width", 0) or 0)
            if expected_h > 0 and expected_w > 0:
                actual_h, actual_w = int(img_u8.shape[0]), int(img_u8.shape[1])
                if (actual_h, actual_w) != (expected_h, expected_w):
                    self._show_warning(
                        purpose,
                        (
                            "Selected image shape does not match the loaded stack.\n"
                            f"Expected: {expected_w}x{expected_h}\n"
                            f"Got: {actual_w}x{actual_h}"
                        ),
                    )
                    return None
        return img_u8

    @staticmethod
    def _snap_scale_points_axis(p1, p2):
        x1, y1 = float(p1[0]), float(p1[1])
        x2, y2 = float(p2[0]), float(p2[1])
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        if dx >= dy:
            y = (y1 + y2) * 0.5
            return (x1, y), (x2, y), "horizontal"
        x = (x1 + x2) * 0.5
        return (x, y1), (x, y2), "vertical"

    def _refine_scale_bar_points(self, _img_u8, p1, p2, linewidth=7, endpoint_window_px=8, force_axis=False):
        del linewidth, endpoint_window_px
        p1_used = (float(p1[0]), float(p1[1]))
        p2_used = (float(p2[0]), float(p2[1]))
        axis_mode = "free"
        if bool(force_axis):
            p1_used, p2_used, axis_mode = self._snap_scale_points_axis(p1_used, p2_used)
        return {
            "p1_ref": p1_used,
            "p2_ref": p2_used,
            "refined_ok": False,
            "score": 1.0,
            "fallback": True,
            "axis_mode": axis_mode,
            "p1_snap": p1_used,
            "p2_snap": p2_used,
        }

    @staticmethod
    def _center_window_on_screen(window, *, width: int | None = None, height: int | None = None) -> None:
        center_window_on_screen(window, width=width, height=height)

    def _open_generate_metrics_popup(self) -> None:
        self._get_window_controller().open_generate_metrics_popup()

    def _compute_analysis_preview_frame(
        self,
        *,
        event_start: int,
        baseline_pre_frames: int,
        apply_horizontal_bar_denoise: bool,
        apply_smoothing: bool,
        apply_baseline_subtraction: bool,
        apply_global_normalization: bool,
    ) -> np.ndarray:
        return self._get_analysis_launch_controller().compute_analysis_preview_frame(
            event_start=event_start,
            baseline_pre_frames=baseline_pre_frames,
            apply_horizontal_bar_denoise=apply_horizontal_bar_denoise,
            apply_smoothing=apply_smoothing,
            apply_baseline_subtraction=apply_baseline_subtraction,
            apply_global_normalization=apply_global_normalization,
        )

    def _prompt_analysis_open_options(self, *, event_id: str, event_start: int, event_end: int) -> dict[str, object] | None:
        return self._get_analysis_launch_controller().prompt_analysis_open_options(
            event_id=event_id,
            event_start=event_start,
            event_end=event_end,
        )

    def _analyze_selected_event(self) -> None:
        self._get_analysis_launch_controller().analyze_selected_event()

    def _run_model_startup_preflight(self) -> None:
        self._get_model_setup_controller().run_startup_preflight()

    def _refresh_model_gate_ui(self) -> None:
        btn = getattr(self, "btn_open_analysis", None)
        if btn is None:
            return
        try:
            allowed = bool(self._model_setup_ready and not self._model_setup_disabled)
            selection = tuple(self.tree.selection()) if hasattr(self, "tree") else ()
            state = "disabled" if not allowed or len(selection) > 1 else "normal"
            # Keep a stable visual style here. The 0.1.6 UI overhaul regressed
            # this button by changing both state and style dynamically, which
            # made its rendered height drift from the adjacent action buttons.
            btn.configure(state=state, style="AppQuiet.TButton")
        except Exception:
            return

    def _on_root_close(self) -> None:
        self._get_project_controller().request_host_close()

    def _on_stack_loaded(self, reader: StackReader, info) -> None:
        self._get_project_controller().on_stack_loaded(reader, info)

    def _warmup_main_preview_async(self) -> None:
        self._get_project_controller().warmup_main_preview_async()

    def _on_load_progress(self, current: int, total: int) -> None:
        self._get_project_controller().on_load_progress(current, total)

    def _on_export_progress(self, payload: dict) -> None:
        event_name = str(payload.get("event_label", "") or payload.get("event_id", "?"))
        phase = payload.get("phase")
        if phase == "event":
            event_text = f"Export event {payload.get('current', 0)}/{payload.get('total', 0)}: {event_name}."
            self._set_status(event_text)
            self._log_info(event_text)
            return
        if phase == "analysis_prepare":
            total = int(payload.get("total", 0) or 0)
            current = int(payload.get("current", 0) or 0)
            if total <= 0:
                return
            stage = str(payload.get("stage", "prepare") or "prepare").replace("_", " ")
            percent = max(0, min(100, int((current * 100) / total)))
            self._set_status(
                f"Preparing analysis images for {event_name}: {current}/{total} ({percent}%) [{stage}]"
            )
            bucket = percent // 10
            key = (
                "analysis_prepare",
                str(event_name),
                str(payload.get("stage", "prepare")),
                int(bucket),
            )
            if key != getattr(self, "_last_export_analysis_prepare_key", None):
                self._last_export_analysis_prepare_key = key
                self._log_info(
                    f"Preparing analysis images for {event_name}: {current}/{total} ({percent}%) [{stage}]."
                )
            return
        if phase == "frame":
            total = int(payload.get("total", 0) or 0)
            current = int(payload.get("current", 0) or 0)
            if total <= 0:
                return
            bucket = int((current * 100) / total) // 5
            if bucket > self._export_progress_bucket:
                self._export_progress_bucket = bucket
                self._set_status(f"Exporting frames: {current}/{total} ({min(100, bucket * 5)}%)")
                self._log_info(f"Export progress: wrote {current}/{total} frames ({min(100, bucket * 5)}%).")

    def _on_event_select(self, _event=None) -> None:
        selected = self.tree.selection()
        if not selected:
            self._set_active_event_id(None)
            self._refresh_model_gate_ui()
            return

        self._set_active_event_id(selected[0])
        self._refresh_model_gate_ui()
        event = self._get_event_by_id(self._active_event_id())
        if event is None:
            return

        self.preview_scale.set(event.start_idx)
        self._update_preview(event.start_idx)

    def _get_event_by_id(self, event_id: str | None):
        return self.browser_controller.get_event(event_id)

    def _normalize_bounds(self, start: int, end: int) -> tuple[int, int, bool, bool]:
        if self.stack_info is None:
            raise RuntimeError("No stack loaded.")
        total = self.stack_info.frame_count
        if total <= 0:
            raise RuntimeError("Empty stack.")

        changed_by_clamp = start < 0 or end < 0 or start >= total or end >= total
        swapped = int(end) < int(start)
        start, end = self.browser_controller.normalize_bounds(start, end, total)

        return start, end, changed_by_clamp, swapped

    def _parse_frame_index(self, value: str, default_idx: int, field_name: str) -> int:
        raw = value.strip()
        if raw == "":
            return int(default_idx)
        try:
            return int(raw)
        except ValueError:
            try:
                return int(float(raw))
            except ValueError as exc:
                raise ValueError(f"{field_name} must be a frame number.") from exc

    def _duration_sec(self, duration_frames: int) -> float | None:
        return None

    def _mark_sd(self) -> None:
        self.popup_controller.open_new()

    def _edit_selected(self) -> None:
        self.popup_controller.open_edit_selected()

    def _rename_selected_event(self) -> None:
        selected = list(self.tree.selection())
        if not selected:
            self._log_warn("Rename Selected blocked: no event selected.")
            self._show_warning("SD Event", "Select one event first.")
            return
        if len(selected) != 1:
            self._log_warn("Rename Selected blocked: multiple events selected.")
            self._show_warning("SD Event", "Select exactly one event to rename.")
            return
        event = self._get_event_by_id(selected[0])
        if event is None:
            self._log_warn("Rename Selected blocked: selected event not found.")
            self._show_warning("SD Event", "Selected event was not found.")
            return
        new_label = simpledialog.askstring(
            "Rename SD Event",
            "Event name:",
            initialvalue=str(event.label),
            parent=self.root,
        )
        if new_label is None:
            return
        cleaned = str(new_label).strip()
        if not cleaned:
            self._show_warning("Rename SD Event", "Event name cannot be empty.")
            return
        updated = self.browser_controller.update_event(
            event.event_id,
            start_idx=None,
            end_idx=None,
            label=cleaned,
            frame_count=int(self.stack_info.frame_count) if self.stack_info is not None else int(event.end_idx + 1),
            flags=dict(event.flags),
        )
        self._sync_event_projections()
        if self.tree.exists(updated.event_id):
            self.tree.selection_set(updated.event_id)
            self.tree.see(updated.event_id)
        self._set_active_event_id(updated.event_id)
        self._set_status(f"Renamed {updated.event_id}.")
        self._log_info(f"Renamed {updated.event_id} to '{cleaned}'.")

    def _open_mark_popup(self, mode: str, event_id: str | None) -> None:
        self.popup_controller.open_popup(mode=mode, event_id=event_id)

    def _on_event_tree_context_menu(self, event) -> str | None:
        if not hasattr(self, "tree") or self.tree is None:
            return None
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return None
        self.tree.selection_set(row_id)
        self.tree.focus(row_id)
        self._on_event_select()
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Rename Event", command=self._rename_selected_event)
        menu.add_command(label="Edit Bounds", command=self._edit_selected)
        menu.add_separator()
        menu.add_command(label="Delete Event", command=self._delete_selected_events)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    def _on_mark_popup_destroy(self, _event=None) -> None:
        self.popup_controller.on_destroy(_event)

    def _popup_step(self, delta: int) -> None:
        if self.stack_info is None or self._mark_scale is None:
            return
        low, high = self._popup_overlay_bounds()
        idx = max(low, min(self._mark_popup_current_idx + int(delta), high))
        self._mark_scale.set(idx)
        self._popup_update_preview(idx)

    def _popup_on_slide(self, value: str) -> None:
        idx = int(float(value))
        self._schedule_popup_preview_update(idx)

    def _schedule_popup_preview_update(self, idx: int) -> None:
        if self._mark_popup is None or not self._mark_popup.winfo_exists():
            return
        self._pending_popup_frame_idx = int(idx)
        if self._pending_popup_after_id is not None:
            try:
                self._mark_popup.after_cancel(self._pending_popup_after_id)
            except Exception:
                pass
        self._pending_popup_after_id = self._mark_popup.after(16, self._flush_popup_preview_update)

    def _flush_popup_preview_update(self) -> None:
        self._pending_popup_after_id = None
        if self._pending_popup_frame_idx is None:
            return
        idx = int(self._pending_popup_frame_idx)
        self._pending_popup_frame_idx = None
        self._popup_update_preview(idx)
        self._redraw_popup_overlay()

    def _popup_set_start_current(self) -> None:
        if self._mark_start_var is None:
            return
        self._mark_start_var.set(str(self._mark_popup_current_idx))
        self._redraw_popup_overlay()
        self._schedule_popup_recompute(align_baseline_to_start=True)

    def _popup_set_end_current(self) -> None:
        if self._mark_end_var is None:
            return
        self._mark_end_var.set(str(self._mark_popup_current_idx))
        self._redraw_popup_overlay()

    def _popup_on_contrast_change(self, value: str) -> None:
        try:
            factor = float(value)
        except ValueError:
            factor = float(self._mark_contrast_var.get()) if self._mark_contrast_var is not None else 1.0
        factor = max(0.5, min(3.0, factor))
        if abs(factor - 1.0) <= 0.05:
            factor = 1.0
        if self._mark_contrast_var is not None:
            self._mark_contrast_var.set(factor)
        if self._mark_contrast_label_var is not None:
            self._mark_contrast_label_var.set(f"Contrast: {factor:.2f}x")
        self._popup_update_preview(self._mark_popup_current_idx)

    def _popup_parse_baseline_controls(self) -> tuple[int, int]:
        if self.stack_info is None:
            raise RuntimeError("No stack loaded.")
        frame_count = int(self.stack_info.frame_count)
        count_raw = self._mark_baseline_count_var.get().strip() if self._mark_baseline_count_var is not None else "30"
        end_raw = self._mark_baseline_end_var.get().strip() if self._mark_baseline_end_var is not None else "0"
        try:
            baseline_count = int(float(count_raw))
        except ValueError as exc:
            raise ValueError("Baseline Count must be a frame number.") from exc
        try:
            baseline_end = int(float(end_raw))
        except ValueError as exc:
            raise ValueError("Baseline End must be a frame number.") from exc
        if baseline_count < 1:
            raise ValueError("Baseline Count must be >= 1.")
        baseline_end = max(0, min(baseline_end, frame_count - 1))
        return baseline_count, baseline_end

    def _auto_adjust_baseline_from_start(self, force_match_start: bool = False) -> bool:
        if self.stack_info is None or self._mark_start_var is None:
            return False
        if self._mark_baseline_count_var is None or self._mark_baseline_end_var is None:
            return False
        start_raw = self._mark_start_var.get().strip()
        if not start_raw:
            return False
        try:
            start_idx = int(float(start_raw))
            baseline_end = int(float(self._mark_baseline_end_var.get().strip()))
        except ValueError:
            return False

        frame_count = int(self.stack_info.frame_count)
        if frame_count <= 0:
            return False
        next_end, changed = adjust_baseline_end_for_start(
            start_idx,
            frame_count,
            baseline_end,
            force_match_start=force_match_start,
        )
        if changed:
            self._mark_baseline_end_var.set(str(next_end))
            return True
        return False

    def _set_popup_loading(self, loading: bool, text: str = "Loading...") -> None:
        if self._mark_loading_var is None or self._mark_loading_label is None or self._mark_loading_bar is None:
            return
        if loading:
            self._mark_loading_var.set(text)
            if not self._mark_loading_label.winfo_ismapped():
                self._mark_loading_label.pack(anchor="w", pady=(0, 2))
            if not self._mark_loading_bar.winfo_ismapped():
                self._mark_loading_bar.pack(fill="x", pady=(0, 4))
            self._mark_loading_bar.start(8)
            if self._mark_popup is not None and self._mark_popup.winfo_exists():
                self._mark_popup.update_idletasks()
        else:
            self._mark_loading_bar.stop()
            if self._mark_loading_bar.winfo_ismapped():
                self._mark_loading_bar.pack_forget()
            if self._mark_loading_label.winfo_ismapped():
                self._mark_loading_label.pack_forget()
            self._mark_loading_var.set("")

    def _popup_range_x_to_idx(self, x: float) -> int:
        if self.stack_info is None or self._mark_range_canvas is None:
            return 0
        width = max(2, self._mark_range_canvas.winfo_width() - 12)
        frame_count = int(self.stack_info.frame_count)
        return linear_x_to_value(x - 6.0, width, 0, max(0, frame_count - 1))

    def _popup_range_idx_to_x(self, idx: int) -> float:
        if self.stack_info is None or self._mark_range_canvas is None:
            return 6.0
        width = max(2, self._mark_range_canvas.winfo_width() - 12)
        frame_count = int(self.stack_info.frame_count)
        return 6.0 + linear_value_to_x(idx, 0, max(0, frame_count - 1), width)

    def _redraw_popup_range_selector(self) -> None:
        if self._mark_range_canvas is None or self.stack_info is None:
            return
        c = self._mark_range_canvas
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 20 or h < 12:
            return

        y = h // 2
        c.create_line(6, y, w - 6, y, fill="#4c5058", width=4, capstyle=tk.ROUND)
        x0 = self._popup_range_idx_to_x(self._mark_range_start_idx)
        x1 = self._popup_range_idx_to_x(self._mark_range_end_idx)
        left = min(x0, x1)
        right = max(x0, x1)
        c.create_line(left, y, right, y, fill="#9cdb8f", width=6, capstyle=tk.ROUND)
        c.create_rectangle(left, y - 4, right, y + 4, fill="#9cdb8f", outline="")

        handle_radius = 7
        inner_radius = 4
        for x_pos, fill in ((x0, "#b7ffd9"), (x1, "#ffd1d1")):
            c.create_oval(
                x_pos - handle_radius,
                y - handle_radius,
                x_pos + handle_radius,
                y + handle_radius,
                fill="#171b20",
                outline="#e7edf2",
                width=2,
            )
            c.create_oval(
                x_pos - inner_radius,
                y - inner_radius,
                x_pos + inner_radius,
                y + inner_radius,
                fill=fill,
                outline="",
            )

    def _popup_range_press(self, event) -> None:
        if self.stack_info is None or self._mark_range_canvas is None:
            return
        x_start = self._popup_range_idx_to_x(self._mark_range_start_idx)
        x_end = self._popup_range_idx_to_x(self._mark_range_end_idx)
        self._mark_range_active_handle = "start" if abs(event.x - x_start) <= abs(event.x - x_end) else "end"
        self._popup_range_drag(event)

    def _popup_range_drag(self, event) -> None:
        if self._mark_range_active_handle is None:
            return
        idx = self._popup_range_x_to_idx(event.x)
        if self._mark_range_active_handle == "start":
            self._on_popup_range_changed(idx, self._mark_range_end_idx, drag_final=False)
        else:
            self._on_popup_range_changed(self._mark_range_start_idx, idx, drag_final=False)

    def _popup_range_release(self, _event) -> None:
        self._on_popup_range_changed(self._mark_range_start_idx, self._mark_range_end_idx, drag_final=True)
        self._mark_range_active_handle = None

    def _on_popup_range_changed(self, start_idx: int, end_idx: int, drag_final: bool = False) -> None:
        self._mark_last_full_refresh_note = ""
        self._apply_popup_range_bounds(start_idx, end_idx)
        if drag_final:
            self._redraw_popup_overlay()

    def _apply_popup_range_bounds(self, start_idx: int, end_idx: int) -> None:
        if self.stack_info is None or self._mark_scale is None:
            return
        # Keep the selected popup frame valid by preventing range collapse past current.
        current_idx = int(self._mark_popup_current_idx)
        mark_start, mark_end = self._popup_get_normalized_mark_bounds_for_overlay()
        if mark_start is not None:
            start_idx = min(int(start_idx), int(mark_start))
        if mark_end is not None:
            end_idx = max(int(end_idx), int(mark_end))
        start_idx = min(int(start_idx), current_idx)
        end_idx = max(int(end_idx), current_idx)
        start_idx, end_idx, clamped_current, _removed = clamp_popup_range(
            start_idx,
            end_idx,
            int(self.stack_info.frame_count),
            current_idx,
            self._mark_processed_cache,
        )
        self._mark_popup_local_start = start_idx
        self._mark_popup_local_end = end_idx
        self._mark_range_start_idx = start_idx
        self._mark_range_end_idx = end_idx
        self._mark_popup_current_idx = clamped_current
        self._mark_scale.configure(from_=start_idx, to=end_idx)
        self._mark_scale.set(clamped_current)
        self._popup_update_window_info()
        self._redraw_popup_overlay()
        self._redraw_popup_range_selector()
        self._popup_update_preview(clamped_current)

    def _refresh_popup_full_sequence(self) -> None:
        if self.stack_info is None:
            return
        range_start, range_end = self._popup_overlay_bounds()
        ok = self._recompute_popup_pipeline_for_bounds(
            range_start,
            range_end,
            show_errors=True,
            loading_text="Refreshing current sequence...",
        )
        if ok:
            self._mark_last_full_refresh_note = " | Current sequence refreshed"
            self._popup_update_window_info()

    def _recompute_popup_pipeline_for_bounds(
        self,
        range_start: int,
        range_end: int,
        show_errors: bool = True,
        loading_text: str = "Computing popup sequence...",
        fast_mode: bool = False,
        normalization_range_start: int | None = None,
        normalization_range_end: int | None = None,
    ) -> bool:
        if self._mark_popup is None or not self._mark_popup.winfo_exists() or self.stack_info is None:
            return False
        try:
            baseline_count, baseline_end = self._popup_parse_baseline_controls()
        except Exception as exc:
            if show_errors:
                self._log_warn(f"Popup recompute failed: {exc}")
                messagebox.showwarning("Mark SD", str(exc), parent=self.root)
            return False
        self._popup_job_seq += 1
        job_id = int(self._popup_job_seq)
        self._popup_active_job_id = job_id
        self._set_popup_loading(True, loading_text)
        req = PopupProcessRequest(
            job_id=job_id,
            range_start=int(range_start),
            range_end=int(range_end),
            baseline_count=int(baseline_count),
            baseline_end=int(baseline_end),
            current_idx=int(self._mark_popup_current_idx),
            warm_radius=4 if fast_mode else 10,
            sample_stride=9 if fast_mode else 5,
            norm_range_start=(
                None if normalization_range_start is None else int(normalization_range_start)
            ),
            norm_range_end=(
                None if normalization_range_end is None else int(normalization_range_end)
            ),
        )

        def done(result: PopupProcessResult | None, error: Exception | None) -> None:
            self.root.after(0, lambda: self._on_popup_process_result(job_id, result, error, show_errors))

        self._popup_engine.submit_popup_job(req, done)
        return True

    def _on_popup_process_result(
        self,
        job_id: int,
        result: PopupProcessResult | None,
        error: Exception | None,
        show_errors: bool,
    ) -> None:
        if self._mark_popup is None or not self._mark_popup.winfo_exists():
            return
        if int(job_id) != int(self._popup_active_job_id):
            return

        self._set_popup_loading(False)

        if error is not None:
            self._log_warn(f"Popup recompute failed: {error}")
            if show_errors:
                messagebox.showwarning("Mark SD", str(error), parent=self.root)
            return
        if result is None:
            return

        self._mark_baseline_frame = result.baseline_frame
        self._mark_norm_p1 = float(result.p1)
        self._mark_norm_p99 = float(result.p99)
        self._mark_processed_cache.clear()
        for idx in sorted(result.warmed_frames.keys()):
            self._cache_processed_frame(idx, result.warmed_frames[idx])

        t = result.timings_ms
        self._log_info(
            "Popup recompute timings (ms): "
            f"baseline={t.get('baseline', 0.0):.1f}, norm={t.get('norm', 0.0):.1f}, "
            f"warm={t.get('warm', 0.0):.1f}, total={t.get('total', 0.0):.1f}."
        )
        self._popup_update_window_info()
        self._popup_update_preview(self._mark_popup_current_idx)

    def _schedule_popup_recompute(
        self,
        show_errors: bool = False,
        delay_ms: int = 1400,
        align_baseline_to_start: bool = False,
    ) -> None:
        if self._mark_popup is None or not self._mark_popup.winfo_exists():
            return
        adjusted = self._auto_adjust_baseline_from_start(force_match_start=align_baseline_to_start)
        if adjusted:
            self._redraw_popup_overlay()
        if show_errors:
            self._mark_recompute_show_errors = True
        if self._mark_recompute_after_id is not None:
            try:
                self._mark_popup.after_cancel(self._mark_recompute_after_id)
            except Exception:
                pass
        self._mark_recompute_after_id = self._mark_popup.after(
            max(1000, int(delay_ms)), self._run_scheduled_popup_recompute
        )

    def _run_scheduled_popup_recompute(self) -> None:
        show_errors = bool(self._mark_recompute_show_errors)
        self._mark_recompute_show_errors = False
        self._mark_recompute_after_id = None
        self._recompute_popup_pipeline(show_errors=show_errors)

    def _recompute_popup_pipeline(self, show_errors: bool = True) -> bool:
        if self._mark_popup is None or not self._mark_popup.winfo_exists() or self.stack_info is None:
            return False
        adjusted = self._auto_adjust_baseline_from_start(force_match_start=False)
        if adjusted:
            self._redraw_popup_overlay()
        if self._mark_recompute_after_id is not None:
            try:
                self._mark_popup.after_cancel(self._mark_recompute_after_id)
            except Exception:
                pass
            self._mark_recompute_after_id = None
        self._mark_recompute_show_errors = False

        range_start, range_end = self._popup_overlay_bounds()
        self._mark_last_full_refresh_note = ""
        return self._recompute_popup_pipeline_for_bounds(
            range_start,
            range_end,
            show_errors=show_errors,
            fast_mode=not show_errors,
        )

    def _get_popup_processed_frame(self, frame_idx: int) -> np.ndarray:
        if self.reader is None:
            raise RuntimeError("Stack not loaded.")

        if self._mark_baseline_frame is None:
            raw = self.reader.read_frame(frame_idx, use_cache=True)
            return self._normalize_frame_percentile(raw)

        if frame_idx in self._mark_processed_cache:
            frame = self._mark_processed_cache.pop(frame_idx)
            self._mark_processed_cache[frame_idx] = frame
            return frame

        frame_u8 = self._popup_engine.get_processed_frame(
            frame_idx,
            self._mark_baseline_frame,
            self._mark_norm_p1,
            self._mark_norm_p99,
        )
        self._cache_processed_frame(frame_idx, frame_u8)
        return frame_u8

    def _cache_processed_frame(self, frame_idx: int, frame_u8: np.ndarray) -> None:
        self._mark_processed_cache[int(frame_idx)] = frame_u8
        while len(self._mark_processed_cache) > self._mark_processed_cache_max:
            self._mark_processed_cache.popitem(last=False)
        self._trim_numpy_cache_by_bytes(self._mark_processed_cache, self._mark_processed_cache_max_bytes)

    def _popup_start_resize_mini(self, event) -> None:
        if self._mark_mini_frame is None:
            return
        self._mark_resize_start_x = event.x_root
        self._mark_resize_start_y = event.y_root
        self._mark_resize_start_w = self._mark_mini_frame.winfo_width()
        self._mark_resize_start_h = self._mark_mini_frame.winfo_height()

    def _popup_do_resize_mini(self, event) -> None:
        if self._mark_mini_frame is None or self._mark_resize_start_x is None:
            return
        dx = self._mark_resize_start_x - event.x_root
        dy = event.y_root - self._mark_resize_start_y
        delta = max(dx, dy)
        base_w = self._mark_resize_start_w if self._mark_resize_start_w is not None else self._mark_mini_frame.winfo_width()
        base_h = self._mark_resize_start_h if self._mark_resize_start_h is not None else self._mark_mini_frame.winfo_height()
        new_size = max(70, min(450, max(base_w, base_h) + delta))
        self._mark_mini_frame.configure(width=new_size, height=new_size)
        self._mark_mini_frame.update_idletasks()
        self._update_popup_mini_raw(self._mark_popup_current_idx)

    def _popup_stop_resize_mini(self, _event) -> None:
        self._mark_resize_start_x = None
        self._mark_resize_start_y = None
        self._mark_resize_start_w = None
        self._mark_resize_start_h = None
        self._update_popup_mini_raw(self._mark_popup_current_idx)

    def _update_popup_mini_raw(self, frame_idx: int) -> None:
        return self._get_preview_controller().update_popup_mini_raw(frame_idx)

    def _popup_update_window_info(self) -> None:
        return self._get_preview_controller().popup_update_window_info()

    def _popup_update_preview(self, frame_idx: int) -> None:
        return self._get_preview_controller().popup_update_preview(frame_idx)

    def _popup_confirm(self) -> None:
        self.popup_controller.confirm()

    def _popup_cancel(self) -> None:
        self.popup_controller.cancel()

    def _delete_selected_events(self) -> None:
        self.popup_controller.delete_selected_events()

    def _step_preview(self, delta: int) -> None:
        if self.stack_info is None:
            return
        idx = max(0, min(self.current_frame_idx + int(delta), self.stack_info.frame_count - 1))
        self.preview_scale.set(idx)
        self._update_preview(idx)

    def _on_preview_slide(self, value: str) -> None:
        idx = int(float(value))
        self._schedule_main_preview_update(idx)

    def _schedule_main_preview_update(self, idx: int) -> None:
        return self._get_preview_controller().schedule_main_preview_update(idx)

    def _flush_main_preview_update(self) -> None:
        return self._get_preview_controller().flush_main_preview_update()

    def _normalize_frame_percentile(self, frame: np.ndarray) -> np.ndarray:
        return self._get_preview_controller().normalize_frame_percentile(frame)

    def _apply_display_contrast(self, frame_u8: np.ndarray, factor: float) -> np.ndarray:
        return self._get_preview_controller().apply_display_contrast(frame_u8, factor)

    def _render_preview_image(
        self,
        frame: np.ndarray,
        label: ttk.Label,
        fallback_size: tuple[int, int],
        pre_normalized: bool = False,
        contrast_factor: float = 1.0,
    ) -> ImageTk.PhotoImage:
        return self._get_preview_controller().render_preview_image(
            frame,
            label,
            fallback_size,
            pre_normalized=pre_normalized,
            contrast_factor=contrast_factor,
        )

    def _cache_main_render(self, key: tuple[int, int, int], image: ImageTk.PhotoImage) -> None:
        return self._get_preview_controller().cache_main_render(key, image)

    def _update_preview(self, frame_idx: int) -> None:
        return self._get_preview_controller().update_preview(frame_idx)

    def _scale_value_to_x(
        self,
        scale: tk.Scale | None,
        canvas: tk.Canvas | None,
        value: int,
        start_idx: int,
        end_idx: int,
        width: float,
    ) -> float:
        return self._get_preview_controller().scale_value_to_x(scale, canvas, value, start_idx, end_idx, width)

    def _scale_x_to_value(
        self,
        scale: tk.Scale | None,
        canvas: tk.Canvas | None,
        x_px: float,
        start_idx: int,
        end_idx: int,
        width: float,
    ) -> int:
        return self._get_preview_controller().scale_x_to_value(scale, canvas, x_px, start_idx, end_idx, width)

    def _draw_overlay_bar(
        self,
        canvas: tk.Canvas | None,
        scale: tk.Scale | None,
        start_idx: int,
        end_idx: int,
        spans: list[tuple[int, int, str]],
        markers: list[tuple[int, str]],
    ) -> None:
        return self._get_preview_controller().draw_overlay_bar(canvas, scale, start_idx, end_idx, spans, markers)

    def _redraw_main_overlay(self) -> None:
        return self._get_preview_controller().redraw_main_overlay()

    def _on_main_overlay_click(self, event) -> None:
        return self._get_preview_controller().on_main_overlay_click(event)

    def _popup_overlay_bounds(self) -> tuple[int, int]:
        return self._get_preview_controller().popup_overlay_bounds()

    def _popup_get_normalized_mark_bounds_for_overlay(self) -> tuple[int | None, int | None]:
        return self._get_preview_controller().popup_get_normalized_mark_bounds_for_overlay()

    def _redraw_popup_overlay(self) -> None:
        return self._get_preview_controller().redraw_popup_overlay()

    def _selected_event_ids(self) -> list[str]:
        return list(self.tree.selection())

    def _export_selected(self) -> None:
        ids = self._selected_event_ids()
        if not ids:
            self._log_warn("Export Selected blocked: no events selected.")
            messagebox.showwarning("Export", "Select one or more events in the table.", parent=self.root)
            return
        options = self._prompt_export_options(ids)
        if options is None:
            self._log_info("Export (selected) canceled from options dialog.")
            return
        self._log_info(f"Preparing export for {len(ids)} selected event(s).")
        self._run_export(ids, options=options)

    def _export_all(self) -> None:
        if not self.events:
            self._log_warn("Export All blocked: no events available.")
            messagebox.showwarning("Export", "No events to export.", parent=self.root)
            return
        event_ids = [event.event_id for event in self.events]
        options = self._prompt_export_options(event_ids)
        if options is None:
            self._log_info("Export (all) canceled from options dialog.")
            return
        self._log_info(f"Preparing export for all {len(self.events)} event(s).")
        self._run_export(event_ids, options=options)

    def _has_binary_masks_for_events(self, event_ids: list[str]) -> bool:
        return bool(self._get_window_controller().has_binary_masks_for_events(list(event_ids or [])))

    @staticmethod
    def _has_valid_scale(metrics_settings: dict) -> bool:
        return HostWindowController._has_valid_scale(metrics_settings)

    @staticmethod
    def _has_valid_roi(metrics_settings: dict) -> bool:
        return HostWindowController._has_valid_roi(metrics_settings)

    def _resolve_export_metric_prerequisites(self, event_ids: list[str]) -> dict[str, dict[str, object]]:
        return self._get_window_controller().resolve_export_metric_prerequisites(list(event_ids or []))

    @staticmethod
    def _attach_disabled_tooltip(parent, widget, message: str) -> None:
        HostWindowController.attach_disabled_tooltip(parent, widget, message)

    def _prompt_export_options(self, event_ids: list[str]) -> dict[str, bool] | None:
        return self._get_window_controller().prompt_export_options(list(event_ids or []))

    def _get_window_controller(self) -> HostWindowController:
        controller = getattr(self, "window_controller", None)
        if isinstance(controller, HostWindowController):
            return controller
        controller = HostWindowController(self)
        self.window_controller = controller
        return controller

    def _get_preview_controller(self) -> HostPreviewController:
        controller = getattr(self, "preview_controller", None)
        if isinstance(controller, HostPreviewController):
            return controller
        controller = HostPreviewController(self)
        self.preview_controller = controller
        return controller

    def _get_project_controller(self) -> HostProjectLifecycleController:
        controller = getattr(self, "project_controller", None)
        if isinstance(controller, HostProjectLifecycleController):
            return controller
        controller = HostProjectLifecycleController(self)
        self.project_controller = controller
        return controller

    def _get_analysis_launch_controller(self) -> AnalysisLaunchController:
        controller = getattr(self, "analysis_launch_controller", None)
        if isinstance(controller, AnalysisLaunchController):
            return controller
        controller = AnalysisLaunchController(self)
        self.analysis_launch_controller = controller
        return controller

    def _get_model_setup_controller(self) -> HostModelSetupController:
        controller = getattr(self, "model_setup_controller", None)
        if isinstance(controller, HostModelSetupController):
            return controller
        controller = HostModelSetupController(self)
        self.model_setup_controller = controller
        return controller

    def _run_export(self, event_ids: list[str], *, options: dict[str, object]) -> None:
        self._get_window_controller().run_export(list(event_ids or []), options=options)

    def _on_export_done(self, result: dict) -> None:
        self._set_status(f"Export complete: {result['events_exported']} event(s), {result['frames_exported']} frame(s).")
        self._log_info(
            f"Export complete: {result['events_exported']} event(s), {result['frames_exported']} frame(s), "
            f"analysis_images={int(result.get('analysis_images_exported', 0))}, "
            f"mask_overlays={int(result.get('mask_overlay_images_exported', 0))}, "
            f"metrics_files={int(result.get('metrics_files_exported', 0))}, output={result['output_dir']}."
        )
        self._gc_runtime_caches(aggressive=False, run_python_gc=False)
        messagebox.showinfo("Export", f"Output written to:\n{result['output_dir']}", parent=self.root)

    def _trim_numpy_cache_by_bytes(self, cache: OrderedDict[int, np.ndarray], max_bytes: int) -> None:
        total = 0
        for arr in cache.values():
            total += int(getattr(arr, "nbytes", 0))
        while cache and total > int(max_bytes):
            _k, old = cache.popitem(last=False)
            total -= int(getattr(old, "nbytes", 0))

    def _gc_runtime_caches(self, aggressive: bool = False, run_python_gc: bool = False) -> None:
        if aggressive:
            self._main_render_cache.clear()
            self._mark_processed_cache.clear()
            self._normalized_frame_u8_cache.clear()
        else:
            while len(self._main_render_cache) > max(8, self._main_render_cache_max // 2):
                self._main_render_cache.popitem(last=False)
            while len(self._mark_processed_cache) > max(8, self._mark_processed_cache_max // 2):
                self._mark_processed_cache.popitem(last=False)
            while len(self._normalized_frame_u8_cache) > max(16, self._normalized_frame_u8_cache_max // 2):
                self._normalized_frame_u8_cache.popitem(last=False)
            self._trim_numpy_cache_by_bytes(self._mark_processed_cache, self._mark_processed_cache_max_bytes)
            self._trim_numpy_cache_by_bytes(
                self._normalized_frame_u8_cache,
                self._normalized_frame_u8_cache_max_bytes,
            )

        self._popup_engine.collect_garbage(aggressive=aggressive)
        if self.reader is not None:
            self.reader.collect_garbage(aggressive=aggressive)
        if run_python_gc:
            gc.collect()

    def _schedule_periodic_cache_gc(self) -> None:
        if self._cache_gc_after_id is not None:
            try:
                self.root.after_cancel(self._cache_gc_after_id)
            except Exception:
                pass
        self._cache_gc_after_id = self.root.after(45_000, self._run_periodic_cache_gc)

    def _run_periodic_cache_gc(self) -> None:
        self._cache_gc_after_id = None
        try:
            self._gc_runtime_caches(aggressive=False, run_python_gc=False)
        finally:
            self._schedule_periodic_cache_gc()
