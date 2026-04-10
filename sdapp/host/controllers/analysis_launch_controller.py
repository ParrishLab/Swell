from __future__ import annotations

from collections import OrderedDict
import time
import tkinter as tk
from tkinter import messagebox

import numpy as np
from PIL import Image, ImageTk

from sdapp.analysis.ui.theme import SPACING, apply_theme
from sdapp.host.analysis_payload_mapper import apply_analysis_scope_flags
from sdapp.shared.frame_source import (
    EventScopedFrameSource,
    PreparedFrameSource,
    VisualizationCancelled,
)
from sdapp.shared.frame_source.launch_preparation import build_launch_preparation_cache_key
from sdapp.shared.menu.factory import build_shared_menu
from sdapp.shared.ui import BackgroundTaskRunner
from sdapp.shared.ui.bootstrap import center_window_on_screen as center_window, semantic_button_options, ttk


class AnalysisLaunchController:
    def __init__(self, app) -> None:
        self.app = app

    def _event_display_name(self, event_id: str) -> str:
        try:
            event = self.app.browser_controller.get_event(str(event_id))
        except Exception:
            event = None
        label = str(getattr(event, "label", "") or "").strip() if event is not None else ""
        return label or str(event_id)

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

        self._task_runner().start(_worker)

    def _preview_cache(self) -> OrderedDict:
        cache = getattr(self.app, "_analysis_preview_cache", None)
        if isinstance(cache, OrderedDict):
            return cache
        cache = OrderedDict()
        self.app._analysis_preview_cache = cache
        return cache

    def _task_runner(self) -> BackgroundTaskRunner:
        runner = getattr(self.app, "_background_task_runner", None)
        if isinstance(runner, BackgroundTaskRunner):
            return runner
        runner = BackgroundTaskRunner(self.app.root)
        self.app._background_task_runner = runner
        return runner

    def _cache_preview_entry(self, key: tuple, entry: dict[str, object]) -> None:
        cache = self._preview_cache()
        cache[key] = dict(entry)
        cache.move_to_end(key)
        while len(cache) > 16:
            cache.popitem(last=False)

    @staticmethod
    def _event_scope(event_start: int, event_end: int, baseline_pre_frames: int) -> tuple[int, int, int]:
        scope_start = max(0, int(event_start) - int(max(1, baseline_pre_frames)))
        scope_end = max(scope_start, int(event_end))
        local_frame_idx = max(0, int(event_start) - scope_start)
        return int(scope_start), int(scope_end), int(local_frame_idx)

    def _default_baseline_pre_frames_for_event(self, event_id: str) -> int:
        fallback = max(1, int(getattr(self.app, "baseline_pre_frames", 30) or 30))
        browser = getattr(self.app, "browser_controller", None)
        getter = getattr(browser, "get_event", None)
        if not callable(getter):
            return fallback
        try:
            event = getter(str(event_id))
        except Exception:
            return fallback
        flags = dict(getattr(event, "flags", {}) or {}) if event is not None else {}
        try:
            return max(1, int(flags.get("baseline_pre_frames", fallback)))
        except Exception:
            return fallback

    @staticmethod
    def _launch_processing_options(
        *,
        apply_horizontal_bar_denoise: bool,
        apply_smoothing: bool,
        apply_baseline_subtraction: bool,
        apply_global_normalization: bool,
        apply_stabilization: bool,
    ) -> dict[str, bool]:
        return {
            "horizontal_bar_denoise": bool(apply_horizontal_bar_denoise),
            "smoothing": bool(apply_smoothing),
            "baseline_subtraction": bool(apply_baseline_subtraction),
            "global_normalization": bool(apply_global_normalization),
            "stabilization": bool(apply_stabilization),
        }

    def _launch_preparation_cache_key(
        self,
        *,
        event_id: str,
        event_start: int,
        event_end: int,
        baseline_pre_frames: int,
        apply_horizontal_bar_denoise: bool,
        apply_smoothing: bool,
        apply_baseline_subtraction: bool,
        apply_global_normalization: bool,
        apply_stabilization: bool,
    ) -> tuple[str, int, int, int, bool, bool, bool, bool, bool]:
        scope_start, scope_end, _local_frame_idx = self._event_scope(event_start, event_end, baseline_pre_frames)
        return build_launch_preparation_cache_key(
            event_id=str(event_id or ""),
            scope_start=scope_start,
            scope_end=scope_end,
            baseline_pre_frames=baseline_pre_frames,
            apply_horizontal_bar_denoise=apply_horizontal_bar_denoise,
            apply_smoothing=apply_smoothing,
            apply_baseline_subtraction=apply_baseline_subtraction,
            apply_global_normalization=apply_global_normalization,
            apply_stabilization=apply_stabilization,
        )

    def _prepare_analysis_launch_preview(
        self,
        *,
        event_id: str = "",
        event_start: int,
        event_end: int,
        baseline_pre_frames: int,
        apply_horizontal_bar_denoise: bool,
        apply_smoothing: bool,
        apply_baseline_subtraction: bool,
        apply_global_normalization: bool,
        apply_stabilization: bool,
        should_cancel=None,
    ) -> dict[str, object]:
        started = time.perf_counter()
        frame_source = self.app.browser_controller.get_frame_source()
        if frame_source is None:
            raise RuntimeError("No host frame source is available for analysis.")
        scope_start, scope_end, local_frame_idx = self._event_scope(event_start, event_end, baseline_pre_frames)
        scoped_source = EventScopedFrameSource(frame_source, scope_start, scope_end)
        processing = self._launch_processing_options(
            apply_horizontal_bar_denoise=apply_horizontal_bar_denoise,
            apply_smoothing=apply_smoothing,
            apply_baseline_subtraction=apply_baseline_subtraction,
            apply_global_normalization=apply_global_normalization,
            apply_stabilization=apply_stabilization,
        )
        launch_cache_key = self._launch_preparation_cache_key(
            event_id=str(event_id or ""),
            event_start=event_start,
            event_end=event_end,
            baseline_pre_frames=baseline_pre_frames,
            apply_horizontal_bar_denoise=apply_horizontal_bar_denoise,
            apply_smoothing=apply_smoothing,
            apply_baseline_subtraction=apply_baseline_subtraction,
            apply_global_normalization=apply_global_normalization,
            apply_stabilization=apply_stabilization,
        )
        prepared_source = PreparedFrameSource(
            scoped_source,
            baseline_frames=max(1, int(baseline_pre_frames)),
            apply_horizontal_bar_denoise=bool(apply_horizontal_bar_denoise),
            apply_smoothing=bool(apply_smoothing),
            apply_baseline_subtraction=bool(apply_baseline_subtraction),
            apply_global_normalization=bool(apply_global_normalization),
            apply_stabilization=bool(apply_stabilization),
        )
        stats = prepared_source.prepare(should_cancel=should_cancel)
        raw_frame = prepared_source.get_raw_frame(local_frame_idx)
        sub_frame = prepared_source.get_subtracted_frame(local_frame_idx)
        frame_u8 = prepared_source.get_visual_frame(local_frame_idx)
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
                "cache_key": launch_cache_key,
                "scope_start": int(scope_start),
                "scope_end": int(scope_end),
                "local_frame_idx": int(local_frame_idx),
                "baseline_pre_frames": max(1, int(baseline_pre_frames)),
                "processing": dict(processing),
                "prepared_source": prepared_source,
                "preview_frame_u8": np.asarray(frame_u8, dtype=np.uint8, copy=False),
                "raw_frame": np.asarray(raw_frame, dtype=np.float32, copy=False),
                "sub_frame": np.asarray(sub_frame, dtype=np.float32, copy=False),
                "viz_frame": np.asarray(frame_u8, dtype=np.uint8, copy=False),
                "stats": stats,
            },
        }

    def prompt_analysis_open_options(self, *, event_id: str, event_start: int, event_end: int) -> dict[str, object] | None:
        dialog = tk.Toplevel(self.app.root)
        dialog.withdraw()
        dialog.title(f"Open Analysis Options - {self._event_display_name(str(event_id))}")
        dialog.transient(self.app.root)
        dialog.resizable(False, False)
        dialog.geometry("760x560")
        apply_theme(dialog)

        shell = ttk.Frame(dialog, padding=SPACING.outer, style="AppShell.TFrame")
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=1)

        summary = ttk.Frame(shell, padding=SPACING.card, style="AppSurface.TFrame")
        summary.pack(fill="x", pady=(0, SPACING.inner))
        summary.columnconfigure(0, weight=1)
        summary.columnconfigure(1, weight=0)
        ttk.Label(summary, text=f"Event range: {event_start + 1} - {event_end + 1}", style="AppMeta.TLabel").grid(row=0, column=0, sticky="w")

        default_baseline_pre_frames = self._default_baseline_pre_frames_for_event(str(event_id))

        baseline_row = ttk.Frame(summary, style="AppSurface.TFrame")
        baseline_row.grid(row=0, column=1, sticky="e", padx=(SPACING.inner, 0))
        baseline_var = tk.StringVar(value=str(int(default_baseline_pre_frames)))
        ttk.Label(baseline_row, text="Baseline Frames", style="AppMeta.TLabel").pack(side="left")
        baseline_entry = ttk.Entry(baseline_row, textvariable=baseline_var, width=6, style="AppCompact.TEntry")
        baseline_entry.pack(side="left", padx=(SPACING.gap, 0))

        checks = ttk.Frame(shell, padding=SPACING.card, style="AppSurface.TFrame")
        checks.pack(fill="x", pady=(0, SPACING.inner))
        checks.columnconfigure(0, weight=1)
        checks.columnconfigure(1, weight=1)
        ttk.Label(checks, text="Preprocessing", style="AppSectionTitle.TLabel").pack(anchor="w", pady=(0, SPACING.gap))
        bar_denoise_var = tk.BooleanVar(value=False)
        smoothing_var = tk.BooleanVar(value=True)
        subtract_var = tk.BooleanVar(value=True)
        normalize_var = tk.BooleanVar(value=True)
        stabilize_var = tk.BooleanVar(value=False)
        checks_grid = ttk.Frame(checks, style="AppSurface.TFrame")
        checks_grid.pack(fill="x")
        checks_grid.columnconfigure(0, weight=1)
        checks_grid.columnconfigure(1, weight=1)
        ttk.Checkbutton(checks_grid, text="Horizontal Bar Denoise", variable=bar_denoise_var, style="AppSurface.TCheckbutton").grid(
            row=0, column=0, sticky="w", pady=(0, 2), padx=(0, SPACING.inner)
        )
        ttk.Checkbutton(checks_grid, text="Smoothing", variable=smoothing_var, style="AppSurface.TCheckbutton").grid(
            row=0, column=1, sticky="w", pady=(0, 2)
        )
        ttk.Checkbutton(checks_grid, text="Baseline Subtraction", variable=subtract_var, style="AppSurface.TCheckbutton").grid(
            row=1, column=0, sticky="w", pady=(2, 0), padx=(0, SPACING.inner)
        )
        ttk.Checkbutton(checks_grid, text="Global Normalization", variable=normalize_var, style="AppSurface.TCheckbutton").grid(
            row=1, column=1, sticky="w", pady=(2, 0)
        )
        ttk.Checkbutton(checks_grid, text="Stabilize", variable=stabilize_var, style="AppSurface.TCheckbutton").grid(
            row=2, column=0, sticky="w", pady=(2, 0), padx=(0, SPACING.inner)
        )

        preview_frame = ttk.Frame(shell, padding=SPACING.card, style="AppSurface.TFrame", width=460, height=260)
        preview_frame.pack(fill="x", pady=(0, SPACING.gap))
        preview_frame.pack_propagate(False)
        ttk.Label(preview_frame, text="Preview", style="AppSectionTitle.TLabel").pack(anchor="w", pady=(0, SPACING.gap))
        preview_body = ttk.Frame(preview_frame, padding=SPACING.gap, style="AppInset.TFrame")
        preview_body.pack(fill="both", expand=True)
        preview_label = ttk.Label(preview_body, anchor="center", style="Card.TLabel")
        preview_label.pack(fill="both", expand=True)
        preview_label.configure(text="Loading preview...")

        footer = ttk.Frame(shell, style="AppShell.TFrame")
        footer.pack(fill="x", pady=(8, 0))
        status_var = tk.StringVar(value="Preparing exact preview...")
        ttk.Label(footer, textvariable=status_var, style="AppMeta.TLabel").pack(side="left")

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
                return int(default_baseline_pre_frames)

        def _preview_cache_key() -> tuple:
            return self._launch_preparation_cache_key(
                event_id=str(event_id),
                event_start=int(event_start),
                event_end=int(event_end),
                baseline_pre_frames=_read_baseline(),
                apply_horizontal_bar_denoise=bool(bar_denoise_var.get()),
                apply_smoothing=bool(smoothing_var.get()),
                apply_baseline_subtraction=bool(subtract_var.get()),
                apply_global_normalization=bool(normalize_var.get()),
                apply_stabilization=bool(stabilize_var.get()),
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
            apply_horizontal_bar_denoise = bool(bar_denoise_var.get())
            apply_smoothing = bool(smoothing_var.get())
            apply_subtraction = bool(subtract_var.get())
            apply_normalization = bool(normalize_var.get())
            apply_stabilization = bool(stabilize_var.get())

            def _worker() -> dict[str, object] | None:
                try:
                    return self._prepare_analysis_launch_preview(
                        event_id=str(event_id),
                        event_start=int(event_start),
                        event_end=int(event_end),
                        baseline_pre_frames=int(baseline_count),
                        apply_horizontal_bar_denoise=apply_horizontal_bar_denoise,
                        apply_smoothing=apply_smoothing,
                        apply_baseline_subtraction=apply_subtraction,
                        apply_global_normalization=apply_normalization,
                        apply_stabilization=apply_stabilization,
                        should_cancel=lambda g=generation: bool(state.get("closed")) or int(state.get("generation", 0)) != int(g),
                    )
                except VisualizationCancelled:
                    return None

            def _on_preview(payload: dict[str, object] | None) -> None:
                if not isinstance(payload, dict):
                    return
                self._cache_preview_entry(cache_key, payload)
                _apply_preview(payload, generation)

            def _on_preview_error(exc: Exception) -> None:
                if int(state.get("generation", 0)) == int(generation):
                    status_var.set(f"Preview unavailable: {exc}")

            self._task_runner().start(_worker, on_success=_on_preview, on_error=_on_preview_error)

        def _schedule_preview_refresh() -> None:
            existing = state.get("debounce_after_id")
            if existing:
                try:
                    dialog.after_cancel(existing)
                except Exception:
                    pass
            state["debounce_after_id"] = dialog.after(80, _refresh_preview)

        for var in (bar_denoise_var, smoothing_var, subtract_var, normalize_var, stabilize_var):
            var.trace_add("write", lambda *_args: _schedule_preview_refresh())
        for evt in ("<KeyRelease>", "<FocusOut>", "<Return>", "<MouseWheel>", "<ButtonRelease-1>"):
            baseline_entry.bind(evt, lambda _e: _schedule_preview_refresh())

        buttons = ttk.Frame(shell, style="AppShell.TFrame")
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
                        "horizontal_bar_denoise": bool(bar_denoise_var.get()),
                        "smoothing": bool(smoothing_var.get()),
                        "baseline_subtraction": bool(subtract_var.get()),
                        "global_normalization": bool(normalize_var.get()),
                        "stabilization": bool(stabilize_var.get()),
                    },
                    "launch_preparation": state.get("launch_preparation")
                    or (cached_payload.get("launch_preparation") if isinstance(cached_payload, dict) else None),
                }
            )
            dialog.destroy()

        ttk.Button(buttons, text="Cancel", command=_cancel, **semantic_button_options("secondary")).pack(side="right")
        ttk.Button(buttons, text="Open Analysis", command=_open, **semantic_button_options("primary")).pack(side="right", padx=(0, 8))

        self.center_window_on_screen(dialog, width=760, height=560)
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
        flags = apply_analysis_scope_flags(
            flags,
            event_start=event_start,
            event_end=event_end,
            baseline_pre_frames=baseline_pre,
        )
        flags["analysis_processing"] = dict(options.get("processing", {}))
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
                host_context_for_event=self.app.browser_controller.host_context_for_event,
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
    def center_window_on_screen(window, *, width: int | None = None, height: int | None = None) -> None:
        center_window(window, width=width, height=height)

    def compute_analysis_preview_frame(
        self,
        *,
        event_start: int,
        baseline_pre_frames: int,
        apply_horizontal_bar_denoise: bool,
        apply_smoothing: bool,
        apply_baseline_subtraction: bool,
        apply_global_normalization: bool,
        apply_stabilization: bool,
    ) -> np.ndarray:
        frame_source = self.app.browser_controller.get_frame_source()
        if frame_source is None:
            return np.zeros((64, 64), dtype=np.uint8)
        payload = self._prepare_analysis_launch_preview(
            event_start=int(event_start),
            event_end=int(event_start),
            baseline_pre_frames=max(1, int(baseline_pre_frames)),
            apply_horizontal_bar_denoise=bool(apply_horizontal_bar_denoise),
            apply_smoothing=bool(apply_smoothing),
            apply_baseline_subtraction=bool(apply_baseline_subtraction),
            apply_global_normalization=bool(apply_global_normalization),
            apply_stabilization=bool(apply_stabilization),
        )
        return np.asarray(payload.get("frame_u8"), dtype=np.uint8)
