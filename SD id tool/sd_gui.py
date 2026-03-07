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
from browser_controller import BrowserController
from config import APP_TITLE, DEFAULT_BASELINE_PRE_FRAMES, TraceResult
from exporter import export_analysis
from mark_popup_controller import MarkPopupController
from processing_engine import PopupProcessRequest, PopupProcessResult, PopupProcessingEngine
from stack_reader import StackReader
from ui_logic import (
    adjust_baseline_end_for_start,
    clamp_popup_range,
    linear_value_to_x,
    linear_x_to_value,
    normalize_overlay_bounds,
)


class SDAnalyzerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1400x900")

        self.reader: StackReader | None = None
        self.stack_info = None
        self.trace: TraceResult | None = None
        self.browser_controller = BrowserController()
        self.current_event_id: str | None = None
        self.current_frame_idx = 0
        self.current_project_path: str | None = None
        self.popup_controller = MarkPopupController(self)
        self.baseline_pre_frames = DEFAULT_BASELINE_PRE_FRAMES
        self._set_readers: dict[str, StackReader] = {}
        self._set_stack_infos: dict[str, object] = {}
        self._set_input_dirs: dict[str, str] = {}
        self._sd_set_display_to_id: dict[str, str] = {}
        self._sd_set_var = tk.StringVar(value="")

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

        self._build_ui()
        self._build_menu()
        self.root.protocol("WM_DELETE_WINDOW", self._on_root_close)
        self._schedule_periodic_cache_gc()

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=8)
        main.pack(fill="both", expand=True)

        control = ttk.LabelFrame(main, text="Controls", padding=8)
        control.pack(fill="x")

        ttk.Label(control, text="Input Folder").grid(row=0, column=0, sticky="w")
        self.input_var = tk.StringVar()
        ttk.Entry(control, textvariable=self.input_var, width=70).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(control, text="Load Stack", command=self._load_stack).grid(row=0, column=2, padx=3)

        ttk.Label(control, text="Output Folder").grid(row=1, column=0, sticky="w")
        self.output_var = tk.StringVar(value=str(Path.cwd() / "output"))
        ttk.Entry(control, textvariable=self.output_var, width=70).grid(row=1, column=1, sticky="ew", padx=6)
        ttk.Button(control, text="Browse", command=self._browse_output).grid(row=1, column=2, padx=3)

        control.columnconfigure(1, weight=1)

        self.status_var = tk.StringVar(value="Idle")
        ttk.Label(main, textvariable=self.status_var).pack(anchor="w", pady=(4, 6))

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

        set_frame = ttk.LabelFrame(right_top, text="SD Sets", padding=6)
        set_frame.pack(fill="x", pady=(6, 0))
        set_frame.columnconfigure(0, weight=1)
        self.sd_set_combo = ttk.Combobox(set_frame, textvariable=self._sd_set_var, state="readonly")
        self.sd_set_combo.grid(row=0, column=0, columnspan=3, sticky="ew", padx=2, pady=2)
        self.sd_set_combo.bind("<<ComboboxSelected>>", self._on_sd_set_selected)
        ttk.Button(set_frame, text="Create Set (Load Stack)", command=self._load_stack).grid(
            row=1, column=0, sticky="ew", padx=2, pady=2
        )
        ttk.Button(set_frame, text="Rename Set", command=self._rename_active_sd_set).grid(
            row=1, column=1, sticky="ew", padx=2, pady=2
        )
        ttk.Button(set_frame, text="Delete Set", command=self._delete_active_sd_set).grid(
            row=1, column=2, sticky="ew", padx=2, pady=2
        )

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
        ttk.Button(action_frame, text="Export Selected", command=self._export_selected).grid(
            row=1, column=0, sticky="ew", padx=2, pady=2
        )
        ttk.Button(action_frame, text="Export All", command=self._export_all).grid(
            row=1, column=1, sticky="ew", padx=2, pady=2
        )
        ttk.Button(action_frame, text="Analyze SD", command=self._analyze_selected_event).grid(
            row=2, column=0, columnspan=2, sticky="ew", padx=2, pady=(6, 2)
        )

        bottom_header = ttk.Frame(right_bottom)
        bottom_header.pack(fill="x")
        ttk.Label(bottom_header, text="Drag divider above to resize Events/Logs").pack(side="left")
        ttk.Button(bottom_header, text="Reset Layout", command=self._reset_right_layout).pack(side="right")

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
        self.root.after(220, self._reset_right_layout)
        self._bind_main_keys()
        self._log_info("Application started in manual SD marking mode.")
        self._refresh_sd_set_controls()

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="New Project", command=self._new_project)
        file_menu.add_command(label="Open Project...", command=self._open_project_dialog)
        file_menu.add_separator()
        file_menu.add_command(label="Save Project", command=self._save_project)
        file_menu.add_command(label="Save Project As...", command=self._save_project_as)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_root_close)
        menubar.add_cascade(label="File", menu=file_menu)
        self.root.config(menu=menubar)

    def _browse_input(self) -> None:
        self._log_info("Input browse clicked.")
        folder = filedialog.askdirectory()
        if folder:
            self.input_var.set(folder)
            self._log_info(f"Input folder selected: {folder}")
        else:
            self._log_info("Input browse canceled.")

    def _browse_output(self) -> None:
        self._log_info("Output browse clicked.")
        folder = filedialog.askdirectory()
        if folder:
            self.output_var.set(folder)
            self._log_info(f"Output folder selected: {folder}")
        else:
            self._log_info("Output browse canceled.")

    def _set_status(self, text: str) -> None:
        self.status_var.set(text)

    def _clear_logs(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self._log_info("Logs cleared.")

    def _reset_right_layout(self) -> None:
        if not hasattr(self, "right_split"):
            return
        total = max(self.right_split.winfo_height(), self.root.winfo_height())
        target = int(total * 0.62)
        try:
            self.right_split.sashpos(0, target)
            self._log_info("Layout reset: Events/Logs split restored.")
        except Exception:
            pass

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
        messagebox.showwarning(title, text)

    def save_host_session(self, path: str | None = None):
        return self.browser_controller.save_session(path)

    def _new_project(self) -> None:
        self.browser_controller.reset_project()
        self.current_project_path = None
        self.reader = None
        self.stack_info = None
        self.trace = None
        self.current_frame_idx = 0
        self.current_event_id = None
        self._set_readers.clear()
        self._set_stack_infos.clear()
        self._set_input_dirs.clear()
        self._main_render_cache.clear()
        self._mini_raw_u8_cache.clear()
        self._mark_processed_cache.clear()
        self.preview_scale.configure(from_=0, to=1)
        self.preview_scale.set(0)
        self.preview_label.configure(image="")
        self.preview_label_info.set("Frame: -")
        self._sync_event_projections()
        self._refresh_sd_set_controls()
        self._set_status("New project created.")
        self._log_info("Project reset.")

    def _save_project(self) -> None:
        if not self.browser_controller.list_sd_sets():
            self._show_warning("Save Project", "No SD sets to save.")
            return
        target = self.current_project_path
        if target is None:
            self._save_project_as()
            return
        state = self.save_host_session(target)
        self.current_project_path = state.project_path
        self._set_status(f"Saved project: {Path(self.current_project_path).name}")
        self._log_info(f"Saved project to {self.current_project_path}.")

    def _save_project_as(self) -> None:
        if not self.browser_controller.list_sd_sets():
            self._show_warning("Save Project", "No SD sets to save.")
            return
        path = filedialog.asksaveasfilename(
            title="Save SD Project",
            defaultextension=".sdproj",
            filetypes=[("SD Project", "*.sdproj"), ("All files", "*.*")],
        )
        if not path:
            return
        state = self.save_host_session(path)
        self.current_project_path = state.project_path
        self._set_status(f"Saved project: {Path(self.current_project_path).name}")
        self._log_info(f"Saved project as {self.current_project_path}.")

    def _open_project_dialog(self) -> None:
        path = filedialog.askopenfilename(
            title="Open SD Project",
            filetypes=[
                ("SD Project", "*.sdproj"),
                ("Legacy Session", "*.sdsession"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        self._open_project(path)

    def _open_project(self, path: str) -> None:
        try:
            state = self.browser_controller.open_session(path)
            self.current_project_path = state.project_path
            self._set_readers.clear()
            self._set_stack_infos.clear()
            self._set_input_dirs.clear()
            missing_dirs: list[str] = []
            failed_sets: list[str] = []
            for sd_set_id, sd_set in state.sd_sets.items():
                stack_ref = sd_set.stack_ref
                if stack_ref is None:
                    continue
                input_dir = str(stack_ref.input_dir or "")
                if not input_dir:
                    continue
                self._set_input_dirs[str(sd_set_id)] = input_dir
                if not Path(input_dir).exists():
                    missing_dirs.append(f"{sd_set_id}: {input_dir}")
                    continue
                if not self._bind_reader_for_set(str(sd_set_id), input_dir, show_errors=False):
                    failed_sets.append(str(sd_set_id))
            self._refresh_sd_set_controls()
            active_set_id = self.browser_controller.get_active_sd_set_id()
            if active_set_id is not None:
                self._activate_sd_set(active_set_id, prompt_on_missing=False)
            if missing_dirs:
                self._show_warning(
                    "Open Project",
                    "Some SD set folders are missing and were not rebound:\n\n" + "\n".join(missing_dirs),
                )
            if failed_sets:
                self._show_warning(
                    "Open Project",
                    "Some SD sets failed to load from disk and need manual reload:\n\n" + "\n".join(failed_sets),
                )
            self._set_status(f"Opened project: {Path(path).name}")
            self._log_info(f"Opened project from {path}.")
        except Exception as exc:
            self._log_error(f"Open project failed: {exc}")
            self._show_warning("Open Project", str(exc))

    def _refresh_sd_set_controls(self) -> None:
        sets = self.browser_controller.list_sd_sets()
        self._sd_set_display_to_id = {}
        values: list[str] = []
        active_id = self.browser_controller.get_active_sd_set_id()
        active_label = ""
        for sd_set in sets:
            display_name = str(sd_set.metadata.get("display_name", "")).strip() or str(sd_set.sd_set_id)
            label = f"{display_name} [{sd_set.sd_set_id}]"
            self._sd_set_display_to_id[label] = str(sd_set.sd_set_id)
            values.append(label)
            if str(sd_set.sd_set_id) == str(active_id):
                active_label = label
        if hasattr(self, "sd_set_combo"):
            self.sd_set_combo["values"] = values
            self._sd_set_var.set(active_label if active_label else (values[0] if values else ""))

    def _on_sd_set_selected(self, _event=None) -> None:
        label = self._sd_set_var.get()
        sd_set_id = self._sd_set_display_to_id.get(label)
        if not sd_set_id:
            return
        self._activate_sd_set(sd_set_id)

    def _activate_sd_set(self, sd_set_id: str, prompt_on_missing: bool = True) -> None:
        if not self.browser_controller.select_sd_set(sd_set_id):
            return
        if sd_set_id not in self._set_readers:
            input_dir = self._set_input_dirs.get(sd_set_id)
            if input_dir:
                self._bind_reader_for_set(sd_set_id, input_dir, show_errors=prompt_on_missing)
        reader = self._set_readers.get(sd_set_id)
        info = self._set_stack_infos.get(sd_set_id)
        if reader is not None and info is not None:
            self.reader = reader
            self._popup_engine.set_reader(reader)
            self.stack_info = info
            self.preview_scale.configure(from_=0, to=max(0, int(info.frame_count) - 1))
            frame_idx = 0
            active_event = self.browser_controller.selected_event()
            if active_event is not None:
                frame_idx = int(active_event.start_idx)
            self.preview_scale.set(frame_idx)
            self._update_preview(frame_idx)
        else:
            self.reader = None
            self.stack_info = None
            self.preview_label.configure(image="")
            self.preview_label_info.set("Frame: -")
        self._sync_event_projections()
        self._refresh_sd_set_controls()
        self._set_status(f"Active SD set: {sd_set_id}")

    def _bind_reader_for_set(self, sd_set_id: str, input_dir: str, show_errors: bool = True) -> bool:
        try:
            reader = StackReader()
            info = reader.open_stack(input_dir)
            self._set_readers[sd_set_id] = reader
            self._set_stack_infos[sd_set_id] = info
            self._set_input_dirs[sd_set_id] = input_dir
            self.browser_controller.bind_frame_source_for_set(sd_set_id, reader)
            return True
        except Exception as exc:
            self._log_warn(f"Failed to bind SD set {sd_set_id} from {input_dir}: {exc}")
            if show_errors:
                self._show_warning("Missing SD Stack", f"Could not open stack for {sd_set_id}:\n{input_dir}\n\n{exc}")
            return False

    def _rename_active_sd_set(self) -> None:
        active_id = self.browser_controller.get_active_sd_set_id()
        if active_id is None:
            self._show_warning("Rename SD Set", "No active SD set.")
            return
        current_name = active_id
        for sd_set in self.browser_controller.list_sd_sets():
            if sd_set.sd_set_id == active_id:
                current_name = str(sd_set.metadata.get("display_name", "")).strip() or active_id
                break
        new_name = simpledialog.askstring("Rename SD Set", "Set display name:", initialvalue=current_name, parent=self.root)
        if new_name is None:
            return
        if not self.browser_controller.rename_sd_set(active_id, new_name):
            self._show_warning("Rename SD Set", "Unable to rename SD set.")
            return
        self._refresh_sd_set_controls()
        self._set_status(f"Renamed SD set: {active_id}")

    def _delete_active_sd_set(self) -> None:
        active_id = self.browser_controller.get_active_sd_set_id()
        if active_id is None:
            self._show_warning("Delete SD Set", "No active SD set.")
            return
        if len(self.browser_controller.list_sd_sets()) <= 1:
            self._show_warning("Delete SD Set", "At least one SD set must remain.")
            return
        if not messagebox.askyesno("Delete SD Set", f"Delete {active_id}?"):
            return
        if not self.browser_controller.delete_sd_set(active_id):
            self._show_warning("Delete SD Set", "Unable to delete SD set.")
            return
        self._set_readers.pop(active_id, None)
        self._set_stack_infos.pop(active_id, None)
        self._set_input_dirs.pop(active_id, None)
        next_active = self.browser_controller.get_active_sd_set_id()
        self._refresh_sd_set_controls()
        if next_active is not None:
            self._activate_sd_set(next_active)

    def get_analysis_handoff_payload(self) -> dict | None:
        return self.browser_controller.handoff.selected_event_payload()

    def _on_analysis_sync(self, payload: dict) -> None:
        result = self.browser_controller.apply_analysis_sync(payload)
        if bool(result.get("ok")):
            event_id = result["normalized"]["event_id"]
            self._log_info(f"Analysis sync accepted for event {event_id}.")
            self._set_status(f"Analysis sync saved: {event_id}")
            return
        code = result.get("code", "PAYLOAD_INVALID")
        message = result.get("message", "Unknown sync validation error.")
        self._log_warn(f"Analysis sync rejected [{code}]: {message}")
        self._set_status(f"Analysis sync rejected: {code}")

    def _load_portable_app_class(self):
        repo_root = Path(__file__).resolve().parents[1]
        portable_root = repo_root / "portable_app"
        if str(portable_root) not in sys.path:
            sys.path.append(str(portable_root))
        from app.app import SDSegmentationApp

        return SDSegmentationApp

    def _analyze_selected_event(self) -> None:
        if self.reader is None or self.stack_info is None:
            self._show_warning("Analyze SD", "Load a stack first.")
            return
        active_event_id = self._active_event_id()
        if active_event_id is None:
            self._show_warning("Analyze SD", "Select an event first.")
            return

        handoff = self.get_analysis_handoff_payload()
        if handoff is None:
            self._show_warning("Analyze SD", "Unable to build analysis handoff for selected event.")
            return
        if isinstance(handoff, dict) and handoff.get("ok") is False:
            message = str(handoff.get("message", "Invalid handoff payload."))
            code = str(handoff.get("code", "PAYLOAD_INVALID"))
            self._show_warning("Analyze SD", f"Handoff rejected ({code}).\n{message}")
            return

        frame_source = self.browser_controller.get_frame_source()
        if frame_source is None:
            self._show_warning("Analyze SD", "No host frame source is available for analysis.")
            return

        event_payload = dict(handoff.get("event", {}))
        flags = dict(event_payload.get("flags", {}))
        event_start = int(event_payload.get("start_idx", 0))
        event_end = int(event_payload.get("end_idx", event_start))
        baseline_pre = int(max(0, self.baseline_pre_frames))
        scope_start = max(0, event_start - baseline_pre)
        scope_end = max(scope_start, event_end)
        flags["baseline_pre_frames"] = baseline_pre
        flags["analysis_scope_start_idx"] = scope_start
        flags["analysis_scope_end_idx"] = scope_end
        flags["analysis_local_event_start_idx"] = event_start - scope_start
        flags["analysis_local_event_end_idx"] = event_end - scope_start
        event_payload["flags"] = flags
        handoff["event"] = event_payload

        try:
            AppClass = self._load_portable_app_class()
            win = tk.Toplevel(self.root)
            win.title(f"Analyze SD - {active_event_id}")
            app = AppClass(win)
            open_result = app.open_from_host_handoff(
                handoff,
                frame_source=frame_source,
                sync_emitter=self._on_analysis_sync,
            )
            if not bool(open_result.get("ok")):
                code = str(open_result.get("code", "PAYLOAD_INVALID"))
                message = str(open_result.get("message", "Unknown open error."))
                win.destroy()
                self._show_warning("Analyze SD", f"Open failed ({code}).\n{message}")
                return
            self._analysis_windows.append((win, app))
            self._set_status(f"Opened analysis workspace for {active_event_id}.")
            self._log_info(f"Opened analysis workspace for event {active_event_id}.")
        except Exception as exc:
            self._log_error(f"Analyze SD failed: {exc}")
            self._show_warning("Analyze SD", f"Failed to open analysis workspace:\n{exc}")

    def _on_root_close(self) -> None:
        for win, app in list(self._analysis_windows):
            try:
                if hasattr(win, "winfo_exists") and win.winfo_exists():
                    if hasattr(app, "on_close"):
                        app.on_close()
                    else:
                        win.destroy()
            except Exception:
                pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def _load_stack(self) -> None:
        self._log_info("Load Stack clicked.")
        folder = filedialog.askdirectory(title="Select Stack Folder")
        if not folder:
            self._log_info("Load Stack canceled: no input folder selected.")
            return
        self.input_var.set(folder)
        input_dir = folder

        self._set_status("Loading stack...")
        self._log_info(f"Started loading stack from: {input_dir}")
        self._load_progress_bucket = -1

        def worker() -> None:
            try:
                reader = StackReader()
                info = reader.open_stack(input_dir, progress_callback=self._on_load_progress)
                self.root.after(0, lambda: self._on_stack_loaded(reader, info))
            except Exception as exc:
                self.root.after(0, lambda: self._set_status(f"Load failed: {exc}"))
                self._log_error(f"Load failed: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def _on_stack_loaded(self, reader: StackReader, info) -> None:
        self.reader = reader
        self._popup_engine.set_reader(reader)
        self.stack_info = info
        self.trace = None
        self.browser_controller.on_stack_loaded(reader, info)
        active_set_id = self.browser_controller.get_active_sd_set_id()
        if active_set_id is not None:
            self._set_readers[str(active_set_id)] = reader
            self._set_stack_infos[str(active_set_id)] = info
            input_dir = str(getattr(self.stack_info, "input_dir", "") or self.input_var.get().strip())
            if input_dir:
                self._set_input_dirs[str(active_set_id)] = input_dir
        self.current_event_id = None
        self.current_frame_idx = 0
        self._main_render_cache.clear()
        self._mini_raw_u8_cache.clear()
        self._mark_processed_cache.clear()
        self._sync_event_projections()

        if self._mark_popup is not None and self._mark_popup.winfo_exists():
            self._mark_popup.destroy()

        self.preview_scale.configure(from_=0, to=max(0, info.frame_count - 1))
        self.preview_scale.set(0)
        self._update_preview(0)
        self._refresh_sd_set_controls()
        self._redraw_main_overlay()
        self._set_status(f"Loaded {info.frame_count} frames ({info.frame_width}x{info.frame_height}, dtype={info.dtype})")
        self._log_info(
            f"Load complete: {info.frame_count} frame(s), shape={info.frame_width}x{info.frame_height}, dtype={info.dtype}."
        )
        self._warmup_main_preview_async()
        self._gc_runtime_caches(aggressive=False, run_python_gc=True)

    def _warmup_main_preview_async(self) -> None:
        if self.reader is None:
            return
        frame_count = int(self.reader.get_frame_count())
        if frame_count <= 0:
            return

        indices = list(range(min(8, frame_count)))

        def worker() -> None:
            try:
                for idx in indices:
                    if self.reader is None:
                        return
                    self.reader.read_frame(idx, use_cache=True)
                self._popup_engine.prewarm_smoothed(indices[:4])
                self._log_info("Load warmup complete: prefetched initial frames.")
            except Exception as exc:
                self._log_warn(f"Load warmup skipped: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def _on_load_progress(self, current: int, total: int) -> None:
        if total <= 0:
            return
        bucket = int((current * 100) / total) // 5
        if bucket > self._load_progress_bucket:
            self._load_progress_bucket = bucket
            self._log_info(f"Load progress: indexing files {current}/{total} ({min(100, bucket * 5)}%).")

    def _on_export_progress(self, payload: dict) -> None:
        phase = payload.get("phase")
        if phase == "event":
            self._log_info(
                f"Export event {payload.get('current', 0)}/{payload.get('total', 0)}: {payload.get('event_id', '?')}."
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
        if self.reader is None or self.stack_info is None:
            self._log_warn("Mark popup blocked: no stack loaded.")
            messagebox.showwarning("Mark SD", "Load a stack first.")
            return

        if self._mark_popup is not None and self._mark_popup.winfo_exists():
            self._mark_popup.focus_force()
            self._mark_popup.lift()
            return

        event = self._get_event_by_id(event_id) if event_id else None
        if mode == "edit" and event is None:
            self._log_warn("Edit popup blocked: selected event not found.")
            messagebox.showwarning("Edit", "Selected event was not found.")
            return

        if mode == "edit" and event is not None:
            center_idx = int((event.start_idx + event.end_idx) // 2)
            start_default = event.start_idx
            end_default = event.end_idx
        else:
            center_idx = int(self.current_frame_idx)
            start_default = center_idx
            end_default = center_idx

        frame_count = int(self.stack_info.frame_count)
        self._mark_popup_local_start = max(0, center_idx - 100)
        self._mark_popup_local_end = min(frame_count - 1, center_idx + 100)
        self._mark_range_start_idx = self._mark_popup_local_start
        self._mark_range_end_idx = self._mark_popup_local_end
        self._mark_popup_anchor_idx = center_idx
        self._mark_popup_current_idx = center_idx
        self._mark_last_full_refresh_note = ""
        self._mark_popup_mode = mode
        self._mark_popup_event_id = event_id

        popup = tk.Toplevel(self.root)
        self._mark_popup = popup
        popup.title("Mark SD" if mode == "new" else f"Edit SD ({event_id})")
        popup.geometry("1200x850")
        popup.transient(self.root)

        content = ttk.Frame(popup, padding=8)
        content.pack(fill="both", expand=True)

        top_row = ttk.Frame(content)
        top_row.pack(fill="x", pady=(0, 6))
        self._mark_range_canvas = tk.Canvas(top_row, height=28, bg="#24262a", highlightthickness=0, bd=0, cursor="hand2")
        self._mark_range_canvas.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._mark_range_canvas.bind("<Configure>", lambda _e: self._redraw_popup_range_selector())
        self._mark_range_canvas.bind("<Button-1>", self._popup_range_press)
        self._mark_range_canvas.bind("<B1-Motion>", self._popup_range_drag)
        self._mark_range_canvas.bind("<ButtonRelease-1>", self._popup_range_release)
        ttk.Button(top_row, text="Refresh Current Sequence", command=self._refresh_popup_full_sequence).pack(side="right")

        self._mark_main_view_shell = ttk.Frame(content)
        self._mark_main_view_shell.pack(fill="both", expand=True, pady=(6, 6))
        self._mark_preview_label = ttk.Label(self._mark_main_view_shell, anchor="center")
        self._mark_preview_label.pack(fill="both", expand=True)

        self._mark_mini_frame = ttk.Frame(self._mark_main_view_shell, width=180, height=180)
        self._mark_mini_frame.pack_propagate(False)
        self._mark_mini_frame.place(relx=1.0, rely=0.0, anchor="ne", x=-12, y=12)
        self._mark_mini_canvas = tk.Canvas(
            self._mark_mini_frame,
            bg="black",
            width=170,
            height=170,
            highlightthickness=1,
            highlightbackground="gray",
        )
        self._mark_mini_canvas.pack(fill="both", expand=True)
        self._mark_mini_grip = tk.Label(
            self._mark_mini_frame,
            text="\u2199",
            font=("Arial", 15),
            cursor="fleur",
            bg="#444",
            fg="white",
        )
        self._mark_mini_grip.place(relx=0.0, rely=1.0, anchor="sw", width=24, height=24)
        self._mark_mini_grip.bind("<Button-1>", self._popup_start_resize_mini)
        self._mark_mini_grip.bind("<B1-Motion>", self._popup_do_resize_mini)
        self._mark_mini_grip.bind("<ButtonRelease-1>", self._popup_stop_resize_mini)

        self._mark_frame_info_var = tk.StringVar(value="Frame: -")
        self._mark_window_info_var = tk.StringVar(value="")
        self._mark_loading_var = tk.StringVar(value="")
        self._mark_contrast_var = tk.DoubleVar(value=1.0)
        self._mark_contrast_label_var = tk.StringVar(value="Contrast: 1.00x")
        ttk.Label(content, textvariable=self._mark_frame_info_var).pack(anchor="w", pady=(0, 2))
        ttk.Label(content, textvariable=self._mark_window_info_var).pack(anchor="w", pady=(0, 2))
        self._mark_loading_label = ttk.Label(content, textvariable=self._mark_loading_var, foreground="#8fdcff")
        self._mark_loading_bar = ttk.Progressbar(content, mode="indeterminate")

        self._mark_overlay = tk.Canvas(content, height=12, bg="#2a2b2f", highlightthickness=0, bd=0)
        self._mark_overlay.pack(fill="x", pady=(4, 2))
        self._mark_overlay.bind("<Configure>", lambda _e: self._redraw_popup_overlay())

        self._mark_scale = tk.Scale(
            content,
            from_=self._mark_popup_local_start,
            to=self._mark_popup_local_end,
            orient="horizontal",
            showvalue=False,
            relief="flat",
            highlightthickness=0,
            command=self._popup_on_slide,
        )
        self._mark_scale.pack(fill="x", pady=(0, 6))

        nav_row = ttk.Frame(content)
        nav_row.pack(fill="x", pady=(4, 0))
        ttk.Button(nav_row, text="Prev", command=lambda: self._popup_step(-1)).pack(side="left", padx=2)
        ttk.Button(nav_row, text="Next", command=lambda: self._popup_step(1)).pack(side="left", padx=2)
        ttk.Button(nav_row, text="Set Start", command=self._popup_set_start_current).pack(side="left", padx=6)
        ttk.Button(nav_row, text="Set End", command=self._popup_set_end_current).pack(side="left", padx=2)

        baseline_row = ttk.Frame(content)
        baseline_row.pack(fill="x", pady=(6, 0))
        ttk.Label(baseline_row, text="Baseline Count").pack(side="left")
        baseline_count_default = 30
        baseline_end_default = max(0, self._mark_popup_anchor_idx - 1)
        self._mark_baseline_count_var = tk.StringVar(value=str(baseline_count_default))
        baseline_count_entry = ttk.Entry(baseline_row, textvariable=self._mark_baseline_count_var, width=8)
        baseline_count_entry.pack(side="left", padx=(6, 14))
        ttk.Label(baseline_row, text="Baseline End").pack(side="left")
        self._mark_baseline_end_var = tk.StringVar(value=str(baseline_end_default))
        baseline_end_entry = ttk.Entry(baseline_row, textvariable=self._mark_baseline_end_var, width=8)
        baseline_end_entry.pack(side="left", padx=(6, 18))
        ttk.Label(baseline_row, textvariable=self._mark_contrast_label_var).pack(side="left")
        ttk.Scale(
            baseline_row,
            from_=0.5,
            to=3.0,
            orient="horizontal",
            length=150,
            variable=self._mark_contrast_var,
            command=self._popup_on_contrast_change,
        ).pack(side="left", padx=(8, 0))

        bounds_frame = ttk.Frame(content)
        bounds_frame.pack(fill="x")
        ttk.Label(bounds_frame, text="Start").pack(side="left")
        self._mark_start_var = tk.StringVar(value=str(start_default))
        start_entry = ttk.Entry(bounds_frame, textvariable=self._mark_start_var, width=10)
        start_entry.pack(side="left", padx=(4, 14))
        ttk.Label(bounds_frame, text="End").pack(side="left")
        self._mark_end_var = tk.StringVar(value=str(end_default))
        end_entry = ttk.Entry(bounds_frame, textvariable=self._mark_end_var, width=10)
        end_entry.pack(side="left", padx=(4, 14))
        start_entry.bind(
            "<KeyRelease>",
            lambda _e: (self._redraw_popup_overlay(), self._schedule_popup_recompute(align_baseline_to_start=True)),
        )
        end_entry.bind("<KeyRelease>", lambda _e: self._redraw_popup_overlay())
        start_entry.bind(
            "<Return>", lambda _e: self._schedule_popup_recompute(show_errors=True, align_baseline_to_start=True)
        )
        start_entry.bind(
            "<FocusOut>", lambda _e: self._schedule_popup_recompute(show_errors=True, align_baseline_to_start=True)
        )
        baseline_count_entry.bind("<Return>", lambda _e: self._schedule_popup_recompute(show_errors=True))
        baseline_end_entry.bind("<Return>", lambda _e: self._schedule_popup_recompute(show_errors=True))
        baseline_count_entry.bind("<FocusOut>", lambda _e: self._schedule_popup_recompute(show_errors=True))
        baseline_end_entry.bind("<FocusOut>", lambda _e: self._schedule_popup_recompute(show_errors=True))
        baseline_count_entry.bind("<KeyRelease>", lambda _e: self._schedule_popup_recompute())
        baseline_end_entry.bind("<KeyRelease>", lambda _e: self._schedule_popup_recompute())

        buttons = ttk.Frame(content)
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(buttons, text="Confirm", command=self._popup_confirm).pack(side="right", padx=2)
        ttk.Button(buttons, text="Cancel", command=self._popup_cancel).pack(side="right", padx=2)

        popup.protocol("WM_DELETE_WINDOW", self._popup_cancel)
        popup.bind("<Destroy>", self._on_mark_popup_destroy)
        self._bind_popup_keys(popup)

        popup.update_idletasks()
        self._redraw_popup_range_selector()
        if self._mark_scale is not None:
            self._mark_scale.set(center_idx)
        popup.after_idle(
            lambda: self._recompute_popup_pipeline_for_bounds(
                self._mark_popup_local_start,
                self._mark_popup_local_end,
                show_errors=False,
                loading_text="Computing selected range...",
            )
        )

    def _on_mark_popup_destroy(self, _event=None) -> None:
        popup_ref = self._mark_popup
        if popup_ref is not None and popup_ref.winfo_exists():
            return
        self._popup_engine.cancel_active()
        self._popup_active_job_id = 0
        if self._mark_recompute_after_id is not None and popup_ref is not None:
            try:
                popup_ref.after_cancel(self._mark_recompute_after_id)
            except Exception:
                pass
        if self._pending_popup_after_id is not None and popup_ref is not None:
            try:
                popup_ref.after_cancel(self._pending_popup_after_id)
            except Exception:
                pass
        self._mark_recompute_after_id = None
        self._pending_popup_after_id = None
        self._pending_popup_frame_idx = None
        self._mark_popup = None
        self._mark_popup_mode = None
        self._mark_popup_event_id = None
        self._mark_popup_anchor_idx = 0
        self._mark_popup_image = None
        self._mark_popup_mini_image = None
        self._mark_start_var = None
        self._mark_end_var = None
        self._mark_baseline_count_var = None
        self._mark_baseline_end_var = None
        self._mark_contrast_var = None
        self._mark_contrast_label_var = None
        self._mark_frame_info_var = None
        self._mark_window_info_var = None
        self._mark_loading_var = None
        self._mark_loading_label = None
        self._mark_loading_bar = None
        self._mark_scale = None
        self._mark_preview_label = None
        self._mark_overlay = None
        self._mark_range_canvas = None
        self._mark_range_active_handle = None
        self._mark_range_start_idx = 0
        self._mark_range_end_idx = 0
        self._mark_last_full_refresh_note = ""
        self._mark_recompute_show_errors = False
        self._mark_main_view_shell = None
        self._mark_mini_frame = None
        self._mark_mini_canvas = None
        self._mark_mini_grip = None
        self._mark_resize_start_x = None
        self._mark_resize_start_y = None
        self._mark_resize_start_w = None
        self._mark_resize_start_h = None
        self._mark_baseline_frame = None
        self._mark_norm_p1 = 0.0
        self._mark_norm_p99 = 1.0
        self._mark_processed_cache.clear()
        self._mini_raw_u8_cache.clear()
        self._gc_runtime_caches(aggressive=False, run_python_gc=True)

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
        start_idx, end_idx, clamped_current, _removed = clamp_popup_range(
            start_idx,
            end_idx,
            int(self.stack_info.frame_count),
            self._mark_popup_current_idx,
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
                messagebox.showwarning("Mark SD", str(exc))
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
                messagebox.showwarning("Mark SD", str(error))
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
        if self.stack_info is None or self._mark_popup_mode is None:
            return

        try:
            start_raw = self._mark_start_var.get() if self._mark_start_var is not None else ""
            end_raw = self._mark_end_var.get() if self._mark_end_var is not None else ""
            start = self._parse_frame_index(start_raw, self._mark_popup_current_idx, "Start")
            end = self._parse_frame_index(end_raw, self._mark_popup_current_idx, "End")
            start, end, changed_by_clamp, swapped = self._normalize_bounds(start, end)
        except ValueError as exc:
            self._log_warn(f"Mark popup validation failed: {exc}")
            messagebox.showwarning("Mark SD", str(exc))
            return
        except Exception as exc:
            self._log_error(f"Mark popup failed: {exc}")
            messagebox.showwarning("Mark SD", str(exc))
            return

        duration_frames = end - start + 1
        duration_sec = self._duration_sec(duration_frames)

        if self._mark_popup_mode == "edit":
            event = self._get_event_by_id(self._mark_popup_event_id)
            if event is None:
                self._log_warn("Edit confirm failed: event not found.")
                messagebox.showwarning("Edit", "Selected event was not found.")
                return
            old_start = event.start_idx
            old_end = event.end_idx
            event = self.browser_controller.update_event(
                event.event_id,
                start_idx=start,
                end_idx=end,
                label=event.label,
                frame_count=int(self.stack_info.frame_count),
            )
            self._sync_event_projections()
            self.tree.selection_set(event.event_id)
            self._set_active_event_id(event.event_id)
            self._set_status(f"Updated {event.event_id} boundaries.")
            self._log_info(f"Updated {event.event_id}: [{old_start}, {old_end}] -> [{start}, {end}].")
        else:
            event = self.browser_controller.create_event(
                start_idx=start,
                end_idx=end,
                frame_count=int(self.stack_info.frame_count),
            )
            self._sync_event_projections()
            self.tree.selection_set(event.event_id)
            self._set_active_event_id(event.event_id)
            self._set_status(f"Added {event.event_id}.")
            self._log_info(f"Added {event.event_id}: start={start}, end={end}, duration={duration_frames} frame(s).")

        if changed_by_clamp:
            self._log_info("Popup values were clamped to valid frame range.")
        if swapped:
            self._log_info("Popup swapped start/end to keep start <= end.")

        self.preview_scale.set(start)
        self._update_preview(start)
        self._popup_cancel()

    def _popup_cancel(self) -> None:
        if self._mark_popup is not None and self._mark_popup.winfo_exists():
            self._mark_popup.destroy()

    def _delete_selected_events(self) -> None:
        ids = list(self.tree.selection())
        if not ids:
            self._log_warn("Delete blocked: no events selected.")
            messagebox.showwarning("Event", "Select one or more events first.")
            return

        selected = set(ids)
        deleted = self.browser_controller.delete_events(ids)
        self._sync_event_projections()
        if self._active_event_id() in selected:
            self._set_active_event_id(None)

        self._set_status(f"Deleted {deleted} event(s).")
        self._log_info(f"Deleted {deleted} event(s).")

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

        frame_u8 = np.clip((frame.astype(np.float32) - p1) / (p99 - p1), 0.0, 1.0)
        return (frame_u8 * 255).astype(np.uint8)

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
            frame = self.reader.read_frame(frame_idx, use_cache=True)
            image = self._render_preview_image(
                frame,
                self.preview_label,
                fallback_size=(1100, 800),
                pre_normalized=False,
                contrast_factor=1.0,
            )
            self._cache_main_render(cache_key, image)
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
        self._log_info("Export Selected clicked.")
        ids = self._selected_event_ids()
        if not ids:
            self._log_warn("Export Selected blocked: no events selected.")
            messagebox.showwarning("Export", "Select one or more events in the table.")
            return
        self._log_info(f"Preparing export for {len(ids)} selected event(s).")
        self._run_export(ids)

    def _export_all(self) -> None:
        self._log_info("Export All clicked.")
        if not self.events:
            self._log_warn("Export All blocked: no events available.")
            messagebox.showwarning("Export", "No events to export.")
            return
        self._log_info(f"Preparing export for all {len(self.events)} event(s).")
        self._run_export([event.event_id for event in self.events])

    def _run_export(self, event_ids: list[str]) -> None:
        if self.reader is None:
            self._log_warn("Export blocked: load a stack first.")
            messagebox.showwarning("Export", "Load a stack first.")
            return

        output_dir = self.output_var.get().strip()
        if not output_dir:
            self._log_warn("Export blocked: no output folder selected.")
            messagebox.showwarning("Export", "Select an output folder.")
            return

        baseline_pre = int(self.baseline_pre_frames)
        self._set_status("Exporting...")
        self._export_progress_bucket = -1
        self._log_info(
            f"Started export to {output_dir} for {len(event_ids)} event(s), baseline_pre_frames={baseline_pre}."
        )

        def worker() -> None:
            try:
                assert self.reader is not None
                export_events = self.browser_controller.export_candidates(event_ids)
                result = export_analysis(
                    reader=self.reader,
                    events=export_events,
                    output_dir=output_dir,
                    baseline_pre_frames=baseline_pre,
                    trace=self.trace,
                    selected_event_ids=event_ids,
                    progress_callback=self._on_export_progress,
                )
                self.root.after(0, lambda: self._on_export_done(result))
            except Exception as exc:
                self.root.after(0, lambda: self._set_status(f"Export failed: {exc}"))
                self._log_error(f"Export failed: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def _on_export_done(self, result: dict) -> None:
        self._set_status(f"Export complete: {result['events_exported']} event(s), {result['frames_exported']} frame(s).")
        self._log_info(
            f"Export complete: {result['events_exported']} event(s), {result['frames_exported']} frame(s), "
            f"output={result['output_dir']}."
        )
        self._gc_runtime_caches(aggressive=False, run_python_gc=False)
        messagebox.showinfo("Export", f"Output written to:\n{result['output_dir']}")

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
