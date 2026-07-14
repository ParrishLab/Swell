import importlib.util
import os
import sys
import threading
import gc
import time
import subprocess
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, ttk
from swell.shared.ui import dialogs as messagebox

import numpy as np

from swell.shared.config import AppConfig
from swell.analysis.core.io import IOActions
from swell.analysis.core.segmentation import SegmentationActions
from swell.analysis.core.render import RenderActions
from swell.analysis.core.undo import UndoActions
from swell.analysis.core.frame_source import EagerFrameSource, FrameSequenceView
from swell.analysis.core.analysis_controller import AnalysisController
from swell.analysis.core.analysis_context import AnalysisContext
from swell.analysis.core.seg_state import SegmentationState
from swell.analysis.core.inference_manager import InferenceManager
from swell.analysis.core.interaction_controller import InteractionController
from swell.analysis.core.project_schema import utc_now_iso
from swell.analysis.core.project_store import ProjectStore
from swell.analysis.core.project_autosave import AutosaveSnapshot, ProjectAutosaveManager
from swell.analysis.core.autosave_naming import derive_autosave_tag
from swell.analysis.core.session_state import SessionState
from swell.analysis.core import mask_import_workflow
from swell.analysis.core.mask_import_dialog import MaskImportDialogService
from swell.analysis.core.project_session import ProjectSessionService, SessionSnapshot
from swell.analysis.core.analysis_workspace import AnalysisWorkspaceController, WorkspaceUiState
from swell.analysis.core.overlay_state import frame_spans, span_length, largest_contiguous_span, compute_propagated_state
from swell.analysis.core.runtime_state import AnalysisFrameState, AnalysisModelState, AnalysisRuntimeState, HostModeState
from swell.analysis.core import overlay_renderer
from swell.analysis.core.preview_resize import start_resize_preview as do_start_resize_preview
from swell.analysis.core.preview_resize import do_resize_preview as do_preview_resize
from swell.analysis.core.preview_resize import stop_resize_preview as do_stop_resize_preview
from swell.analysis.core.propagation_progress import PropagationProgressLogger
from swell.shared.ui.theme import APP_COLORS
from swell.analysis.core.app_context import AppContext
from swell.analysis.core import project_workflow
from swell.analysis.core.region_tools import REGION_EXCLUDE_TOOL, REGION_INCLUDE_TOOL
from swell.analysis.core.viewport import (
    ViewportState,
    clamp_viewport_center,
    compute_transform,
    fit_viewport,
    pan_viewport,
    zoom_viewport_at,
)
from swell.shared.app_metadata import format_window_title
from swell.shared.diagnostics import stage as perf_stage
from swell.analysis.controllers import (
    AnalysisHostModeController,
    AnalysisModelController,
    AnalysisRuntimeController,
    AnalysisWindowController,
)
from swell.analysis.ui.layout import LayoutBuilder
from swell.shared.utils.paths import get_app_root, get_resources_root
from swell.shared.ui.bootstrap import center_window_on_screen, ttk as themed_ttk
from swell.shared.services import CheckpointRuntimeService, MODEL_CHECKPOINT_METADATA_KEY


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(str(name)) is not None
    except Exception:
        return False


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


class SwellAnalysisApp(LayoutBuilder, IOActions, SegmentationActions, RenderActions, UndoActions):
    def __init__(self, root, *, menu_builder=None, menu_mode="analysis", host_mode: bool = False):
        self.root = root
        self.root.title(format_window_title("Swell Analysis"))
        self.root.geometry("1400x950")
        center_window_on_screen(self.root, width=1400, height=950)

        self.app_root = str(get_app_root())
        self.resource_root = str(get_resources_root())
        self._is_release_branch = self._detect_release_branch()
        self._app_icon_image = None
        self._apply_runtime_icon()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.frame_state = AnalysisFrameState()
        self.current_project_path = None
        self.project_dirty = False
        self.session_state = SessionState()
        self.active_event_id = "event_001"
        self.session_state.event_records = {}
        self._project_created_at = utc_now_iso()
        self._project_embed_images = False
        self._propagation_committed_snapshot = None
        self.runtime_state = AnalysisRuntimeState()
        self.model_state = AnalysisModelState()
        self.host_mode_state = HostModeState()
        self._host_launch_preparation = None
        self._host_post_open_ui_initialized = False

        self.current_frame_idx = 0
        self.seg_state = SegmentationState()
        self.points = self.seg_state.points
        self.boxes = self.seg_state.boxes
        self.selected_point = None
        self.selected_region_id = None
        self.paint_layers = self.seg_state.paint_layers

        self.display_ratio = 1.0
        self.img_offset_x = 0
        self.img_offset_y = 0
        self.viewport_state = ViewportState(center_x=0.5, center_y=0.5, zoom_factor=1.0)
        self._space_pan_requested = False
        self._mask_peek_hold_requested = False
        self._mask_peek = False
        self.mask_peek_sticky_var = tk.BooleanVar(value=False)
        self._viewport_pan_active = False
        self._viewport_pan_canvas = None
        self._viewport_pan_last_x = None
        self._viewport_pan_last_y = None

        self.last_mouse_x = None
        self.last_mouse_y = None
        self.last_img_x = None
        self.last_img_y = None
        self.is_dragging = False

        self.scale_px_per_mm = None
        self.roi_mask = None
        self.roi_points = []
        self.roi_polygons = []
        self.scale_points = []
        self.scale_axis_lock = True
        self._scale_is_local_override = False
        self._roi_is_local_override = False
        self._frames_per_sec_is_local_override = False
        self.analysis_mode = None

        self.sam2_runtime = None
        self.sam2_frame_cache = None
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
        self.analysis_panel_open = tk.BooleanVar(value=False)
        self._controls_hint_logged = False
        self._analysis_log_buffer_limit = 150
        self._analysis_log_entries: list[str] = []
        self._analysis_prewarm_generation = 0
        self._analysis_prewarm_thread = None
        self._analysis_prewarm_window = 4
        self._last_prewarm_frame_idx = None
        self._pending_display_update = False
        self._pending_display_preview = True
        self._pending_leverage_recompute_job = None
        self._propagation_progress_active = False
        self._timeline_progress_state = None
        self._timeline_progress_item_ids = {}
        self._timeline_loading_animation_job = None
        self._timeline_loading_animation_phase = 0.0
        self._initial_frame_nav_ts = None
        self._last_segmentation_edit_blocked_ts = 0.0

        self.ghost_outlines_enabled_var = tk.BooleanVar(value=False)
        self.ghost_range_var = tk.IntVar(value=2)
        self.leverage_visibility_var = tk.BooleanVar(value=True)
        self.ghost_outlines_enabled_var.trace_add("write", lambda *_: self._queue_display_update(True))
        self.ghost_range_var.trace_add("write", lambda *_: self._queue_display_update(True))
        self.leverage_visibility_var.trace_add("write", lambda *_: self._redraw_slider_overlay())

        self.config = AppConfig.load()
        self.set_input_source_hint("Host-provided event scope")
        self.set_model_token(self.config.model_token())
        self.set_baseline_frame_count(self.config.default_baseline)
        self.project_store = ProjectStore()
        self.project_session_service = ProjectSessionService()
        self.analysis_workspace = AnalysisWorkspaceController(
            session_service=self.project_session_service,
            session_state=self.session_state,
            seg_state=self.seg_state,
            on_event_opened=self._on_workspace_event_opened,
        )
        self.mask_import_dialog = MaskImportDialogService()
        self.autosave_manager = self._create_project_autosave_manager()

        with perf_stage("SwellAnalysisApp.setup_ui"):
            self.setup_ui()
        self.window_controller = AnalysisWindowController(self)
        self.host_mode_controller = AnalysisHostModeController(self)
        self.model_controller = AnalysisModelController(self)
        self.runtime_controller = AnalysisRuntimeController(self)
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
            on_update=self._on_propagation_progress_update,
        )
        if hasattr(self.root, "after"):
            self.root.after(0, self._emit_optional_runtime_dependency_warnings)
        else:
            self._emit_optional_runtime_dependency_warnings()
        with perf_stage("SwellAnalysisApp.InferenceManager.__init__"):
            self.inference_manager = InferenceManager(
                state=self.seg_state,
            root=self.root,
            predictor_lock=self.predictor_lock,
            get_sensitivity=lambda: float(self.sensitivity.get()),
            get_current_frame_idx=lambda: int(self.current_frame_idx),
            get_frame_count=self._get_frame_count,
            get_frame_shape=self._get_frame_shape,
            set_slider_frame=lambda idx: self.slider.set(idx),
            update_display=lambda: self._queue_display_update(True),
            recompute_markers=self._recompute_slider_jump_markers,
            set_propagated_frames=self._set_propagated_frames,
            set_status=self._set_runtime_status,
            prop_log_start=self._prop_log_start,
            prop_log_tick=self._prop_log_tick,
            prop_log_finish=self._prop_log_finish,
            on_propagation_status=self._on_propagation_status,
            on_device_oom=self._handle_accelerator_oom,
            log=self.log,
            is_ui_alive=self._ui_alive,
        )
        self.analysis_controller = AnalysisController(
            root=self.root,
            app_root=self.app_root,
            ctx=AnalysisContext(
                get_frame_count=self._get_frame_count,
                get_raw_frame=self._get_raw_frame,
                get_masks_cache=lambda: self.masks_cache,
                get_paint_layers=lambda: self.paint_layers,
                get_points=lambda: self.points,
                get_frame_names=self._get_frame_names,
                get_import_source_hint=self.get_input_source_hint,
                get_current_image_source_paths=lambda: (
                    list(self._current_image_source_paths)
                    if self._current_image_source_paths
                    else list(getattr(getattr(self, "frame_source", None), "source_paths", []) or [])
                ),
                get_current_frame_idx=lambda: int(self.current_frame_idx),
                get_compose_final_mask_for_frame=self._compose_final_mask_for_frame,
                get_nonempty_final_mask_frames=self._collect_nonempty_final_mask_frames,
                get_frames_per_sec=lambda: float(self.frames_per_sec_var.get()),
                get_scale_px_per_mm=lambda: self.scale_px_per_mm,
                set_scale_px_per_mm=lambda v: setattr(self, "scale_px_per_mm", v),
                get_scale_points=lambda: self.scale_points,
                set_scale_points=lambda v: setattr(self, "scale_points", v),
                get_scale_axis_lock=lambda: bool(self.scale_axis_lock),
                set_scale_axis_lock=lambda v: setattr(self, "scale_axis_lock", bool(v)),
                get_last_scale_image_path=lambda: self._last_scale_image_path,
                set_last_scale_image_path=lambda v: setattr(self, "_last_scale_image_path", v or ""),
                get_roi_mask=lambda: self.roi_mask,
                set_roi_mask=lambda v: setattr(self, "roi_mask", v),
                get_roi_points=lambda: self.roi_points,
                set_roi_points=lambda v: setattr(self, "roi_points", v),
                get_roi_polygons=lambda: self.roi_polygons,
                set_roi_polygons=lambda v: setattr(self, "roi_polygons", v),
                update_display=self.update_display,
                apply_host_metrics_settings=self._apply_host_metrics_settings,
                clear_local_metrics_override=self._clear_local_metrics_override,
                log_info=self.log_info,
                log_success=self.log_success,
                on_metrics_settings_changed=self._on_metrics_settings_changed,
                emit_host_global_metrics_update=self._emit_host_global_metrics_update,
                autosave_project_after_metrics_commit=self._autosave_project_after_metrics_commit,
                get_scale_is_local_override=lambda: bool(self._scale_is_local_override),
                set_scale_is_local_override=lambda v: setattr(self, "_scale_is_local_override", bool(v)),
                get_roi_is_local_override=lambda: bool(self._roi_is_local_override),
                set_roi_is_local_override=lambda v: setattr(self, "_roi_is_local_override", bool(v)),
                refresh_metrics_status=self._refresh_metrics_status_labels,
            ),
        )
        self.interaction_controller = InteractionController(
            seg_state=self.seg_state,
            points=self.points,
            boxes=self.boxes,
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
            fill_tolerance=self.fill_tolerance,
            region_start_var=self.region_start_var,
            region_end_var=self.region_end_var,
            get_selected_region_id=lambda: self.selected_region_id,
            set_selected_region_id=self._set_selected_region_id,
            refresh_region_controls=self._refresh_region_controls,
            canvas_left=self.canvas_left,
            slider=self.slider,
            lbl_brush_val=self.lbl_brush_val,
            get_frame_count=self._get_frame_count,
            get_frame_shape_for_idx=self._get_frame_shape_for_idx,
            get_visual_frame=self._get_visual_frame,
            get_display_transform=self._get_display_transform,
            update_display=self.update_display,
            draw_paint_preview_segment=self._draw_paint_preview_segment_on_canvas,
            clear_paint_preview=self._clear_paint_preview_on_canvas,
            draw_box_preview=self._draw_box_preview_on_canvas,
            clear_box_preview=self._clear_box_preview_on_canvas,
            draw_brush_cursor=self._draw_brush_cursor_on_canvas,
            recompute_slider_jump_markers=self._recompute_slider_jump_markers,
            update_mask_prediction=self._update_mask_prediction,
            get_model_ready=lambda: self.model_ready,
            record_action=self.record_action,
            prune_empty_point_frames=self._prune_empty_point_frames,
            can_mutate_segmentation=self._segmentation_edits_allowed,
            on_mutation_blocked=self._on_segmentation_edit_blocked,
            on_region_validation_error=self._show_region_validation_error,
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
        self._refresh_metrics_status_labels()
        self._set_data_controls_enabled(False)
        with perf_stage("SwellAnalysisApp.inference_manager.start"):
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
        self.session_state.active_event_id = str(value or "event_001")

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
        frame_count = int(self._get_frame_count()) if hasattr(self, "_get_frame_count") else 0
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
        frame_count = int(self._get_frame_count()) if hasattr(self, "_get_frame_count") else 0
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

    def get_input_source_hint(self) -> str:
        self._ensure_session_state()
        return str(getattr(self.session_state, "input_source_hint", "") or "")

    def set_input_source_hint(self, value: str | None) -> None:
        self._ensure_session_state()
        self.session_state.input_source_hint = str(value or "")

    def get_model_token(self) -> str:
        self._ensure_session_state()
        return str(getattr(self.session_state, "model_token", "") or "").strip()

    def set_model_token(self, value: str | None) -> None:
        self._ensure_session_state()
        self.session_state.model_token = str(value or "").strip()

    def get_baseline_frame_count(self) -> int:
        self._ensure_session_state()
        try:
            value = int(getattr(self.session_state, "baseline_frame_count", 30))
        except Exception:
            value = 30
        return max(1, value)

    def set_baseline_frame_count(self, value) -> None:
        self._ensure_session_state()
        try:
            parsed = int(value)
        except Exception:
            parsed = 30
        self.session_state.baseline_frame_count = max(1, parsed)

    def _ensure_frame_state(self) -> None:
        if not hasattr(self, "frame_state") or self.frame_state is None:
            self.frame_state = AnalysisFrameState()

    @property
    def frames_raw(self):
        self._ensure_frame_state()
        return self.frame_state.raw_frames

    @frames_raw.setter
    def frames_raw(self, value) -> None:
        self._ensure_frame_state()
        self.frame_state.raw_frames = value

    @property
    def frames_sub(self):
        self._ensure_frame_state()
        return self.frame_state.subtracted_frames

    @frames_sub.setter
    def frames_sub(self, value) -> None:
        self._ensure_frame_state()
        self.frame_state.subtracted_frames = value

    @property
    def frames_sub_viz(self):
        self._ensure_frame_state()
        return self.frame_state.visual_frames

    @frames_sub_viz.setter
    def frames_sub_viz(self, value) -> None:
        self._ensure_frame_state()
        self.frame_state.visual_frames = value

    @property
    def frame_names(self):
        self._ensure_frame_state()
        return self.frame_state.frame_names

    @frame_names.setter
    def frame_names(self, value) -> None:
        self._ensure_frame_state()
        self.frame_state.frame_names = list(value or [])

    @property
    def _selected_import_files(self):
        self._ensure_frame_state()
        return self.frame_state.selected_import_files

    @_selected_import_files.setter
    def _selected_import_files(self, value) -> None:
        self._ensure_frame_state()
        self.frame_state.selected_import_files = None if value is None else list(value)

    @property
    def _current_image_source_paths(self):
        self._ensure_frame_state()
        return self.frame_state.current_image_source_paths

    @_current_image_source_paths.setter
    def _current_image_source_paths(self, value) -> None:
        self._ensure_frame_state()
        self.frame_state.current_image_source_paths = list(value or [])

    @property
    def _image_manifest_entries(self):
        self._ensure_frame_state()
        return self.frame_state.image_manifest_entries

    @_image_manifest_entries.setter
    def _image_manifest_entries(self, value) -> None:
        self._ensure_frame_state()
        self.frame_state.image_manifest_entries = list(value or [])

    @property
    def frame_source(self):
        self._ensure_frame_state()
        return self.frame_state.frame_source

    @frame_source.setter
    def frame_source(self, value) -> None:
        self._ensure_frame_state()
        self.frame_state.frame_source = value

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
    def _host_global_metrics_updater(self):
        self._ensure_runtime_state()
        return self.host_mode_state.global_metrics_updater

    @_host_global_metrics_updater.setter
    def _host_global_metrics_updater(self, value) -> None:
        self._ensure_runtime_state()
        self.host_mode_state.global_metrics_updater = value

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
                on_event_opened=self._on_workspace_event_opened,
            )
        elif hasattr(self.analysis_workspace, "_on_event_opened"):
            self.analysis_workspace._on_event_opened = self._on_workspace_event_opened

    def _set_loading_indicator(self, loading: bool, text: str = "Working...") -> None:
        if hasattr(self, "loading_status_var"):
            self.loading_status_var.set(str(text or "Working...") if loading else "Idle")
        if bool(getattr(self, "_propagation_progress_active", False)):
            return
        if bool(loading):
            self._timeline_progress_state = {"active": True, "kind": "loading", "label": str(text or "Working...")}
            self._schedule_timeline_loading_animation()
            return
        self._cancel_timeline_loading_animation()
        if str((getattr(self, "_timeline_progress_state", {}) or {}).get("kind") or "") == "loading":
            self._timeline_progress_state = None
        self._clear_timeline_progress_items()

    def _set_activity_message(self, text: str) -> None:
        if not hasattr(self, "loading_status_var"):
            return
        if not bool(getattr(self, "_propagation_progress_active", False)):
            self.loading_status_var.set(str(text or "Idle"))

    def _apply_propagation_progress_update(
        self,
        *,
        active: bool,
        done: int,
        total: int,
        label: str,
        status: str,
        run_id: int,
        prop_start=None,
        prop_end=None,
        anchor=None,
        phase=None,
        direction=None,
        phase_done: int = 0,
        phase_total: int = 0,
        forward_done: int = 0,
        forward_total: int = 0,
        backward_done: int = 0,
        backward_total: int = 0,
    ) -> None:
        del run_id
        total_steps = max(0, int(total))
        done_steps = max(0, min(int(done), total_steps if total_steps > 0 else int(done)))
        if bool(active):
            self._propagation_progress_active = True
            pct = 100 if total_steps <= 0 else int(round((done_steps / max(1, total_steps)) * 100))
            if hasattr(self, "loading_status_var"):
                self.loading_status_var.set(f"{label} {pct}% ({done_steps}/{total_steps})")
            frame_count = int(self._get_frame_count()) if hasattr(self, "_get_frame_count") else 0
            self._timeline_progress_state = {
                "active": True,
                "kind": "propagation",
                "done": done_steps,
                "total": total_steps,
                "label": str(label or "Propagation"),
                "status": str(status or "progress"),
                "prop_start": 0 if prop_start is None else int(prop_start),
                "prop_end": max(0, frame_count - 1) if prop_end is None else int(prop_end),
                "anchor": 0 if anchor is None else int(anchor),
                "phase": None if phase is None else str(phase),
                "direction": None if direction is None else str(direction),
                "phase_done": int(phase_done or 0),
                "phase_total": int(phase_total or 0),
                "forward_done": int(forward_done or 0),
                "forward_total": int(forward_total or 0),
                "backward_done": int(backward_done or 0),
                "backward_total": int(backward_total or 0),
            }
            self._update_timeline_progress_layer()
            return

        self._propagation_progress_active = False
        if str((getattr(self, "_timeline_progress_state", {}) or {}).get("kind") or "") == "propagation":
            self._timeline_progress_state = None
        self._clear_timeline_progress_items()
        terminal_messages = {
            "complete": "Propagation complete",
            "stopped": "Propagation stopped",
            "failed": "Propagation failed",
        }
        if status in terminal_messages and hasattr(self, "loading_status_var"):
            self.loading_status_var.set(terminal_messages[status])
        if int(getattr(self, "_loading_task_count", 0) or 0) > 0:
            self._set_loading_indicator(True, str(self.loading_status_var.get() or "Working..."))
            return

    def _on_propagation_progress_update(self, **payload) -> None:
        if not self._ui_alive():
            return

        def _apply() -> None:
            if self._ui_alive():
                self._apply_propagation_progress_update(**payload)

        if threading.current_thread() is threading.main_thread():
            _apply()
        else:
            self.root.after(0, _apply)

    def _begin_loading_task(self, text: str = "Working...") -> None:
        self._loading_task_count = int(getattr(self, "_loading_task_count", 0)) + 1
        self._set_loading_indicator(True, text)

    def _end_loading_task(self) -> None:
        self._loading_task_count = max(0, int(getattr(self, "_loading_task_count", 0)) - 1)
        if self._loading_task_count == 0:
            self._set_loading_indicator(False)

    def _redraw_timeline_progress(self) -> None:
        overlay_renderer.redraw_timeline_progress(self)

    def _update_timeline_progress_layer(self) -> None:
        state = getattr(self, "_timeline_progress_state", None)
        if not state:
            self._clear_timeline_progress_items()
            return
        if str(state.get("kind") or "") == "loading":
            overlay_renderer.update_timeline_loading_progress(self)
        else:
            overlay_renderer.update_timeline_propagation_progress(self)

    def _schedule_timeline_loading_animation(self) -> None:
        if not self._ui_alive():
            return
        self._update_timeline_progress_layer()
        if getattr(self, "_timeline_loading_animation_job", None) is not None:
            return

        def _tick():
            self._timeline_loading_animation_job = None
            state = getattr(self, "_timeline_progress_state", None)
            if not state or str(state.get("kind") or "") != "loading" or not bool(state.get("active", False)):
                return
            self._update_timeline_progress_layer()
            if self._ui_alive():
                self._timeline_loading_animation_job = self.root.after(33, _tick)

        self._timeline_loading_animation_job = self.root.after(33, _tick)

    def _cancel_timeline_loading_animation(self) -> None:
        job = getattr(self, "_timeline_loading_animation_job", None)
        if job is None:
            return
        self._timeline_loading_animation_job = None
        try:
            self.root.after_cancel(job)
        except Exception:
            pass

    def _clear_timeline_progress_items(self) -> None:
        overlay_renderer.clear_timeline_progress_items(self)

    def _refresh_log_tree(self) -> None:
        tree = getattr(self, "log_tree", None)
        if tree is None:
            return
        try:
            for item_id in list(tree.get_children("")):
                tree.delete(item_id)
            for entry in list(getattr(self, "_analysis_log_entries", [])):
                tree.insert("", "end", text=entry)
            children = tree.get_children("")
            if children:
                tree.see(children[-1])
        except Exception:
            return

    def _append_log_entry(self, level: str, context: str, body: str) -> None:
        entry = f"[{str(level or 'INFO').upper()}]"
        if context:
            entry = f"{entry} [{context}]"
        if body:
            entry = f"{entry} {body}"
        entries = getattr(self, "_analysis_log_entries", None)
        if not isinstance(entries, list):
            entries = []
            self._analysis_log_entries = entries
        entries.append(entry)
        limit = max(1, int(getattr(self, "_analysis_log_buffer_limit", 150) or 150))
        if len(entries) > limit:
            del entries[:-limit]

        tree = getattr(self, "log_tree", None)
        if tree is None:
            return
        try:
            tree.insert("", "end", text=entry)
            children = list(tree.get_children(""))
            if len(children) > limit:
                for item_id in children[:-limit]:
                    tree.delete(item_id)
                children = list(tree.get_children(""))
            if children:
                tree.see(children[-1])
        except Exception:
            self._refresh_log_tree()

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
            self._append_log_entry(level, context, body)

    def _set_runtime_status(self, text: str, color: str) -> None:
        return self._get_runtime_controller().set_runtime_status(text, color)

    def _set_busy(self, is_busy, status_text, color):
        return self._get_runtime_controller().set_busy(is_busy, status_text, color)

    def _run_thread(self, target, *, loading_text: str = "Working..."):
        return self._get_runtime_controller().run_thread(target, loading_text=loading_text)

    def _queue_display_update(self, update_preview: bool = True) -> None:
        return self._get_runtime_controller().queue_display_update(update_preview=update_preview)

    def _schedule_analysis_prewarm(self, current_idx: int | None = None) -> None:
        return self._get_runtime_controller().schedule_analysis_prewarm(current_idx=current_idx)

    def _ensure_sam2_runtime(self):
        runtime = getattr(self, "sam2_runtime", None)
        if runtime is not None:
            return runtime
        from swell.analysis.model.sam2_runtime import SAM2RuntimeService

        runtime = SAM2RuntimeService()
        self.sam2_runtime = runtime
        return runtime

    def _ensure_sam2_frame_cache(self):
        frame_cache = getattr(self, "sam2_frame_cache", None)
        if frame_cache is not None:
            return frame_cache
        from swell.analysis.model.sam2_frame_cache import SAM2FrameCache

        frame_cache = SAM2FrameCache()
        self.sam2_frame_cache = frame_cache
        return frame_cache

    def _emit_optional_runtime_dependency_warnings(self) -> None:
        if not _module_available("imagecodecs"):
            self.log_warn("Runtime", "imagecodecs not installed. LZW-compressed TIFFs may fail to load.")
        if not _module_available("sam2"):
            self.log_warn("Runtime", "'sam2' package not found. Model-based tools will be disabled (review-only mode).")
            self.log_warn(
                "Runtime",
                "Install SAM2 with: pip install \"sam-2 @ git+https://github.com/facebookresearch/sam2.git\"",
            )
            self.log_warn("Runtime", f"Python interpreter: {sys.executable}")

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
            root = getattr(self, "root", None)
            if root is None:
                return False
            return bool(root.winfo_exists())
        except (AttributeError, tk.TclError):
            return False

    def _ensure_viewport_state(self) -> None:
        if not hasattr(self, "viewport_state") or self.viewport_state is None:
            self.viewport_state = ViewportState(center_x=0.5, center_y=0.5, zoom_factor=1.0)

    def _current_image_dimensions(self) -> tuple[int, int]:
        frame_count = int(self._get_frame_count()) if hasattr(self, "_get_frame_count") else 0
        if frame_count <= 0:
            return 1, 1
        idx = max(0, min(int(getattr(self, "current_frame_idx", 0)), max(0, frame_count - 1)))
        try:
            frame_h, frame_w = self._get_frame_shape_for_idx(idx)
        except Exception:
            return 1, 1
        return max(1, int(frame_w)), max(1, int(frame_h))

    def _iter_viewport_canvas_sizes(self, *, exclude_preview: bool = False) -> list[tuple[int, int]]:
        sizes: list[tuple[int, int]] = []
        for name in ("canvas_left", "canvas_right", "canvas_reference_popout", "canvas_preview"):
            if bool(exclude_preview) and name == "canvas_preview":
                continue
            canvas = getattr(self, name, None)
            if canvas is None:
                continue
            try:
                if hasattr(canvas, "winfo_exists") and not bool(canvas.winfo_exists()):
                    continue
                sizes.append((max(1, int(canvas.winfo_width())), max(1, int(canvas.winfo_height()))))
            except Exception:
                continue
        return sizes or [(1, 1)]

    def _sync_legacy_viewport_fields(self) -> None:
        canvas = getattr(self, "canvas_left", None)
        if canvas is None:
            return
        try:
            img_w, img_h = self._current_image_dimensions()
            transform = self._get_canvas_viewport_transform(canvas, img_w, img_h)
        except Exception:
            return
        self.display_ratio = float(transform.scale)
        self.img_offset_x = int(round(transform.offset_x))
        self.img_offset_y = int(round(transform.offset_y))

    def _clamp_shared_viewport(self) -> None:
        self._ensure_viewport_state()
        img_w, img_h = self._current_image_dimensions()
        self.viewport_state = clamp_viewport_center(
            self.viewport_state,
            image_width=img_w,
            image_height=img_h,
            canvas_sizes=self._iter_viewport_canvas_sizes(exclude_preview=True),
        )
        self._sync_legacy_viewport_fields()

    def _reset_viewport_to_fit(self, *, update_display: bool = False) -> None:
        self._ensure_viewport_state()
        img_w, img_h = self._current_image_dimensions()
        self.viewport_state = fit_viewport(
            img_w,
            img_h,
            min_zoom=float(self.viewport_state.min_zoom),
            max_zoom=float(self.viewport_state.max_zoom),
        )
        self._clamp_shared_viewport()
        if bool(update_display) and self._ui_alive():
            self.update_display(update_preview=True)

    def _get_canvas_viewport_transform(self, canvas, img_w: int, img_h: int):
        self._ensure_viewport_state()
        transform = compute_transform(
            self.viewport_state,
            canvas_width=max(1, int(canvas.winfo_width())),
            canvas_height=max(1, int(canvas.winfo_height())),
            image_width=max(1, int(img_w)),
            image_height=max(1, int(img_h)),
        )
        if getattr(self, "canvas_left", None) is canvas:
            self.display_ratio = float(transform.scale)
            self.img_offset_x = int(round(transform.offset_x))
            self.img_offset_y = int(round(transform.offset_y))
        return transform

    def _get_display_transform(self, canvas, img_w, img_h):
        transform = self._get_canvas_viewport_transform(canvas, img_w, img_h)
        return transform.scale, transform.offset_x, transform.offset_y

    def _zoom_shared_viewport(self, canvas, direction: int, anchor_x: float | None = None, anchor_y: float | None = None) -> str | None:
        if self._focus_is_text_input():
            return None
        frame_count = int(self._get_frame_count()) if hasattr(self, "_get_frame_count") else 0
        if frame_count <= 0:
            return "break"
        self._ensure_viewport_state()
        img_w, img_h = self._current_image_dimensions()
        anchor_x = float(anchor_x if anchor_x is not None else (canvas.winfo_width() / 2.0))
        anchor_y = float(anchor_y if anchor_y is not None else (canvas.winfo_height() / 2.0))
        step = 1.25 if int(direction) > 0 else (1.0 / 1.25)
        self.viewport_state = zoom_viewport_at(
            self.viewport_state,
            image_width=img_w,
            image_height=img_h,
            canvas_width=max(1, int(canvas.winfo_width())),
            canvas_height=max(1, int(canvas.winfo_height())),
            anchor_canvas_x=anchor_x,
            anchor_canvas_y=anchor_y,
            new_zoom_factor=float(self.viewport_state.zoom_factor) * float(step),
            shared_canvas_sizes=self._iter_viewport_canvas_sizes(exclude_preview=True),
        )
        self._sync_legacy_viewport_fields()
        self.update_display(update_preview=True)
        return "break"

    def _pan_shared_viewport(self, canvas, delta_x: float, delta_y: float) -> None:
        frame_count = int(self._get_frame_count()) if hasattr(self, "_get_frame_count") else 0
        if frame_count <= 0:
            return
        self._ensure_viewport_state()
        img_w, img_h = self._current_image_dimensions()
        self.viewport_state = pan_viewport(
            self.viewport_state,
            image_width=img_w,
            image_height=img_h,
            canvas_width=max(1, int(canvas.winfo_width())),
            canvas_height=max(1, int(canvas.winfo_height())),
            delta_canvas_x=float(delta_x),
            delta_canvas_y=float(delta_y),
            shared_canvas_sizes=self._iter_viewport_canvas_sizes(exclude_preview=True),
        )
        self._sync_legacy_viewport_fields()
        self.update_display(update_preview=True)

    def _set_space_pan_active(self, event=None):
        if self._focus_is_text_input():
            return None
        self._space_pan_requested = True
        self._sync_viewport_cursor_states()
        return "break" if event is not None else None

    def _clear_space_pan_active(self, event=None):
        self._space_pan_requested = False
        self._sync_viewport_cursor_states()
        return "break" if event is not None else None

    def _refresh_mask_peek_state(self) -> bool:
        sticky = False
        var = getattr(self, "mask_peek_sticky_var", None)
        if var is not None:
            try:
                sticky = bool(var.get())
            except Exception:
                sticky = False
        next_value = bool(getattr(self, "_mask_peek_hold_requested", False) or sticky)
        changed = next_value != bool(getattr(self, "_mask_peek", False))
        self._mask_peek = next_value
        if changed and self._ui_alive():
            self._queue_display_update(True)
        return changed

    def _set_mask_peek_hold_active(self, event=None):
        if self._focus_is_text_input():
            return None
        if bool(getattr(self, "_mask_peek_hold_requested", False)):
            return "break" if event is not None else None
        self._mask_peek_hold_requested = True
        self._refresh_mask_peek_state()
        return "break" if event is not None else None

    def _clear_mask_peek_hold_active(self, event=None):
        if not bool(getattr(self, "_mask_peek_hold_requested", False)):
            return "break" if event is not None else None
        self._mask_peek_hold_requested = False
        self._refresh_mask_peek_state()
        return "break" if event is not None else None

    def _on_mask_peek_sticky_toggled(self):
        self._refresh_mask_peek_state()

    def _sync_viewport_cursor_states(self) -> None:
        active_canvas = getattr(self, "_viewport_pan_canvas", None) if bool(getattr(self, "_viewport_pan_active", False)) else None
        for canvas_name in ("canvas_right", "canvas_preview"):
            canvas = getattr(self, canvas_name, None)
            if canvas is None:
                continue
            cursor = "fleur" if bool(getattr(self, "_space_pan_requested", False)) or canvas is active_canvas else "arrow"
            try:
                canvas.config(cursor=cursor)
            except Exception:
                pass
        if getattr(self, "canvas_left", None) is not None:
            self._draw_brush_cursor_on_canvas()

    def _start_canvas_pan(self, canvas, event) -> str | None:
        if not bool(getattr(self, "_space_pan_requested", False)):
            return None
        self._viewport_pan_active = True
        self._viewport_pan_canvas = canvas
        self._viewport_pan_last_x = float(event.x)
        self._viewport_pan_last_y = float(event.y)
        try:
            canvas.config(cursor="fleur")
        except Exception:
            pass
        self._sync_viewport_cursor_states()
        return "break"

    def _drag_canvas_pan(self, canvas, event) -> str | None:
        if not bool(getattr(self, "_viewport_pan_active", False)) or getattr(self, "_viewport_pan_canvas", None) is not canvas:
            return None
        if self._viewport_pan_last_x is None or self._viewport_pan_last_y is None:
            self._viewport_pan_last_x = float(event.x)
            self._viewport_pan_last_y = float(event.y)
            return "break"
        dx = float(event.x) - float(self._viewport_pan_last_x)
        dy = float(event.y) - float(self._viewport_pan_last_y)
        self._viewport_pan_last_x = float(event.x)
        self._viewport_pan_last_y = float(event.y)
        self._pan_shared_viewport(canvas, dx, dy)
        return "break"

    def _stop_canvas_pan(self, canvas, _event=None) -> str | None:
        if getattr(self, "_viewport_pan_canvas", None) is canvas:
            self._viewport_pan_active = False
            self._viewport_pan_canvas = None
            self._viewport_pan_last_x = None
            self._viewport_pan_last_y = None
            try:
                self._sync_viewport_cursor_states()
            except Exception:
                pass
            return "break"
        return None

    def _on_canvas_mouse_wheel(self, event):
        delta = getattr(event, "delta", 0)
        num = getattr(event, "num", None)
        direction = 0
        if delta:
            direction = 1 if float(delta) > 0 else -1
        elif num in (4, 5):
            direction = 1 if int(num) == 4 else -1
        if direction == 0:
            return None
        if bool(int(getattr(event, "state", 0)) & 0x0001):
            self._step_brush_size(direction)
            return "break"
        return self._zoom_shared_viewport(event.widget, direction, getattr(event, "x", 0.0), getattr(event, "y", 0.0))

    def _on_viewport_canvas_configure(self, _event=None):
        frame_count = int(self._get_frame_count()) if hasattr(self, "_get_frame_count") else 0
        if frame_count <= 0:
            return None
        self._clamp_shared_viewport()
        self._queue_display_update(update_preview=True)
        return None

    def _center_window(self, window=None, *, width: int | None = None, height: int | None = None) -> None:
        target = window if window is not None else self.root
        if target is None:
            return
        center_window_on_screen(target, width=width, height=height)

    def _frame_source_capabilities(self):
        frame_source = getattr(self, "frame_source", None)
        return dict(getattr(frame_source, "capabilities", {}) or {}) if frame_source is not None else {}

    def _get_raw_frame(self, idx):
        frame_source = getattr(self, "frame_source", None)
        if frame_source is not None:
            return frame_source.get_raw_frame(int(idx))
        frames_raw = getattr(self, "frames_raw", None)
        if frames_raw is None:
            return None
        return frames_raw[int(idx)]

    def _get_subtracted_frame(self, idx):
        frame_source = getattr(self, "frame_source", None)
        if frame_source is not None:
            capabilities = self._frame_source_capabilities()
            if bool(capabilities.get("subtracted")):
                return frame_source.get_subtracted_frame(int(idx))
        frames_sub = getattr(self, "frames_sub", None)
        if frames_sub is None:
            return None
        return frames_sub[int(idx)]

    def _get_visual_frame(self, idx):
        frame_source = getattr(self, "frame_source", None)
        if frame_source is not None:
            capabilities = self._frame_source_capabilities()
            if bool(capabilities.get("visual")):
                return frame_source.get_visual_frame(int(idx))
        frames_sub_viz = getattr(self, "frames_sub_viz", None)
        if frames_sub_viz is None:
            return None
        return frames_sub_viz[int(idx)]

    def _get_frames_raw(self):
        frame_source = getattr(self, "frame_source", None)
        frames_raw = getattr(self, "frames_raw", None)
        if frame_source is not None:
            try:
                count = int(getattr(frame_source, "frame_count", 0) or 0)
            except Exception:
                count = 0
            if count > 0 and callable(getattr(frame_source, "get_raw_frame", None)):
                return FrameSequenceView(frame_source, "get_raw_frame")
        return frames_raw

    def _get_frame_count(self):
        frame_source = getattr(self, "frame_source", None)
        if frame_source is not None:
            count = int(getattr(frame_source, "frame_count", 0) or 0)
            if count > 0:
                return count
            self.log_debug(
                "FrameState",
                f"frame_source present but frame_count invalid ({count}); falling back to frames_raw",
            )
        frames = self._get_frames_raw()
        fallback = len(frames) if frames is not None else 0
        self.log_debug("FrameState", f"_get_frame_count fallback result={fallback}")
        return fallback

    def _get_frame_shape(self):
        frames = self._get_frames_raw()
        fallback_shape = None
        if frames is not None and len(frames) > 0:
            first_frame = frames[0]
            if first_frame is not None and hasattr(first_frame, "shape"):
                fallback_shape = tuple(int(v) for v in first_frame.shape[:2])
        frame_source = getattr(self, "frame_source", None)
        if frame_source is not None:
            shape = getattr(frame_source, "frame_shape", (0, 0))
            if shape and len(shape) >= 2:
                height = int(shape[0] or 0)
                width = int(shape[1] or 0)
                if height > 0 and width > 0:
                    source_shape = (height, width)
                    if fallback_shape is not None and tuple(source_shape) != tuple(fallback_shape):
                        self.log_warn(
                            "FrameState",
                            f"frame_source shape {source_shape} disagrees with loaded frame shape {fallback_shape}; using loaded frames",
                        )
                        return fallback_shape
                    return height, width
                self.log_debug(
                    "FrameState",
                    f"frame_source present but frame_shape invalid ({shape}); falling back to frames_raw",
                )
        if fallback_shape is None:
            self.log_debug("FrameState", "_get_frame_shape fallback result=(0, 0)")
            return 0, 0
        self.log_debug("FrameState", f"_get_frame_shape fallback result={fallback_shape}")
        return fallback_shape

    def _get_frame_shape_for_idx(self, idx):
        frame = self._get_raw_frame(idx)
        if frame is None:
            return self._get_frame_shape()
        arr = np.asarray(frame)
        if arr.ndim >= 2:
            return tuple(int(v) for v in arr.shape[:2])
        return self._get_frame_shape()

    def _has_loaded_stack(self):
        return self._get_frame_count() > 0

    def _get_frames_sub_viz(self):
        frame_source = getattr(self, "frame_source", None)
        frames_sub_viz = getattr(self, "frames_sub_viz", None)
        if frame_source is not None:
            capabilities = self._frame_source_capabilities()
            if bool(capabilities.get("visual")):
                return FrameSequenceView(frame_source, "get_visual_frame")
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
            before = None
            original_state = None
            try:
                before = str(widget.get())
            except Exception:
                before = "<unreadable>"
            try:
                original_state = str(widget.cget("state"))
            except Exception:
                original_state = None
            try:
                if original_state and original_state != "normal":
                    try:
                        widget.configure(state="normal")
                    except Exception:
                        pass
                widget.delete(0, tk.END)
                widget.insert(0, text)
            except (tk.TclError, AttributeError):
                # Fallback for widgets exposing ttk-style set().
                try:
                    widget.set(text)
                except (tk.TclError, AttributeError):
                    pass
            finally:
                if original_state and original_state != "normal":
                    try:
                        widget.configure(state=original_state)
                    except Exception:
                        pass
            after = None
            try:
                after = str(widget.get())
            except Exception:
                after = "<unreadable>"
            self.log_debug(
                "Spinbox",
                f"_set_spinbox_value widget={getattr(widget, 'widgetName', type(widget).__name__)} "
                f"state={original_state} before={before} requested={text} after={after}",
            )
            if widget in (getattr(self, "spin_prop_start", None), getattr(self, "spin_prop_end", None)):
                redraw = getattr(self, "_redraw_propagation_range_bar", None)
                if callable(redraw):
                    redraw()
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
        interactive_types = [
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
        ]
        for widget_name in ("Button", "Entry", "Spinbox", "Scale", "Radiobutton", "Checkbutton"):
            bootstrap_type = getattr(themed_ttk, widget_name, None)
            if bootstrap_type is not None and bootstrap_type not in interactive_types:
                interactive_types.append(bootstrap_type)
        for child in parent.winfo_children():
            if isinstance(child, tuple(interactive_types)):
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
                self.lbl_status.configure(text="Status: Idle", foreground=APP_COLORS["muted"])
        else:
            if not self._controls_hint_logged:
                self.log_info(
                    "App",
                    "Open an event from the Swell main window to enable tools, propagation, and mask save.",
                )
                self._controls_hint_logged = True

    def _set_analysis_panel(self, open_state):
        is_open = bool(open_state)
        self.analysis_panel_open.set(is_open)
        if not hasattr(self, "btn_analysis_toggle") or not hasattr(self, "frame_analysis_body"):
            return
        self.frame_analysis_body.grid_remove()
        if is_open:
            self.frame_analysis_body.grid()

    def _toggle_analysis_panel(self):
        self._set_analysis_panel(not bool(self.analysis_panel_open.get()))

    def log(self, level, context, message):
        lvl = str(level).upper()
        if lvl == "DEBUG" and bool(getattr(self, "_is_release_branch", False)):
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

        if total <= 1:
            return width / 2.0
        return (clamped_idx / float(total - 1)) * max(0.0, float(width - 1))

    def _compose_final_mask_for_frame(self, frame_idx):
        frame_count = self._get_frame_count()
        if frame_count <= 0 or frame_idx < 0 or frame_idx >= frame_count:
            return None
        expected_shape = self._get_frame_shape()
        cached_mask = None
        if hasattr(self, "seg_state") and getattr(self.seg_state, "masks_cache", None) is not None:
            cached_mask = self.seg_state.masks_cache.get(frame_idx)
        if cached_mask is not None:
            cached_shape = getattr(cached_mask, "shape", None)
            if cached_shape is not None and tuple(cached_shape[:2]) != tuple(expected_shape):
                self.log_debug(
                    "Overlay",
                    f"_compose_final_mask_for_frame frame={frame_idx} cached_mask_shape={cached_shape} expected_shape={expected_shape}",
                )
        final_mask = self.seg_state.compose_final_mask(frame_idx, expected_shape)
        if final_mask is not None and getattr(final_mask, "shape", None) != tuple(expected_shape):
            self.log_debug(
                "Overlay",
                f"_compose_final_mask_for_frame frame={frame_idx} final_mask_shape={getattr(final_mask, 'shape', None)} expected_shape={expected_shape}",
            )
        return final_mask

    def _collect_nonempty_final_mask_frames(self):
        frame_count = self._get_frame_count()
        if frame_count <= 0:
            self.log_debug("Overlay", "_collect_nonempty_final_mask_frames aborted: frame_count<=0")
            return set()
        frame_shape = self._get_frame_shape()
        masks_cache = getattr(getattr(self, "seg_state", None), "masks_cache", {}) or {}
        paint_layers = getattr(getattr(self, "seg_state", None), "paint_layers", {}) or {}
        mask_sample = []
        for frame_idx in sorted(int(i) for i in masks_cache.keys())[:8]:
            mask = masks_cache.get(frame_idx)
            mask_sample.append((frame_idx, getattr(mask, "shape", None)))
        paint_sample = []
        for frame_idx in sorted(int(i) for i in paint_layers.keys())[:8]:
            layer = paint_layers.get(frame_idx) or {}
            paint_sample.append(
                (
                    frame_idx,
                    getattr(layer.get("plus"), "shape", None),
                    getattr(layer.get("minus"), "shape", None),
                )
            )
        frames_raw = self._get_frames_raw()
        first_raw_shape = None
        if frames_raw is not None and len(frames_raw) > 0 and frames_raw[0] is not None:
            first_raw_shape = getattr(frames_raw[0], "shape", None)
        frames = self.seg_state.get_exportable_mask_frames(frame_count, frame_shape)
        self.log_debug(
            "Overlay",
            f"_collect_nonempty_final_mask_frames frame_count={frame_count} frame_shape={frame_shape} "
            f"first_raw_shape={first_raw_shape} "
            f"mask_keys={sorted(int(i) for i in masks_cache.keys())[:12]} mask_shapes={mask_sample} "
            f"paint_shapes={paint_sample} "
            f"result={sorted(int(i) for i in frames)[:12]}",
        )
        return frames

    def _collect_user_defined_frames(self):
        frame_count = self._get_frame_count()
        if frame_count <= 0:
            return set()
        return self.seg_state.get_prompt_anchor_frames(frame_count)

    def _collect_nonempty_mask_frames_without_regions(self):
        frame_count = self._get_frame_count()
        if frame_count <= 0:
            return set()
        return self.seg_state.get_timeline_extent_frames(frame_count, self._get_frame_shape())

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

    def _recompute_leverage_map(self):
        from swell.analysis.core.leverage import compute_leverage, compute_trouble

        seg_state = getattr(self, "seg_state", None)
        if seg_state is None:
            return
        fc = self._get_frame_count()
        if fc <= 0:
            seg_state.set_leverage_map({}, None)
            return
        shape = self._get_frame_shape()
        candidates = seg_state.get_exportable_mask_frames(fc, shape)
        if not candidates:
            seg_state.set_leverage_map({}, None)
            return
        masks = {}
        for frame_idx in sorted(candidates):
            mask = seg_state.compose_final_mask(frame_idx, shape)
            if mask is not None:
                masks[int(frame_idx)] = np.asarray(mask, dtype=bool)
        user = seg_state.get_prompt_anchor_frames(fc)
        trouble = compute_trouble(masks, fc, shape, user)
        leverage, suggested = compute_leverage(trouble, fc)
        seg_state.set_leverage_map(leverage, suggested)

    def _schedule_leverage_recompute(self, delay_ms: int = 120):
        existing = getattr(self, "_pending_leverage_recompute_job", None)
        if existing is not None:
            try:
                self.root.after_cancel(existing)
            except Exception:
                pass
        if not self._ui_alive():
            self._recompute_leverage_map()
            return

        def _run():
            self._pending_leverage_recompute_job = None
            self._recompute_leverage_map()
            self._redraw_slider_overlay()

        self._pending_leverage_recompute_job = self.root.after(max(0, int(delay_ms)), _run)

    def _find_clicked_marker_frame(self, x_px):
        return overlay_renderer.find_clicked_marker_frame(self, x_px)

    def _on_slider_overlay_click(self, event):
        target_frame = self._find_clicked_marker_frame(event.x)
        if target_frame is None:
            return
        self.slider.set(target_frame)

    def _clear_propagation_overlay_state(self):
        self.log_debug(
            "Overlay",
            f"Clearing propagation overlay state previous_markers={getattr(self, 'slider_jump_markers', {})} "
            f"previous_propagated={sorted(int(i) for i in getattr(self, 'propagated_frame_indices', set()))[:12]}",
        )
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
            self.log_debug("Overlay", "_set_propagated_frames aborted: frame_count<=0")
            self._clear_propagation_overlay_state()
            return
        self.log_debug(
            "Overlay",
            f"_set_propagated_frames input={sorted(int(i) for i in indices)[:20]} frame_count={frame_count} mark_dirty={mark_dirty}",
        )
        next_state = compute_propagated_state(
            indices=indices,
            previous_history_indices=self._propagated_history_indices,
            frame_count=frame_count,
        )
        self._propagated_history_indices = set(next_state.propagated_history_indices)
        self._largest_propagated_span = next_state.largest_propagated_span
        self.propagated_frame_indices = set(next_state.propagated_frame_indices)
        self.propagated_frame_spans = list(next_state.propagated_frame_spans)
        self.log_debug(
            "Overlay",
            f"_set_propagated_frames result largest_span={self._largest_propagated_span} "
            f"history={sorted(int(i) for i in self._propagated_history_indices)[:20]} "
            f"propagated={sorted(int(i) for i in self.propagated_frame_indices)[:20]}",
        )
        self._recompute_leverage_map()
        self._recompute_slider_jump_markers()
        if mark_dirty:
            self._mark_project_dirty("propagation_complete")

    def _redraw_slider_overlay(self):
        return overlay_renderer.redraw_slider_overlay(self)

    def _update_slider_playhead(self):
        return overlay_renderer.update_slider_playhead(self)

    def _render_progress_line(self, done, total):
        return self.progress_logger.render_progress_line(done, total)

    def _prop_log_start(self, total_steps, label="Propagation", **kwargs):
        return self.progress_logger.start(total_steps=total_steps, label=label, **kwargs)

    def _prop_log_tick(self, increment=1, run_id=None, **kwargs):
        self.progress_logger.tick(increment=increment, run_id=run_id, **kwargs)

    def _prop_log_finish(self, status, run_id=None):
        self.progress_logger.finish(status=status, run_id=run_id)

    def _validate_assets(self):
        resource_root = str(getattr(self, "resource_root", self.app_root))
        model_token = self.get_model_token()
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
            msg = "Missing " + ", ".join(missing) + ". Place assets in swell/resources/models and swell/resources/configs."
            self.log_warn("App", msg)
            self.lbl_status.configure(text="Status: Assets Missing", foreground=APP_COLORS["warning"])

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
        controller = getattr(self, "interaction_controller", None)
        if controller is not None and hasattr(controller, "reset_transient_state"):
            controller.reset_transient_state()
        self.points.clear()
        self.selected_point = None
        self.seg_state.boxes.clear()
        self.boxes = self.seg_state.boxes
        self.selected_region_id = None
        self.paint_layers.clear()
        self.masks_cache.clear()
        self.seg_state.ground_truth_frames.clear()
        self.seg_state.clear_persistent_regions()
        self.seg_state.set_leverage_map({}, None)
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
        self._analysis_prewarm_generation = 0
        self._last_prewarm_frame_idx = None
        self._initial_frame_nav_ts = None
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
        frame_count = int(self._get_frame_count()) if hasattr(self, "_get_frame_count") else 0
        return self.project_session_service.event_record_to_legacy_dict(
            self.project_session_service.ensure_event_record("event_001", frame_count, {})
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
        self.analysis_workspace.open_event("event_001")

        self._finalize_load_ui()
        self._reset_viewport_to_fit(update_display=False)
        self._schedule_analysis_prewarm(0)
        self._initial_frame_nav_ts = time.perf_counter()
        self.start_model_initialization(reason="stack_loaded")
        self._mark_project_dirty("import_stack")

    def on_right_canvas_click(self, event):
        # Analysis interactions are handled in dedicated pop-up windows.
        return

    def on_right_canvas_double_click(self, event):
        return

    def start_scale_selection(self):
        self.analysis_controller.start_local_scale_selection()

    def start_roi_selection(self):
        self.analysis_controller.start_local_roi_selection()

    def compute_metrics_preview(self):
        self._get_window_controller().compute_metrics_preview()

    def start_local_scale_selection(self):
        self.analysis_controller.start_local_scale_selection()

    def start_global_scale_selection(self):
        self.analysis_controller.start_global_scale_selection()

    def start_local_roi_selection(self):
        self.analysis_controller.start_local_roi_selection()

    def start_global_roi_selection(self):
        self.analysis_controller.start_global_roi_selection()

    def _setup_project_menu(self):
        project_workflow.setup_project_menu(self)

    def _mark_project_dirty(self, reason=""):
        self.project_dirty = True
        manager = getattr(self, "autosave_manager", None)
        if manager is not None and hasattr(manager, "schedule"):
            try:
                if self._has_loaded_stack():
                    manager.schedule(str(reason or "dirty"))
            except Exception as exc:
                self._on_autosave_error(exc, f"schedule:{reason}")

    def _segmentation_edits_allowed(self) -> bool:
        manager = getattr(self, "inference_manager", None)
        if manager is None or not hasattr(manager, "is_propagation_running"):
            return True
        try:
            return not bool(manager.is_propagation_running())
        except Exception:
            return False

    def _on_segmentation_edit_blocked(self, action: str = "edit") -> None:
        now = time.monotonic()
        if now - float(getattr(self, "_last_segmentation_edit_blocked_ts", 0.0)) < 1.0:
            return
        self._last_segmentation_edit_blocked_ts = now
        message = "Segmentation edits are blocked while propagation is running."
        if hasattr(self, "lbl_status"):
            try:
                self.lbl_status.configure(text=f"Status: {message}", foreground=APP_COLORS["warning"])
            except Exception:
                pass
        if callable(getattr(self, "log_warn", None)):
            try:
                self.log_warn("Propagation", f"{message} Attempted action: {action}.")
            except Exception:
                pass

    def _create_project_autosave_manager(self) -> ProjectAutosaveManager:
        autosave_dir = Path(self.app_root) / "autosaves"
        return ProjectAutosaveManager(
            snapshot_callable=self._build_autosave_snapshot,
            write_callable=self._write_autosave_snapshot,
            autosave_dir=autosave_dir,
            name_tag_provider=self._autosave_name_tag,
            dispatch_to_main=self._dispatch_autosave_to_main,
            on_error=self._on_autosave_error,
        )

    def _build_autosave_snapshot(self) -> AutosaveSnapshot | None:
        if not self._has_loaded_stack():
            return None
        state, images_manifest, roi_data, event_payloads = self._build_project_payload()
        return AutosaveSnapshot(
            project_state=state,
            images_manifest=images_manifest,
            roi_data=roi_data,
            event_payloads=event_payloads,
            embed_images=bool(getattr(self, "_project_embed_images", False)),
        )

    def _write_autosave_snapshot(self, snapshot: AutosaveSnapshot, target_path: Path) -> None:
        self.project_store.save(
            target_path,
            snapshot.project_state,
            snapshot.images_manifest,
            snapshot.roi_data,
            snapshot.event_payloads,
            embed_images=bool(snapshot.embed_images),
        )

    def _autosave_name_tag(self) -> str:
        source_paths = list(getattr(self, "_current_image_source_paths", []) or [])
        entry_value = ""
        try:
            entry_value = str(self.get_input_source_hint() or "")
        except Exception:
            entry_value = ""
        return derive_autosave_tag(source_paths, entry_value)

    def _dispatch_autosave_to_main(self, fn) -> None:
        root = getattr(self, "root", None)
        if root is not None and hasattr(root, "after"):
            root.after(0, fn)
        else:
            fn()

    def _on_autosave_error(self, exc: Exception, context: str):
        self.log_warn("Autosave", f"Autosave failed ({context}): {exc}")
        if hasattr(self, "lbl_status"):
            try:
                self.lbl_status.configure(text="Status: Autosave warning (see log)", foreground=APP_COLORS["warning"])
            except Exception:
                pass

    def _build_project_payload(self):
        if self.frame_source is None or not self._has_loaded_stack():
            raise RuntimeError("No loaded stack to save.")
        frame_count = self._get_frame_count()
        prop_start = int(self.spin_prop_start.get())
        prop_end = int(self.spin_prop_end.get())
        snapshot = self.analysis_workspace.build_session_snapshot(
            WorkspaceUiState(
                current_frame_idx=int(self.current_frame_idx),
                tool_mode=str(self.tool_mode.get()),
                display_ratio=float(getattr(self, "display_ratio", 1.0)),
                img_offset_x=int(getattr(self, "img_offset_x", 0)),
                img_offset_y=int(getattr(self, "img_offset_y", 0)),
                analysis_start=1,
                analysis_end=max(1, int(frame_count)),
                prop_start=prop_start,
                prop_end=prop_end,
                export_start=prop_start,
                export_end=prop_end,
                baseline_frame_count=self.get_baseline_frame_count(),
                scale_px_per_mm=self.scale_px_per_mm,
                scale_points=list(self.scale_points) if self.scale_points else [],
                scale_axis_lock=bool(self.scale_axis_lock),
                scale_image_path=str(getattr(self, "_last_scale_image_path", "") or ""),
                roi_points=list(self.roi_points) if self.roi_points else [],
                roi_polygons=list(self.roi_polygons) if self.roi_polygons else [],
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
        if not self._segmentation_edits_allowed():
            self._on_segmentation_edit_blocked("import_external_masks")
            return False
        return mask_import_workflow.import_external_masks(self)

    def _apply_loaded_project(self, loaded, project_path):
        return project_workflow.apply_loaded_project(self, loaded, project_path)

    def _on_propagation_status(self, status, prop_start, prop_end):
        if not self._has_loaded_stack():
            return
        if status == "started":
            self._propagation_committed_snapshot = self.project_session_service.copy_masks_dict(self.seg_state.masks_cache)
        preserve_stopped_masks = str(status) == "stopped_preserve"
        transition = self.analysis_workspace.on_propagation_status(
            status=str(status),
            prop_start=int(prop_start),
            prop_end=int(prop_end),
            committed_snapshot=None if preserve_stopped_masks else self._propagation_committed_snapshot,
        )
        self.event_records[str(self.active_event_id or "event_001")] = transition.event_record

        if status == "complete":
            self._propagation_committed_snapshot = None
            if hasattr(self, "compute_metrics_preview") and self._ui_alive():
                self.root.after(0, self.compute_metrics_preview)
            return
        if status in ("stopped", "failed") and transition.restored_masks is not None:
            self.seg_state.masks_cache.clear()
            self.seg_state.set_leverage_map({}, None)
            for frame_idx, mask in transition.restored_masks.items():
                self.seg_state.masks_cache[int(frame_idx)] = np.asarray(mask, dtype=bool).copy()
            self.seg_state.invalidate_final_mask_frames()
            if self._ui_alive():
                self.root.after(0, self._recompute_slider_jump_markers)
                self.root.after(0, self.update_display)
        if status == "stopped_preserve":
            self.seg_state.invalidate_final_mask_frames()
            if self._ui_alive():
                self.root.after(0, self._recompute_slider_jump_markers)
                self.root.after(0, self.update_display)
        if status in ("stopped", "stopped_preserve", "failed"):
            self._propagation_committed_snapshot = None
            self._mark_project_dirty("propagation_draft")

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
        return self._get_host_mode_controller().open_from_host_context(
            context=context,
            frame_source=frame_source,
            host_context_for_event=host_context_for_event,
            on_analysis_update=on_analysis_update,
            on_metrics_update=on_metrics_update,
            on_global_metrics_update=on_global_metrics_update,
            on_checkpoint_update=on_checkpoint_update,
            on_open_model_manager=on_open_model_manager,
            on_project_saved=on_project_saved,
            on_sync_result=on_sync_result,
            on_log_message=on_log_message,
            on_host_project_save=on_host_project_save,
            on_host_project_path=on_host_project_path,
            sync_emitter=sync_emitter,
            launch_preparation=launch_preparation,
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

    def _prepare_host_mode_buffers(
        self,
        frame_source,
        on_ready_message: str | None = None,
        prefer_async: bool = False,
    ):
        return self._get_host_mode_controller().prepare_host_mode_buffers(
            frame_source,
            on_ready_message,
            prefer_async=prefer_async,
        )

    def _is_propagation_running(self):
        return project_workflow.is_propagation_running(self)

    def on_close(self):
        return project_workflow.on_close(self)

    def force_close(self):
        return project_workflow.force_close(self)

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
        if bool(getattr(self, "_viewport_pan_active", False)) and getattr(self, "_viewport_pan_canvas", None) is getattr(self, "canvas_left", None):
            self.canvas_left.delete("cursor_brush")
            self.canvas_left.config(cursor="fleur")
            return

        if bool(getattr(self, "_space_pan_requested", False)):
            self.canvas_left.delete("cursor_brush")
            self.canvas_left.config(cursor="fleur")
            return

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
        color = APP_COLORS["white"] if mode == "brush" else APP_COLORS["danger"]

        self.canvas_left.create_oval(x - r, y - r, x + r, y + r, outline=color, width=2, fill="", tag="cursor_brush")

    def _draw_paint_preview_segment_on_canvas(self, x0, y0, x1, y1, radius, mode):
        color = APP_COLORS["cyan"] if mode == "brush" else APP_COLORS["danger"]
        width = max(1.0, float(radius) * 2.0)
        if abs(x1 - x0) < 0.001 and abs(y1 - y0) < 0.001:
            self.canvas_left.create_oval(
                x0 - radius,
                y0 - radius,
                x0 + radius,
                y0 + radius,
                outline="",
                fill=color,
                tags="paint_preview",
            )
            return
        self.canvas_left.create_line(
            x0,
            y0,
            x1,
            y1,
            fill=color,
            width=width,
            capstyle=tk.ROUND,
            joinstyle=tk.ROUND,
            smooth=False,
            tags="paint_preview",
        )

    def _clear_paint_preview_on_canvas(self):
        self.canvas_left.delete("paint_preview")

    def _draw_box_preview_on_canvas(self, x0, y0, x1, y1):
        self.canvas_left.delete("box_preview")
        self.canvas_left.create_rectangle(
            x0,
            y0,
            x1,
            y1,
            outline=APP_COLORS["accent"],
            width=2,
            dash=(4, 3),
            tags="box_preview",
        )

    def _clear_box_preview_on_canvas(self):
        self.canvas_left.delete("box_preview")

    def _refresh_region_controls(self):
        if hasattr(self, "_refresh_regions_dock"):
            self._refresh_regions_dock()
        if hasattr(self, "_sync_tool_options"):
            self._sync_tool_options()

    def _show_region_validation_error(self, message):
        messagebox.showwarning("Region", str(message), parent=self.root)

    def _set_selected_region_id(self, region_id):
        self.selected_region_id = None if region_id is None else str(region_id)
        self._sync_region_options_from_selection()
        if hasattr(self, "_refresh_regions_dock"):
            self._refresh_regions_dock()
        if hasattr(self, "_sync_tool_options"):
            self._sync_tool_options()

    def _default_region_frame_range(self) -> tuple[int, int]:
        frame_count = max(0, int(self._get_frame_count())) if hasattr(self, "_get_frame_count") else 0
        max_idx = max(0, frame_count - 1)
        try:
            current_idx = int(getattr(self, "current_frame_idx", 0))
        except Exception:
            current_idx = 0
        current_idx = max(0, min(max_idx, current_idx))
        return current_idx, current_idx

    def _reset_region_options_to_default_range(self):
        start, end = self._default_region_frame_range()
        if hasattr(self, "region_start_var"):
            self.region_start_var.set(str(start + 1))
        if hasattr(self, "region_end_var"):
            self.region_end_var.set(str(end + 1))

    def _sync_region_options_from_selection(self):
        region_id = getattr(self, "selected_region_id", None)
        region = self.seg_state.get_persistent_region(region_id) if region_id else None
        if region is None:
            return
        if hasattr(self, "region_start_var"):
            self.region_start_var.set(str(int(region.get("frame_start", 0)) + 1))
        if hasattr(self, "region_end_var"):
            self.region_end_var.set(str(int(region.get("frame_end", 0)) + 1))

    def commit_region_draft(self):
        if not self._segmentation_edits_allowed():
            self._on_segmentation_edit_blocked("region_add")
            return False
        changed = bool(self.interaction_controller.commit_region_draft())
        if changed:
            self.tool_mode.set("select")
            self._schedule_leverage_recompute()
            self._mark_project_dirty("region_add")
        return changed

    def cancel_region_draft(self):
        return bool(self.interaction_controller.cancel_region_draft())

    def close_region_draft(self):
        return bool(self.interaction_controller.close_region_draft())

    def apply_selected_region_options(self):
        if not self._segmentation_edits_allowed():
            self._on_segmentation_edit_blocked("region_options")
            return False
        changed = bool(self.interaction_controller.apply_selected_region_options())
        if changed:
            self._schedule_leverage_recompute()
            self._mark_project_dirty("region_options")
        return changed

    def _apply_selected_region_options_event(self, event=None):
        if not getattr(self, "selected_region_id", None):
            return None
        changed = self.apply_selected_region_options()
        return "break" if changed and event is not None else None

    def convert_selected_region_mode(self):
        if not self._segmentation_edits_allowed():
            self._on_segmentation_edit_blocked("region_convert")
            return False
        region_id = getattr(self, "selected_region_id", None)
        region = self.seg_state.get_persistent_region(region_id) if region_id else None
        if region is None:
            return False
        current = str(region.get("mode", "include"))
        next_mode = "include" if current == "exclude" else "exclude"
        changed = bool(self.interaction_controller.set_selected_region_mode(next_mode))
        if changed:
            self._schedule_leverage_recompute()
            self._mark_project_dirty("region_convert")
        return changed

    def delete_selected_region(self):
        if not self._segmentation_edits_allowed():
            self._on_segmentation_edit_blocked("region_delete")
            return False
        changed = bool(self.interaction_controller.delete_selected_region())
        if changed:
            self._schedule_leverage_recompute()
            self._mark_project_dirty("region_delete")
        return changed

    def duplicate_selected_region(self):
        if not self._segmentation_edits_allowed():
            self._on_segmentation_edit_blocked("region_duplicate")
            return False
        changed = bool(self.interaction_controller.duplicate_selected_region())
        if changed:
            self._schedule_leverage_recompute()
            self._mark_project_dirty("region_duplicate")
        return changed

    def _set_region_enabled(self, region_id, value):
        if not self._segmentation_edits_allowed():
            self._on_segmentation_edit_blocked("region_enabled")
            return False
        changed = bool(self.interaction_controller.set_region_flag(str(region_id), "enabled", bool(value)))
        if changed:
            self._schedule_leverage_recompute()
            self._mark_project_dirty("region_enabled")
        return changed

    def _set_region_visible(self, region_id, value):
        if not self._segmentation_edits_allowed():
            self._on_segmentation_edit_blocked("region_visible")
            return False
        changed = bool(self.interaction_controller.set_region_flag(str(region_id), "visible", bool(value)))
        if changed:
            self._mark_project_dirty("region_visible")
        return changed

    def fill_current_frame_holes(self):
        if not self._segmentation_edits_allowed():
            self._on_segmentation_edit_blocked("fill_holes")
            return False
        changed = bool(self.interaction_controller.fill_current_frame_holes())
        if changed:
            self._schedule_leverage_recompute()
            self._mark_project_dirty("fill_holes")
        return changed

    def _current_frame_has_nonempty_mask(self) -> bool:
        shape = self._get_frame_shape_for_idx(self.current_frame_idx)
        mask = self.seg_state.compose_final_mask(self.current_frame_idx, shape)
        return bool(mask is not None and np.any(mask))

    def is_current_frame_ground_truth(self) -> bool:
        return self.seg_state.is_ground_truth_frame(self.current_frame_idx)

    def _refresh_ground_truth_controls(self, has_mask=None):
        button = getattr(self, "btn_ground_truth", None)
        if button is None:
            return
        locked = self.is_current_frame_ground_truth()
        if has_mask is None:
            has_mask = self._current_frame_has_nonempty_mask()
        text = "Unlock current ground truth" if locked else "Lock current frame as ground truth"
        state = "normal" if locked or bool(has_mask) else "disabled"
        try:
            button.configure(text=text, state=state)
        except Exception:
            pass

    def toggle_ground_truth_current_frame(self):
        if not self._segmentation_edits_allowed():
            self._on_segmentation_edit_blocked("ground_truth")
            return False
        idx = int(self.current_frame_idx)
        locked = self.seg_state.is_ground_truth_frame(idx)
        if not locked and not self._current_frame_has_nonempty_mask():
            self.log_info("Ground Truth", "Current frame has no mask to lock.")
            self._refresh_ground_truth_controls(has_mask=False)
            return False
        before = locked
        after = not locked
        self.seg_state.set_ground_truth(idx, after)
        self.record_action("ground_truth", idx, before, after)
        self._refresh_ground_truth_controls()
        self._recompute_slider_jump_markers()
        self._schedule_leverage_recompute()
        self.update_display()
        self._mark_project_dirty("ground_truth")
        return True

    def on_mouse_leave(self, event):
        self.interaction_controller.on_mouse_leave(event)

    def on_brush_size_change(self, val):
        self.interaction_controller.on_brush_size_change(val)

    def on_nav_left(self, event=None):
        # Root-level arrow binds also fire while editing text entries; don't
        # scrub the timeline while the user is moving the text cursor.
        if event is not None and self._focus_is_text_input():
            return None
        return self.interaction_controller.on_nav_left(event)

    def on_nav_right(self, event=None):
        if event is not None and self._focus_is_text_input():
            return None
        return self.interaction_controller.on_nav_right(event)

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
        return "break"

    def _set_tool_eraser_hotkey(self, event=None):
        if self._focus_is_text_input():
            return None
        self.tool_mode.set("eraser")
        return "break"

    def _set_tool_select_hotkey(self, event=None):
        if self._focus_is_text_input():
            return None
        self.tool_mode.set("select")
        return "break"

    def _set_tool_point_pos_hotkey(self, event=None):
        if self._focus_is_text_input():
            return None
        self.tool_mode.set("point_pos")
        return "break"

    def _set_tool_point_neg_hotkey(self, event=None):
        if self._focus_is_text_input():
            return None
        self.tool_mode.set("point_neg")
        return "break"

    def _set_tool_box_hotkey(self, event=None):
        if self._focus_is_text_input():
            return None
        self.tool_mode.set("box")
        return "break"

    def _set_tool_fill_hotkey(self, event=None):
        if self._focus_is_text_input():
            return None
        self.tool_mode.set("fill")
        return "break"

    def _set_tool_fill_erase_hotkey(self, event=None):
        if self._focus_is_text_input():
            return None
        self.tool_mode.set("fill_erase")
        return "break"

    def _set_tool_region_hotkey(self, event=None):
        if self._focus_is_text_input():
            return None
        self._set_tool_mode(REGION_INCLUDE_TOOL)
        return "break"

    def _set_tool_region_exclude_hotkey(self, event=None):
        if self._focus_is_text_input():
            return None
        self._set_tool_mode(REGION_EXCLUDE_TOOL)
        return "break"

    def _toggle_ground_truth_hotkey(self, event=None):
        if self._focus_is_text_input():
            return None
        self.toggle_ground_truth_current_frame()
        return "break"

    def _save_current_masks_hotkey(self, event=None):
        self.save_current_masks()
        return "break"

    def _step_brush_size(self, direction: int) -> None:
        scale = getattr(self, "scale_brush", None)
        var = getattr(self, "brush_size", None)
        if scale is None or var is None:
            return
        try:
            minimum = float(scale.cget("from"))
            maximum = float(scale.cget("to"))
            current = float(var.get())
        except Exception:
            return
        step = 1.0 if int(direction) > 0 else -1.0
        next_value = max(minimum, min(maximum, current + step))
        if abs(next_value - current) < 1e-9:
            return
        var.set(next_value)
        self.on_brush_size_change(next_value)
        if str(getattr(self.tool_mode, "get", lambda: "")()) in {"brush", "eraser"}:
            self._draw_brush_cursor_on_canvas()

    def _zoom_in_hotkey(self, event=None):
        if not hasattr(self, "canvas_left"):
            return None
        return self._zoom_shared_viewport(self.canvas_left, 1)

    def _zoom_out_hotkey(self, event=None):
        if not hasattr(self, "canvas_left"):
            return None
        return self._zoom_shared_viewport(self.canvas_left, -1)

    def _reset_zoom_hotkey(self, event=None):
        if self._focus_is_text_input():
            return None
        self._reset_viewport_to_fit(update_display=True)
        return "break"

    def on_mouse_down(self, event):
        if self._start_canvas_pan(self.canvas_left, event) == "break":
            return "break"
        self.interaction_controller.on_mouse_down(event)

    def on_mouse_drag(self, event):
        if self._drag_canvas_pan(self.canvas_left, event) == "break":
            return "break"
        self.interaction_controller.on_mouse_drag(event)

    def on_mouse_up(self, event):
        if self._stop_canvas_pan(self.canvas_left, event) == "break":
            return "break"
        changed = bool(self.interaction_controller.on_mouse_up(event))
        if changed:
            self._schedule_leverage_recompute()
            self._mark_project_dirty("mouse_up")

    def delete_selected_point(self, event=None):
        # Delete/BackSpace are bound on the root window, so this also fires
        # while typing in an Entry (e.g. the region frame-range fields); without
        # this guard a Backspace there deletes the selected region.
        if event is not None and self._focus_is_text_input():
            return None
        if not self._segmentation_edits_allowed():
            self._on_segmentation_edit_blocked("delete_point")
            return None
        changed = bool(self.interaction_controller.delete_selected_point(event))
        if changed:
            self._mark_project_dirty("delete_point")

    def _analysis_payload_has_saved_masks(self, payload) -> bool:
        return self._get_window_controller().analysis_payload_has_saved_masks(payload)

    def _event_has_saved_masks_in_project(self) -> bool:
        return self._get_window_controller().event_has_saved_masks_in_project()

    def _sync_project_path_from_host(self) -> None:
        self._get_window_controller().sync_project_path_from_host()

    def _sync_saved_mask_overlay_state(self, *, reset_history: bool = True) -> None:
        try:
            nonempty = self._collect_nonempty_final_mask_frames()
            if callable(getattr(self, "log_debug", None)):
                try:
                    sample = sorted(int(i) for i in nonempty)[:8]
                    self.log_debug(
                        "Overlay",
                        f"Saved-mask reseed active_event_id={getattr(self, 'active_event_id', None)} "
                        f"frame_count={self._get_frame_count()} frame_shape={self._get_frame_shape()} "
                        f"frames={len(nonempty)} sample={sample}",
                    )
                except Exception:
                    pass
            if bool(reset_history):
                self._clear_propagation_overlay_state()
            self._set_propagated_frames(nonempty, mark_dirty=False)
        except Exception as exc:
            self.log_warn("Overlay", f"Saved-mask reseed failed: {exc}")
            return

    def _on_workspace_event_opened(self, _event_id: str) -> None:
        self._refresh_host_metrics_for_active_event(_event_id)
        # Propagation overlay state is event-local in host mode; clear stale history
        # and rebuild from the newly opened event's saved masks.
        self.log_debug(
            "Overlay",
            f"_on_workspace_event_opened event_id={_event_id} "
            f"active_event_id={getattr(self, 'active_event_id', None)} "
            f"frame_count={self._get_frame_count()} frame_shape={self._get_frame_shape()}",
        )
        self._clear_propagation_overlay_state()
        self._recompute_slider_jump_markers()
        self._sync_saved_mask_overlay_state(reset_history=False)

    def _refresh_host_metrics_for_active_event(self, event_id: str) -> None:
        if not bool(getattr(self, "_host_mode", False)):
            return
        context_provider = getattr(self, "_host_context_provider", None)
        if not callable(context_provider):
            return
        try:
            context = context_provider(str(event_id or ""))
        except Exception as exc:
            self.log_warn("HostMode", f"Failed to refresh metrics for event {event_id}: {exc}")
            return
        if not isinstance(context, dict):
            return
        metrics_settings = context.get("metrics_settings")
        local_metrics_settings = context.get("local_metrics_settings")
        self._apply_host_metrics_settings(
            metrics_settings if isinstance(metrics_settings, dict) else None,
            local_metrics_settings if isinstance(local_metrics_settings, dict) else None,
        )

    def _collect_current_metrics_settings(self) -> dict[str, object]:
        return self._get_window_controller().collect_current_metrics_settings()

    def _apply_host_metrics_settings(self, metrics_settings: dict | None, local_metrics_settings: dict | None = None) -> None:
        self._get_window_controller().apply_host_metrics_settings(metrics_settings, local_metrics_settings)

    def _emit_host_metrics_update(self, reason: str) -> dict[str, object] | None:
        return self._get_window_controller().emit_host_metrics_update(reason)

    def _clear_local_metrics_override(self, reason: str, keys: list[str]) -> dict[str, object] | None:
        return self._get_window_controller().clear_local_metrics_override(reason, keys)

    def _emit_host_global_metrics_update(self, reason: str, metrics_settings: dict[str, object]) -> dict[str, object] | None:
        return self._get_window_controller().emit_host_global_metrics_update(reason, metrics_settings)

    def _autosave_project_after_metrics_commit(self, reason: str) -> dict[str, object]:
        return self._get_window_controller().autosave_project_after_metrics_commit(reason)

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

    def _refresh_metrics_status_labels(self) -> None:
        self._get_window_controller().refresh_metrics_status_labels()

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

    def _get_runtime_controller(self) -> AnalysisRuntimeController:
        controller = getattr(self, "runtime_controller", None)
        if isinstance(controller, AnalysisRuntimeController):
            return controller
        controller = AnalysisRuntimeController(self)
        self.runtime_controller = controller
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
        if not self._segmentation_edits_allowed():
            self._on_segmentation_edit_blocked("clear_frame")
            return False
        changed = bool(self.interaction_controller.clear_current_frame_data())
        self._sync_saved_mask_overlay_state(reset_history=True)
        if changed:
            self._mark_project_dirty("clear_frame")
