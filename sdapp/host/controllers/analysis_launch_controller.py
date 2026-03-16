from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import numpy as np
from PIL import Image, ImageTk
from scipy.ndimage import gaussian_filter

from sdapp.shared.menu.factory import build_shared_menu


class AnalysisLaunchController:
    def __init__(self, app) -> None:
        self.app = app

    @staticmethod
    def load_analysis_app_class():
        from sdapp.analysis.app import SDSegmentationApp

        return SDSegmentationApp

    def prompt_analysis_open_options(self, *, event_id: str, event_start: int, event_end: int) -> dict[str, object] | None:
        dialog = tk.Toplevel(self.app.root)
        dialog.title(f"Open Analysis Options - {event_id}")
        dialog.transient(self.app.root)
        dialog.resizable(False, False)
        dialog.grab_set()

        shell = ttk.Frame(dialog, padding=10)
        shell.pack(fill="both", expand=True)

        ttk.Label(shell, text=f"Event range: {event_start + 1} - {event_end + 1}").pack(anchor="w")

        baseline_row = ttk.Frame(shell)
        baseline_row.pack(fill="x", pady=(8, 6))
        ttk.Label(baseline_row, text="Baseline Frames:").pack(side="left")
        baseline_var = tk.StringVar(value=str(max(1, int(self.app.baseline_pre_frames))))
        baseline_spin = tk.Spinbox(baseline_row, from_=1, to=500, width=6, textvariable=baseline_var)
        baseline_spin.pack(side="left", padx=(8, 0))

        checks = ttk.LabelFrame(shell, text="Processing")
        checks.pack(fill="x", pady=(0, 8))
        smoothing_var = tk.BooleanVar(value=True)
        subtract_var = tk.BooleanVar(value=True)
        normalize_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(checks, text="Smoothing", variable=smoothing_var).pack(anchor="w", padx=6, pady=(4, 2))
        ttk.Checkbutton(checks, text="Baseline Subtraction", variable=subtract_var).pack(anchor="w", padx=6, pady=2)
        ttk.Checkbutton(checks, text="Global Normalization", variable=normalize_var).pack(anchor="w", padx=6, pady=(2, 4))

        preview_frame = ttk.LabelFrame(shell, text="Preview (event start frame)")
        preview_frame.pack(fill="both", expand=True)
        preview_label = ttk.Label(preview_frame, anchor="center")
        preview_label.pack(fill="both", expand=True, padx=6, pady=6)

        footer = ttk.Frame(shell)
        footer.pack(fill="x", pady=(8, 0))
        status_var = tk.StringVar(value="Adjust settings to preview analysis rendering.")
        ttk.Label(footer, textvariable=status_var).pack(side="left")

        result: dict[str, object] = {"ok": False}

        def _read_baseline() -> int:
            try:
                return max(1, int(float(str(baseline_var.get()).strip() or "1")))
            except Exception:
                return max(1, int(self.app.baseline_pre_frames))

        def _refresh_preview() -> None:
            try:
                frame_u8 = self.compute_analysis_preview_frame(
                    event_start=int(event_start),
                    baseline_pre_frames=_read_baseline(),
                    apply_smoothing=bool(smoothing_var.get()),
                    apply_baseline_subtraction=bool(subtract_var.get()),
                    apply_global_normalization=bool(normalize_var.get()),
                )
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
                preview_label.configure(image=tk_img)
                status_var.set("Preview updated.")
            except Exception as exc:
                status_var.set(f"Preview unavailable: {exc}")

        for var in (smoothing_var, subtract_var, normalize_var):
            var.trace_add("write", lambda *_args: _refresh_preview())
        for evt in ("<KeyRelease>", "<FocusOut>", "<<Increment>>", "<<Decrement>>", "<MouseWheel>", "<ButtonRelease-1>"):
            baseline_spin.bind(evt, lambda _e: _refresh_preview())

        buttons = ttk.Frame(shell)
        buttons.pack(fill="x", pady=(8, 0))

        def _cancel() -> None:
            dialog.destroy()

        def _open() -> None:
            baseline_count = _read_baseline()
            result.update(
                {
                    "ok": True,
                    "baseline_pre_frames": int(baseline_count),
                    "processing": {
                        "smoothing": bool(smoothing_var.get()),
                        "baseline_subtraction": bool(subtract_var.get()),
                        "global_normalization": bool(normalize_var.get()),
                    },
                }
            )
            dialog.destroy()

        ttk.Button(buttons, text="Cancel", command=_cancel).pack(side="right")
        ttk.Button(buttons, text="Open Analysis", command=_open).pack(side="right", padx=(0, 8))

        _refresh_preview()
        self.center_window_on_screen(dialog)
        self.app.root.wait_window(dialog)
        return result if bool(result.get("ok")) else None

    def analyze_selected_event(self) -> None:
        if self.app.reader is None or self.app.stack_info is None:
            self.app._show_warning("Open Analysis", "Load a stack first.")
            return
        active_event_id = self.app._active_event_id()
        if active_event_id is None:
            self.app._show_warning("Open Analysis", "Select an event first.")
            return

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
                sync_emitter=None,
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
        if self.app.reader is None:
            return np.zeros((64, 64), dtype=np.uint8)
        frame_idx = max(0, int(event_start))
        raw = np.asarray(self.app.reader.read_frame(frame_idx), dtype=np.float32)
        if raw.ndim == 3 and raw.shape[2] in (3, 4):
            raw = raw[:, :, :3].mean(axis=2)
        target = gaussian_filter(raw, sigma=0.5) if bool(apply_smoothing) else raw

        source_stack = [target]
        working = target
        if bool(apply_baseline_subtraction):
            bcount = max(1, int(baseline_pre_frames))
            bstart = max(0, frame_idx - bcount)
            bindices = list(range(bstart, frame_idx))
            if not bindices:
                bindices = [frame_idx]
            baseline_parts: list[np.ndarray] = []
            for idx in bindices:
                src = np.asarray(self.app.reader.read_frame(int(idx)), dtype=np.float32)
                if src.ndim == 3 and src.shape[2] in (3, 4):
                    src = src[:, :, :3].mean(axis=2)
                baseline_parts.append(gaussian_filter(src, sigma=0.5) if bool(apply_smoothing) else src)
            baseline = np.median(np.stack(baseline_parts, axis=0), axis=0).astype(np.float32, copy=False)
            working = target - baseline
            source_stack = [(part - baseline).astype(np.float32, copy=False) for part in baseline_parts]
            source_stack.append(working)

        if bool(apply_global_normalization):
            sampled = np.stack(source_stack, axis=0)
            p1 = float(np.percentile(sampled, 1))
            p99 = float(np.percentile(sampled, 99))
            denom = p99 - p1
            if denom <= 0:
                denom = 1e-8
            clipped = np.clip(working, p1, p99)
            return np.clip(((clipped - p1) / denom) * 255.0, 0.0, 255.0).astype(np.uint8)
        return self.app._preview_to_u8(working)
