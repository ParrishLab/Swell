from __future__ import annotations

from pathlib import Path

import numpy as np

from sdapp.shared.frame_source import EventScopedFrameSource, build_visualization_stack


class AnalysisHostModeController:
    def __init__(self, app) -> None:
        self.app = app

    def emit_host_sync(self, reason: str) -> dict[str, object] | None:
        if not hasattr(self.app, "analysis_workspace") or self.app.analysis_workspace is None:
            return None
        if callable(getattr(self.app, "_host_analysis_updater", None)):
            payload = self.app.analysis_workspace.export_active_event_analysis_payload()
            if payload is not None:
                payload["metrics_settings"] = self.app._collect_current_metrics_settings()
                try:
                    result = self.app._host_analysis_updater(payload)
                    if isinstance(result, dict):
                        if bool(result.get("ok")):
                            self.app.log_debug("HostSync", f"Applied direct host update on {reason}.")
                        else:
                            code = str(result.get("code", "PAYLOAD_INVALID"))
                            message = str(result.get("message", "Host rejected update."))
                            self.app.log_warn("HostSync", f"Host rejected update [{code}]: {message}")
                            try:
                                self.app.lbl_status.configure(text=f"Status: Host rejected sync ({code})", foreground="orange")
                            except Exception:
                                pass
                        notifier = getattr(self.app, "_host_sync_result_notifier", None)
                        if callable(notifier):
                            try:
                                notifier(result)
                            except Exception:
                                pass
                    else:
                        self.app.log_debug("HostSync", f"Applied direct host update on {reason}.")
                except Exception as exc:
                    self.app.log_warn("HostSync", f"Direct host update failed: {exc}")
            return payload
        payload = self.app.analysis_workspace.emit_host_sync(ui_hints=self.app._host_ui_hints())
        if payload is not None:
            self.app.log_debug("HostSync", f"Emitted host sync on {reason}.")
        return payload

    def open_from_host_context(
        self,
        context: dict,
        frame_source=None,
        on_analysis_update=None,
        on_metrics_update=None,
        on_project_saved=None,
        on_sync_result=None,
        on_log_message=None,
        on_host_project_save=None,
        on_host_project_path=None,
        sync_emitter=None,
    ):
        self.app._ensure_analysis_workspace()
        self.app._host_mode = True
        self.app._host_analysis_updater = on_analysis_update
        self.app._host_project_saved_notifier = on_project_saved
        self.app._host_sync_result_notifier = on_sync_result
        self.app._host_log_notifier = on_log_message
        self.app._host_metrics_updater = on_metrics_update
        self.app._host_project_saver = on_host_project_save
        self.app._host_project_path_provider = on_host_project_path
        if not callable(self.app._host_project_saver):
            return {
                "ok": False,
                "code": "PAYLOAD_INVALID",
                "message": "Host project saver callback is required for host-bound analysis.",
            }
        if isinstance(context, dict):
            project_path = context.get("project_path")
            if isinstance(project_path, str) and project_path.strip():
                self.app.current_project_path = str(Path(project_path).expanduser().resolve())
        if not self.app.current_project_path and callable(self.app._host_project_path_provider):
            try:
                host_path = self.app._host_project_path_provider()
            except Exception:
                host_path = None
            if isinstance(host_path, str) and host_path.strip():
                self.app.current_project_path = str(Path(host_path).expanduser().resolve())
        event_id = ""
        if isinstance(context, dict):
            event_payload = dict(context.get("event", {}))
            event_id = str(event_payload.get("event_id", "") or "")
            analysis_state = context.get("analysis_state")
            if event_id:
                self.app._saved_project_masks_by_event[str(event_id)] = self.app._analysis_payload_has_saved_masks(analysis_state)
            flags = dict(event_payload.get("flags", {})) if isinstance(event_payload.get("flags"), dict) else {}
            processing = (
                dict(flags.get("analysis_processing", {}))
                if isinstance(flags.get("analysis_processing"), dict)
                else {}
            )
            self.app._host_processing_options = {
                "apply_smoothing": bool(processing.get("smoothing", True)),
                "apply_baseline_subtraction": bool(processing.get("baseline_subtraction", True)),
                "apply_global_normalization": bool(processing.get("global_normalization", True)),
            }
        scoped_source = frame_source
        if frame_source is not None:
            event = dict(context.get("event", {})) if isinstance(context, dict) else {}
            flags = dict(event.get("flags", {})) if isinstance(event.get("flags"), dict) else {}
            scope_start = flags.get("analysis_scope_start_idx", event.get("start_idx"))
            scope_end = flags.get("analysis_scope_end_idx", event.get("end_idx"))
            if scope_start is not None and scope_end is not None:
                scoped_source = EventScopedFrameSource(frame_source, int(scope_start), int(scope_end))
            self.app.frame_source = scoped_source
        if self.app.frame_source is not None:
            self.app.analysis_workspace.bind_frame_source(self.app.frame_source)
        result = self.app.analysis_workspace.open_from_host_event_context(
            context,
            frame_source=self.app.frame_source,
            sync_emitter=sync_emitter,
        )
        if not bool(result.get("ok")):
            return result
        metrics_settings = context.get("metrics_settings") if isinstance(context, dict) else None
        self.app._apply_host_metrics_settings(metrics_settings if isinstance(metrics_settings, dict) else None)
        self.app._sync_saved_mask_overlay_state()
        if self.app.frame_source is not None:
            try:
                ready = bool(
                    self.app._prepare_host_mode_buffers(
                        self.app.frame_source,
                        on_ready_message="Host direct workspace initialized.",
                    )
                )
            except TypeError:
                ready = bool(self.app._prepare_host_mode_buffers(self.app.frame_source))
            if hasattr(self.app, "app_context") and self.app.app_context is not None:
                self.app.app_context.frame_source = self.app.frame_source
            if ready:
                self.app._post_host_mode_open_ui("Host direct workspace initialized.")
        model_path = ""
        try:
            model_path = str(self.app.entry_model.get() or "").strip()
        except Exception:
            model_path = ""
        if model_path:
            self.app.log_info("HostMode", "Initializing SAM2 for host-driven workspace...")
            self.app._run_thread(self.app._init_sam2_background)
        else:
            self.app.log_warn("HostMode", "No SAM2 model configured; model tools will remain disabled.")
        return result

    def open_from_host_handoff(self, payload: dict, frame_source=None, sync_emitter=None):
        self.app._ensure_analysis_workspace()
        self.app._host_mode = True
        self.app._host_analysis_updater = None
        self.app._host_project_saved_notifier = None
        self.app._host_sync_result_notifier = None
        self.app._host_log_notifier = None
        self.app._host_metrics_updater = None
        self.app._host_project_saver = None
        self.app._host_project_path_provider = None
        self.app._host_processing_options = None
        self.app._saved_project_masks_by_event = {}
        scoped_source = frame_source
        if frame_source is not None:
            event = dict(payload.get("event", {})) if isinstance(payload, dict) else {}
            flags = dict(event.get("flags", {})) if isinstance(event.get("flags"), dict) else {}
            scope_start = flags.get("analysis_scope_start_idx", event.get("start_idx"))
            scope_end = flags.get("analysis_scope_end_idx", event.get("end_idx"))
            if scope_start is not None and scope_end is not None:
                scoped_source = EventScopedFrameSource(frame_source, int(scope_start), int(scope_end))
            self.app.frame_source = scoped_source
            processing = (
                dict(flags.get("analysis_processing", {}))
                if isinstance(flags.get("analysis_processing"), dict)
                else {}
            )
            self.app._host_processing_options = {
                "apply_smoothing": bool(processing.get("smoothing", True)),
                "apply_baseline_subtraction": bool(processing.get("baseline_subtraction", True)),
                "apply_global_normalization": bool(processing.get("global_normalization", True)),
            }
        if self.app.frame_source is not None:
            self.app.analysis_workspace.bind_frame_source(self.app.frame_source)
        result = self.app.analysis_workspace.open_from_handoff_payload(
            payload,
            frame_source=self.app.frame_source,
            sync_emitter=sync_emitter,
        )
        if not bool(result.get("ok")):
            return result
        self.app._sync_saved_mask_overlay_state()

        if self.app.frame_source is not None:
            try:
                ready = bool(
                    self.app._prepare_host_mode_buffers(
                        self.app.frame_source,
                        on_ready_message="Host-driven analysis workspace initialized.",
                    )
                )
            except TypeError:
                ready = bool(self.app._prepare_host_mode_buffers(self.app.frame_source))
            if hasattr(self.app, "app_context") and self.app.app_context is not None:
                self.app.app_context.frame_source = self.app.frame_source
            if ready:
                self.app._post_host_mode_open_ui("Host-driven analysis workspace initialized.")
        model_path = ""
        try:
            model_path = str(self.app.entry_model.get() or "").strip()
        except Exception:
            model_path = ""
        if model_path:
            self.app.log_info("HostMode", "Initializing SAM2 for host-driven workspace...")
            self.app._run_thread(self.app._init_sam2_background)
        else:
            self.app.log_warn("HostMode", "No SAM2 model configured; model tools will remain disabled.")
        return result

    def post_host_mode_open_ui(self, message: str) -> None:
        if not (hasattr(self.app, "slider") and hasattr(self.app, "canvas_left")):
            return
        self.app._finalize_load_ui()
        active_event_id = str(getattr(self.app, "active_event_id", "") or "")
        if active_event_id and hasattr(self.app, "analysis_workspace") and self.app.analysis_workspace is not None:
            try:
                self.app.analysis_workspace.open_event(active_event_id)
            except Exception:
                pass
        self.app._sync_saved_mask_overlay_state()
        self.app.display_ratio = 1.0
        self.app.img_offset_x = 0
        self.app.img_offset_y = 0
        self.app.root.after_idle(lambda: self.app.update_display(update_preview=True))
        self.app.root.after(120, lambda: self.app.update_display(update_preview=True))
        self.app.log_info("HostMode", message)
        try:
            self.app.lbl_status.configure(text="Status: Host-bound mode (project managed by SD ID)", foreground="gray")
        except Exception:
            pass

    def prepare_host_mode_buffers(self, frame_source, on_ready_message: str | None = None):
        if not hasattr(self.app, "_host_buffer_generation"):
            self.app._host_buffer_generation = 0
        if not hasattr(self.app, "_host_buffer_cache_key"):
            self.app._host_buffer_cache_key = None
        if not hasattr(self.app, "_host_buffer_sync_limit"):
            self.app._host_buffer_sync_limit = 240
        frame_count = int(getattr(frame_source, "frame_count", 0) or 0)
        if frame_count <= 0:
            self.app.frames_raw = None
            self.app.frames_sub = None
            self.app.frames_sub_viz = None
            self.app.frame_names = []
            self.app._current_image_source_paths = []
            self.app._host_buffer_cache_key = None
            return True

        baseline_count = 30
        if hasattr(self.app, "spin_baseline"):
            try:
                baseline_count = int(self.app.spin_baseline.get())
            except Exception:
                baseline_count = 30
        if bool(getattr(self.app, "_host_mode", False)):
            workspace = getattr(self.app, "analysis_workspace", None)
            host_ctx = getattr(workspace, "_host_context", None)
            if isinstance(host_ctx, dict):
                event_payload = dict(host_ctx.get("event", {}))
                flags = dict(event_payload.get("flags", {})) if isinstance(event_payload.get("flags"), dict) else {}
                try:
                    baseline_count = int(flags.get("baseline_pre_frames", baseline_count))
                except Exception:
                    pass
            baseline_count = max(1, int(baseline_count))
            if hasattr(self.app, "spin_baseline"):
                try:
                    self.app._set_spinbox_value(self.app.spin_baseline, baseline_count)
                except Exception:
                    pass
        self.app.frame_names = list(getattr(frame_source, "frame_names", []))
        self.app._current_image_source_paths = list(getattr(frame_source, "source_paths", []))
        baseline_count = int(max(1, baseline_count))
        processing_opts = dict(getattr(self.app, "_host_processing_options", {}) or {})
        apply_smoothing = bool(processing_opts.get("apply_smoothing", True))
        apply_baseline_subtraction = bool(processing_opts.get("apply_baseline_subtraction", True))
        apply_global_normalization = bool(processing_opts.get("apply_global_normalization", True))
        cache_key = (
            id(frame_source),
            int(frame_count),
            tuple(int(v) for v in getattr(frame_source, "frame_shape", (0, 0))),
            int(baseline_count),
            bool(apply_smoothing),
            bool(apply_baseline_subtraction),
            bool(apply_global_normalization),
        )
        if self.app._host_buffer_cache_key == cache_key and self.app.frames_sub_viz is not None:
            return True

        sync_limit = int(getattr(self.app, "_host_buffer_sync_limit", 240))
        if frame_count <= sync_limit:
            raw_frames, frames_sub, frames_viz = build_visualization_stack(
                frame_source,
                baseline_frames=baseline_count,
                apply_smoothing=apply_smoothing,
                apply_baseline_subtraction=apply_baseline_subtraction,
                apply_global_normalization=apply_global_normalization,
            )
            self.app.frames_raw = raw_frames
            self.app.frames_sub = frames_sub
            self.app.frames_sub_viz = frames_viz
            self.app._host_buffer_cache_key = cache_key
            return True

        self.app.frames_raw = None
        self.app.frames_sub = None
        self.app.frames_sub_viz = None
        self.app._host_buffer_cache_key = None
        self.app._host_buffer_generation += 1
        generation = self.app._host_buffer_generation
        self.app.log_info("HostMode", f"Preparing visualization cache in background ({frame_count} frames)...")

        def _worker() -> None:
            raw_frames, frames_sub, frames_viz = build_visualization_stack(
                frame_source,
                baseline_frames=baseline_count,
                apply_smoothing=apply_smoothing,
                apply_baseline_subtraction=apply_baseline_subtraction,
                apply_global_normalization=apply_global_normalization,
            )

            def _apply() -> None:
                if generation != self.app._host_buffer_generation:
                    return
                self.app.frames_raw = raw_frames
                self.app.frames_sub = frames_sub
                self.app.frames_sub_viz = frames_viz
                self.app._host_buffer_cache_key = cache_key
                if self.app._ui_alive():
                    self.app._post_host_mode_open_ui(on_ready_message or "Host workspace ready.")

            if self.app._ui_alive():
                self.app.root.after(0, _apply)

        self.app._run_thread(_worker)
        return False
