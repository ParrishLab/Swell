import os
import sys
import threading
import shutil
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
from sdapp.analysis.core.project_autosave import AutosaveSnapshot, ProjectAutosaveManager
from sdapp.analysis.core.project_schema import utc_now_iso
from sdapp.analysis.core.project_store import ProjectStore, cleanup_stale_temp_files
from sdapp.analysis.core.session_state import SessionState
from sdapp.analysis.core import mask_import_workflow
from sdapp.analysis.core.mask_import_dialog import MaskImportDialogService
from sdapp.analysis.core.project_session import ProjectSessionService, SessionSnapshot
from sdapp.analysis.core.analysis_workspace import AnalysisWorkspaceController, WorkspaceUiState
from sdapp.analysis.core.overlay_state import frame_spans, span_length, largest_contiguous_span, compute_propagated_state
from sdapp.analysis.core import overlay_renderer
from sdapp.analysis.core.preview_resize import start_resize_preview as do_start_resize_preview
from sdapp.analysis.core.preview_resize import do_resize_preview as do_preview_resize
from sdapp.analysis.core.preview_resize import stop_resize_preview as do_stop_resize_preview
from sdapp.analysis.core.propagation_progress import PropagationProgressLogger
from sdapp.analysis.core.app_context import AppContext
from sdapp.analysis.core.autosave_naming import derive_autosave_tag
from sdapp.analysis.core import project_workflow
from sdapp.analysis.ui.layout import LayoutBuilder
from sdapp.analysis.ui.theme import apply_theme
from sdapp.analysis.utils.paths import get_app_root, get_resources_root
from sdapp.analysis.model import SAM2RuntimeService
from sdapp.shared.frame_source import EventScopedFrameSource, build_visualization_stack


# Check for imagecodecs
try:
    import imagecodecs  # noqa: F401
except ImportError:
    print("WARNING: imagecodecs not installed. LZW-compressed TIFFs may fail to load.")
    print("Install with: pip install imagecodecs")

# Check for SAM2
try:
    import sam2  # noqa: F401
except ImportError:
    print("CRITICAL WARNING: 'sam2' package not found. Segmentation features will be disabled.")
    print("Please install SAM2: pip install git+https://github.com/facebookresearch/sam2.git")
    print(f"Python interpreter: {sys.executable}")


class PrintLogger:
    def __init__(self, text_widget, root, *, dark_theme: bool = True):
        self.text_widget = text_widget
        self.root = root
        self.dark_theme = bool(dark_theme)
        self._init_tags()

    def _init_tags(self):
        if self.dark_theme:
            colors = {
                "level_default": "#ffffff",
                "level_info": "#9ad0ff",
                "level_success": "#8ee58e",
                "level_warn": "#ffd27f",
                "level_error": "#ff9a9a",
                "level_debug": "#b9b9b9",
            }
        else:
            colors = {
                "level_default": "#1f1f1f",
                "level_info": "#1f4ea8",
                "level_success": "#0f6b0f",
                "level_warn": "#8a5b00",
                "level_error": "#9f1d1d",
                "level_debug": "#555555",
            }
        for tag, color in colors.items():
            self.text_widget.tag_configure(tag, foreground=color)

    def _tag_for_message(self, message):
        stripped = message.lstrip()
        if stripped.startswith("[ERROR]"):
            return "level_error"
        if stripped.startswith("[WARN]"):
            return "level_warn"
        if stripped.startswith("[SUCCESS]"):
            return "level_success"
        if stripped.startswith("[DEBUG]"):
            return "level_debug"
        if stripped.startswith("[INFO]"):
            return "level_info"
        return "level_default"

    def _insert_colored(self, message):
        text = str(message)
        if text == "":
            return
        chunks = text.splitlines(keepends=True)
        if not chunks:
            chunks = [text]
        for chunk in chunks:
            tag = self._tag_for_message(chunk)
            self.text_widget.insert(tk.END, chunk, (tag,))

    def write(self, message):
        if "NSOpenPanel" in message and "method identifier" in message:
            return
        self.root.after(0, self._append_text, message)

    def _append_text(self, message):
        self.text_widget.configure(state="normal")
        self._insert_colored(message)
        self.text_widget.see(tk.END)
        self.text_widget.configure(state="disabled")

    def write_progress(self, message):
        self.root.after(0, self._replace_last_line, message)

    def _replace_last_line(self, message):
        self.text_widget.configure(state="normal")
        try:
            normalized = str(message).rstrip("\r\n")
            self.text_widget.delete("end-2l linestart", "end-1c")
            self._insert_colored(normalized + "\n")
        except tk.TclError:
            # Fallback to append-only behavior if replacement fails.
            fallback = str(message)
            if not fallback.endswith("\n"):
                fallback += "\n"
            self._insert_colored(fallback)
        self.text_widget.see(tk.END)
        self.text_widget.configure(state="disabled")

    def flush(self):
        pass


class SDSegmentationApp(LayoutBuilder, IOActions, SegmentationActions, RenderActions, UndoActions):
    def __init__(self, root, *, menu_builder=None, menu_mode="analysis", host_mode: bool = False):
        self.root = root
        self.root.title("IOS SD Segmenter (Merged Final)")
        self.root.geometry("1400x950")

        self.app_root = str(get_app_root())
        self.resource_root = str(get_resources_root())
        self._is_release_branch = self._detect_release_branch()
        self._app_icon_image = None
        self._apply_runtime_icon()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # State Variables
        self.frames_raw = None
        self.frames_sub = None
        self.frames_sub_viz = None
        self.frame_names = []
        self._selected_import_files = None
        self._browse_mode = "folder"
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

        self.current_frame_idx = 0
        self.seg_state = SegmentationState()
        self.points = self.seg_state.points
        self.selected_point = None
        self.paint_layers = self.seg_state.paint_layers

        # Display State
        self.display_ratio = 1.0
        self.img_offset_x = 0
        self.img_offset_y = 0

        # Cursor State
        self.last_mouse_x = None
        self.last_mouse_y = None
        self.last_img_x = None
        self.last_img_y = None
        self.is_dragging = False

        # Reset analysis state
        self.scale_px_per_mm = None
        self.roi_mask = None
        self.roi_points = []
        self.scale_points = []
        self.analysis_mode = None

        # SAM2 State
        self.predictor = None
        self.inference_state = None
        self.model_ready = False
        self.sam2_runtime = SAM2RuntimeService()
        self.masks_cache = self.seg_state.masks_cache
        self.temp_dir = None

        # Undo/Redo Stacks
        self.undo_stack = []
        self.redo_stack = []
        self.paint_snapshot_before = None
        self.points_snapshot_before = None

        # Background Processing
        self.predictor_lock = threading.Lock()
        self._largest_propagated_span = None
        self._propagated_history_indices = set()
        self.propagated_frame_indices = set()
        self.propagated_frame_spans = []
        self.slider_jump_markers = {}
        self._slider_marker_hit_tolerance_px = 6
        self._slider_marker_bounds = {}
        self._export_range_auto_follow = True
        self._analysis_range_auto_follow = True
        self._programmatic_spinbox_update = False
        self._last_scale_image_path = ""
        self.export_panel_open = tk.BooleanVar(value=False)
        self.analysis_panel_open = tk.BooleanVar(value=False)
        self._controls_hint_logged = False
        self._host_mode = bool(host_mode)
        self._host_analysis_updater = None
        self._host_project_saved_notifier = None
        self._host_sync_result_notifier = None
        self._host_project_saver = None

        # Config
        self.config = AppConfig.load()
        self.project_store = ProjectStore()
        self.project_session_service = ProjectSessionService()
        self.analysis_workspace = AnalysisWorkspaceController(
            session_service=self.project_session_service,
            session_state=self.session_state,
            seg_state=self.seg_state,
        )
        self.mask_import_dialog = MaskImportDialogService()
        autosave_dir = Path(self.app_root) / "autosaves"
        self._autosave_dir = autosave_dir
        self.autosave_manager = ProjectAutosaveManager(
            snapshot_callable=self._build_autosave_snapshot,
            write_callable=self._write_autosave_snapshot,
            autosave_dir=autosave_dir,
            max_slots=3,
            debounce_sec=2.5,
            name_tag_provider=self._autosave_name_tag,
            dispatch_to_main=lambda fn: self.root.after(0, fn),
            on_error=self._on_autosave_error,
        )

        # UI Layout
        # Tk ttk styles are process-global. In integrated host mode, applying
        # the analysis dark theme would restyle the host window as well.
        if not self._host_mode:
            apply_theme(self.root)
        self.setup_ui()
        if menu_builder is not None:
            self._menu_bar = menu_builder(self.root, self, mode=menu_mode, host_mode=self._host_mode)
        else:
            self._setup_project_menu()
        self.root.bind("<FocusIn>", self._ensure_menu_bar_bound, add="+")
        self.btn_run.configure(state="disabled")
        self._validate_assets()

        self.logger = PrintLogger(self.log_text, self.root, dark_theme=not self._host_mode)
        sys.stdout = self.logger
        sys.stderr = self.logger
        self._cleanup_stale_autosave_temps()
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
            set_status=lambda text, color: self.lbl_status.configure(text=text, foreground=color),
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
            get_output_folder=lambda: self.entry_output.get(),
            get_export_range=lambda: (int(self.spin_export_start.get()) - 1, int(self.spin_export_end.get()) - 1),
            get_analysis_range=lambda: (
                int(self.spin_analysis_start.get()) - 1,
                int(self.spin_analysis_end.get()) - 1,
            ),
            get_seconds_per_frame=lambda: float(self.seconds_per_frame_var.get()),
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
        self._set_data_controls_enabled(False)
        self.inference_manager.start()
        # Prompt only after controllers/workers are initialized; recovery may reset state.
        self._maybe_prompt_autosave_recovery()

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

    @property
    def _analysis_range_auto_follow(self):
        self._ensure_session_state()
        return self.session_state.analysis_range_auto_follow

    @_analysis_range_auto_follow.setter
    def _analysis_range_auto_follow(self, value):
        self._ensure_session_state()
        self.session_state.analysis_range_auto_follow = bool(value)

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

    # ========================================================================
    # Helpers
    # ========================================================================

    def _set_busy(self, is_busy, status_text, color):
        self.lbl_status.configure(text=status_text, foreground=color)
        self.btn_import.configure(state="disabled" if is_busy else "normal")
        if is_busy:
            self.btn_run.configure(state="disabled")
        else:
            self.btn_run.configure(state="normal" if self.model_ready else "disabled")

    def _run_thread(self, target):
        threading.Thread(target=target, daemon=True).start()

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

    def _on_analysis_range_user_edit(self, event=None):
        if not getattr(self, "_programmatic_spinbox_update", False):
            self._analysis_range_auto_follow = False

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
                    "Import image sequence to enable tools, propagation, export, and analysis.",
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
        self.btn_analysis_toggle.configure(text=f"Analysis {'▾' if is_open else '▸'}")
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
        print(f"[{lvl}]{ctx} {message}")

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
        model_path = self.entry_model.get().strip()
        if model_path and not os.path.isabs(model_path):
            model_path = os.path.join(resource_root, model_path)

        missing = []
        if not model_path or not os.path.exists(model_path):
            missing.append("model weights")

        configs_root = os.path.join(resource_root, "configs")
        if not os.path.exists(configs_root):
            missing.append("configs folder")

        if missing:
            msg = "Missing " + ", ".join(missing) + ". Place assets in sdapp/resources/models and sdapp/resources/configs."
            self.log_warn("App", msg)
            self.lbl_status.configure(text="Status: Assets Missing", foreground="orange")

    def load_model_from_menu(self):
        self.log_info("Model", "Loading SAM2 model...")
        self._run_thread(self._init_sam2_background)

    def validate_assets_from_menu(self):
        self._validate_assets()

    def _reset_model_state(self):
        # Stop background work and clear queued inference jobs.
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
        self._analysis_range_auto_follow = True
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
        # Only reset after a successful load to avoid losing work on failed import
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
        self._run_thread(self._init_sam2_background)
        self._mark_project_dirty("import_stack")

    def on_right_canvas_click(self, event):
        # Analysis interactions are handled in dedicated pop-up windows.
        return

    def on_right_canvas_double_click(self, event):
        # Analysis interactions are handled in dedicated pop-up windows.
        return

    def start_scale_selection(self):
        self.analysis_controller.start_scale_selection()

    def start_roi_selection(self):
        self.analysis_controller.start_roi_selection()

    def run_metrics_analysis(self):
        self.analysis_controller.run_metrics_analysis()

    def _setup_project_menu(self):
        project_workflow.setup_project_menu(self)

    def _mark_project_dirty(self, reason=""):
        self.project_dirty = True
        if (
            not bool(getattr(self, "_host_mode", False))
            and self._has_loaded_stack()
            and hasattr(self, "autosave_manager")
            and self.autosave_manager is not None
        ):
            self.autosave_manager.schedule(reason=reason)

    def _build_autosave_snapshot(self):
        if not self._has_loaded_stack():
            return None
        state, images_manifest, roi_data, event_payloads = self._build_project_payload()
        return AutosaveSnapshot(
            project_state=state,
            images_manifest=images_manifest,
            roi_data=roi_data,
            event_payloads=event_payloads,
            embed_images=bool(self._project_embed_images),
        )

    def _write_autosave_snapshot(self, snapshot: AutosaveSnapshot, target_path: Path):
        self.project_store.save(
            target_path=target_path,
            project_state=snapshot.project_state,
            images_manifest=snapshot.images_manifest,
            roi_data=snapshot.roi_data,
            event_payloads=snapshot.event_payloads,
            embed_images=bool(snapshot.embed_images),
        )
        self._emit_host_sync(reason="autosave")
        self.log_debug("Autosave", f"Wrote autosave: {target_path.name}")

    def _on_autosave_error(self, exc: Exception, context: str):
        self.log_warn("Autosave", f"Autosave failed ({context}): {exc}")
        if hasattr(self, "lbl_status"):
            try:
                self.lbl_status.configure(text="Status: Autosave warning (see log)", foreground="orange")
            except Exception:
                pass

    def _cleanup_stale_autosave_temps(self):
        removed = cleanup_stale_temp_files(self._autosave_dir, pattern="*.sdproj.tmp", older_than_sec=86400)
        if removed > 0:
            self.log_info("Autosave", f"Removed {removed} stale autosave temp file(s).")

    def _autosave_name_tag(self):
        entry = ""
        if hasattr(self, "entry_input"):
            try:
                entry = str(self.entry_input.get() or "").strip()
            except Exception:
                entry = ""
        return derive_autosave_tag(self._current_image_source_paths, entry)

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
                analysis_start=int(self.spin_analysis_start.get()) if hasattr(self, "spin_analysis_start") else 1,
                analysis_end=int(self.spin_analysis_end.get()) if hasattr(self, "spin_analysis_end") else frame_count,
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
        if not hasattr(self, "analysis_workspace") or self.analysis_workspace is None:
            return None
        if callable(getattr(self, "_host_analysis_updater", None)):
            payload = self.analysis_workspace.export_active_event_analysis_payload()
            if payload is not None:
                try:
                    result = self._host_analysis_updater(payload)
                    if isinstance(result, dict):
                        if bool(result.get("ok")):
                            self.log_debug("HostSync", f"Applied direct host update on {reason}.")
                        else:
                            code = str(result.get("code", "PAYLOAD_INVALID"))
                            message = str(result.get("message", "Host rejected update."))
                            self.log_warn("HostSync", f"Host rejected update [{code}]: {message}")
                            try:
                                self.lbl_status.configure(text=f"Status: Host rejected sync ({code})", foreground="orange")
                            except Exception:
                                pass
                        notifier = getattr(self, "_host_sync_result_notifier", None)
                        if callable(notifier):
                            try:
                                notifier(result)
                            except Exception:
                                pass
                    else:
                        self.log_debug("HostSync", f"Applied direct host update on {reason}.")
                except Exception as exc:
                    self.log_warn("HostSync", f"Direct host update failed: {exc}")
            return payload
        payload = self.analysis_workspace.emit_host_sync(ui_hints=self._host_ui_hints())
        if payload is not None:
            self.log_debug("HostSync", f"Emitted host sync on {reason}.")
        return payload

    def _save_project_to_path(self, target_path, is_autosave=False):
        project_workflow.save_project_to_path(self, target_path, is_autosave=is_autosave)

    def save_project(self):
        return project_workflow.save_project(self)

    def save_project_as(self):
        return project_workflow.save_project_as(self)

    def convert_to_project(self):
        return project_workflow.convert_to_project(self)

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

    def open_project(self):
        return project_workflow.open_project(self)

    def open_from_host_context(
        self,
        context: dict,
        frame_source=None,
        on_analysis_update=None,
        on_project_saved=None,
        on_sync_result=None,
        on_host_project_save=None,
        sync_emitter=None,
    ):
        self._ensure_analysis_workspace()
        self._host_mode = True
        self._host_analysis_updater = on_analysis_update
        self._host_project_saved_notifier = on_project_saved
        self._host_sync_result_notifier = on_sync_result
        self._host_project_saver = on_host_project_save
        scoped_source = frame_source
        if frame_source is not None:
            event = dict(context.get("event", {})) if isinstance(context, dict) else {}
            flags = dict(event.get("flags", {})) if isinstance(event.get("flags"), dict) else {}
            scope_start = flags.get("analysis_scope_start_idx", event.get("start_idx"))
            scope_end = flags.get("analysis_scope_end_idx", event.get("end_idx"))
            if scope_start is not None and scope_end is not None:
                scoped_source = EventScopedFrameSource(frame_source, int(scope_start), int(scope_end))
            self.frame_source = scoped_source
        if self.frame_source is not None:
            self.analysis_workspace.bind_frame_source(self.frame_source)
        result = self.analysis_workspace.open_from_host_event_context(
            context,
            frame_source=self.frame_source,
            sync_emitter=sync_emitter,
        )
        if not bool(result.get("ok")):
            return result
        if self.frame_source is not None:
            self._prepare_host_mode_buffers(self.frame_source)
            if hasattr(self, "app_context") and self.app_context is not None:
                self.app_context.frame_source = self.frame_source
        if hasattr(self, "slider") and hasattr(self, "canvas_left"):
            self._finalize_load_ui()
            self.display_ratio = 1.0
            self.img_offset_x = 0
            self.img_offset_y = 0
            self.root.after_idle(lambda: self.update_display(update_preview=True))
            self.root.after(120, lambda: self.update_display(update_preview=True))
            self.log_info("HostMode", "Host direct workspace initialized.")
            try:
                self.lbl_status.configure(text="Status: Host-bound mode (project managed by SD ID)", foreground="gray")
            except Exception:
                pass
        model_path = ""
        try:
            model_path = str(self.entry_model.get() or "").strip()
        except Exception:
            model_path = ""
        if model_path:
            self.log_info("HostMode", "Initializing SAM2 for host-driven workspace...")
            self._run_thread(self._init_sam2_background)
        else:
            self.log_warn("HostMode", "No SAM2 model configured; model tools will remain disabled.")
        return result

    def open_from_host_handoff(self, payload: dict, frame_source=None, sync_emitter=None):
        self._ensure_analysis_workspace()
        self._host_mode = True
        self._host_analysis_updater = None
        self._host_project_saved_notifier = None
        self._host_sync_result_notifier = None
        self._host_project_saver = None
        scoped_source = frame_source
        if frame_source is not None:
            event = dict(payload.get("event", {})) if isinstance(payload, dict) else {}
            flags = dict(event.get("flags", {})) if isinstance(event.get("flags"), dict) else {}
            scope_start = flags.get("analysis_scope_start_idx", event.get("start_idx"))
            scope_end = flags.get("analysis_scope_end_idx", event.get("end_idx"))
            if scope_start is not None and scope_end is not None:
                scoped_source = EventScopedFrameSource(frame_source, int(scope_start), int(scope_end))
            self.frame_source = scoped_source
        if self.frame_source is not None:
            self.analysis_workspace.bind_frame_source(self.frame_source)
        result = self.analysis_workspace.open_from_handoff_payload(
            payload,
            frame_source=self.frame_source,
            sync_emitter=sync_emitter,
        )
        if not bool(result.get("ok")):
            return result

        if self.frame_source is not None:
            self._prepare_host_mode_buffers(self.frame_source)
            if hasattr(self, "app_context") and self.app_context is not None:
                self.app_context.frame_source = self.frame_source
        if hasattr(self, "slider") and hasattr(self, "canvas_left"):
            self._finalize_load_ui()
            self.display_ratio = 1.0
            self.img_offset_x = 0
            self.img_offset_y = 0
            self.root.after_idle(lambda: self.update_display(update_preview=True))
            self.root.after(120, lambda: self.update_display(update_preview=True))
            self.log_info("HostMode", "Host-driven analysis workspace initialized.")
        model_path = ""
        try:
            model_path = str(self.entry_model.get() or "").strip()
        except Exception:
            model_path = ""
        if model_path:
            self.log_info("HostMode", "Initializing SAM2 for host-driven workspace...")
            self._run_thread(self._init_sam2_background)
        else:
            self.log_warn("HostMode", "No SAM2 model configured; model tools will remain disabled.")
        return result

    def _shutdown_model_resources(self):
        self.model_ready = False
        self.predictor = None
        self.inference_state = None
        if hasattr(self, "sam2_runtime") and self.sam2_runtime is not None:
            try:
                self.sam2_runtime.shutdown()
            except Exception:
                pass
        try:
            if self.temp_dir and os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception:
            pass
        try:
            import torch

            if torch.backends.mps.is_available():
                torch.mps.empty_cache()
            elif torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    def _prepare_host_mode_buffers(self, frame_source):
        frame_count = int(getattr(frame_source, "frame_count", 0) or 0)
        if frame_count <= 0:
            self.frames_raw = None
            self.frames_sub = None
            self.frames_sub_viz = None
            self.frame_names = []
            self._current_image_source_paths = []
            return

        baseline_count = 30
        if hasattr(self, "spin_baseline"):
            try:
                baseline_count = int(self.spin_baseline.get())
            except Exception:
                baseline_count = 30
        raw_frames, frames_sub, frames_viz = build_visualization_stack(
            frame_source,
            baseline_frames=int(baseline_count),
        )
        self.frames_raw = raw_frames
        self.frames_sub = frames_sub
        self.frames_sub_viz = frames_viz
        self.frame_names = list(getattr(frame_source, "frame_names", []))
        self._current_image_source_paths = list(getattr(frame_source, "source_paths", []))

    def recover_autosave(self):
        return project_workflow.recover_autosave(self)

    def _maybe_prompt_autosave_recovery(self):
        if bool(getattr(self, "_host_mode", False)):
            return None
        return project_workflow.maybe_prompt_autosave_recovery(self)

    def new_project(self):
        return project_workflow.new_project(self)

    # ========================================================================
    # CLEANUP LOGIC
    # ========================================================================

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

    # ========================================================================
    # PREVIEW RESIZE
    # ========================================================================

    def start_resize_preview(self, event):
        return do_start_resize_preview(self, event)

    def do_resize_preview(self, event):
        return do_preview_resize(self, event)

    def stop_resize_preview(self, event):
        return do_stop_resize_preview(self, event)

    # ========================================================================
    # CURSOR VISUALIZATION
    # ========================================================================

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

    # ========================================================================
    # KEYBOARD COMMANDS
    # ========================================================================

    def on_nav_left(self, event=None):
        self.interaction_controller.on_nav_left(event)

    def on_nav_right(self, event=None):
        self.interaction_controller.on_nav_right(event)

    def on_browse_primary(self):
        self.browse_input_primary(getattr(self, "_browse_mode", "folder"))

    def on_browse_select_folder(self):
        self._browse_mode = "folder"
        self.browse_input_folder()

    def on_browse_select_files(self):
        self._browse_mode = "files"
        self.browse_input_files()

    def on_browse_model(self):
        resource_root = Path(getattr(self, "resource_root", self.app_root))
        current_text = ""
        try:
            current_text = str(self.entry_model.get() or "").strip()
        except Exception:
            current_text = ""

        current_abs = ""
        if current_text:
            p = Path(current_text)
            if not p.is_absolute():
                p = resource_root / p
            current_abs = str(p.resolve())

        initialdir = str((resource_root / "models").resolve())
        if current_text:
            try:
                p = Path(current_text)
                if not p.is_absolute():
                    p = resource_root / p
                if p.exists():
                    initialdir = str((p.parent if p.is_file() else p).resolve())
            except Exception:
                pass

        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Select SAM2 Model",
            initialdir=initialdir,
            filetypes=[
                ("PyTorch model", "*.pt *.pth"),
                ("All files", "*.*"),
            ],
        )
        if not selected:
            return

        selected_abs = str(Path(selected).resolve())
        if selected_abs == current_abs:
            self.log_info("Model", "Selected model is unchanged; skipping reload.")
            return

        self.entry_model.delete(0, tk.END)
        self.entry_model.insert(0, selected_abs)
        self.log_info("Model", f"Model changed to: {Path(selected_abs).name}. Reloading...")
        self._run_thread(self._init_sam2_background)

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

    # ========================================================================
    # MOUSE INTERACTION
    # ========================================================================

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

    # ========================================================================
    # EXPORT RESULTS (BINARY)
    # ========================================================================

    def export_results(self):
        if not self.masks_cache and not self.paint_layers:
            messagebox.showwarning("No Masks", "Please generate masks first.")
            return

        try:
            output_folder = self.entry_output.get()
            if output_folder and not os.path.isabs(output_folder):
                output_folder = os.path.join(self.app_root, output_folder)
            mask_dir = os.path.join(output_folder, "binary_masks")
            if not os.path.exists(mask_dir):
                os.makedirs(mask_dir)

            self.log_info("Export", "Started binary mask export.")

            total_frames = self._get_frame_count()
            export_start, export_end = self._parse_clamped_frame_range(
                self.spin_export_start,
                self.spin_export_end,
                total_frames,
            )

            self.log_info("Export", f"Exporting frames {export_start + 1}-{export_end + 1}.")

            for frame_idx in range(export_start, export_end + 1):
                mask = self._compose_final_mask_for_frame(frame_idx)
                if mask is None:
                    mask = np.zeros(self._get_frame_shape(), dtype=bool)

                original_name = self.frame_names[frame_idx]
                output_name = f"Mask_{original_name}"
                output_path = os.path.join(mask_dir, output_name)

                binary_output = mask.astype(np.uint8) * 255
                cv2.imwrite(output_path, binary_output)
            exported_count = (export_end - export_start + 1) if export_end >= export_start else 0
            self.log_success(
                "Export",
                f"Completed binary mask export ({exported_count} frames). Output: {output_folder}",
            )
            messagebox.showinfo("Success", "Export Complete! Binary masks saved.")

        except Exception as e:
            self.log_error("Export", f"Export failed: {e}")
            import traceback

            traceback.print_exc()

    # ========================================================================
    # MISC
    # ========================================================================

    def clear_current_frame_data(self):
        self.interaction_controller.clear_current_frame_data()
        self._mark_project_dirty("clear_frame")


def main():
    os.chdir(get_app_root())
    root = tk.Tk()
    app = SDSegmentationApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
