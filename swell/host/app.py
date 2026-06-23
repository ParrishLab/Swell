from __future__ import annotations

from collections import OrderedDict
import gc
import sys
import threading
from datetime import datetime
from pathlib import Path
from time import perf_counter
import tkinter as tk
from tkinter import filedialog, ttk
from swell.shared.ui import dialogs as messagebox
from swell.shared.ui import dialogs as simpledialog

import numpy as np
from PIL import Image, ImageTk

from swell.shared.ui.theme import CANVAS_BACKGROUND, SLIDER_OVERLAY_BACKGROUND, SPACING
from swell.shared.config import AppConfig
from .auto_detect_controller import AutoDetectController
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
from .popup_window_manager import PopupWindowManager
from .processing_engine import PopupProcessingEngine
from .preview_controller import HostPreviewController
from .stack_reader import StackReader
from swell.shared.lru_cache import LRUCache
from swell.shared.services import AnalysisWindowManager, CheckpointRuntimeService, SingleInstanceBridge
from swell.shared.menu.factory import build_shared_menu
from swell.shared.app_metadata import format_window_title
from swell.shared.frame_source import normalize_visual_frame
from swell.shared.persistence.schema import METADATA_EMBED_IMAGES_KEY
from swell.shared.ui.bootstrap import center_window_on_screen, semantic_button_options


def format_bytes(num_bytes: int) -> str:
    """Human-readable size, e.g. 512 B, 4.2 MB, 1.8 GB."""
    size = float(max(0, int(num_bytes)))
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


class SwellHostApp:
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
        self.auto_detect_controller = AutoDetectController(self)
        self._host_modal_dialog_depth = 0
        self._startup_preflight_completed = False
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
        self.embed_images_menu_var = tk.BooleanVar(value=False)
        self._embedded_extract_dir: str | None = None

        self.tk_preview_image: ImageTk.PhotoImage | None = None
        self.max_log_lines = 500
        self._load_progress_bucket = -1
        self._export_progress_bucket = -1

        self._popup = PopupWindowManager()
        self.preview_overlay: tk.Canvas | None = None
        self._main_render_cache: LRUCache[tuple[int, int, int], ImageTk.PhotoImage] = LRUCache(max_items=24, gc_min_keep=8)
        self._normalized_frame_u8_cache: LRUCache[tuple[int, str], np.ndarray] = LRUCache(max_items=64, max_bytes=160 * 1024 * 1024, gc_min_keep=16)
        self._pending_main_frame_idx: int | None = None
        self._pending_main_after_id: str | None = None
        self._last_log_msg: str = ""
        self._last_log_time: float = 0.0
        self._cache_gc_after_id: str | None = None
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

        self._sweep_stale_embedded_extract_dirs()
        self._build_ui()
        self._refresh_model_gate_ui()
        self._build_menu()
        self.root.protocol("WM_DELETE_WINDOW", self._on_root_close)
        self._register_platform_open_handlers()
        self._start_instance_listener()
        if initial_project_path:
            self.root.after(0, lambda p=str(initial_project_path): self.open_project_request(p))
        self._schedule_periodic_cache_gc()
        self.root.after(250, self._run_model_startup_preflight)

    def _sweep_stale_embedded_extract_dirs(self) -> None:
        try:
            from swell.shared.persistence.zip_io import cleanup_stale_extract_dirs

            cleanup_stale_extract_dirs()
        except Exception:
            pass

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
        # Autodetect is half the size of the other buttons.
        nav_row.columnconfigure(0, weight=1)
        for column in range(1, 4):
            nav_row.columnconfigure(column, weight=2)

        ttk.Button(nav_row, text="Autodetect", command=self.auto_detect_controller.start, **semantic_button_options("secondary")).grid(
            row=0,
            column=0,
            sticky="ew",
            padx=(0, SPACING.gap),
        )
        ttk.Button(nav_row, text="Prev", command=lambda: self._step_preview(-1), **semantic_button_options("secondary")).grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(0, SPACING.gap),
        )
        ttk.Button(nav_row, text="Mark Event", command=self._mark_sd, **semantic_button_options("primary")).grid(
            row=0,
            column=2,
            sticky="ew",
            padx=(0, SPACING.gap),
        )
        ttk.Button(nav_row, text="Next", command=lambda: self._step_preview(1), **semantic_button_options("secondary")).grid(
            row=0,
            column=3,
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
        ttk.Label(table_frame, text="Marked Events", style="AppSidebarTitle.TLabel").grid(row=0, column=0, sticky="w")

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
        self._log_info("Application started in manual event marking mode.")

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
            self._log_warn("Single-instance listener unavailable; external project forwarding is disabled.")

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
        if self._popup.mark_popup is not None and self._popup.mark_popup.winfo_exists():
            return None
        self._step_preview(step)
        return "break"

    def _handle_popup_key(self, event, step: int):
        if self._focus_is_entry(getattr(event, "widget", None)):
            return None
        self._get_popup_controller().preview_controller.step(step)
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

    def _active_embedded_extract_dir(self) -> str | None:
        path = str(getattr(self, "_embedded_extract_dir", "") or "").strip()
        if not path:
            return None
        try:
            candidate = Path(path).expanduser()
        except Exception:
            return None
        if candidate.exists() and candidate.is_dir():
            return str(candidate)
        return None

    def _embedded_images_source_dir(self) -> str | None:
        active_extract = self._active_embedded_extract_dir()
        if active_extract:
            return active_extract
        input_dir = getattr(getattr(self, "stack_info", None), "input_dir", None)
        if input_dir:
            return str(input_dir)
        input_var = getattr(self, "input_var", None)
        getter = getattr(input_var, "get", None)
        if callable(getter):
            raw = str(getter() or "").strip()
            if raw:
                return raw
        return None

    def _session_embed_images_enabled(self) -> bool:
        try:
            metadata = dict(self.browser_controller.session.state().metadata or {})
        except Exception:
            return False
        return bool(metadata.get(METADATA_EMBED_IMAGES_KEY, False))

    def _validate_host_session_save_allowed(self) -> None:
        active_extract = self._active_embedded_extract_dir()
        if not active_extract or self._session_embed_images_enabled():
            return
        try:
            stack_ref = self.browser_controller.session.state().stack_ref
        except Exception:
            stack_ref = None
        source_dir = str(getattr(stack_ref, "input_dir", "") or "").strip()
        source_missing = True
        if source_dir:
            try:
                source_missing = not Path(source_dir).expanduser().is_dir()
            except Exception:
                source_missing = True
        if source_missing:
            raise RuntimeError(
                "This project is currently using embedded fallback images because the original stack folder is missing. "
                "Re-enable source-image embedding or rebind the stack folder before saving; otherwise the project would "
                "reference a temporary folder that will be deleted."
            )

    def save_host_session(self, path: str | None = None):
        self._validate_host_session_save_allowed()
        embedded_source = self._embedded_images_source_dir() if self._session_embed_images_enabled() else None
        return self.browser_controller.save_session(path, embedded_images_input_dir=embedded_source)

    def _new_project(self) -> None:
        self._get_project_controller().new_project()

    def _save_project(self) -> None:
        self._get_project_controller().save_project()

    def _save_project_as(self) -> None:
        self._get_project_controller().save_project_as()

    def toggle_embed_source_images(self) -> None:
        value = bool(self.embed_images_menu_var.get())
        if value and not self._confirm_embed_source_images():
            self.embed_images_menu_var.set(False)
            return
        self.browser_controller.session.set_metadata(embed_source_images=value)
        state = "embed source images in the project file" if value else "store images by folder reference only"
        self._set_status(f"Save will now {state}.")

    def _embedded_images_size_estimate(self, input_dir: str | Path | None = None) -> tuple[int, int]:
        """Return (file_count, total_bytes) for the current stack's source files."""
        from swell.shared.frame_source.stack_files import list_stack_files

        input_dir = input_dir or self._embedded_images_source_dir()
        if not input_dir:
            return 0, 0
        count = 0
        total = 0
        for path in list_stack_files(input_dir):
            try:
                total += int(path.stat().st_size)
                count += 1
            except OSError:
                continue
        return count, total

    def _confirm_embed_source_images(self) -> bool:
        count, total = self._embedded_images_size_estimate()
        if count:
            added = f"about {format_bytes(total)} across {count} frame(s)"
        else:
            added = "the full size of the source image stack"
        return bool(
            messagebox.askyesno(
                "Embed Source Images",
                (
                    "Embedding copies the source frames into the .swell file so the project "
                    "stays usable if the original folder moves.\n\n"
                    f"This will increase the saved project size by {added}.\n\n"
                    "Enable embedding?"
                ),
                parent=self.root,
            )
        )

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
        parent=None,
        purpose: str,
        force_picker: bool = False,
    ) -> tuple[np.ndarray, str] | None:
        selected = ""
        if not force_picker and str(purpose or "").lower() == "scale":
            last_scale_image_path = str(getattr(self, "_last_scale_image_path", "") or "").strip()
            if last_scale_image_path and Path(last_scale_image_path).is_file():
                selected = last_scale_image_path
        if not selected:
            initialdir = self._metrics_picker_initial_dir()
            initialfile = self._metrics_picker_initial_file()
            picker_options = {
                "title": f"Select Image for {purpose}",
                "initialdir": initialdir,
                "initialfile": initialfile,
                "filetypes": [
                    ("Image files", "*.tif *.tiff *.png *.jpg *.jpeg *.bmp"),
                    ("TIFF files", "*.tif *.tiff"),
                    ("All files", "*.*"),
                ],
            }
            if parent is not None:
                picker_options["parent"] = parent
            selected = filedialog.askopenfilename(**picker_options)
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
        return img_u8, Path(selected).name

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
        if bool(getattr(self, "_startup_preflight_completed", False)):
            return
        if int(getattr(self, "_host_modal_dialog_depth", 0) or 0) > 0:
            try:
                self.root.after(250, self._run_model_startup_preflight)
            except Exception:
                pass
            return
        try:
            self._get_model_setup_controller().run_startup_preflight()
        finally:
            self._startup_preflight_completed = True

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
            self._show_warning("Event", "Select one event first.")
            return
        if len(selected) != 1:
            self._log_warn("Rename Selected blocked: multiple events selected.")
            self._show_warning("Event", "Select exactly one event to rename.")
            return
        event = self._get_event_by_id(selected[0])
        if event is None:
            self._log_warn("Rename Selected blocked: selected event not found.")
            self._show_warning("Event", "Selected event was not found.")
            return

        def _commit_rename(val: str) -> None:
            val = str(val).strip()
            if not val:
                self._show_warning("Rename Event", "Event name cannot be empty.")
                return
            if val == str(event.label):
                return
            updated = self.browser_controller.update_event(
                event.event_id,
                start_idx=None,
                end_idx=None,
                label=val,
                frame_count=int(self.stack_info.frame_count) if self.stack_info is not None else int(event.end_idx + 1),
                flags=dict(event.flags),
            )
            self._sync_event_projections()
            if self.tree.exists(updated.event_id):
                self.tree.selection_set(updated.event_id)
                self.tree.see(updated.event_id)
            self._set_active_event_id(updated.event_id)
            event_display_name = getattr(self.browser_controller, "event_display_name", None)
            display_name = str(event_display_name(updated.event_id) if callable(event_display_name) else val).strip() or val
            self._set_status(f"Renamed {display_name}.")
            self._log_info(f"Renamed {updated.event_id} to '{display_name}'.")

        try:
            bbox = self.tree.bbox(selected[0], "id")
        except AttributeError:
            bbox = None
        if not bbox:
            new_label = simpledialog.askstring(
                "Rename Event",
                "Event name:",
                initialvalue=str(event.label),
                parent=self.root,
            )
            if new_label is not None:
                _commit_rename(new_label)
            return
        x, y, w, h = bbox

        entry = ttk.Entry(self.tree)
        entry.insert(0, str(event.label))
        entry.select_range(0, "end")
        entry.place(x=x, y=y, width=w, height=h)
        entry.focus_set()

        def _save(_e=None):
            if not entry.winfo_exists():
                return
            val = entry.get().strip()
            entry.destroy()
            _commit_rename(val)

        def _cancel(_e=None):
            if entry.winfo_exists():
                entry.destroy()

        entry.bind("<Return>", _save)
        entry.bind("<Escape>", _cancel)
        entry.bind("<FocusOut>", _save)

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
        if not hasattr(self, "popup_controller"):
            self.popup_controller = MarkPopupController(self)
        self.popup_controller.on_destroy(_event)

    def _popup_confirm(self) -> None:
        if not hasattr(self, "popup_controller"):
            self.popup_controller = MarkPopupController(self)
        self.popup_controller.confirm()

    def _popup_cancel(self) -> None:
        if not hasattr(self, "popup_controller"):
            self.popup_controller = MarkPopupController(self)
        self.popup_controller.cancel()

    def _delete_selected_events(self) -> None:
        if not hasattr(self, "popup_controller"):
            self.popup_controller = MarkPopupController(self)
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

    def _get_popup_controller(self) -> MarkPopupController:
        controller = getattr(self, "popup_controller", None)
        if isinstance(controller, MarkPopupController):
            return controller
        controller = MarkPopupController(self)
        self.popup_controller = controller
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
            f"analysis_overlays={int(result.get('analysis_overlay_images_exported', 0))}, "
            f"contour_maps={int(result.get('contour_maps_exported', 0))}, "
            f"metrics_files={int(result.get('metrics_files_exported', 0))}, output={result['output_dir']}."
        )
        self._gc_runtime_caches(aggressive=False, run_python_gc=False)
        messagebox.showinfo("Export", f"Output written to:\n{result['output_dir']}", parent=self.root)

    def _gc_runtime_caches(self, aggressive: bool = False, run_python_gc: bool = False) -> None:
        try:
            from swell.shared.persistence.zip_io import touch_extract_dir_marker

            touch_extract_dir_marker(self._active_embedded_extract_dir())
        except Exception:
            pass
        self._main_render_cache.gc(aggressive=aggressive)
        self._popup.mark_processed_cache.gc(aggressive=aggressive)
        self._normalized_frame_u8_cache.gc(aggressive=aggressive)
        self._popup.engine.collect_garbage(aggressive=aggressive)
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
