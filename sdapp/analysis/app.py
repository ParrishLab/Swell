import os
import sys
import threading
import gc
import time
import subprocess
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import cv2
import numpy as np

from sdapp.analysis.core.state import AppConfig
from sdapp.analysis.core.io import IOActions
from sdapp.analysis.core.segmentation import SegmentationActions
from sdapp.analysis.core.render import RenderActions
from sdapp.analysis.core.undo import UndoActions
from sdapp.analysis.core.frame_source import EagerFrameSource
from sdapp.analysis.core.analysis_controller import AnalysisController
from sdapp.analysis.core.seg_state import SegmentationState
from sdapp.analysis.core.inference_manager import InferenceManager
from sdapp.analysis.core.interaction_controller import InteractionController
from sdapp.analysis.core.project_schema import utc_now_iso
from sdapp.analysis.core.project_store import ProjectStore
from sdapp.analysis.core.session_state import SessionState
from sdapp.analysis.core import mask_import_workflow
from sdapp.analysis.core.mask_import_dialog import MaskImportDialogService
from sdapp.analysis.core.project_session import ProjectSessionService, SessionSnapshot
from sdapp.analysis.core.analysis_workspace import AnalysisWorkspaceController, WorkspaceUiState
from sdapp.analysis.core.overlay_state import frame_spans, span_length, largest_contiguous_span, compute_propagated_state
from sdapp.analysis.core.runtime_state import AnalysisModelState, AnalysisRuntimeState, HostModeState
from sdapp.analysis.core import overlay_renderer
from sdapp.analysis.core.preview_resize import start_resize_preview as do_start_resize_preview
from sdapp.analysis.core.preview_resize import do_resize_preview as do_preview_resize
from sdapp.analysis.core.preview_resize import stop_resize_preview as do_stop_resize_preview
from sdapp.analysis.core.propagation_progress import PropagationProgressLogger
from sdapp.analysis.core.app_context import AppContext
from sdapp.analysis.core import project_workflow
from sdapp.analysis.controllers import AnalysisHostModeController, AnalysisModelController, AnalysisWindowController
from sdapp.analysis.ui.layout import LayoutBuilder
from sdapp.analysis.utils.paths import get_app_root, get_resources_root
from sdapp.analysis.model import SAM2RuntimeService
from sdapp.shared.services import CheckpointRuntimeService, MODEL_CHECKPOINT_METADATA_KEY


# Optional dependency checks for runtime capabilities.
try:
    import imagecodecs  # noqa: F401
except ImportError:
    print("WARNING: imagecodecs not installed. LZW-compressed TIFFs may fail to load.")
    print("Install with: pip install imagecodecs")

try:
    import sam2  # noqa: F401
except ImportError:
    print("WARNING: 'sam2' package not found. Model-based tools will be disabled (review-only mode).")
    print("Install SAM2 for model-based segmentation: pip install git+https://github.com/facebookresearch/sam2.git")
    print(f"Python interpreter: {sys.executable}")


class PrintLogger:
    def __init__(self, root, *, message_sink=None):
        self.root = root
        self._message_sink = message_sink

    def write(self, message):
        if "NSOpenPanel" in message and "method identifier" in message:
            return
        if self._message_sink is None:
            return
        self.root.after(0, lambda: self._message_sink(str(message), False))

    def write_progress(self, message):
        if self._message_sink is None:
            return
        self.root.after(0, lambda: self._message_sink(str(message), True))

    def flush(self):
        return None


class SDSegmentationApp(LayoutBuilder, IOActions, SegmentationActions, RenderActions, UndoActions):
    def __init__(self, root, *, menu_builder=None, menu_mode="analysis", host_mode: bool = False):
        if not bool(host_mode):
            raise RuntimeError(
                "Standalone SD Segmenter runtime has been removed. "
                "Open analysis from the SD ID main window."
            )
        self.root = root
        self.root.title("IOS SD Segmenter (Merged Final)")
        self.root.geometry("1400x950")

        self.app_root = str(get_app_root())
        self.resource_root = str(get_resources_root())
        self._is_release_branch = self._detect_release_branch()
        self._app_icon_image = None
        self._apply_runtime_icon()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.frames_raw = None
        self.frames_sub = None
        self.frames_sub_viz = None
        self.frame_names = []
        self._selected_import_files = None
        self._current_image_source_paths = []
        self._image_manifest_entries = []
        self.frame_source = None
        self.current_project_path = None
        self.project_dirty = False
        self.session_state = SessionState()
        self.active_event_id = "sd_event_001"
        self.session_state.event_records = {}
        self._project_created_at = utc_now_iso()
        self._project_embed_images = False
        self._propagation_committed_snapshot = None
        self.runtime_state = AnalysisRuntimeState()
        self.model_state = AnalysisModelState()
        self.host_mode_state = HostModeState()

        self.current_frame_idx = 0
        self.seg_state = SegmentationState()
        self.points = self.seg_state.points
        self.selected_point = None
        self.paint_layers = self.seg_state.paint_layers

        self.display_ratio = 1.0
        self.img_offset_x = 0
        self.img_offset_y = 0

        self.last_mouse_x = None
        self.last_mouse_y = None
        self.last_img_x = None
        self.last_img_y = None
        self.is_dragging = False

        self.scale_px_per_mm = None
        self.roi_mask = None
        self.roi_points = []
        self.scale_points = []
        self.analysis_mode = None

        self.sam2_runtime = SAM2RuntimeService()
        self.checkpoint_runtime = CheckpointRuntimeService()
        self.masks_cache = self.seg_state.masks_cache

        self.undo_stack = []
        self.redo_stack = []
        self.paint_snapshot_before = None
        self.points_snapshot_before = None

        self.predictor_lock = threading.Lock()
        self._largest_propagated_span = None
        self._propagated_history_indices = set()
        self.propagated_frame_indices = set()
        self.propagated_frame_spans = []
        self.slider_jump_markers = {}
        self._slider_marker_hit_tolerance_px = 6
        self._slider_marker_bounds = {}
        self._export_range_auto_follow = True
        self._programmatic_spinbox_update = False
        self._last_scale_image_path = ""
        self.export_panel_open = tk.BooleanVar(value=False)
        self.analysis_panel_open = tk.BooleanVar(value=False)
        self._controls_hint_logged = False

        self.config = AppConfig.load()
        self.project_store = ProjectStore()
        self.project_session_service = ProjectSessionService()
        self.analysis_workspace = AnalysisWorkspaceController(
            session_service=self.project_session_service,
            session_state=self.session_state,
            seg_state=self.seg_state,
        )
        self.mask_import_dialog = MaskImportDialogService()
        self.autosave_manager = None

        self.setup_ui()
        self.window_controller = AnalysisWindowController(self)
        self.host_mode_controller = AnalysisHostModeController(self)
        self.model_controller = AnalysisModelController(self)
        if menu_builder is not None:
            self._menu_bar = menu_builder(self.root, self, mode=menu_mode, host_mode=self._host_mode)
        else:
            self._setup_project_menu()
        self.root.bind("<FocusIn>", self._ensure_menu_bar_bound, add="+")
        self.btn_save_masks.configure(state="disabled")
        self._validate_assets()

        self.logger = PrintLogger(self.root, message_sink=self._on_logger_message)
        self.progress_logger = PropagationProgressLogger(
            write_progress=self.logger.write_progress,
            log_info=self.log_info,
            log_success=self.log_success,
            log_warn=self.log_warn,
            log_error=self.log_error,
        )
        self.inference_manager = InferenceManager(
            state=self.seg_state,
            root=self.root,
            predictor_lock=self.predictor_lock,
            get_sensitivity=lambda: float(self.sensitivity.get()),
            get_current_frame_idx=lambda: int(self.current_frame_idx),
            get_frames_raw=self._get_frames_raw,
            set_slider_frame=lambda idx: self.slider.set(idx),
            update_display=self.update_display,
            recompute_markers=self._recompute_slider_jump_markers,
            set_propagated_frames=self._set_propagated_frames,
            set_status=self._set_runtime_status,
            prop_log_start=self._prop_log_start,
            prop_log_tick=self._prop_log_tick,
            prop_log_finish=self._prop_log_finish,
            on_propagation_status=self._on_propagation_status,
            log=self.log,
            is_ui_alive=self._ui_alive,
        )
        self.analysis_controller = AnalysisController(
            root=self.root,
            app_root=self.app_root,
            get_frames_raw=self._get_frames_raw,
            get_masks_cache=lambda: self.masks_cache,
            get_paint_layers=lambda: self.paint_layers,
            get_points=lambda: self.points,
            get_frame_names=self._get_frame_names,
            get_input_folder=lambda: self.entry_input.get(),
            get_compose_final_mask_for_frame=self._compose_final_mask_for_frame,
            get_nonempty_final_mask_frames=self._collect_nonempty_final_mask_frames,
            get_frames_per_sec=lambda: float(self.frames_per_sec_var.get()),
            get_scale_px_per_mm=lambda: self.scale_px_per_mm,
            set_scale_px_per_mm=lambda v: setattr(self, "scale_px_per_mm", v),
            get_scale_points=lambda: self.scale_points,
            set_scale_points=lambda v: setattr(self, "scale_points", v),
            get_last_scale_image_path=lambda: self._last_scale_image_path,
            set_last_scale_image_path=lambda v: setattr(self, "_last_scale_image_path", v or ""),
            get_roi_mask=lambda: self.roi_mask,
            set_roi_mask=lambda v: setattr(self, "roi_mask", v),
            get_roi_points=lambda: self.roi_points,
            set_roi_points=lambda v: setattr(self, "roi_points", v),
            update_display=self.update_display,
            log_info=self.log_info,
            log_success=self.log_success,
            on_metrics_settings_changed=self._on_metrics_settings_changed,
        )
        self.interaction_controller = InteractionController(
            seg_state=self.seg_state,
            points=self.points,
            paint_layers=self.paint_layers,
            masks_cache=self.masks_cache,
            get_current_frame_idx=lambda: self.current_frame_idx,
            set_selected_point=lambda v: setattr(self, "selected_point", v),
            get_selected_point=lambda: self.selected_point,
            get_is_dragging=lambda: self.is_dragging,
            set_is_dragging=lambda v: setattr(self, "is_dragging", v),
            get_last_mouse_x=lambda: self.last_mouse_x,
            set_last_mouse_x=lambda v: setattr(self, "last_mouse_x", v),
            set_last_mouse_y=lambda v: setattr(self, "last_mouse_y", v),
            get_last_img_x=lambda: self.last_img_x,
            set_last_img_x=lambda v: setattr(self, "last_img_x", v),
            get_last_img_y=lambda: self.last_img_y,
            set_last_img_y=lambda v: setattr(self, "last_img_y", v),
            get_points_snapshot_before=lambda: self.points_snapshot_before,
            set_points_snapshot_before=lambda v: setattr(self, "points_snapshot_before", v),
            get_paint_snapshot_before=lambda: self.paint_snapshot_before,
            set_paint_snapshot_before=lambda v: setattr(self, "paint_snapshot_before", v),
            tool_mode=self.tool_mode,
            brush_size=self.brush_size,
            canvas_left=self.canvas_left,
            slider=self.slider,
            lbl_brush_val=self.lbl_brush_val,
            get_frames_sub_viz=self._get_frames_sub_viz,
            get_frames_raw=self._get_frames_raw,
            get_display_ratio=lambda: self.display_ratio,
            get_display_transform=self._get_display_transform,
            update_display=self.update_display,
            draw_brush_cursor=self._draw_brush_cursor_on_canvas,
            recompute_slider_jump_markers=self._recompute_slider_jump_markers,
            update_mask_prediction=self._update_mask_prediction,
            get_model_ready=lambda: self.model_ready,
            record_action=self.record_action,
            prune_empty_point_frames=self._prune_empty_point_frames,
        )
        self.app_context = AppContext(
            app_root=Path(self.app_root),
            project_store=self.project_store,
            project_session_service=self.project_session_service,
            mask_import_dialog=self.mask_import_dialog,
            autosave_manager=self.autosave_manager,
            session_state=self.session_state,
            analysis_workspace=self.analysis_workspace,
            frame_source=self.frame_source,
            inference_manager=self.inference_manager,
            analysis_controller=self.analysis_controller,
        )
        if hasattr(self, "entry_frames_per_sec"):
            self.entry_frames_per_sec.bind("<FocusOut>", self._on_frames_per_sec_commit, add="+")
            self.entry_frames_per_sec.bind("<Return>", self._on_frames_per_sec_commit, add="+")
        self._set_data_controls_enabled(False)
        self.inference_manager.start()

    def _ensure_menu_bar_bound(self, _event=None) -> None:
        menu = getattr(self, "_menu_bar", None)
        if menu is None:
            return
        try:
            current_menu = str(self.root.cget("menu") or "")
            if current_menu == "":
                self.root.config(menu=menu)
        except Exception:
            pass

    @property
    def active_event_id(self):
        self._ensure_session_state()
        return self.session_state.active_event_id

    @active_event_id.setter
    def active_event_id(self, value):
        self._ensure_session_state()
        self.session_state.active_event_id = str(value or "sd_event_001")

    @property
    def event_states(self):
        self._ensure_session_state()
        service = getattr(self, "project_session_service", None) or ProjectSessionService()
        return service.event_records_to_legacy_dict(self.session_state.event_records)

    @event_states.setter
    def event_states(self, value):
        self._ensure_session_state()
        if not value:
            self.session_state.event_records = {}
            return
        frames_raw = getattr(self, "frames_raw", None)
        frame_count = len(frames_raw) if frames_raw is not None else 0
        service = getattr(self, "project_session_service", None) or ProjectSessionService()
        self.session_state.event_records = service.coerce_event_records(value, frame_count)

    @property
    def event_records(self):
        self._ensure_session_state()
        return self.session_state.event_records

    @event_records.setter
    def event_records(self, value):
        self._ensure_session_state()
        if not value:
            self.session_state.event_records = {}
            return
        frames_raw = getattr(self, "frames_raw", None)
        frame_count = len(frames_raw) if frames_raw is not None else 0
        service = getattr(self, "project_session_service", None) or ProjectSessionService()
        self.session_state.event_records = service.coerce_event_records(value, frame_count)

    @property
    def _propagation_committed_snapshot(self):
        self._ensure_session_state()
        return self.session_state.propagation_committed_snapshot

    @_propagation_committed_snapshot.setter
    def _propagation_committed_snapshot(self, value):
        self._ensure_session_state()
        self.session_state.propagation_committed_snapshot = value

    @property
    def _export_range_auto_follow(self):
        self._ensure_session_state()
        return self.session_state.export_range_auto_follow

    @_export_range_auto_follow.setter
    def _export_range_auto_follow(self, value):
        self._ensure_session_state()
        self.session_state.export_range_auto_follow = bool(value)

    def _ensure_runtime_state(self) -> None:
        if not hasattr(self, "runtime_state") or self.runtime_state is None:
            self.runtime_state = AnalysisRuntimeState()
        if not hasattr(self, "model_state") or self.model_state is None:
            self.model_state = AnalysisModelState()
        if not hasattr(self, "host_mode_state") or self.host_mode_state is None:
            self.host_mode_state = HostModeState()

    @property
    def predictor(self):
        self._ensure_runtime_state()
        return self.model_state.predictor

    @predictor.setter
    def predictor(self, value) -> None:
        self._ensure_runtime_state()
        self.model_state.predictor = value

    @property
    def inference_state(self):
        self._ensure_runtime_state()
        return self.model_state.inference_state

    @inference_state.setter
    def inference_state(self, value) -> None:
        self._ensure_runtime_state()
        self.model_state.inference_state = value

    @property
    def model_ready(self):
        self._ensure_runtime_state()
        return bool(self.model_state.model_ready)

    @model_ready.setter
    def model_ready(self, value) -> None:
        self._ensure_runtime_state()
        self.model_state.model_ready = bool(value)

    @property
    def temp_dir(self):
        self._ensure_runtime_state()
        return self.model_state.temp_dir

    @temp_dir.setter
    def temp_dir(self, value) -> None:
        self._ensure_runtime_state()
        self.model_state.temp_dir = None if value is None else str(value)

    @property
    def _active_checkpoint_metadata(self):
        self._ensure_runtime_state()
        return self.model_state.checkpoint_metadata

    @_active_checkpoint_metadata.setter
    def _active_checkpoint_metadata(self, value) -> None:
        self._ensure_runtime_state()
        self.model_state.checkpoint_metadata = dict(value) if isinstance(value, dict) else None

    @property
    def _manual_model_override(self):
        self._ensure_runtime_state()
        return self.model_state.manual_model_override

    @_manual_model_override.setter
    def _manual_model_override(self, value) -> None:
        self._ensure_runtime_state()
        self.model_state.manual_model_override = str(value).strip() if value else None

    @property
    def _host_mode(self):
        self._ensure_runtime_state()
        return bool(self.host_mode_state.host_mode)

    @_host_mode.setter
    def _host_mode(self, value) -> None:
        self._ensure_runtime_state()
        self.host_mode_state.host_mode = bool(value)

    @property
    def _host_analysis_updater(self):
        self._ensure_runtime_state()
        return self.host_mode_state.analysis_updater

    @_host_analysis_updater.setter
    def _host_analysis_updater(self, value) -> None:
        self._ensure_runtime_state()
        self.host_mode_state.analysis_updater = value

    @property
    def _host_project_saved_notifier(self):
        self._ensure_runtime_state()
        return self.host_mode_state.project_saved_notifier

    @_host_project_saved_notifier.setter
    def _host_project_saved_notifier(self, value) -> None:
        self._ensure_runtime_state()
        self.host_mode_state.project_saved_notifier = value

    @property
    def _host_sync_result_notifier(self):
        self._ensure_runtime_state()
        return self.host_mode_state.sync_result_notifier

    @_host_sync_result_notifier.setter
    def _host_sync_result_notifier(self, value) -> None:
        self._ensure_runtime_state()
        self.host_mode_state.sync_result_notifier = value

    @property
    def _host_project_saver(self):
        self._ensure_runtime_state()
        return self.host_mode_state.project_saver

    @_host_project_saver.setter
    def _host_project_saver(self, value) -> None:
        self._ensure_runtime_state()
        self.host_mode_state.project_saver = value

    @property
    def _host_project_path_provider(self):
        self._ensure_runtime_state()
        return self.host_mode_state.project_path_provider

    @_host_project_path_provider.setter
    def _host_project_path_provider(self, value) -> None:
        self._ensure_runtime_state()
        self.host_mode_state.project_path_provider = value

    @property
    def _host_log_notifier(self):
        self._ensure_runtime_state()
        return self.host_mode_state.log_notifier

    @_host_log_notifier.setter
    def _host_log_notifier(self, value) -> None:
        self._ensure_runtime_state()
        self.host_mode_state.log_notifier = value

    @property
    def _host_metrics_updater(self):
        self._ensure_runtime_state()
        return self.host_mode_state.metrics_updater

    @_host_metrics_updater.setter
    def _host_metrics_updater(self, value) -> None:
        self._ensure_runtime_state()
        self.host_mode_state.metrics_updater = value

    @property
    def _host_checkpoint_updater(self):
        self._ensure_runtime_state()
        return self.host_mode_state.checkpoint_updater

    @_host_checkpoint_updater.setter
    def _host_checkpoint_updater(self, value) -> None:
        self._ensure_runtime_state()
        self.host_mode_state.checkpoint_updater = value

    @property
    def _host_open_model_manager(self):
        self._ensure_runtime_state()
        return self.host_mode_state.open_model_manager

    @_host_open_model_manager.setter
    def _host_open_model_manager(self, value) -> None:
        self._ensure_runtime_state()
        self.host_mode_state.open_model_manager = value

    @property
    def _host_processing_options(self):
        self._ensure_runtime_state()
        return self.host_mode_state.processing_options

    @_host_processing_options.setter
    def _host_processing_options(self, value) -> None:
        self._ensure_runtime_state()
        self.host_mode_state.processing_options = None if value is None else dict(value)

    @property
    def _host_project_metadata(self):
        self._ensure_runtime_state()
        return self.host_mode_state.project_metadata

    @_host_project_metadata.setter
    def _host_project_metadata(self, value) -> None:
        self._ensure_runtime_state()
        self.host_mode_state.project_metadata = dict(value) if isinstance(value, dict) else None

    @property
    def _saved_project_masks_by_event(self):
        self._ensure_runtime_state()
        return self.host_mode_state.saved_project_masks_by_event

    @_saved_project_masks_by_event.setter
    def _saved_project_masks_by_event(self, value) -> None:
        self._ensure_runtime_state()
        self.host_mode_state.saved_project_masks_by_event = dict(value or {})

    @property
    def _suppress_metrics_emit(self):
        self._ensure_runtime_state()
        return bool(self.host_mode_state.suppress_metrics_emit)

    @_suppress_metrics_emit.setter
    def _suppress_metrics_emit(self, value) -> None:
        self._ensure_runtime_state()
        self.host_mode_state.suppress_metrics_emit = bool(value)

    @property
    def _host_buffer_generation(self):
        self._ensure_runtime_state()
        return int(self.host_mode_state.buffer_generation)

    @_host_buffer_generation.setter
    def _host_buffer_generation(self, value) -> None:
        self._ensure_runtime_state()
        self.host_mode_state.buffer_generation = int(value)

    @property
    def _host_buffer_cache_key(self):
        self._ensure_runtime_state()
        return self.host_mode_state.buffer_cache_key

    @_host_buffer_cache_key.setter
    def _host_buffer_cache_key(self, value) -> None:
        self._ensure_runtime_state()
        self.host_mode_state.buffer_cache_key = value

    @property
    def _host_buffer_sync_limit(self):
        self._ensure_runtime_state()
        return int(self.host_mode_state.buffer_sync_limit)

    @_host_buffer_sync_limit.setter
    def _host_buffer_sync_limit(self, value) -> None:
        self._ensure_runtime_state()
        self.host_mode_state.buffer_sync_limit = int(value)

    @property
    def _loading_task_count(self):
        self._ensure_runtime_state()
        return int(self.runtime_state.loading_task_count)

    @_loading_task_count.setter
    def _loading_task_count(self, value) -> None:
        self._ensure_runtime_state()
        self.runtime_state.loading_task_count = int(value)

    def _ensure_session_state(self):
        if not hasattr(self, "session_state") or self.session_state is None:
            self.session_state = SessionState()

    def _ensure_analysis_workspace(self):
        self._ensure_session_state()
        if not hasattr(self, "project_session_service") or self.project_session_service is None:
            self.project_session_service = ProjectSessionService()
        if not hasattr(self, "seg_state") or self.seg_state is None:
            self.seg_state = SegmentationState()
        if not hasattr(self, "analysis_workspace") or self.analysis_workspace is None:
            self.analysis_workspace = AnalysisWorkspaceController(
                session_service=self.project_session_service,
                session_state=self.session_state,
                seg_state=self.seg_state,
            )

    def _set_loading_indicator(self, loading: bool, text: str = "Working...") -> None:
        if not hasattr(self, "loading_status_var") or not hasattr(self, "loading_bar"):
            return
        if bool(loading):
            self.loading_status_var.set(str(text or "Working..."))
            if not self.loading_bar.winfo_ismapped():
                self.loading_bar.pack(fill="x", padx=6, pady=(0, 6))
            self.loading_bar.start(8)
            return
        self.loading_bar.stop()
        if self.loading_bar.winfo_ismapped():
            self.loading_bar.pack_forget()

    def _set_activity_message(self, text: str) -> None:
        if not hasattr(self, "loading_status_var"):
            return
        self.loading_status_var.set(str(text or "Idle"))

    def _begin_loading_task(self, text: str = "Working...") -> None:
        self._loading_task_count = int(getattr(self, "_loading_task_count", 0)) + 1
        self._set_loading_indicator(True, text)

    def _end_loading_task(self) -> None:
        self._loading_task_count = max(0, int(getattr(self, "_loading_task_count", 0)) - 1)
        if self._loading_task_count == 0:
            self._set_loading_indicator(False)

    def _on_logger_message(self, message: str, is_progress: bool = False) -> None:
        text = str(message or "").strip()
        if not text:
            return
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for line in lines:
            level = "INFO"
            context = "Analysis"
            body = line
            if line.startswith("[") and "]" in line:
                first = line[1 : line.find("]")]
                rest = line[line.find("]") + 1 :].strip()
                if first in {"INFO", "WARN", "ERROR", "SUCCESS", "DEBUG"}:
                    level = first
                    body = rest
                    if body.startswith("[") and "]" in body:
                        context = body[1 : body.find("]")]
                        body = body[body.find("]") + 1 :].strip()
                elif first:
                    context = first
            if callable(getattr(self, "_host_log_notifier", None)):
                try:
                    self._host_log_notifier(level, context, body)
                except Exception:
                    pass
            if bool(is_progress) and context == "Propagation":
                self._set_loading_indicator(True, body or "Propagating...")

    def _set_runtime_status(self, text: str, color: str) -> None:
        status = str(text or "")
        self._set_activity_message(status)
        if "Propagating" in status:
            self._set_loading_indicator(True, status)
            return
        if status in {"Propagation Complete", "Propagation Stopped", "Propagation Error"}:
            if self._loading_task_count <= 0:
                if hasattr(self, "loading_bar"):
                    self.loading_bar.stop()
                    if self.loading_bar.winfo_ismapped():
                        self.loading_bar.pack_forget()

    def _set_busy(self, is_busy, status_text, color):
        self.lbl_status.configure(text=status_text, foreground=color)
        if hasattr(self, "btn_import"):
            self.btn_import.configure(state="disabled" if is_busy else "normal")
        self._set_loading_indicator(bool(is_busy), str(status_text).replace("Status:", "").strip() or "Working...")
        if hasattr(self, "btn_save_masks"):
            if is_busy:
                self.btn_save_masks.configure(state="disabled")
            else:
                self.btn_save_masks.configure(state="normal" if self._has_loaded_stack() else "disabled")

    def _run_thread(self, target, *, loading_text: str = "Working..."):
        self._begin_loading_task(loading_text)

        def _wrapped() -> None:
            try:
                target()
            finally:
                if self._ui_alive():
                    self.root.after(0, self._end_loading_task)

        threading.Thread(target=_wrapped, daemon=True).start()

    def _apply_runtime_icon(self):
        try:
            resource_root = Path(getattr(self, "resource_root", self.app_root))
            icon_path = resource_root / "assets" / "app_icon_runtime.png"
            if not icon_path.exists():
                self.log_warn("App", f"Runtime icon not found: {icon_path}")
                return
            icon_image = tk.PhotoImage(file=str(icon_path))
            self.root.iconphoto(True, icon_image)
            # Keep a strong reference so Tk doesn't drop the image.
            self._app_icon_image = icon_image
        except Exception as exc:
            self.log_warn("App", f"Failed to apply runtime icon: {exc}")

    def _detect_release_branch(self):
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self.app_root,
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            )
            if result.returncode != 0:
                return False
            return result.stdout.strip() == "release"
        except (OSError, subprocess.SubprocessError, ValueError):
            return False

    def _ui_alive(self):
        try:
            return bool(self.root.winfo_exists())
        except tk.TclError:
            return False

    def _center_window(self, window=None) -> None:
        target = window if window is not None else self.root
        if target is None:
            return
        try:
            target.update_idletasks()
            width = int(target.winfo_width())
            height = int(target.winfo_height())
            if width <= 1:
                width = int(target.winfo_reqwidth())
            if height <= 1:
                height = int(target.winfo_reqheight())
            width = max(1, width)
            height = max(1, height)
            x = max(0, int((int(target.winfo_screenwidth()) - width) / 2))
            y = max(0, int((int(target.winfo_screenheight()) - height) / 2))
            target.geometry(f"{width}x{height}+{x}+{y}")
        except Exception:
            return

    def _get_frames_raw(self):
        frame_source = getattr(self, "frame_source", None)
        frames_raw = getattr(self, "frames_raw", None)
        if frame_source is not None:
            return getattr(frame_source, "raw_frames", frames_raw)
        return frames_raw

    def _get_frame_count(self):
        frame_source = getattr(self, "frame_source", None)
        if frame_source is not None:
            return int(getattr(frame_source, "frame_count", 0) or 0)
        frames = self._get_frames_raw()
        return len(frames) if frames is not None else 0

    def _get_frame_shape(self):
        frame_source = getattr(self, "frame_source", None)
        if frame_source is not None:
            shape = getattr(frame_source, "frame_shape", (0, 0))
            if shape and len(shape) >= 2:
                return int(shape[0]), int(shape[1])
        frames = self._get_frames_raw()
        if frames is None or len(frames) == 0:
            return 0, 0
        return tuple(frames[0].shape[:2])

    def _has_loaded_stack(self):
        return self._get_frame_count() > 0

    def _get_frames_sub_viz(self):
        frame_source = getattr(self, "frame_source", None)
        frames_sub_viz = getattr(self, "frames_sub_viz", None)
        if frame_source is not None:
            return getattr(frame_source, "visual_frames", frames_sub_viz)
        return frames_sub_viz

    def _get_frame_names(self):
        frame_source = getattr(self, "frame_source", None)
        frame_names = getattr(self, "frame_names", [])
        if frame_source is not None:
            return list(getattr(frame_source, "frame_names", frame_names))
        return list(frame_names)

    def _set_spinbox_value(self, widget, value):
        text = str(value)
        prev_flag = self._programmatic_spinbox_update
        self._programmatic_spinbox_update = True
        try:
            try:
                widget.delete(0, tk.END)
                widget.insert(0, text)
            except (tk.TclError, AttributeError):
                # Fallback for widgets exposing ttk-style set().
                try:
                    widget.set(text)
                except (tk.TclError, AttributeError):
                    pass
        finally:
            self._programmatic_spinbox_update = prev_flag

    def _on_export_range_user_edit(self, event=None):
        if not getattr(self, "_programmatic_spinbox_update", False):
            self._export_range_auto_follow = False

    def _set_widget_enabled(self, widget, enabled):
        state = "normal" if enabled else "disabled"
        try:
            widget.configure(state=state)
        except tk.TclError:
            pass

    def _parse_clamped_frame_range(self, start_widget, end_widget, total_frames):
        if total_frames <= 0:
            return 0, -1
        try:
            start_idx = int(start_widget.get()) - 1
            end_idx = int(end_widget.get()) - 1
        except (TypeError, ValueError, tk.TclError):
            return 0, total_frames - 1
        start_idx = max(0, min(start_idx, total_frames - 1))
        end_idx = max(0, min(end_idx, total_frames - 1))
        return start_idx, end_idx

    def _set_container_controls_enabled(self, parent, enabled):
        interactive_types = (
            tk.Button,
            tk.Entry,
            tk.Spinbox,
            tk.Scale,
            tk.Radiobutton,
            tk.Checkbutton,
            ttk.Button,
            ttk.Entry,
            ttk.Spinbox,
            ttk.Scale,
            ttk.Radiobutton,
            ttk.Checkbutton,
        )
        for child in parent.winfo_children():
            if isinstance(child, interactive_types):
                self._set_widget_enabled(child, enabled)
            self._set_container_controls_enabled(child, enabled)

    def _set_data_controls_enabled(self, enabled):
        if hasattr(self, "frame_tools"):
            self._set_container_controls_enabled(self.frame_tools, enabled)
        if hasattr(self, "frame_prop"):
            self._set_container_controls_enabled(self.frame_prop, enabled)
        if hasattr(self, "right_controls"):
            self._set_container_controls_enabled(self.right_controls, enabled)
        if hasattr(self, "slider"):
            self._set_widget_enabled(self.slider, enabled)
        if hasattr(self, "slider_overlay"):
            self.slider_overlay.configure(cursor="hand2" if enabled else "arrow")

        if enabled:
            self._controls_hint_logged = False
            if hasattr(self, "lbl_status") and "Import image sequence to enable" in self.lbl_status.cget("text"):
                self.lbl_status.configure(text="Status: Idle", foreground="gray")
        else:
            if not self._controls_hint_logged:
                self.log_info(
                    "App",
                    "Open an SD event from the SD ID main window to enable tools, propagation, and mask save.",
                )
                self._controls_hint_logged = True

    def _set_export_panel(self, open_state):
        is_open = bool(open_state)
        self.export_panel_open.set(is_open)
        if not hasattr(self, "btn_export_toggle") or not hasattr(self, "frame_export_body"):
            return
        self.btn_export_toggle.configure(text=f"Export {'▾' if is_open else '▸'}")
        self.frame_export_body.pack_forget()
        if is_open:
            self.frame_export_body.pack(fill="x", padx=4, pady=(0, 4))

    def _set_analysis_panel(self, open_state):
        is_open = bool(open_state)
        self.analysis_panel_open.set(is_open)
        if not hasattr(self, "btn_analysis_toggle") or not hasattr(self, "frame_analysis_body"):
            return
        self.btn_analysis_toggle.configure(text=f"Adjust Metrics {'▾' if is_open else '▸'}")
        self.frame_analysis_body.pack_forget()
        if is_open:
            self.frame_analysis_body.pack(fill="x", padx=4, pady=(0, 4))

    def _toggle_export_panel(self):
        self._set_export_panel(not bool(self.export_panel_open.get()))

    def _toggle_analysis_panel(self):
        self._set_analysis_panel(not bool(self.analysis_panel_open.get()))

    def log(self, level, context, message):
        lvl = str(level).upper()
        if lvl == "DEBUG" and self._is_release_branch:
            return
        ctx = f"[{context}]" if context else ""
        line = f"[{lvl}]{ctx} {message}"
        self._on_logger_message(line, False)
        if not bool(getattr(self, "_host_mode", False)):
            print(line)

    def log_info(self, context, message):
        self.log("INFO", context, message)

    def log_warn(self, context, message):
        self.log("WARN", context, message)

    def log_error(self, context, message):
        self.log("ERROR", context, message)

    def log_success(self, context, message):
        self.log("SUCCESS", context, message)

    def log_debug(self, context, message):
        self.log("DEBUG", context, message)

    def _frame_to_overlay_x(self, frame_idx, width=None, total_frames=None):
        total = total_frames if total_frames is not None else self._get_frame_count()
        if width is None:
            width = self.slider_overlay.winfo_width() if hasattr(self, "slider_overlay") else 0
        width = max(0, int(width))
        clamped_idx = float(max(0.0, min(float(frame_idx), max(0.0, float(total - 1)))))

        # Prefer ttk.Scale's own coordinate mapping to stay visually aligned with slider values.
        if hasattr(self, "slider") and hasattr(self, "slider_overlay"):
            try:
                coords = self.slider.coords(float(clamped_idx))
                if coords and len(coords) >= 1:
                    slider_x = float(coords[0])
                    x_offset = float(self.slider.winfo_rootx() - self.slider_overlay.winfo_rootx())
                    return slider_x + x_offset
            except (tk.TclError, TypeError, ValueError):
                pass

        if total <= 1:
            return width / 2.0
        return (clamped_idx / float(total - 1)) * max(0.0, float(width - 1))

    def _compose_final_mask_for_frame(self, frame_idx):
        frame_count = self._get_frame_count()
        if frame_count <= 0 or frame_idx < 0 or frame_idx >= frame_count:
            return None
        return self.seg_state.compose_final_mask(frame_idx, self._get_frame_shape())

    def _collect_nonempty_final_mask_frames(self):
        frame_count = self._get_frame_count()
        if frame_count <= 0:
            return set()
        return self.seg_state.get_nonempty_final_mask_frames(frame_count, self._get_frame_shape())

    def _collect_user_defined_frames(self):
        frame_count = self._get_frame_count()
        if frame_count <= 0:
            return set()
        return self.seg_state.get_user_frames(frame_count)

    def _build_frame_spans(self, indices):
        return frame_spans(indices)

    def _span_length(self, span):
        return span_length(span)

    def _get_largest_contiguous_span(self, indices):
        return largest_contiguous_span(indices)

    def _has_valid_points(self, frame_idx):
        return frame_idx in self.seg_state.get_valid_point_frames()

    def _prune_empty_point_frames(self):
        self.seg_state.prune_invalid_points()

    def _recompute_slider_jump_markers(self):
        return overlay_renderer.recompute_slider_jump_markers(self)

    def _find_clicked_marker_frame(self, x_px):
        return overlay_renderer.find_clicked_marker_frame(self, x_px)

    def _on_slider_overlay_click(self, event):
        target_frame = self._find_clicked_marker_frame(event.x)
        if target_frame is None:
            return
        self.slider.set(target_frame)

    def _clear_propagation_overlay_state(self):
        self._largest_propagated_span = None
        self._propagated_history_indices = set()
        self.propagated_frame_indices = set()
        self.propagated_frame_spans = []
        self.slider_jump_markers = {}
        self._slider_marker_bounds = {}
        self._redraw_slider_overlay()

    def _set_propagated_frames(self, indices, mark_dirty=True):
        frame_count = self._get_frame_count()
        if frame_count <= 0:
            self._clear_propagation_overlay_state()
            return
        next_state = compute_propagated_state(
            indices=indices,
            previous_history_indices=self._propagated_history_indices,
            frame_count=frame_count,
        )
        self._propagated_history_indices = set(next_state.propagated_history_indices)
        self._largest_propagated_span = next_state.largest_propagated_span
        self.propagated_frame_indices = set(next_state.propagated_frame_indices)
        self.propagated_frame_spans = list(next_state.propagated_frame_spans)
        self._recompute_slider_jump_markers()
        if mark_dirty:
            self._mark_project_dirty("propagation_complete")

    def _redraw_slider_overlay(self):
        return overlay_renderer.redraw_slider_overlay(self)

    def _render_progress_line(self, done, total):
        return self.progress_logger.render_progress_line(done, total)

    def _prop_log_start(self, total_steps, label="Propagation"):
        return self.progress_logger.start(total_steps=total_steps, label=label)

    def _prop_log_tick(self, increment=1, run_id=None):
        self.progress_logger.tick(increment=increment, run_id=run_id)

    def _prop_log_finish(self, status, run_id=None):
        self.progress_logger.finish(status=status, run_id=run_id)

    def _validate_assets(self):
        resource_root = str(getattr(self, "resource_root", self.app_root))
        model_token = self.entry_model.get().strip()
        missing = []
        if model_token:
            if str(model_token).startswith("managed://"):
                descriptor_id = model_token.split("managed://", 1)[-1].strip()
                descriptor = self.checkpoint_runtime.find_descriptor(descriptor_id)
                if descriptor is None:
                    missing.append("managed model catalog entry")
                else:
                    managed_path = self.checkpoint_runtime.descriptor_path(descriptor)
                    if not managed_path.exists():
                        missing.append("managed model file")
            else:
                model_path = model_token
                if model_path and not os.path.isabs(model_path):
                    model_path = os.path.join(resource_root, model_path)
                if not model_path or not os.path.exists(model_path):
                    missing.append("model file")
        else:
            missing.append("model file")

        configs_root = os.path.join(resource_root, "configs")
        if not os.path.exists(configs_root):
            missing.append("configs folder")

        if missing:
            msg = "Missing " + ", ".join(missing) + ". Place assets in sdapp/resources/models and sdapp/resources/configs."
            self.log_warn("App", msg)
            self.lbl_status.configure(text="Status: Assets Missing", foreground="orange")

    def load_model_from_menu(self):
        self.log_info("Model", "Loading SAM2 model...")
        self.start_model_initialization(reason="menu_load")

    def validate_assets_from_menu(self):
        self._validate_assets()

    def _reset_model_state(self):
        self.inference_manager.on_model_unloaded()
        self.model_ready = False
        self.predictor = None
        self.inference_state = None

    def _reset_interaction_state(self):
        self.points.clear()
        self.selected_point = None
        self.paint_layers.clear()
        self.masks_cache.clear()
        self.seg_state.invalidate_user_frames()
        self.seg_state.invalidate_final_mask_frames()
        self.undo_stack = []
        self.redo_stack = []
        self.paint_snapshot_before = None
        self.points_snapshot_before = None

    def _reset_frame_data_state(self):
        self.frames_raw = None
        self.frames_sub = None
        self.frames_sub_viz = None
        self.frame_names = []
        self._selected_import_files = None
        self._current_image_source_paths = []
        self.frame_source = None
        if hasattr(self, "analysis_workspace"):
            self.analysis_workspace.bind_frame_source(None)
        if hasattr(self, "app_context") and self.app_context is not None:
            self.app_context.frame_source = None
        self.current_frame_idx = 0
        self.event_records = {}
        self._propagation_committed_snapshot = None

    def _reset_cursor_overlay_state(self):
        self.last_mouse_x = None
        self.last_mouse_y = None
        self.last_img_x = None
        self.last_img_y = None
        self.is_dragging = False
        self._export_range_auto_follow = True
        self._clear_propagation_overlay_state()
        self._set_data_controls_enabled(False)

    def _clear_canvases_safely(self):
        try:
            self.canvas_left.delete("all")
            self.canvas_right.delete("all")
            self.canvas_preview.delete("all")
        except tk.TclError:
            pass

    def _reset_for_new_import(self):
        self._reset_model_state()
        self._reset_interaction_state()
        self._reset_frame_data_state()
        self._reset_cursor_overlay_state()
        self._clear_canvases_safely()

        self.cleanup_temp_files()

    def _default_event_state(self):
        frame_count = len(self.frames_raw) if self.frames_raw is not None else 0
        return self.project_session_service.event_record_to_legacy_dict(
            self.project_session_service.ensure_event_record("sd_event_001", frame_count, {})
        )

    def _apply_loaded_stack(self, frames_raw, frames_sub, frames_sub_viz, frame_names, source_paths=None):
        # Reset only after load succeeds to avoid losing in-memory work on failed import.
        self._reset_for_new_import()

        self.frames_raw = frames_raw
        self.frames_sub = frames_sub
        self.frames_sub_viz = frames_sub_viz
        self.frame_names = list(frame_names)
        self._current_image_source_paths = list(source_paths or [])
        self.frame_source = EagerFrameSource(
            raw_frames=self.frames_raw,
            subtracted_frames=self.frames_sub,
            visual_frames=self.frames_sub_viz,
            frame_names=self.frame_names,
            source_paths=self._current_image_source_paths,
        )
        self._ensure_analysis_workspace()
        self.analysis_workspace.bind_frame_source(self.frame_source)
        if hasattr(self, "app_context") and self.app_context is not None:
            self.app_context.frame_source = self.frame_source
        self.analysis_workspace.reset_workspace_for_new_stack()
        self.analysis_workspace.open_event("sd_event_001")

        self._finalize_load_ui()
        self.start_model_initialization(reason="stack_loaded")
        self._mark_project_dirty("import_stack")

    def on_right_canvas_click(self, event):
        # Analysis interactions are handled in dedicated pop-up windows.
        return

    def on_right_canvas_double_click(self, event):
        return

    def start_scale_selection(self):
        self.analysis_controller.start_scale_selection()

    def start_roi_selection(self):
        self.analysis_controller.start_roi_selection()

    def _setup_project_menu(self):
        project_workflow.setup_project_menu(self)

    def _mark_project_dirty(self, reason=""):
        self.project_dirty = True

    def _on_autosave_error(self, exc: Exception, context: str):
        self.log_warn("Autosave", f"Autosave failed ({context}): {exc}")
        if hasattr(self, "lbl_status"):
            try:
                self.lbl_status.configure(text="Status: Autosave warning (see log)", foreground="orange")
            except Exception:
                pass

    def _build_project_payload(self):
        if self.frame_source is None or not self._has_loaded_stack():
            raise RuntimeError("No loaded stack to save.")
        frame_count = self._get_frame_count()
        snapshot = self.analysis_workspace.build_session_snapshot(
            WorkspaceUiState(
                current_frame_idx=int(self.current_frame_idx),
                tool_mode=str(self.tool_mode.get()),
                display_ratio=float(getattr(self, "display_ratio", 1.0)),
                img_offset_x=int(getattr(self, "img_offset_x", 0)),
                img_offset_y=int(getattr(self, "img_offset_y", 0)),
                analysis_start=1,
                analysis_end=max(1, int(frame_count)),
                prop_start=int(self.spin_prop_start.get()),
                prop_end=int(self.spin_prop_end.get()),
                export_start=int(self.spin_export_start.get()),
                export_end=int(self.spin_export_end.get()),
                baseline_frame_count=int(self.spin_baseline.get()),
                scale_px_per_mm=self.scale_px_per_mm,
                roi_points=list(self.roi_points) if self.roi_points else [],
                roi_mask=self.roi_mask,
                created_at=self._project_created_at,
            )
        )
        return self.project_session_service.build_payload(snapshot)

    def _host_ui_hints(self) -> dict[str, object]:
        tool = "select"
        try:
            tool = str(self.tool_mode.get())
        except Exception:
            pass
        return {
            "last_frame": int(getattr(self, "current_frame_idx", 0)),
            "active_tool": tool,
        }

    def _emit_host_sync(self, reason: str) -> dict[str, object] | None:
        return self._get_host_mode_controller().emit_host_sync(reason)

    def _save_project_to_path(self, target_path, is_autosave=False):
        project_workflow.save_project_to_path(self, target_path, is_autosave=is_autosave)

    def save_project(self):
        return project_workflow.save_project(self)

    def save_project_as(self):
        return project_workflow.save_project_as(self)

    def _resolve_project_image_paths(self, loaded):
        return project_workflow.resolve_project_image_paths(self, loaded)

    def import_external_masks(self):
        return mask_import_workflow.import_external_masks(self)

    def _apply_loaded_project(self, loaded, project_path):
        return project_workflow.apply_loaded_project(self, loaded, project_path)

    def _on_propagation_status(self, status, prop_start, prop_end):
        if not self._has_loaded_stack():
            return
        if status == "started":
            self._propagation_committed_snapshot = self.project_session_service.copy_masks_dict(self.seg_state.masks_cache)
        transition = self.analysis_workspace.on_propagation_status(
            status=str(status),
            prop_start=int(prop_start),
            prop_end=int(prop_end),
            committed_snapshot=self._propagation_committed_snapshot,
        )
        self.event_records[str(self.active_event_id or "sd_event_001")] = transition.event_record

        if status == "complete":
            self._propagation_committed_snapshot = None
            return
        if status in ("stopped", "failed") and transition.restored_masks is not None:
            self.seg_state.masks_cache.clear()
            for frame_idx, mask in transition.restored_masks.items():
                self.seg_state.masks_cache[int(frame_idx)] = np.asarray(mask, dtype=bool).copy()
            self.seg_state.invalidate_final_mask_frames()
            if self._ui_alive():
                self.root.after(0, self._recompute_slider_jump_markers)
                self.root.after(0, self.update_display)
        if status in ("stopped", "failed"):
            self._propagation_committed_snapshot = None
            self._mark_project_dirty("propagation_draft")

    def open_from_host_context(
        self,
        context: dict,
        frame_source=None,
        on_analysis_update=None,
        on_metrics_update=None,
        on_checkpoint_update=None,
        on_open_model_manager=None,
        on_project_saved=None,
        on_sync_result=None,
        on_log_message=None,
        on_host_project_save=None,
        on_host_project_path=None,
        sync_emitter=None,
    ):
        return self._get_host_mode_controller().open_from_host_context(
            context=context,
            frame_source=frame_source,
            on_analysis_update=on_analysis_update,
            on_metrics_update=on_metrics_update,
            on_checkpoint_update=on_checkpoint_update,
            on_open_model_manager=on_open_model_manager,
            on_project_saved=on_project_saved,
            on_sync_result=on_sync_result,
            on_log_message=on_log_message,
            on_host_project_save=on_host_project_save,
            on_host_project_path=on_host_project_path,
            sync_emitter=sync_emitter,
        )

    def open_from_host_handoff(self, payload: dict, frame_source=None, sync_emitter=None):
        return self._get_host_mode_controller().open_from_host_handoff(
            payload=payload,
            frame_source=frame_source,
            sync_emitter=sync_emitter,
        )

    def _post_host_mode_open_ui(self, message: str) -> None:
        self._get_host_mode_controller().post_host_mode_open_ui(message)

    def _shutdown_model_resources(self):
        self._get_model_controller().shutdown_model_resources()

    def _prepare_host_mode_buffers(self, frame_source, on_ready_message: str | None = None):
        return self._get_host_mode_controller().prepare_host_mode_buffers(frame_source, on_ready_message)

    def _is_propagation_running(self):
        return project_workflow.is_propagation_running(self)

    def on_close(self):
        return project_workflow.on_close(self)

    def cleanup_temp_files(self):
        if self.temp_dir and os.path.exists(self.temp_dir):
            try:
                self.log_debug("App", f"Cleaning up temp files in {self.temp_dir}...")
                shutil.rmtree(self.temp_dir)
            except Exception as e:
                self.log_warn("App", f"Could not remove temp dir: {e}")

    def start_resize_preview(self, event):
        return do_start_resize_preview(self, event)

    def do_resize_preview(self, event):
        return do_preview_resize(self, event)

    def stop_resize_preview(self, event):
        return do_stop_resize_preview(self, event)

    def on_mouse_move(self, event):
        self.interaction_controller.on_mouse_move(event)

    def _draw_brush_cursor_on_canvas(self):
        mode = self.tool_mode.get()
        if mode == "select":
            self.canvas_left.delete("cursor_brush")
            self.canvas_left.config(cursor="arrow")
            return

        if mode not in ["brush", "eraser"]:
            self.canvas_left.delete("cursor_brush")
            self.canvas_left.config(cursor="cross")
            return

        self.canvas_left.config(cursor="none")
        self.canvas_left.delete("cursor_brush")

        if self.last_mouse_x is None:
            return

        r = self.brush_size.get() * self.display_ratio
        x, y = self.last_mouse_x, self.last_mouse_y
        color = "white" if mode == "brush" else "red"

        self.canvas_left.create_oval(x - r, y - r, x + r, y + r, outline=color, width=2, fill="", tag="cursor_brush")

    def on_mouse_leave(self, event):
        self.interaction_controller.on_mouse_leave(event)

    def on_brush_size_change(self, val):
        self.interaction_controller.on_brush_size_change(val)

    def on_nav_left(self, event=None):
        self.interaction_controller.on_nav_left(event)

    def on_nav_right(self, event=None):
        self.interaction_controller.on_nav_right(event)

    def on_browse_model(self):
        self._get_model_controller().browse_model()

    def open_checkpoint_manager(self):
        self._get_model_controller().open_model_manager()

    def open_model_manager(self):
        self._get_model_controller().open_model_manager()

    def _focus_is_text_input(self):
        try:
            focused = self.root.focus_get()
        except tk.TclError:
            return False
        if focused is None:
            return False

        text_types = (tk.Entry, tk.Text, tk.Spinbox, ttk.Entry, ttk.Spinbox)
        try:
            if isinstance(focused, text_types):
                return True
        except TypeError:
            pass

        class_name = ""
        try:
            class_name = str(focused.winfo_class()).lower()
        except Exception:
            class_name = str(getattr(focused, "widgetName", "")).lower()
        return class_name in {"entry", "text", "spinbox", "ttk::entry", "ttk::spinbox"}

    def _set_tool_brush_hotkey(self, event=None):
        if self._focus_is_text_input():
            return None
        self.tool_mode.set("brush")
        self.update_display()
        return "break"

    def _set_tool_eraser_hotkey(self, event=None):
        if self._focus_is_text_input():
            return None
        self.tool_mode.set("eraser")
        self.update_display()
        return "break"

    def on_mouse_down(self, event):
        self.interaction_controller.on_mouse_down(event)

    def on_mouse_drag(self, event):
        self.interaction_controller.on_mouse_drag(event)

    def on_mouse_up(self, event):
        self.interaction_controller.on_mouse_up(event)
        self._mark_project_dirty("mouse_up")

    def delete_selected_point(self, event=None):
        self.interaction_controller.delete_selected_point(event)
        self._mark_project_dirty("delete_point")

    def _analysis_payload_has_saved_masks(self, payload) -> bool:
        return self._get_window_controller().analysis_payload_has_saved_masks(payload)

    def _event_has_saved_masks_in_project(self) -> bool:
        return self._get_window_controller().event_has_saved_masks_in_project()

    def _sync_project_path_from_host(self) -> None:
        self._get_window_controller().sync_project_path_from_host()

    def _sync_saved_mask_overlay_state(self) -> None:
        try:
            nonempty = self._collect_nonempty_final_mask_frames()
            self._set_propagated_frames(nonempty, mark_dirty=False)
        except Exception:
            return

    def _collect_current_metrics_settings(self) -> dict[str, object]:
        return self._get_window_controller().collect_current_metrics_settings()

    def _apply_host_metrics_settings(self, metrics_settings: dict | None) -> None:
        self._get_window_controller().apply_host_metrics_settings(metrics_settings)

    def _emit_host_metrics_update(self, reason: str) -> dict[str, object] | None:
        return self._get_window_controller().emit_host_metrics_update(reason)

    def _emit_host_checkpoint_update(self, reason: str) -> dict[str, object] | None:
        if not bool(getattr(self, "_host_mode", False)):
            return None
        updater = getattr(self, "_host_checkpoint_updater", None)
        if not callable(updater):
            return None
        payload = {
            "event_id": str(getattr(self, "active_event_id", "") or ""),
            "model_checkpoint": dict(getattr(self, "_active_checkpoint_metadata", {}) or {}),
            "reason": str(reason or ""),
        }
        try:
            result = updater(payload)
        except Exception as exc:
            self.log_warn("HostSync", f"Direct host model metadata update failed: {exc}")
            return {"ok": False, "code": "PAYLOAD_INVALID", "message": str(exc)}
        if isinstance(result, dict) and not bool(result.get("ok", False)):
            code = str(result.get("code", "PAYLOAD_INVALID"))
            message = str(result.get("message", "Host rejected model metadata update."))
            self.log_warn("HostSync", f"Host rejected model metadata update [{code}]: {message}")
        return result if isinstance(result, dict) else {"ok": True}

    def _set_active_checkpoint_metadata(self, metadata: dict | None, *, notify_host: bool = True, reason: str = "update") -> None:
        self._active_checkpoint_metadata = dict(metadata) if isinstance(metadata, dict) else None
        if bool(notify_host):
            self._emit_host_checkpoint_update(reason=str(reason or "update"))

    def _project_recorded_checkpoint_metadata(self) -> dict | None:
        meta = dict(getattr(self, "_host_project_metadata", {}) or {})
        model_meta = meta.get(MODEL_CHECKPOINT_METADATA_KEY)
        if isinstance(model_meta, dict):
            return dict(model_meta)
        return None

    def _on_metrics_settings_changed(self, reason: str) -> None:
        self._get_window_controller().on_metrics_settings_changed(reason)

    def _on_frames_per_sec_commit(self, _event=None):
        return self._get_window_controller().on_frames_per_sec_commit(_event)

    def _get_window_controller(self) -> AnalysisWindowController:
        controller = getattr(self, "window_controller", None)
        if isinstance(controller, AnalysisWindowController):
            return controller
        controller = AnalysisWindowController(self)
        self.window_controller = controller
        return controller

    def _get_host_mode_controller(self) -> AnalysisHostModeController:
        controller = getattr(self, "host_mode_controller", None)
        if isinstance(controller, AnalysisHostModeController):
            return controller
        controller = AnalysisHostModeController(self)
        self.host_mode_controller = controller
        return controller

    def _get_model_controller(self) -> AnalysisModelController:
        controller = getattr(self, "model_controller", None)
        if isinstance(controller, AnalysisModelController):
            return controller
        controller = AnalysisModelController(self)
        self.model_controller = controller
        return controller

    def _mark_active_event_saved_masks_present(self) -> None:
        self._get_window_controller().mark_active_event_saved_masks_present()

    def _show_masks_saved_popup(self) -> None:
        self._get_window_controller().show_masks_saved_popup()

    def save_current_masks(self):
        self._get_window_controller().save_current_masks()

    def export_results(self):
        # Compatibility alias for older bindings.
        return self.save_current_masks()

    def clear_current_frame_data(self):
        self.interaction_controller.clear_current_frame_data()
        self._mark_project_dirty("clear_frame")


def main():
    raise RuntimeError(
        "Standalone SD Segmenter launch is not supported. "
        "Start the unified host app with `python -m sdapp.main`."
    )


if __name__ == "__main__":
    main()
