from __future__ import annotations

from collections import OrderedDict
import gc
import sys
import threading
from datetime import datetime
from pathlib import Path
from time import perf_counter
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np
from PIL import Image, ImageTk
import tifffile

from sdapp.analysis.core.state import AppConfig
from .browser_controller import BrowserController
from .config import APP_TITLE, DEFAULT_BASELINE_PRE_FRAMES, TraceResult
from .controllers import (
    AnalysisLaunchController,
    HostModelSetupController,
    HostProjectLifecycleController,
    HostUpdateController,
    HostWindowController,
)
from .mark_popup_controller import MarkPopupController
from .processing_engine import PopupProcessRequest, PopupProcessResult, PopupProcessingEngine
from .stack_reader import StackReader
from .ui_geometry import (
    adjust_baseline_end_for_start,
    clamp_popup_range,
    linear_value_to_x,
    linear_x_to_value,
    normalize_overlay_bounds,
)

from sdapp.shared.services import AnalysisWindowManager, CheckpointRuntimeService, SingleInstanceBridge
from sdapp.shared.menu.factory import build_shared_menu
from sdapp.shared.app_metadata import format_window_title
from sdapp.shared.frame_source import normalize_visual_frame


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
        self._app_icon_image: ImageTk.PhotoImage | None = None
        self._apply_runtime_icon()
        self._instance_bridge = instance_bridge

        self.reader: StackReader | None = None
        self.stack_info = None
        self.trace: TraceResult | None = None
        self.browser_controller = BrowserController()
        self.window_controller = HostWindowController(self)
        self.project_controller = HostProjectLifecycleController(self)
        self.analysis_launch_controller = AnalysisLaunchController(self)
        self.update_controller = HostUpdateController(self)
        self.checkpoint_runtime = CheckpointRuntimeService()
        self.model_setup_controller = HostModelSetupController(self)
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
        self._mini_raw_u8_cache: OrderedDict[int, np.ndarray] = OrderedDict()
        self._mini_raw_u8_cache_max = 48
        self._pending_main_frame_idx: int | None = None
        self._pending_main_after_id: str | None = None
        self._pending_popup_frame_idx: int | None = None
        self._pending_popup_after_id: str | None = None
        self._last_log_msg: str = ""
        self._last_log_time: float = 0.0
        self._cache_gc_after_id: str | None = None
        self._mark_processed_cache_max_bytes = 220 * 1024 * 1024
        self._mini_raw_u8_cache_max_bytes = 120 * 1024 * 1024
        self._analysis_windows: list[tuple[tk.Toplevel, object]] = []
        self.analysis_window_manager = AnalysisWindowManager()
        self._analysis_options_preview_image: ImageTk.PhotoImage | None = None
        self._analysis_preview_cache: OrderedDict[tuple, dict[str, object]] = OrderedDict()
        self._analysis_app_class_cache = None
        self._analysis_app_import_started = False

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
        self.update_controller.schedule_startup_check()

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
        main = ttk.Frame(self.root, padding=8)
        main.pack(fill="both", expand=True)

        self.status_var = tk.StringVar(value="Idle")
        ttk.Label(main, textvariable=self.status_var).pack(anchor="w", pady=(0, 6))

        body = ttk.Panedwindow(main, orient="horizontal")
        body.pack(fill="both", expand=True)

        left = ttk.Frame(body)
        right = ttk.Frame(body)
        body.add(left, weight=6)
        body.add(right, weight=2)
        self.body_split = body

        viewer_frame = ttk.LabelFrame(left, text="Frame Viewer", padding=6)
        viewer_frame.pack(fill="both", expand=True)

        self.preview_label = ttk.Label(viewer_frame, anchor="center")
        self.preview_label.pack(fill="both", expand=True)

        self.preview_label_info = tk.StringVar(value="Frame: -")
        ttk.Label(viewer_frame, textvariable=self.preview_label_info).pack(anchor="w")

        self.preview_overlay = tk.Canvas(viewer_frame, height=12, bg="#2a2b2f", highlightthickness=0, bd=0, cursor="hand2")
        self.preview_overlay.pack(fill="x", pady=(4, 2))
        self.preview_overlay.bind("<Configure>", lambda _e: self._redraw_main_overlay())
        self.preview_overlay.bind("<Button-1>", self._on_main_overlay_click)

        self.preview_scale = tk.Scale(
            viewer_frame,
            from_=0,
            to=1,
            orient="horizontal",
            showvalue=False,
            relief="flat",
            highlightthickness=0,
            command=self._on_preview_slide,
        )
        self.preview_scale.pack(fill="x", pady=(6, 4))

        nav_row = ttk.Frame(viewer_frame)
        nav_row.pack(fill="x")
        ttk.Button(nav_row, text="Prev", command=lambda: self._step_preview(-1)).pack(side="left", padx=2)
        ttk.Button(nav_row, text="Mark SD", command=self._mark_sd).pack(side="left", padx=6)
        ttk.Button(nav_row, text="Next", command=lambda: self._step_preview(1)).pack(side="left", padx=2)

        right_split = ttk.Panedwindow(right, orient="vertical")
        right_split.pack(fill="both", expand=True)
        self.right_split = right_split
        right_top = ttk.Frame(right_split)
        right_bottom = ttk.Frame(right_split)
        right_split.add(right_top, weight=3)
        right_split.add(right_bottom, weight=2)

        table_frame = ttk.LabelFrame(right_top, text="Marked SD Events", padding=6)
        table_frame.pack(fill="both", expand=True)
        columns = ("id", "start", "end", "duration")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=12, selectmode="extended")
        for col, width in [("id", 110), ("start", 75), ("end", 75), ("duration", 95)]:
            self.tree.heading(col, text=col.upper())
            self.tree.column(col, width=width, anchor="center")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_event_select)

        action_frame = ttk.LabelFrame(right_top, text="Event Actions", padding=6)
        action_frame.pack(fill="x", pady=(6, 0))
        for col in range(2):
            action_frame.columnconfigure(col, weight=1)
        ttk.Button(action_frame, text="Edit Selected", command=self._edit_selected).grid(
            row=0, column=0, sticky="ew", padx=2, pady=2
        )
        ttk.Button(action_frame, text="Delete Selected", command=self._delete_selected_events).grid(
            row=0, column=1, sticky="ew", padx=2, pady=2
        )
        self.btn_open_analysis = ttk.Button(action_frame, text="Open Analysis...", command=self._analyze_selected_event)
        self.btn_open_analysis.grid(row=1, column=0, columnspan=2, sticky="ew", padx=2, pady=(6, 2))
        ttk.Button(action_frame, text="Open Metrics...", command=self._open_generate_metrics_popup).grid(
            row=2, column=0, columnspan=2, sticky="ew", padx=2, pady=2
        )
        ttk.Button(action_frame, text="Export Selected", command=self._export_selected).grid(
            row=3, column=0, sticky="ew", padx=2, pady=2
        )
        ttk.Button(action_frame, text="Export All", command=self._export_all).grid(
            row=3, column=1, sticky="ew", padx=2, pady=2
        )

        logs_frame = ttk.LabelFrame(right_bottom, text="Logs", padding=6)
        logs_frame.pack(fill="both", expand=True, pady=(6, 0))
        clear_row = ttk.Frame(logs_frame)
        clear_row.pack(fill="x")
        ttk.Button(clear_row, text="Clear Logs", command=self._clear_logs).pack(side="right")
        self.log_text = tk.Text(logs_frame, height=8, wrap="word", state="disabled")
        log_scroll = ttk.Scrollbar(logs_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

        self.root.after(150, self._reset_main_layout)
        self._bind_main_keys()
        self._log_info("Application started in manual SD marking mode.")

    def _build_menu(self) -> None:
        build_shared_menu(self.root, self, mode="host", host_mode=False)

    def check_for_updates(self) -> None:
        self.update_controller.check_for_updates()

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
        line = f"[{datetime.now().strftime('%H:%M:%S')}] [{level}] {message}\n"
        if threading.current_thread() is threading.main_thread():
            self._append_log_line(line)
        else:
            self.root.after(0, lambda: self._append_log_line(line))

    def _append_log_line(self, line: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line)
        total_lines = int(float(self.log_text.index("end-1c").split(".")[0]))
        if total_lines > self.max_log_lines:
            remove_count = total_lines - self.max_log_lines
            self.log_text.delete("1.0", f"{remove_count + 1}.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

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
            values = (event.event_id, event.start_idx, event.end_idx, event.duration_frames)
            self.tree.insert("", "end", iid=event.event_id, values=values)
        for event_id in list(selected):
            if self.tree.exists(event_id):
                self.tree.selection_add(event_id)

    def refresh_timeline_overlays(self, _events, _active_event_id: str | None) -> None:
        self._redraw_main_overlay()

    def _show_warning(self, title: str, text: str) -> None:
        messagebox.showwarning(title, text, parent=self.root)

    def save_host_session(self, path: str | None = None):
        return self.browser_controller.save_session(path)

    def _new_project(self) -> None:
        self._get_project_controller().new_project()

    def _save_project(self) -> None:
        self._get_project_controller().save_project()

    def _save_project_as(self) -> None:
        self._get_project_controller().save_project_as()

    def _open_project_dialog(self) -> None:
        self._get_project_controller().open_project_dialog()

    def _open_project(self, path: str) -> None:
        self._get_project_controller().open_project(path)

    def open_project_request(self, path: str) -> bool:
        return self._get_project_controller().open_project_request(path)

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
        selected = filedialog.askopenfilename(
            parent=parent,
            title=f"Select Image for {purpose}",
            initialdir=self._metrics_picker_initial_dir(),
            filetypes=[
                ("Image files", "*.tif *.tiff *.png *.jpg *.jpeg *.bmp"),
                ("TIFF files", "*.tif *.tiff"),
                ("All files", "*.*"),
            ],
        )
        if not selected:
            return None
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
    def _center_window_on_screen(window) -> None:
        HostWindowController.center_window_on_screen(window)

    def _open_generate_metrics_popup(self) -> None:
        self._get_window_controller().open_generate_metrics_popup()

    def _compute_analysis_preview_frame(
        self,
        *,
        event_start: int,
        baseline_pre_frames: int,
        apply_smoothing: bool,
        apply_baseline_subtraction: bool,
        apply_global_normalization: bool,
    ) -> np.ndarray:
        return self._get_analysis_launch_controller().compute_analysis_preview_frame(
            event_start=event_start,
            baseline_pre_frames=baseline_pre_frames,
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
            state = "normal" if bool(self._model_setup_ready and not self._model_setup_disabled) else "disabled"
            btn.configure(state=state)
        except Exception:
            return

    def _on_root_close(self) -> None:
        if self._instance_bridge is not None:
            self._instance_bridge.stop()
        self.analysis_window_manager.close_all()
        try:
            self.root.destroy()
        except Exception:
            pass

    def _on_stack_loaded(self, reader: StackReader, info) -> None:
        self._get_project_controller().on_stack_loaded(reader, info)

    def _warmup_main_preview_async(self) -> None:
        self._get_project_controller().warmup_main_preview_async()

    def _on_load_progress(self, current: int, total: int) -> None:
        self._get_project_controller().on_load_progress(current, total)

    def _on_export_progress(self, payload: dict) -> None:
        phase = payload.get("phase")
        if phase == "event":
            event_text = f"Export event {payload.get('current', 0)}/{payload.get('total', 0)}: {payload.get('event_id', '?')}."
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
                f"Preparing analysis images for {payload.get('event_id', '?')}: {current}/{total} ({percent}%) [{stage}]"
            )
            bucket = percent // 10
            key = (
                "analysis_prepare",
                str(payload.get("event_id", "?")),
                str(payload.get("stage", "prepare")),
                int(bucket),
            )
            if key != getattr(self, "_last_export_analysis_prepare_key", None):
                self._last_export_analysis_prepare_key = key
                self._log_info(
                    f"Preparing analysis images for {payload.get('event_id', '?')}: {current}/{total} ({percent}%) [{stage}]."
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
            return

        self._set_active_event_id(selected[0])
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

    def _open_mark_popup(self, mode: str, event_id: str | None) -> None:
        self.popup_controller.open_popup(mode=mode, event_id=event_id)

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
        r = 6
        c.create_oval(x0 - r, y - r, x0 + r, y + r, fill="#b7ffd9", outline="")
        c.create_oval(x1 - r, y - r, x1 + r, y + r, fill="#ffd1d1", outline="")

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
            if show_errors:
                self._log_warn(f"Popup recompute failed: {error}")
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
        if self.reader is None or self._mark_mini_canvas is None or self._mark_mini_frame is None:
            return
        raw_u8 = self._mini_raw_u8_cache.get(int(frame_idx))
        if raw_u8 is None:
            raw = self.reader.read_frame(frame_idx, use_cache=True)
            raw_u8 = self._normalize_frame_percentile(raw)
            self._mini_raw_u8_cache[int(frame_idx)] = raw_u8
            while len(self._mini_raw_u8_cache) > self._mini_raw_u8_cache_max:
                self._mini_raw_u8_cache.popitem(last=False)
            self._trim_numpy_cache_by_bytes(self._mini_raw_u8_cache, self._mini_raw_u8_cache_max_bytes)
        pil = Image.fromarray(raw_u8)
        canvas_w = max(40, self._mark_mini_canvas.winfo_width())
        canvas_h = max(40, self._mark_mini_canvas.winfo_height())
        max_w = max(40, canvas_w - 8)
        max_h = max(40, canvas_h - 8)
        pil.thumbnail((max_w, max_h), Image.Resampling.BILINEAR)
        self._mark_popup_mini_image = ImageTk.PhotoImage(pil)
        self._mark_mini_canvas.delete("all")
        self._mark_mini_canvas.create_image(canvas_w // 2, canvas_h // 2, image=self._mark_popup_mini_image, anchor="center")

    def _popup_update_window_info(self) -> None:
        if self._mark_window_info_var is None:
            return
        baseline_count = self._mark_baseline_count_var.get().strip() if self._mark_baseline_count_var is not None else "30"
        baseline_end = self._mark_baseline_end_var.get().strip() if self._mark_baseline_end_var is not None else "0"
        self._mark_window_info_var.set(
            f"Range: [{self._mark_popup_local_start}, {self._mark_popup_local_end}] | "
            f"Baseline: count={baseline_count}, end={baseline_end}{self._mark_last_full_refresh_note}"
        )

    def _popup_update_preview(self, frame_idx: int) -> None:
        if self.reader is None or self.stack_info is None or self._mark_preview_label is None:
            return
        low, high = self._popup_overlay_bounds()
        frame_idx = max(low, min(frame_idx, high))
        self._mark_popup_current_idx = frame_idx

        frame = self._get_popup_processed_frame(frame_idx)
        contrast_factor = float(self._mark_contrast_var.get()) if self._mark_contrast_var is not None else 1.0
        image = self._render_preview_image(
            frame,
            self._mark_preview_label,
            fallback_size=(1000, 700),
            pre_normalized=True,
            contrast_factor=contrast_factor,
        )
        self._mark_popup_image = image
        self._mark_preview_label.configure(image=image)

        self._update_popup_mini_raw(frame_idx)

        if self._mark_frame_info_var is not None:
            frame_name = self.reader.get_frame_name(frame_idx)
            self._mark_frame_info_var.set(f"Frame: {frame_idx}  [{frame_name}]")
        self._popup_update_window_info()
        self._redraw_popup_overlay()

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
        self._pending_main_frame_idx = int(idx)
        if self._pending_main_after_id is not None:
            try:
                self.root.after_cancel(self._pending_main_after_id)
            except Exception:
                pass
        self._pending_main_after_id = self.root.after(16, self._flush_main_preview_update)

    def _flush_main_preview_update(self) -> None:
        self._pending_main_after_id = None
        if self._pending_main_frame_idx is None:
            return
        idx = int(self._pending_main_frame_idx)
        self._pending_main_frame_idx = None
        self._update_preview(idx)

    def _normalize_frame_percentile(self, frame: np.ndarray) -> np.ndarray:
        p1 = float(np.percentile(frame, 1))
        p99 = float(np.percentile(frame, 99))
        if p99 <= p1:
            p99 = p1 + 1.0
        return normalize_visual_frame(frame, p1=p1, p99=p99)

    def _apply_display_contrast(self, frame_u8: np.ndarray, factor: float) -> np.ndarray:
        if factor <= 0:
            return frame_u8
        adjusted = (frame_u8.astype(np.float32) - 127.5) * factor + 127.5
        return np.clip(adjusted, 0.0, 255.0).astype(np.uint8)

    def _render_preview_image(
        self,
        frame: np.ndarray,
        label: ttk.Label,
        fallback_size: tuple[int, int],
        pre_normalized: bool = False,
        contrast_factor: float = 1.0,
    ) -> ImageTk.PhotoImage:
        if pre_normalized and frame.dtype == np.uint8:
            frame_u8 = frame
        else:
            frame_u8 = self._normalize_frame_percentile(frame)
        if abs(contrast_factor - 1.0) > 1e-6:
            frame_u8 = self._apply_display_contrast(frame_u8, contrast_factor)

        img = Image.fromarray(frame_u8)
        max_w = label.winfo_width() - 12
        max_h = label.winfo_height() - 12
        if max_w < 120 or max_h < 120:
            max_w, max_h = fallback_size
        img.thumbnail((max_w, max_h), Image.Resampling.BILINEAR)
        return ImageTk.PhotoImage(img)

    def _cache_main_render(self, key: tuple[int, int, int], image: ImageTk.PhotoImage) -> None:
        self._main_render_cache[key] = image
        self._main_render_cache.move_to_end(key)
        while len(self._main_render_cache) > self._main_render_cache_max:
            self._main_render_cache.popitem(last=False)

    def _update_preview(self, frame_idx: int) -> None:
        if self.reader is None or self.stack_info is None:
            return
        frame_idx = max(0, min(frame_idx, self.stack_info.frame_count - 1))
        self.current_frame_idx = frame_idx
        max_w = self.preview_label.winfo_width() - 12
        max_h = self.preview_label.winfo_height() - 12
        if max_w < 120 or max_h < 120:
            max_w, max_h = (1100, 800)
        cache_key = (int(frame_idx), int(max_w), int(max_h))
        image = self._main_render_cache.get(cache_key)
        if image is None:
            try:
                frame = self.reader.read_frame(frame_idx, use_cache=True)
                image = self._render_preview_image(
                    frame,
                    self.preview_label,
                    fallback_size=(1100, 800),
                    pre_normalized=False,
                    contrast_factor=1.0,
                )
                self._cache_main_render(cache_key, image)
                setattr(self, "_preview_decode_error_shown", False)
            except Exception as exc:
                self._set_status("Preview load failed.")
                self._log_error(f"Preview decode failed for frame {frame_idx}: {exc}")
                if not bool(getattr(self, "_preview_decode_error_shown", False)):
                    self._preview_decode_error_shown = True
                    self._show_warning(
                        "Preview Decode Error",
                        (
                            "Unable to decode one or more stack frames. "
                            "If this is a compressed TIFF stack, required codecs may be missing in this build."
                            f"\n\nDetails: {exc}"
                        ),
                    )
                return
        self.tk_preview_image = image
        self.preview_label.configure(image=image)

        frame_name = self.reader.get_frame_name(frame_idx)
        self.preview_label_info.set(f"Frame: {frame_idx}  [{frame_name}]")
        self._redraw_main_overlay()

    def _scale_value_to_x(
        self,
        scale: tk.Scale | None,
        canvas: tk.Canvas | None,
        value: int,
        start_idx: int,
        end_idx: int,
        width: float,
    ) -> float:
        if scale is not None and canvas is not None:
            try:
                sx, _sy = scale.coords(value)
                x_abs = scale.winfo_rootx() + float(sx)
                cx_abs = canvas.winfo_rootx()
                x_canvas = x_abs - cx_abs
                if 0.0 <= x_canvas <= float(width):
                    return x_canvas
            except Exception:
                pass
        return linear_value_to_x(value, start_idx, end_idx, width)

    def _scale_x_to_value(
        self,
        scale: tk.Scale | None,
        canvas: tk.Canvas | None,
        x_px: float,
        start_idx: int,
        end_idx: int,
        width: float,
    ) -> int:
        if scale is not None and canvas is not None:
            try:
                x_abs = canvas.winfo_rootx() + float(x_px)
                sx = x_abs - scale.winfo_rootx()
                low_x, _ = scale.coords(start_idx)
                high_x, _ = scale.coords(end_idx)
                left = float(min(low_x, high_x))
                right = float(max(low_x, high_x))
                if right > left:
                    frac = max(0.0, min(1.0, (float(sx) - left) / (right - left)))
                    idx = int(round(start_idx + frac * float(end_idx - start_idx)))
                    return max(start_idx, min(end_idx, idx))
            except Exception:
                pass
        return linear_x_to_value(x_px, width, start_idx, end_idx)

    def _draw_overlay_bar(
        self,
        canvas: tk.Canvas | None,
        scale: tk.Scale | None,
        start_idx: int,
        end_idx: int,
        spans: list[tuple[int, int, str]],
        markers: list[tuple[int, str]],
    ) -> None:
        if canvas is None:
            return
        canvas.delete("all")
        w = canvas.winfo_width()
        h = canvas.winfo_height()
        if w <= 2 or h <= 2:
            return

        canvas.create_rectangle(0, 0, w, h, fill="#2a2b2f", outline="")
        if end_idx < start_idx:
            return

        for span_start, span_end, color in spans:
            left_x = self._scale_value_to_x(scale, canvas, span_start, start_idx, end_idx, w)
            right_x = self._scale_value_to_x(scale, canvas, span_end, start_idx, end_idx, w)
            left = max(0.0, min(left_x, right_x))
            right = min(float(w), max(left_x, right_x))
            if right - left < 2.0:
                right = min(float(w), left + 2.0)
            canvas.create_rectangle(left, 0, right, h, fill=color, outline="")

        for marker_idx, color in markers:
            x = self._scale_value_to_x(scale, canvas, marker_idx, start_idx, end_idx, w)
            left = max(0.0, x - 1.5)
            right = min(float(w), x + 1.5)
            canvas.create_rectangle(left, 0, right, h, fill=color, outline="")

    def _redraw_main_overlay(self) -> None:
        if self.preview_overlay is None or self.stack_info is None:
            return
        frame_count = int(self.stack_info.frame_count)
        if frame_count <= 0:
            self._draw_overlay_bar(self.preview_overlay, self.preview_scale, 0, 0, [], [])
            return

        spans = [(event.start_idx, event.end_idx, "#7a57c7") for event in self.events]
        markers = [(self.current_frame_idx, "#e6e6e6")]
        self._draw_overlay_bar(self.preview_overlay, self.preview_scale, 0, frame_count - 1, spans, markers)

    def _on_main_overlay_click(self, event) -> None:
        if self.preview_overlay is None or self.stack_info is None:
            return
        frame_count = int(self.stack_info.frame_count)
        if frame_count <= 0:
            return

        clicked_idx = self._scale_x_to_value(
            self.preview_scale,
            self.preview_overlay,
            event.x,
            0,
            frame_count - 1,
            self.preview_overlay.winfo_width(),
        )

        clicked_event = None
        for ev in self.events:
            if ev.start_idx <= clicked_idx <= ev.end_idx:
                clicked_event = ev
                break

        if clicked_event is not None:
            self._set_active_event_id(clicked_event.event_id)
            if self.tree.exists(clicked_event.event_id):
                self.tree.selection_set(clicked_event.event_id)
                self.tree.see(clicked_event.event_id)
            target_idx = clicked_event.start_idx
            self._log_info(
                f"Overlay click: selected {clicked_event.event_id} and jumped to frame {target_idx}."
            )
        else:
            target_idx = clicked_idx
            self._log_info(f"Overlay click: jumped to frame {target_idx}.")

        self.preview_scale.set(target_idx)
        self._update_preview(target_idx)

    def _popup_overlay_bounds(self) -> tuple[int, int]:
        if self._mark_scale is None:
            return self._mark_popup_local_start, self._mark_popup_local_end
        start_idx = int(float(self._mark_scale.cget("from")))
        end_idx = int(float(self._mark_scale.cget("to")))
        if end_idx < start_idx:
            start_idx, end_idx = end_idx, start_idx
        return start_idx, end_idx

    def _popup_get_normalized_mark_bounds_for_overlay(self) -> tuple[int | None, int | None]:
        start_idx: int | None = None
        end_idx: int | None = None
        if self._mark_start_var is not None:
            raw = self._mark_start_var.get().strip()
            if raw:
                try:
                    start_idx = int(float(raw))
                except ValueError:
                    start_idx = None
        if self._mark_end_var is not None:
            raw = self._mark_end_var.get().strip()
            if raw:
                try:
                    end_idx = int(float(raw))
                except ValueError:
                    end_idx = None
        frame_count = int(self.stack_info.frame_count) if self.stack_info is not None else 0
        return normalize_overlay_bounds(start_idx, end_idx, frame_count)

    def _redraw_popup_overlay(self) -> None:
        if self._mark_overlay is None:
            return
        start_idx, end_idx = self._popup_overlay_bounds()
        mark_start, mark_end = self._popup_get_normalized_mark_bounds_for_overlay()

        spans: list[tuple[int, int, str]] = []
        if mark_start is not None and mark_end is not None:
            left = min(mark_start, mark_end)
            right = max(mark_start, mark_end)
            spans.append((left, right, "#00aebf"))

        if self.stack_info is not None:
            frame_count = int(self.stack_info.frame_count)
            try:
                baseline_count, baseline_end = self._popup_parse_baseline_controls()
                baseline_start = max(0, baseline_end - baseline_count + 1)
                if baseline_end >= 0:
                    spans.append((baseline_start, baseline_end, "#2f6fa5"))
            except Exception:
                pass

        markers = [(self._mark_popup_current_idx, "#e6e6e6")]
        if mark_start is not None:
            markers.append((mark_start, "#00d26a"))
        if mark_end is not None:
            markers.append((mark_end, "#ff5c5c"))
        if self.stack_info is not None:
            try:
                _baseline_count, baseline_end = self._popup_parse_baseline_controls()
                markers.append((baseline_end, "#79ccff"))
            except Exception:
                pass

        self._draw_overlay_bar(self._mark_overlay, self._mark_scale, start_idx, end_idx, spans, markers)

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
            self._mini_raw_u8_cache.clear()
        else:
            while len(self._main_render_cache) > max(8, self._main_render_cache_max // 2):
                self._main_render_cache.popitem(last=False)
            while len(self._mark_processed_cache) > max(8, self._mark_processed_cache_max // 2):
                self._mark_processed_cache.popitem(last=False)
            while len(self._mini_raw_u8_cache) > max(12, self._mini_raw_u8_cache_max // 2):
                self._mini_raw_u8_cache.popitem(last=False)
            self._trim_numpy_cache_by_bytes(self._mark_processed_cache, self._mark_processed_cache_max_bytes)
            self._trim_numpy_cache_by_bytes(self._mini_raw_u8_cache, self._mini_raw_u8_cache_max_bytes)

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
