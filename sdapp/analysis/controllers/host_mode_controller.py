from __future__ import annotations

from pathlib import Path
import time

from sdapp.analysis.core.frame_source import FrameSequenceView
from sdapp.shared.frame_source import EventScopedFrameSource, PreparedFrameSource
from sdapp.shared.frame_source.launch_preparation import build_launch_preparation_cache_key
from sdapp.shared.services import MODEL_CHECKPOINT_METADATA_KEY
from sdapp.shared.diagnostics import stage as perf_stage


class AnalysisHostModeController:
    def __init__(self, app) -> None:
        self.app = app

    def _set_host_open_status(self, message: str, color: str = "gray") -> None:
        try:
            self.app.lbl_status.configure(text=f"Status: {str(message)}", foreground=str(color))
        except Exception:
            return

    def _log_overlay_snapshot(self, label: str) -> None:
        try:
            frame_count = int(getattr(self.app, "_get_frame_count", lambda: 0)())
        except Exception:
            frame_count = 0
        try:
            prompt_frames = sorted(int(i) for i in self.app._collect_user_defined_frames())[:12]
        except Exception:
            prompt_frames = []
        try:
            mask_frames = sorted(int(i) for i in self.app._collect_nonempty_final_mask_frames())[:12]
        except Exception:
            mask_frames = []
        markers = dict(getattr(self.app, "slider_jump_markers", {}) or {})
        self.app.log_debug(
            "HostMode",
            f"{label} frame_count={frame_count} prompt_frames={prompt_frames} "
            f"mask_frames={mask_frames} marker_count={len(markers)} "
            f"marker_sample={list(sorted(markers.items()))[:6]}",
        )

    def _visual_frames_ready(self) -> bool:
        get_frames_sub_viz = getattr(self.app, "_get_frames_sub_viz", None)
        if not callable(get_frames_sub_viz):
            return False
        try:
            frames_viz = get_frames_sub_viz()
            frame_count = len(frames_viz) if frames_viz is not None else 0
        except Exception:
            frame_count = 0
        if frame_count <= 0:
            return False
        try:
            return frames_viz[0] is not None
        except Exception:
            return False

    def _maybe_start_host_model_initialization(self, reason: str) -> None:
        if not self._visual_frames_ready():
            self.app._host_pending_model_init_reason = str(reason)
            self.app.log_info("HostMode", "Deferring model initialization until visualization frames are ready...")
            return
        self.app._host_pending_model_init_reason = None
        self.app.log_debug("HostMode", f"Model init kicked reason={reason}")
        self.app.log_info("HostMode", "Initializing model for host-driven workspace...")
        self.app.start_model_initialization(reason=str(reason))

    def _debug_frame_source(self, label: str, frame_source) -> None:
        logger = getattr(self.app, "log_debug", None)
        if not callable(logger):
            return
        if frame_source is None:
            logger("HostMode", f"{label}: frame_source=None")
            return
        try:
            frame_count = getattr(frame_source, "frame_count", None)
        except Exception as exc:
            frame_count = f"<error:{exc}>"
        try:
            frame_shape = getattr(frame_source, "frame_shape", None)
        except Exception as exc:
            frame_shape = f"<error:{exc}>"
        logger(
            "HostMode",
            f"{label}: frame_source_type={type(frame_source).__name__} frame_count={frame_count} frame_shape={frame_shape}",
        )

    @staticmethod
    def _scope_metadata_from_host_context(host_ctx: dict | None) -> tuple[str, int | None, int | None, int | None]:
        if not isinstance(host_ctx, dict):
            return "", None, None, None
        event_payload = dict(host_ctx.get("event", {})) if isinstance(host_ctx.get("event"), dict) else {}
        flags = dict(event_payload.get("flags", {})) if isinstance(event_payload.get("flags"), dict) else {}
        event_id = str(event_payload.get("event_id", "") or "")
        scope_start = flags.get("analysis_scope_start_idx", event_payload.get("start_idx"))
        scope_end = flags.get("analysis_scope_end_idx", event_payload.get("end_idx"))
        local_frame_idx = flags.get("analysis_local_event_start_idx")
        try:
            scope_start_int = None if scope_start is None else int(scope_start)
        except Exception:
            scope_start_int = None
        try:
            scope_end_int = None if scope_end is None else int(scope_end)
        except Exception:
            scope_end_int = None
        try:
            local_frame_idx_int = None if local_frame_idx is None else int(local_frame_idx)
        except Exception:
            local_frame_idx_int = None
        if local_frame_idx_int is None and scope_start_int is not None:
            try:
                local_frame_idx_int = int(event_payload.get("start_idx", scope_start_int)) - scope_start_int
            except Exception:
                local_frame_idx_int = None
        return event_id, scope_start_int, scope_end_int, local_frame_idx_int

    def _launch_preparation_cache_key(
        self,
        *,
        host_ctx: dict | None,
        baseline_count: int,
        apply_horizontal_bar_denoise: bool,
        apply_smoothing: bool,
        apply_baseline_subtraction: bool,
        apply_global_normalization: bool,
        apply_stabilization: bool,
    ) -> tuple[str, int, int, int, bool, bool, bool, bool, bool] | None:
        event_id, scope_start, scope_end, _local_frame_idx = self._scope_metadata_from_host_context(host_ctx)
        if scope_start is None or scope_end is None:
            return None
        return build_launch_preparation_cache_key(
            event_id=event_id,
            scope_start=scope_start,
            scope_end=scope_end,
            baseline_pre_frames=baseline_count,
            apply_horizontal_bar_denoise=apply_horizontal_bar_denoise,
            apply_smoothing=apply_smoothing,
            apply_baseline_subtraction=apply_baseline_subtraction,
            apply_global_normalization=apply_global_normalization,
            apply_stabilization=apply_stabilization,
        )

    def _prewarm_initial_window(self, prepared_source: PreparedFrameSource, current_idx: int | None) -> None:
        frame_total = int(getattr(prepared_source, "frame_count", 0) or 0)
        if frame_total <= 0:
            return
        center = int(0 if current_idx is None else current_idx)
        center = max(0, min(center, frame_total - 1))
        lo = max(0, center - 2)
        hi = min(frame_total - 1, center + 2)
        indices = list(range(lo, hi + 1))
        started = time.perf_counter()
        prepared_source.prewarm(indices)
        self.app.log_debug(
            "Perf",
            f"Host open prewarm elapsed={(time.perf_counter() - started) * 1000.0:.1f}ms "
            f"center={center + 1} frames={len(indices)}",
        )

    def _restore_active_host_event_state(self) -> None:
        active_event_id = str(getattr(self.app, "active_event_id", "") or "")
        workspace = getattr(self.app, "analysis_workspace", None)
        if not active_event_id or workspace is None:
            return
        try:
            workspace.open_event(active_event_id)
            self.app.log_debug("HostMode", f"Event state restored event_id={active_event_id}")
        except Exception as exc:
            self.app.log_warn("HostMode", f"Failed to restore active event state: {exc}")
            return
        recompute = getattr(self.app, "_recompute_slider_jump_markers", None)
        if callable(recompute):
            recompute()
            self.app.log_debug("HostMode", f"First marker recompute complete event_id={active_event_id}")
        sync_overlay = getattr(self.app, "_sync_saved_mask_overlay_state", None)
        if callable(sync_overlay):
            try:
                sync_overlay(reset_history=False)
            except TypeError:
                sync_overlay()
        self._log_overlay_snapshot("after_restore_active_event")

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
        host_context_for_event=None,
        on_analysis_update=None,
        on_metrics_update=None,
        on_global_metrics_update=None,
        on_checkpoint_update=None,
        on_open_model_manager=None,
        on_project_saved=None,
        on_sync_result=None,
        on_log_message=None,
        on_host_project_save=None,
        on_host_project_path=None,
        sync_emitter=None,
        launch_preparation=None,
    ):
        self.app._ensure_analysis_workspace()
        self.app._host_mode = True
        self.app._host_post_open_ui_initialized = False
        self.app._host_pending_model_init_reason = None
        self.app._host_analysis_updater = on_analysis_update
        self.app._host_context_provider = host_context_for_event if callable(host_context_for_event) else None
        self.app._host_project_saved_notifier = on_project_saved
        self.app._host_sync_result_notifier = on_sync_result
        self.app._host_log_notifier = on_log_message
        self.app._host_metrics_updater = on_metrics_update
        self.app._host_global_metrics_updater = on_global_metrics_update
        self.app._host_checkpoint_updater = on_checkpoint_update
        self.app._host_open_model_manager = on_open_model_manager
        self.app._host_project_saver = on_host_project_save
        self.app._host_project_path_provider = on_host_project_path
        self.app._host_project_metadata = (
            dict(context.get("project_metadata", {})) if isinstance(context, dict) else None
        )
        host_project_meta = dict(self.app._host_project_metadata or {})
        recorded_checkpoint = host_project_meta.get(MODEL_CHECKPOINT_METADATA_KEY)
        if isinstance(recorded_checkpoint, dict):
            self.app._set_active_checkpoint_metadata(recorded_checkpoint, notify_host=False, reason="host_context")
        if not callable(self.app._host_project_saver):
            return {
                "ok": False,
                "code": "PAYLOAD_INVALID",
                "message": "Host project saver callback is required for host-bound analysis.",
            }
        if isinstance(context, dict):
            project_path = context.get("project_path")
            if isinstance(project_path, str) and project_path.strip():
                try:
                    self.app.current_project_path = str(Path(project_path).expanduser().resolve())
                except Exception as exc:
                    self.app.current_project_path = str(project_path)
                    self.app.log_warn("HostMode", f"Using non-canonical project path from host context: {exc}")
            model_context = dict(context.get("model_context", {})) if isinstance(context.get("model_context"), dict) else {}
            model_token = str(model_context.get("model_token", "") or "").strip()
            manual_override = str(model_context.get("manual_model_override", "") or "").strip()
            if model_token:
                try:
                    self.app.set_model_token(model_token)
                except Exception:
                    pass
            self.app._manual_model_override = manual_override or None
            active_model_meta = model_context.get("active_model_metadata")
            if isinstance(active_model_meta, dict):
                self.app._set_active_checkpoint_metadata(active_model_meta, notify_host=False, reason="host_model_context")
        if not self.app.current_project_path and callable(self.app._host_project_path_provider):
            try:
                host_path = self.app._host_project_path_provider()
            except Exception:
                host_path = None
            if isinstance(host_path, str) and host_path.strip():
                try:
                    self.app.current_project_path = str(Path(host_path).expanduser().resolve())
                except Exception as exc:
                    self.app.current_project_path = str(host_path)
                    self.app.log_warn("HostMode", f"Using non-canonical project path from host callback: {exc}")
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
                "apply_horizontal_bar_denoise": bool(processing.get("horizontal_bar_denoise", False)),
                "apply_smoothing": bool(processing.get("smoothing", True)),
                "apply_baseline_subtraction": bool(processing.get("baseline_subtraction", True)),
                "apply_global_normalization": bool(processing.get("global_normalization", True)),
                "apply_stabilization": bool(processing.get("stabilization", False)),
            }
        self.app._host_launch_preparation = launch_preparation if isinstance(launch_preparation, dict) else None
        scoped_source = frame_source
        if frame_source is not None:
            event = dict(context.get("event", {})) if isinstance(context, dict) else {}
            flags = dict(event.get("flags", {})) if isinstance(event.get("flags"), dict) else {}
            scope_start = flags.get("analysis_scope_start_idx", event.get("start_idx"))
            scope_end = flags.get("analysis_scope_end_idx", event.get("end_idx"))
            self.app.log_debug(
                "HostMode",
                f"open_from_host_context event_id={event.get('event_id')} scope_start={scope_start} scope_end={scope_end}",
            )
            if scope_start is not None and scope_end is not None:
                scoped_source = EventScopedFrameSource(frame_source, int(scope_start), int(scope_end))
            self.app.frame_source = scoped_source
        self._debug_frame_source("open_from_host_context.bound_source", self.app.frame_source)
        if self.app.frame_source is not None:
            self.app.analysis_workspace.bind_frame_source(self.app.frame_source)
        result = self.app.analysis_workspace.open_from_host_event_context(
            context,
            frame_source=self.app.frame_source,
            sync_emitter=sync_emitter,
        )
        if not bool(result.get("ok")):
            return result
        self.app.log_debug("HostMode", "Host context normalized and event state loaded.")
        metrics_settings = context.get("metrics_settings") if isinstance(context, dict) else None
        local_metrics_settings = context.get("local_metrics_settings") if isinstance(context, dict) else None
        self.app._apply_host_metrics_settings(
            metrics_settings if isinstance(metrics_settings, dict) else None,
            local_metrics_settings if isinstance(local_metrics_settings, dict) else None,
        )
        try:
            self.app._sync_saved_mask_overlay_state(reset_history=True)
        except TypeError:
            self.app._sync_saved_mask_overlay_state()
        self._log_overlay_snapshot("after_host_context_initial_sync")
        self._set_host_open_status("Preparing host workspace...", "orange")
        if self.app.frame_source is not None:
            try:
                ready = bool(
                    self.app._prepare_host_mode_buffers(
                        self.app.frame_source,
                        on_ready_message="Host direct workspace initialized.",
                        prefer_async=True,
                    )
                )
            except TypeError:
                ready = bool(self.app._prepare_host_mode_buffers(self.app.frame_source))
            if hasattr(self.app, "app_context") and self.app.app_context is not None:
                self.app.app_context.frame_source = self.app.frame_source
            if ready:
                self.app._post_host_mode_open_ui("Host direct workspace initialized.")
                self._maybe_start_host_model_initialization("host_context_open")
            else:
                self.app._host_pending_model_init_reason = "host_context_open"
        return result

    def open_from_host_handoff(self, payload: dict, frame_source=None, sync_emitter=None):
        self.app._ensure_analysis_workspace()
        self.app._host_mode = True
        self.app._host_context_provider = None
        self.app._host_analysis_updater = None
        self.app._host_project_saved_notifier = None
        self.app._host_sync_result_notifier = None
        self.app._host_log_notifier = None
        self.app._host_metrics_updater = None
        self.app._host_global_metrics_updater = None
        self.app._host_checkpoint_updater = None
        self.app._host_open_model_manager = None
        self.app._host_project_saver = None
        self.app._host_project_path_provider = None
        self.app._host_project_metadata = None
        self.app._set_active_checkpoint_metadata(None, notify_host=False, reason="host_handoff_reset")
        self.app._host_processing_options = None
        self.app._host_launch_preparation = None
        self.app._host_post_open_ui_initialized = False
        self.app._host_pending_model_init_reason = None
        self.app._saved_project_masks_by_event = {}
        scoped_source = frame_source
        if frame_source is not None:
            event = dict(payload.get("event", {})) if isinstance(payload, dict) else {}
            flags = dict(event.get("flags", {})) if isinstance(event.get("flags"), dict) else {}
            scope_start = flags.get("analysis_scope_start_idx", event.get("start_idx"))
            scope_end = flags.get("analysis_scope_end_idx", event.get("end_idx"))
            self.app.log_debug(
                "HostMode",
                f"open_from_host_handoff event_id={event.get('event_id')} scope_start={scope_start} scope_end={scope_end}",
            )
            if scope_start is not None and scope_end is not None:
                scoped_source = EventScopedFrameSource(frame_source, int(scope_start), int(scope_end))
            self.app.frame_source = scoped_source
            processing = (
                dict(flags.get("analysis_processing", {}))
                if isinstance(flags.get("analysis_processing"), dict)
                else {}
            )
            self.app._host_processing_options = {
                "apply_horizontal_bar_denoise": bool(processing.get("horizontal_bar_denoise", False)),
                "apply_smoothing": bool(processing.get("smoothing", True)),
                "apply_baseline_subtraction": bool(processing.get("baseline_subtraction", True)),
                "apply_global_normalization": bool(processing.get("global_normalization", True)),
                "apply_stabilization": bool(processing.get("stabilization", False)),
            }
        self._debug_frame_source("open_from_host_handoff.bound_source", self.app.frame_source)
        if self.app.frame_source is not None:
            self.app.analysis_workspace.bind_frame_source(self.app.frame_source)
        result = self.app.analysis_workspace.open_from_handoff_payload(
            payload,
            frame_source=self.app.frame_source,
            sync_emitter=sync_emitter,
        )
        if not bool(result.get("ok")):
            return result
        self.app.log_debug("HostMode", "Host handoff normalized and event state loaded.")
        try:
            self.app._sync_saved_mask_overlay_state(reset_history=True)
        except TypeError:
            self.app._sync_saved_mask_overlay_state()
        self._log_overlay_snapshot("after_host_handoff_initial_sync")
        self._set_host_open_status("Preparing host workspace...", "orange")

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
                self._maybe_start_host_model_initialization("host_handoff_open")
            else:
                self.app._host_pending_model_init_reason = "host_handoff_open"
        return result

    def post_host_mode_open_ui(self, message: str) -> None:
        if not (hasattr(self.app, "slider") and hasattr(self.app, "canvas_left")):
            return
        self.app._host_post_open_ui_initialized = True
        self._debug_frame_source("post_host_mode_open_ui.pre_finalize", getattr(self.app, "frame_source", None))
        self._restore_active_host_event_state()
        finalize = getattr(self.app, "_finalize_load_ui", None)
        if callable(finalize):
            try:
                finalize(preserve_workspace_state=True)
            except TypeError:
                finalize()
        if hasattr(self.app, "_reset_viewport_to_fit"):
            self.app._reset_viewport_to_fit(update_display=False)
        def _first_display_update() -> None:
            trace = getattr(self.app, "_open_perf_trace", None)
            if trace is not None:
                trace.mark("first_display_update")
            self.app.update_display(update_preview=True)
        if hasattr(self.app.root, "after_idle"):
            self.app.root.after_idle(_first_display_update)
        self.app.root.after(120, lambda: self.app.update_display(update_preview=True))
        self._log_overlay_snapshot("after_host_open_finalize")
        self.app.log_debug("HostMode", "Host-open finalize complete.")
        self.app.log_info("HostMode", message)
        self._set_host_open_status("Host-bound mode (project managed by SD ID)")

    def prepare_host_mode_buffers(self, frame_source, on_ready_message: str | None = None, prefer_async: bool = False):
        with perf_stage("prepare_host_mode_buffers"):
            return self._prepare_host_mode_buffers_impl(frame_source, on_ready_message, prefer_async)

    def _prepare_host_mode_buffers_impl(self, frame_source, on_ready_message: str | None = None, prefer_async: bool = False):
        if not hasattr(self.app, "_host_buffer_cache_key"):
            self.app._host_buffer_cache_key = None
        frame_count = int(getattr(frame_source, "frame_count", 0) or 0)
        self._debug_frame_source("prepare_host_mode_buffers.input", frame_source)
        if frame_count <= 0:
            self.app.frames_raw = None
            self.app.frames_sub = None
            self.app.frames_sub_viz = None
            self.app.frame_names = []
            self.app._current_image_source_paths = []
            self.app._host_buffer_cache_key = None
            return True

        baseline_count = 30
        if hasattr(self.app, "get_baseline_frame_count"):
            try:
                baseline_count = int(self.app.get_baseline_frame_count())
            except Exception:
                baseline_count = 30
        host_ctx = None
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
            if hasattr(self.app, "set_baseline_frame_count"):
                try:
                    self.app.set_baseline_frame_count(baseline_count)
                except Exception:
                    pass

        self.app.frame_names = list(getattr(frame_source, "frame_names", []))
        self.app._current_image_source_paths = list(getattr(frame_source, "source_paths", []))
        processing_opts = dict(getattr(self.app, "_host_processing_options", {}) or {})
        apply_horizontal_bar_denoise = bool(processing_opts.get("apply_horizontal_bar_denoise", False))
        apply_smoothing = bool(processing_opts.get("apply_smoothing", True))
        apply_baseline_subtraction = bool(processing_opts.get("apply_baseline_subtraction", True))
        apply_global_normalization = bool(processing_opts.get("apply_global_normalization", True))
        apply_stabilization = bool(processing_opts.get("apply_stabilization", False))
        launch_preparation = (
            dict(getattr(self.app, "_host_launch_preparation", {}) or {})
            if isinstance(getattr(self.app, "_host_launch_preparation", None), dict)
            else {}
        )
        launch_cache_key = self._launch_preparation_cache_key(
            host_ctx=host_ctx if isinstance(host_ctx, dict) else None,
            baseline_count=baseline_count,
            apply_horizontal_bar_denoise=apply_horizontal_bar_denoise,
            apply_smoothing=apply_smoothing,
            apply_baseline_subtraction=apply_baseline_subtraction,
            apply_global_normalization=apply_global_normalization,
            apply_stabilization=apply_stabilization,
        )
        _event_id, _scope_start, _scope_end, local_frame_idx = self._scope_metadata_from_host_context(
            host_ctx if isinstance(host_ctx, dict) else None
        )
        prepared_stats = None
        cache_key = (
            tuple(launch_cache_key)
            if launch_cache_key is not None
            else (
                id(frame_source),
                int(frame_count),
                tuple(int(v) for v in getattr(frame_source, "frame_shape", (0, 0))),
                int(max(1, baseline_count)),
                bool(apply_horizontal_bar_denoise),
                bool(apply_smoothing),
                bool(apply_baseline_subtraction),
                bool(apply_global_normalization),
                bool(apply_stabilization),
            )
        )
        if self.app._host_buffer_cache_key == cache_key and self._visual_frames_ready():
            return True

        reusable_prepared_source = None
        candidate = launch_preparation.get("prepared_source")
        candidate_cache_key = launch_preparation.get("cache_key")
        if (
            isinstance(candidate, PreparedFrameSource)
            and launch_cache_key is not None
            and candidate_cache_key is not None
            and tuple(candidate_cache_key) == tuple(launch_cache_key)
            and int(getattr(candidate, "frame_count", 0) or 0) == int(frame_count)
            and tuple(int(v) for v in getattr(candidate, "frame_shape", (0, 0)))
            == tuple(int(v) for v in getattr(frame_source, "frame_shape", (0, 0)))
        ):
            reusable_prepared_source = candidate
            prepared_stats = launch_preparation.get("stats")

        def _build_prepared_source() -> PreparedFrameSource:
            with perf_stage("host_mode.build_prepared_source"):
                started = time.perf_counter()
                if reusable_prepared_source is not None:
                    self.app.log_debug(
                        "Perf",
                        f"Host buffer reuse elapsed={(time.perf_counter() - started) * 1000.0:.1f}ms frames={frame_count}",
                    )
                    return reusable_prepared_source
                prepared_source = PreparedFrameSource(
                    frame_source,
                    baseline_frames=max(1, int(baseline_count)),
                    apply_horizontal_bar_denoise=apply_horizontal_bar_denoise,
                    apply_smoothing=apply_smoothing,
                    apply_baseline_subtraction=apply_baseline_subtraction,
                    apply_global_normalization=apply_global_normalization,
                    apply_stabilization=apply_stabilization,
                    stats=prepared_stats if prepared_stats is not None else None,
                )
                with perf_stage("host_mode.prepared_source.prepare"):
                    prepared_source.prepare()
                self.app.log_debug(
                    "Perf",
                    f"Host buffer preparation elapsed={(time.perf_counter() - started) * 1000.0:.1f}ms frames={frame_count}",
                )
                return prepared_source

        def _apply_prepared_source(prepared_source: PreparedFrameSource) -> None:
            with perf_stage("host_mode.prewarm_initial_window"):
                self._prewarm_initial_window(prepared_source, local_frame_idx)
            self.app.frame_source = prepared_source
            workspace = getattr(self.app, "analysis_workspace", None)
            if workspace is not None:
                workspace.bind_frame_source(prepared_source)
            if hasattr(self.app, "app_context") and self.app.app_context is not None:
                self.app.app_context.frame_source = prepared_source
            self.app.frames_raw = FrameSequenceView(prepared_source, "get_raw_frame")
            self.app.frames_sub = FrameSequenceView(prepared_source, "get_subtracted_frame")
            self.app.frames_sub_viz = FrameSequenceView(prepared_source, "get_visual_frame")
            self.app._host_buffer_cache_key = cache_key
            self.app._host_launch_preparation = None
            if callable(getattr(self.app, "_schedule_analysis_prewarm", None)):
                self.app._schedule_analysis_prewarm(0 if local_frame_idx is None else int(local_frame_idx))
            self.app._initial_frame_nav_ts = time.perf_counter()
            self.app.log_debug("HostMode", f"Prepared source applied frame_count={frame_count}")
            self.app.log_info("HostMode", f"Prepared lazy visualization source ({frame_count} frames).")
            if on_ready_message:
                self.app.log_info("HostMode", str(on_ready_message))

        sync_limit = max(1, int(getattr(self.app, "_host_buffer_sync_limit", 240) or 240))
        has_preview_seed = bool(
            launch_preparation.get("prepared_source") is not None
            or launch_preparation.get("preview_frame_u8") is not None
            or launch_preparation.get("viz_frame") is not None
            or launch_preparation.get("raw_frame") is not None
        )
        should_queue_async = bool(prefer_async) and callable(getattr(self.app, "_run_thread", None))
        if reusable_prepared_source is not None:
            should_queue_async = False
        trace = getattr(self.app, "_open_perf_trace", None)
        if trace is not None:
            trace.annotate(
                buffer_path="async" if should_queue_async else "sync",
                frame_count=int(frame_count),
                sync_limit=int(sync_limit),
                has_preview_seed=bool(has_preview_seed),
                reusable_prepared_source=reusable_prepared_source is not None,
            )
        if should_queue_async:
            generation = int(getattr(self.app, "_host_buffer_generation", 0) or 0) + 1
            self.app._host_buffer_generation = generation
            self.app.frames_raw = None
            self.app.frames_sub = None
            self.app.frames_sub_viz = None

            def _prepare_in_background() -> None:
                prepared_source = _build_prepared_source()

                def _apply_when_ready() -> None:
                    if int(getattr(self.app, "_host_buffer_generation", 0) or 0) != generation:
                        return
                    _apply_prepared_source(prepared_source)
                    if callable(getattr(self.app, "_post_host_mode_open_ui", None)):
                        self.app._post_host_mode_open_ui(str(on_ready_message or "Host workspace initialized."))
                    pending_reason = str(getattr(self.app, "_host_pending_model_init_reason", "") or "").strip()
                    if pending_reason:
                        self._maybe_start_host_model_initialization(pending_reason)

                if callable(getattr(self.app, "_ui_alive", None)) and self.app._ui_alive():
                    self.app.root.after(0, _apply_when_ready)
                else:
                    _apply_when_ready()

            self.app._run_thread(_prepare_in_background, loading_text="Preparing host workspace...")
            return False

        prepared_source = _build_prepared_source()
        _apply_prepared_source(prepared_source)
        return True
