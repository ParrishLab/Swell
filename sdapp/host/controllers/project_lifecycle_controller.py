from __future__ import annotations

from pathlib import Path
import threading
from tkinter import filedialog, messagebox

from sdapp.host.stack_reader import StackReader


class HostProjectLifecycleController:
    def __init__(self, app) -> None:
        self.app = app

    def _dialog_parent(self):
        return getattr(self.app, "root", None)

    @staticmethod
    def _save_as_initial_name(current_project_path: str | None, *, default_base: str) -> str:
        if not current_project_path:
            return str(default_base)
        current_name = Path(str(current_project_path)).name
        if current_name.lower().endswith(".sdproj"):
            stem = Path(current_name).stem
            return stem or str(default_base)
        return current_name

    def new_project(self) -> None:
        folder = filedialog.askdirectory(
            parent=self._dialog_parent(),
            title="Select Stack Folder",
            mustexist=True,
        )
        if not folder:
            self.app._log_info("New Project canceled: no input folder selected.")
            return
        if not self.prepare_context_switch():
            return
        self.load_stack_from_folder(str(folder))

    def save_project(self) -> None:
        if self.app.stack_info is None:
            self.app._show_warning("Save SD Project", "Load a stack before saving.")
            return
        target = self.app.current_project_path
        if target is None:
            self.save_project_as()
            return
        self.app._set_status("Saving project...")

        def worker() -> None:
            try:
                state = self.app.save_host_session(target)
            except Exception as exc:
                self.app.root.after(0, lambda: self.app._show_warning("Save SD Project", str(exc)))
                self.app.root.after(0, lambda: self.app._set_status("Save failed."))
                return

            def on_done() -> None:
                self.app.current_project_path = state.project_path
                self.app.browser_controller.session.set_project_path(self.app.current_project_path)
                self.app._set_status(f"Saved project: {Path(self.app.current_project_path).name}")
                self.app._log_info(f"Saved project to {self.app.current_project_path}.")

            self.app.root.after(0, on_done)

        threading.Thread(target=worker, daemon=True).start()

    def save_project_as(self) -> None:
        if self.app.stack_info is None:
            self.app._show_warning("Save SD Project", "Load a stack before saving.")
            return
        initial_dir = None
        initial_name = self._save_as_initial_name(self.app.current_project_path, default_base="session")
        if self.app.current_project_path:
            current = Path(self.app.current_project_path)
            initial_dir = str(current.parent)
        else:
            initial_dir = self.app.output_var.get().strip() or str(Path.cwd())
        path = filedialog.asksaveasfilename(
            parent=self._dialog_parent(),
            title="Save SD Project As",
            defaultextension=".sdproj",
            filetypes=[("SD Project", "*.sdproj"), ("All files", "*.*")],
            initialdir=initial_dir,
            initialfile=initial_name,
        )
        if not path:
            return
        self.app._set_status("Saving project...")

        def worker() -> None:
            try:
                state = self.app.save_host_session(path)
            except Exception as exc:
                self.app.root.after(0, lambda: self.app._show_warning("Save SD Project", str(exc)))
                self.app.root.after(0, lambda: self.app._set_status("Save failed."))
                return

            def on_done() -> None:
                self.app.current_project_path = state.project_path
                self.app.browser_controller.session.set_project_path(self.app.current_project_path)
                self.app._set_status(f"Saved project: {Path(self.app.current_project_path).name}")
                self.app._log_info(f"Saved project as {self.app.current_project_path}.")

            self.app.root.after(0, on_done)

        threading.Thread(target=worker, daemon=True).start()

    def open_project_dialog(self) -> None:
        path = filedialog.askopenfilename(
            parent=self._dialog_parent(),
            title="Open SD Project",
            filetypes=[
                ("SD Project", "*.sdproj"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        self.open_project_request(path)

    def open_project_request(self, path: str | Path) -> bool:
        raw = str(path or "").strip()
        if not raw:
            self.app._show_warning("Open SD Project", "Project path is empty.")
            return False
        candidate = Path(raw).expanduser()
        if candidate.suffix.lower() != ".sdproj":
            self.app._show_warning("Open SD Project", "Unsupported project format. Expected .sdproj")
            return False
        resolved = candidate.resolve()
        if not resolved.exists() or not resolved.is_file():
            self.app._show_warning("Open SD Project", f"Project file not found:\n\n{resolved}")
            return False
        self.open_project(str(resolved))
        return True

    def open_project(self, path: str) -> None:
        if not self.prepare_context_switch():
            return
        self.app._set_status("Opening project...")

        def worker() -> None:
            try:
                state = self.app.browser_controller.open_session(path)
                stack_info = None
                reader = None
                warning = None
                stack_ref = state.stack_ref
                if stack_ref is not None and str(stack_ref.input_dir or ""):
                    input_dir = str(stack_ref.input_dir)
                    if Path(input_dir).exists():
                        reader = StackReader()
                        stack_info = reader.open_stack(input_dir)
                    else:
                        warning = f"Stack folder is missing and was not rebound:\n\n{input_dir}"

                def on_done() -> None:
                    self.app.current_project_path = state.project_path
                    self.app.browser_controller.session.set_project_path(self.app.current_project_path)
                    if reader is not None and stack_info is not None:
                        self.app.reader = reader
                        self.app.stack_info = stack_info
                        self.app.browser_controller.bind_frame_source(reader)
                        self.app._popup_engine.set_reader(reader)
                        self.app.preview_scale.configure(from_=0, to=max(0, int(stack_info.frame_count) - 1))
                        frame_idx = 0
                        active_event = self.app.browser_controller.selected_event()
                        if active_event is not None:
                            frame_idx = int(active_event.start_idx)
                        self.app.preview_scale.set(frame_idx)
                        self.app._update_preview(frame_idx)
                    self.app._sync_event_projections()
                    if warning:
                        self.app._show_warning("Open SD Project", warning)
                    self.app._set_status(f"Opened project: {Path(path).name}")
                    self.app._log_info(f"Opened project from {path}.")

                self.app.root.after(0, on_done)
            except Exception as exc:
                self.app.root.after(0, lambda: self.app._set_status("Open failed."))
                self.app.root.after(0, lambda: self.app._log_error(f"Open project failed: {exc}"))
                self.app.root.after(0, lambda: self.app._show_warning("Open SD Project", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def on_analysis_sync(self, payload: dict) -> None:
        result = self.app.browser_controller.apply_analysis_sync(payload)
        if bool(result.get("ok")):
            event_id = result["normalized"]["event_id"]
            self.app._log_info(f"Analysis sync accepted for event {event_id}.")
            self.app._set_status(f"Analysis sync saved: {event_id}")
            return
        code = result.get("code", "PAYLOAD_INVALID")
        message = result.get("message", "Unknown sync validation error.")
        self.app._log_warn(f"Analysis sync rejected [{code}]: {message}")
        self.app._set_status(f"Analysis sync rejected: {code}")

    def on_analysis_state_update(self, payload: dict) -> dict:
        result = self.app.browser_controller.apply_direct_analysis_update(payload)
        event_id = str(result.get("event_id", payload.get("event_id", "")))
        if bool(result.get("ok")):
            self.app._log_info(f"Analysis state updated for event {event_id}.")
            self.app._set_status(f"Analysis state saved: {event_id}")
            return result
        code = str(result.get("code", "PAYLOAD_INVALID"))
        message = str(result.get("message", "Unknown analysis update error."))
        self.app._log_warn(f"Analysis update rejected [{code}]: {message}")
        self.app._set_status(f"Analysis update rejected: {code}")
        return result

    def on_analysis_metrics_update(self, payload: dict) -> dict:
        event_id = str(dict(payload or {}).get("event_id", "")).strip()
        if not event_id:
            return {
                "ok": False,
                "code": "PAYLOAD_INVALID",
                "message": "Missing event_id in metrics update payload.",
            }
        event = self.app.browser_controller.get_event(event_id)
        if event is None:
            return {
                "ok": False,
                "code": "EVENT_NOT_FOUND",
                "message": f"event_id not found in host event catalog: {event_id}",
            }
        metrics_settings = dict(payload or {}).get("metrics_settings")
        changed = self.app.browser_controller.upsert_event_metrics_settings(
            event_id,
            dict(metrics_settings or {}),
            merge_missing_only=False,
        )
        if changed:
            self.app._set_status(f"Metrics settings updated: {event_id}")
            self.app._log_info(f"Updated local metrics settings for event {event_id}.")
        return {"ok": True, "event_id": event_id, "changed": bool(changed)}

    def on_analysis_checkpoint_update(self, payload: dict) -> dict:
        checkpoint_meta = dict(payload or {}).get("model_checkpoint")
        if checkpoint_meta is not None and not isinstance(checkpoint_meta, dict):
            return {
                "ok": False,
                "code": "PAYLOAD_INVALID",
                "message": "model_checkpoint must be an object when provided.",
            }
        self.app.browser_controller.set_model_checkpoint_metadata(
            dict(checkpoint_meta or {}) if isinstance(checkpoint_meta, dict) else None
        )
        self.app._set_status("Model metadata updated from analysis.")
        self.app._log_info("Updated project-recorded model metadata from analysis window.")
        return {"ok": True}

    def on_analysis_sync_result(self, result: dict) -> None:
        if not isinstance(result, dict):
            return
        if bool(result.get("ok")):
            return
        code = str(result.get("code", "PAYLOAD_INVALID"))
        message = str(result.get("message", "Host rejected sync update."))
        self.app._log_warn(f"Analysis window reported host rejection [{code}]: {message}")

    def on_analysis_log_message(self, level: str, context: str, message: str) -> None:
        lvl = str(level or "INFO").upper()
        ctx = str(context or "Analysis")
        text = f"[Analysis:{ctx}] {str(message or '')}".strip()
        if lvl in {"ERROR"}:
            self.app._log_error(text)
            return
        if lvl in {"WARN"}:
            self.app._log_warn(text)
            return
        self.app._log_info(text)

    def on_analysis_project_saved(self, project_path: str) -> None:
        try:
            resolved = str(Path(project_path).expanduser().resolve())
        except Exception:
            resolved = str(project_path)
        self.app.current_project_path = resolved
        self.app.browser_controller.session.set_project_path(resolved)
        self.app._set_status(f"Project path updated from analysis: {Path(resolved).name}")
        self.app._log_info(f"Analysis set host project save target to {resolved}.")

    def save_project_from_analysis(self, project_path: str) -> dict:
        state = self.app.save_host_session(project_path)
        resolved = str(Path(state.project_path).expanduser().resolve())
        self.app.current_project_path = resolved
        self.app.browser_controller.session.set_project_path(resolved)
        self.app._set_status(f"Saved project from analysis: {Path(resolved).name}")
        self.app._log_info(f"Host canonical save completed from analysis window: {resolved}.")
        return {
            "ok": True,
            "project_path": resolved,
        }

    def close_analysis_windows_with_prompt(self) -> dict:
        refs = list(self.app.analysis_window_manager.list_windows())
        if not refs:
            self.app._analysis_windows.clear()
            return {"ok": True}
        dirty_refs = [ref for ref in refs if bool(getattr(ref.app, "project_dirty", False))]
        if dirty_refs:
            count = len(dirty_refs)
            response = messagebox.askyesnocancel(
                "Open Analysis Windows",
                (
                    f"{count} analysis window(s) have unsaved changes.\n\n"
                    "Yes = Save and continue\n"
                    "No = Continue without saving\n"
                    "Cancel = Abort"
                ),
                parent=self._dialog_parent(),
            )
            if response is None:
                return {"ok": False, "reason": "canceled"}
            if response is True:
                for ref in dirty_refs:
                    try:
                        ref.app.save_project()
                    except Exception as exc:
                        self.app._show_warning("Context Switch", f"Failed to save analysis window before switching:\n{exc}")
                        return {"ok": False, "reason": "save_failed"}
                    if bool(getattr(ref.app, "project_dirty", False)):
                        return {"ok": False, "reason": "save_canceled"}
        self.app.analysis_window_manager.close_all()
        self.app._analysis_windows.clear()
        return {"ok": True}

    def prepare_context_switch(self) -> bool:
        result = self.close_analysis_windows_with_prompt()
        return bool(result.get("ok"))

    def load_stack_from_folder(self, folder: str) -> None:
        self.app.input_var.set(folder)
        input_dir = str(folder)

        self.app._set_status("Loading stack...")
        self.app._log_info(f"Stack load started: {input_dir}")
        self.app._load_progress_bucket = -1

        def worker() -> None:
            try:
                reader = StackReader()
                info = reader.open_stack(input_dir, progress_callback=self.on_load_progress)
                self.app.root.after(0, lambda: self.on_stack_loaded(reader, info))
            except Exception as exc:
                self.app.root.after(0, lambda: self.app._set_status(f"Load failed: {exc}"))
                self.app._log_error(f"Stack load failed: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def on_stack_loaded(self, reader: StackReader, info) -> None:
        self.app.reader = reader
        self.app._popup_engine.set_reader(reader)
        self.app.stack_info = info
        self.app.trace = None
        self.app.browser_controller.on_stack_loaded(reader, info)
        self.app.current_project_path = None
        self.app.browser_controller.session.set_project_path(None)
        self.app.current_event_id = None
        self.app.current_frame_idx = 0
        self.app._main_render_cache.clear()
        self.app._mini_raw_u8_cache.clear()
        self.app._mark_processed_cache.clear()
        self.app._sync_event_projections()

        if self.app._mark_popup is not None and self.app._mark_popup.winfo_exists():
            self.app._mark_popup.destroy()

        self.app.preview_scale.configure(from_=0, to=max(0, info.frame_count - 1))
        self.app.preview_scale.set(0)
        self.app._update_preview(0)
        self.app._redraw_main_overlay()
        self.app._set_status(f"Loaded {info.frame_count} frames ({info.frame_width}x{info.frame_height}, dtype={info.dtype})")
        self.app._log_info(
            f"Stack load completed: {info.frame_count} frame(s), shape={info.frame_width}x{info.frame_height}, dtype={info.dtype}."
        )
        self.warmup_main_preview_async()
        self.app._gc_runtime_caches(aggressive=False, run_python_gc=True)

    def warmup_main_preview_async(self) -> None:
        if self.app.reader is None:
            return
        frame_count = int(self.app.reader.get_frame_count())
        if frame_count <= 0:
            return

        indices = list(range(min(8, frame_count)))

        def worker() -> None:
            try:
                for idx in indices:
                    if self.app.reader is None:
                        return
                    self.app.reader.read_frame(idx, use_cache=True)
                self.app._popup_engine.prewarm_smoothed(indices[:4])
                self.app._log_info("Load warmup complete: prefetched initial frames.")
            except Exception as exc:
                self.app._log_warn(f"Load warmup skipped: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def on_load_progress(self, current: int, total: int) -> None:
        if total <= 0:
            return
        bucket = int((current * 100) / total) // 5
        if bucket > self.app._load_progress_bucket:
            self.app._load_progress_bucket = bucket
            self.app._log_info(f"Load progress: indexing files {current}/{total} ({min(100, bucket * 5)}%).")
