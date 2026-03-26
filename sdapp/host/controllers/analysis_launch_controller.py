from __future__ import annotations

from collections import OrderedDict
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import numpy as np
from PIL import Image, ImageTk

from sdapp.shared.frame_source import (
    EventScopedFrameSource,
    VisualizationCancelled,
    compute_visualization_stats,
    render_visualization_frame,
)
from sdapp.shared.menu.factory import build_shared_menu


class AnalysisLaunchController:
    def __init__(self, app) -> None:
        self.app = app

    def load_analysis_app_class(self):
        cached = getattr(self.app, "_analysis_app_class_cache", None)
        if cached is not None:
            return cached
        from sdapp.analysis.app import SDSegmentationApp

        self.app._analysis_app_class_cache = SDSegmentationApp
        return SDSegmentationApp

    def prewarm_analysis_app_class_async(self) -> None:
        if bool(getattr(self.app, "_analysis_app_import_started", False)):
            return
        self.app._analysis_app_import_started = True

        def _worker() -> None:
            try:
                self.load_analysis_app_class()
            except Exception as exc:
                self.app._analysis_app_import_started = False
                self.app._log_warn(f"Analysis prewarm skipped: {exc}")

        threading.Thread(target=_worker, daemon=True).start()

    def _preview_cache(self) -> OrderedDict:
        cache = getattr(self.app, "_analysis_preview_cache", None)
        if isinstance(cache, OrderedDict):
            return cache
        cache = OrderedDict()
        self.app._analysis_preview_cache = cache
        return cache

    def _cache_preview_entry(self, key: tuple, entry: dict[str, object]) -> None:
        cache = self._preview_cache()
        cache[key] = dict(entry)
        cache.move_to_end(key)
        while len(cache) > 16:
            cache.popitem(last=False)

    def _prepare_analysis_launch_preview(
        self,
        *,
        event_start: int,
        event_end: int,
        baseline_pre_frames: int,
        apply_smoothing: bool,
        apply_baseline_subtraction: bool,
        apply_global_normalization: bool,
        should_cancel=None,
    ) -> dict[str, object]:
        started = time.perf_counter()
        frame_source = self.app.browser_controller.get_frame_source()
        if frame_source is None:
            raise RuntimeError("No host frame source is available for analysis.")
        scope_start = max(0, int(event_start) - int(baseline_pre_frames))
        scope_end = max(scope_start, int(event_end))
        local_frame_idx = max(0, int(event_start) - scope_start)
        scoped_source = EventScopedFrameSource(frame_source, scope_start, scope_end)
        stats = compute_visualization_stats(
            scoped_source,
            baseline_frames=max(1, int(baseline_pre_frames)),
            apply_smoothing=bool(apply_smoothing),
            apply_baseline_subtraction=bool(apply_baseline_subtraction),
            apply_global_normalization=bool(apply_global_normalization),
            should_cancel=should_cancel,
        )
        raw_frame, sub_frame, frame_u8 = render_visualization_frame(
            scoped_source,
            local_frame_idx,
            stats=stats,
        )
        log_debug = getattr(self.app, "_log_debug", None)
        message = (
            f"Analysis launch preview elapsed={(time.perf_counter() - started) * 1000.0:.1f}ms "
            f"scope={scope_start + 1}-{scope_end + 1}"
        )
        if callable(log_debug):
            log_debug(message)
        else:
            self.app._log_info(message)
        return {
            "frame_u8": frame_u8,
            "launch_preparation": {
                "scope_start": int(scope_start),
                "scope_end": int(scope_end),
                "local_frame_idx": int(local_frame_idx),
                "raw_frame": np.asarray(raw_frame, dtype=np.float32, copy=False),
                "sub_frame": np.asarray(sub_frame, dtype=np.float32, copy=False),
                "viz_frame": np.asarray(frame_u8, dtype=np.uint8, copy=False),
                "stats": stats,
            },
        }

    def prompt_analysis_open_options(self, *, event_id: str, event_start: int, event_end: int) -> dict[str, object] | None:
        dialog = tk.Toplevel(self.app.root)
        dialog.withdraw()
        dialog.title(f"Open Analysis Options - {event_id}")
        dialog.transient(self.app.root)
        dialog.resizable(False, False)

        shell = ttk.Frame(dialog, padding=10)
        shell.pack(fill="both", expand=True)

        ttk.Label(shell, text=f"Event range: {event_start + 1} - {event_end + 1}").pack(anchor="w")

        baseline_row = ttk.Frame(shell)
        baseline_row.pack(fill="x", pady=(8, 6))
        ttk.Label(baseline_row, text="Baseline Frames:").pack(side="left")
        baseline_var = tk.StringVar(value=str(max(1, int(self.app.baseline_pre_frames))))
        baseline_spin = tk.Spinbox(baseline_row, from_=1, to=500, width=6, textvariable=baseline_var)
        baseline_spin.pack(side="left", padx=(8, 0))

        checks = ttk.LabelFrame(shell, text="Preprocessing")
        checks.pack(fill="x", pady=(0, 8))
        smoothing_var = tk.BooleanVar(value=True)
        subtract_var = tk.BooleanVar(value=True)
        normalize_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(checks, text="Smoothing", variable=smoothing_var).pack(anchor="w", padx=6, pady=(4, 2))
        ttk.Checkbutton(checks, text="Baseline Subtraction", variable=subtract_var).pack(anchor="w", padx=6, pady=2)
        ttk.Checkbutton(checks, text="Global Normalization", variable=normalize_var).pack(anchor="w", padx=6, pady=(2, 4))

        preview_frame = ttk.LabelFrame(shell, text="Preview (event start frame)", width=460, height=260)
        preview_frame.pack(fill="x", pady=(0, 4))
        preview_frame.pack_propagate(False)
        preview_label = ttk.Label(preview_frame, anchor="center")
        preview_label.pack(fill="both", expand=True, padx=6, pady=6)
        preview_label.configure(text="Loading preview...")

        footer = ttk.Frame(shell)
        footer.pack(fill="x", pady=(8, 0))
        status_var = tk.StringVar(value="Preparing exact preview...")
        ttk.Label(footer, textvariable=status_var).pack(side="left")

        result: dict[str, object] = {"ok": False}
        state: dict[str, object] = {
            "generation": 0,
            "debounce_after_id": None,
            "launch_preparation": None,
            "closed": False,
        }

        def _read_baseline() -> int:
            try:
                return max(1, int(float(str(baseline_var.get()).strip() or "1")))
            except Exception:
                return max(1, int(self.app.baseline_pre_frames))

        def _preview_cache_key() -> tuple:
            baseline_count = _read_baseline()
            scope_start = max(0, int(event_start) - int(baseline_count))
            scope_end = max(scope_start, int(event_end))
            return (
                str(event_id),
                int(scope_start),
                int(scope_end),
                int(baseline_count),
                bool(smoothing_var.get()),
                bool(subtract_var.get()),
                bool(normalize_var.get()),
            )

        def _apply_preview(payload: dict[str, object], generation: int) -> None:
            if int(state.get("generation", 0)) != int(generation):
                return
            try:
                if not dialog.winfo_exists():
                    return
            except Exception:
                return
            frame_u8 = np.asarray(payload.get("frame_u8"), dtype=np.uint8)
            img = Image.fromarray(frame_u8)
            max_w, max_h = 440, 240
            w, h = img.size
            if w > 0 and h > 0:
                scale = min(max_w / float(w), max_h / float(h))
                nw = max(1, int(round(w * scale)))
                nh = max(1, int(round(h * scale)))
                resample = getattr(getattr(Image, "Resampling", Image), "NEAREST", Image.NEAREST)
                img = img.resize((nw, nh), resample)
            tk_img = ImageTk.PhotoImage(img)
            self.app._analysis_options_preview_image = tk_img
            preview_label.configure(image=tk_img, text="")
            state["launch_preparation"] = payload.get("launch_preparation")
            status_var.set("Preview updated.")

        def _refresh_preview() -> None:
            if bool(state.get("closed")):
                return
            generation = int(state.get("generation", 0)) + 1
            state["generation"] = generation
            state["launch_preparation"] = None
            preview_label.configure(image="", text="Loading preview...")
            status_var.set("Preparing exact preview...")
            cache_key = _preview_cache_key()
            cached = self._preview_cache().get(cache_key)
            if isinstance(cached, dict):
                _apply_preview(cached, generation)
                return

            baseline_count = _read_baseline()
            apply_smoothing = bool(smoothing_var.get())
            apply_subtraction = bool(subtract_var.get())
            apply_normalization = bool(normalize_var.get())

            def _worker() -> None:
                try:
                    payload = self._prepare_analysis_launch_preview(
                        event_start=int(event_start),
                        event_end=int(event_end),
                        baseline_pre_frames=int(baseline_count),
                        apply_smoothing=apply_smoothing,
                        apply_baseline_subtraction=apply_subtraction,
                        apply_global_normalization=apply_normalization,
                        should_cancel=lambda g=generation: bool(state.get("closed")) or int(state.get("generation", 0)) != int(g),
                    )
                except VisualizationCancelled:
                    return
                except Exception as exc:
                    if hasattr(self.app, "root") and self.app.root is not None:
                        self.app.root.after(
                            0,
                            lambda e=exc, g=generation: (
                                status_var.set(f"Preview unavailable: {e}")
                                if int(state.get("generation", 0)) == int(g)
                                else None
                            ),
                        )
                    return
                self._cache_preview_entry(cache_key, payload)
                if hasattr(self.app, "root") and self.app.root is not None:
                    self.app.root.after(0, lambda p=payload, g=generation: _apply_preview(p, g))

            threading.Thread(target=_worker, daemon=True).start()

        def _schedule_preview_refresh() -> None:
            existing = state.get("debounce_after_id")
            if existing:
                try:
                    dialog.after_cancel(existing)
                except Exception:
                    pass
            state["debounce_after_id"] = dialog.after(80, _refresh_preview)

        for var in (smoothing_var, subtract_var, normalize_var):
            var.trace_add("write", lambda *_args: _schedule_preview_refresh())
        for evt in ("<KeyRelease>", "<FocusOut>", "<<Increment>>", "<<Decrement>>", "<MouseWheel>", "<ButtonRelease-1>"):
            baseline_spin.bind(evt, lambda _e: _schedule_preview_refresh())

        buttons = ttk.Frame(shell)
        buttons.pack(fill="x", pady=(8, 0))

        def _cancel() -> None:
            state["closed"] = True
            state["generation"] = int(state.get("generation", 0)) + 1
            existing = state.get("debounce_after_id")
            if existing:
                try:
                    dialog.after_cancel(existing)
                except Exception:
                    pass
            dialog.destroy()

        def _open() -> None:
            baseline_count = _read_baseline()
            state["closed"] = True
            state["generation"] = int(state.get("generation", 0)) + 1
            existing = state.get("debounce_after_id")
            if existing:
                try:
                    dialog.after_cancel(existing)
                except Exception:
                    pass
            cached_payload = self._preview_cache().get(_preview_cache_key())
            result.update(
                {
                    "ok": True,
                    "baseline_pre_frames": int(baseline_count),
                    "processing": {
                        "smoothing": bool(smoothing_var.get()),
                        "baseline_subtraction": bool(subtract_var.get()),
                        "global_normalization": bool(normalize_var.get()),
                    },
                    "launch_preparation": state.get("launch_preparation")
                    or (cached_payload.get("launch_preparation") if isinstance(cached_payload, dict) else None),
                }
            )
            dialog.destroy()

        ttk.Button(buttons, text="Cancel", command=_cancel).pack(side="right")
        ttk.Button(buttons, text="Open Analysis", command=_open).pack(side="right", padx=(0, 8))

        self.center_window_on_screen(dialog)
        dialog.deiconify()
        dialog.grab_set()
        _schedule_preview_refresh()
        self.app.root.wait_window(dialog)
        return result if bool(result.get("ok")) else None

    def analyze_selected_event(self) -> None:
        model_setup = self.app._get_model_setup_controller()
        allowed, reason = model_setup.is_analysis_allowed()
        if not allowed:
            self.app._show_warning(
                "Open Analysis",
                f"Analysis is disabled until model setup is complete.\n\nCurrent state: {reason}",
            )
            open_manager = messagebox.askyesno(
                "Model Setup Required",
                "Open Manage Models now?",
                parent=self.app.root,
            )
            if open_manager:
                model_setup.open_model_manager(required=False)
            return

        if self.app.reader is None or self.app.stack_info is None:
            self.app._show_warning("Open Analysis", "Load a stack first.")
            return
        active_event_id = self.app._active_event_id()
        if active_event_id is None:
            open_full_stack = messagebox.askyesno(
                "Open Analysis",
                "No SD event is selected.\n\n"
                "Open analysis on the entire host stack instead?\n\n"
                "This will create or reuse a Full Stack Analysis event before opening the analysis preview.",
                parent=self.app.root,
            )
            if not open_full_stack:
                return
            try:
                full_stack_event = self.app.browser_controller.ensure_full_stack_analysis_event(
                    frame_count=int(self.app.stack_info.frame_count)
                )
            except Exception as exc:
                self.app._show_warning("Open Analysis", f"Unable to prepare full-stack event:\n{exc}")
                return
            active_event_id = str(full_stack_event.event_id)

        window_scope = "__project__"
        if self.app.analysis_window_manager.focus_event_window(window_scope, active_event_id):
            self.app._set_status(f"Focused analysis workspace for {active_event_id}.")
            return

        frame_source = self.app.browser_controller.get_frame_source()
        if frame_source is None:
            self.app._show_warning("Open Analysis", "No host frame source is available for analysis.")
            return

        try:
            context = self.app.browser_controller.host_context_for_event(active_event_id)
        except Exception as exc:
            self.app._show_warning("Open Analysis", f"Unable to prepare host context:\n{exc}")
            return

        mismatch_result = model_setup.resolve_project_model_mismatch(context.get("project_metadata"))
        if not bool(mismatch_result.get("ok")):
            action = str(mismatch_result.get("action", "blocked"))
            if action == "disabled":
                self.app._show_warning(
                    "Open Analysis",
                    "Model tools are disabled (review-only mode). Resolve model setup from Model > Manage Models...",
                )
            elif action not in {"switch_canceled"}:
                self.app._show_warning(
                    "Open Analysis",
                    str(mismatch_result.get("message", "Model mismatch must be resolved before opening analysis.")),
                )
            return
        context["model_context"] = model_setup.build_host_model_context()

        event_payload = dict(context.get("event", {}))
        flags = dict(event_payload.get("flags", {}))
        event_start = int(event_payload.get("start_idx", 0))
        event_end = int(event_payload.get("end_idx", event_start))
        options = self.prompt_analysis_open_options(
            event_id=str(active_event_id),
            event_start=event_start,
            event_end=event_end,
        )
        if options is None:
            self.app._log_info("Open Analysis canceled from options dialog.")
            return
        baseline_pre = int(max(1, int(options.get("baseline_pre_frames", self.app.baseline_pre_frames))))
        self.app.baseline_pre_frames = baseline_pre
        scope_start = max(0, event_start - baseline_pre)
        scope_end = max(scope_start, event_end)
        flags["baseline_pre_frames"] = baseline_pre
        flags["analysis_processing"] = dict(options.get("processing", {}))
        flags["analysis_scope_start_idx"] = scope_start
        flags["analysis_scope_end_idx"] = scope_end
        flags["analysis_local_event_start_idx"] = event_start - scope_start
        flags["analysis_local_event_end_idx"] = event_end - scope_start
        event_payload["flags"] = flags
        context["event"] = event_payload
        try:
            self.app.browser_controller.update_event(
                str(active_event_id),
                start_idx=None,
                end_idx=None,
                label=None,
                frame_count=int(self.app.stack_info.frame_count),
                flags=flags,
            )
        except Exception as exc:
            self.app._log_warn(f"Unable to persist analysis preprocessing settings for {active_event_id}: {exc}")
        launch_preparation = options.get("launch_preparation")
        try:
            app_cls = self.load_analysis_app_class()
            win = tk.Toplevel(self.app.root)
            win.withdraw()
            win.title(f"Open Analysis - {active_event_id}")

            analysis_app = app_cls(win, menu_builder=build_shared_menu, menu_mode="analysis", host_mode=True)
            open_result = analysis_app.open_from_host_context(
                context,
                frame_source=frame_source,
                on_analysis_update=self.app._on_analysis_state_update,
                on_project_saved=self.app._on_analysis_project_saved,
                on_sync_result=self.app._on_analysis_sync_result,
                on_log_message=self.app._on_analysis_log_message,
                on_host_project_save=self.app._save_project_from_analysis,
                on_host_project_path=lambda: self.app.current_project_path,
                on_metrics_update=self.app._on_analysis_metrics_update,
                on_global_metrics_update=self.app._on_analysis_global_metrics_update,
                on_checkpoint_update=self.app._on_analysis_checkpoint_update,
                on_open_model_manager=self.app.open_model_manager,
                sync_emitter=None,
                launch_preparation=launch_preparation,
            )
            if not bool(open_result.get("ok")):
                code = str(open_result.get("code", "PAYLOAD_INVALID"))
                message = str(open_result.get("message", "Unknown open error."))
                win.destroy()
                self.app._show_warning("Open Analysis", f"Open failed ({code}).\n{message}")
                return
            self.center_window_on_screen(win)
            win.deiconify()
            win.after_idle(lambda w=win: self.center_window_on_screen(w))
            self.app.analysis_window_manager.open_event_window(window_scope, active_event_id, win, analysis_app)
            self.app._analysis_windows.append((win, analysis_app))

            def _on_analysis_destroy(_event=None, sid=str(window_scope), eid=str(active_event_id)) -> None:
                self.app.analysis_window_manager.unregister(sid, eid)
                self.app._analysis_windows = [
                    (w, a)
                    for (w, a) in self.app._analysis_windows
                    if bool(hasattr(w, "winfo_exists") and w.winfo_exists())
                ]
                try:
                    build_shared_menu(self.app.root, self.app, mode="host", host_mode=False)
                except Exception:
                    pass

            win.bind("<Destroy>", _on_analysis_destroy)
            self.app._set_status(f"Opened analysis workspace for {active_event_id}.")
            self.app._log_info(f"Opened analysis workspace for event {active_event_id}.")
        except Exception as exc:
            self.app._log_error(f"Open Analysis failed: {exc}")
            self.app._show_warning("Open Analysis", f"Failed to open analysis workspace:\n{exc}")

    @staticmethod
    def center_window_on_screen(window) -> None:
        try:
            window.update_idletasks()
            width = int(window.winfo_width())
            height = int(window.winfo_height())
            if width <= 1:
                width = int(window.winfo_reqwidth())
            if height <= 1:
                height = int(window.winfo_reqheight())
            width = max(1, width)
            height = max(1, height)
            x = max(0, int((int(window.winfo_screenwidth()) - width) / 2))
            y = max(0, int((int(window.winfo_screenheight()) - height) / 2))
            window.geometry(f"{width}x{height}+{x}+{y}")
        except Exception:
            return

    def compute_analysis_preview_frame(
        self,
        *,
        event_start: int,
        baseline_pre_frames: int,
        apply_smoothing: bool,
        apply_baseline_subtraction: bool,
        apply_global_normalization: bool,
    ) -> np.ndarray:
        frame_source = self.app.browser_controller.get_frame_source()
        if frame_source is None:
            return np.zeros((64, 64), dtype=np.uint8)
        scope_start = max(0, int(event_start) - int(max(1, baseline_pre_frames)))
        scoped_source = EventScopedFrameSource(frame_source, scope_start, int(event_start))
        stats = compute_visualization_stats(
            scoped_source,
            baseline_frames=max(1, int(baseline_pre_frames)),
            apply_smoothing=bool(apply_smoothing),
            apply_baseline_subtraction=bool(apply_baseline_subtraction),
            apply_global_normalization=bool(apply_global_normalization),
        )
        _raw, _sub, viz = render_visualization_frame(
            scoped_source,
            int(event_start) - int(scope_start),
            stats=stats,
        )
        return viz
