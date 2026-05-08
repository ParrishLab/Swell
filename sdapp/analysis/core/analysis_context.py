from __future__ import annotations

"""Callback bundle passed to AnalysisController, replacing the 35-parameter constructor."""

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class AnalysisContext:
    """All callbacks required (or optionally provided) by AnalysisController.

    Required callbacks have no default value; optional callbacks default to
    sensible no-ops so callers only need to supply what they actually use.
    """

    # ------------------------------------------------------------------ #
    # Required callbacks                                                   #
    # ------------------------------------------------------------------ #

    get_frame_count: Callable[[], int]
    get_raw_frame: Callable[[int], Any]
    get_masks_cache: Callable[[], Any]
    get_paint_layers: Callable[[], Any]
    get_points: Callable[[], Any]
    get_frame_names: Callable[[], list]
    get_import_source_hint: Callable[[], str]
    get_compose_final_mask_for_frame: Callable[[int], Any]
    get_nonempty_final_mask_frames: Callable[[], set]
    get_frames_per_sec: Callable[[], float]
    get_scale_px_per_mm: Callable[[], Any]
    set_scale_px_per_mm: Callable[[Any], None]
    get_scale_points: Callable[[], Any]
    set_scale_points: Callable[[Any], None]
    get_scale_axis_lock: Callable[[], bool]
    set_scale_axis_lock: Callable[[bool], None]
    get_last_scale_image_path: Callable[[], str]
    set_last_scale_image_path: Callable[[str], None]
    get_roi_mask: Callable[[], Any]
    set_roi_mask: Callable[[Any], None]
    get_roi_points: Callable[[], Any]
    set_roi_points: Callable[[Any], None]
    update_display: Callable[[], None]
    log_info: Callable[..., None]
    log_success: Callable[..., None]

    # ------------------------------------------------------------------ #
    # Optional callbacks (no-op defaults)                                  #
    # ------------------------------------------------------------------ #

    get_manual_scale_px_per_mm: Callable[[], Any] = field(default=lambda: None)
    set_manual_scale_px_per_mm: Callable[[Any], None] = field(default=lambda _v: None)
    apply_host_metrics_settings: Callable[..., Any] | None = None
    clear_local_metrics_override: Callable[..., Any] | None = None
    get_current_image_source_paths: Callable[[], list] = field(default=lambda: [])
    get_current_frame_idx: Callable[[], int] = field(default=lambda: 0)
    on_metrics_settings_changed: Callable[..., None] | None = None
    emit_host_global_metrics_update: Callable[..., Any] = field(default=lambda _r, _m: None)
    autosave_project_after_metrics_commit: Callable[..., Any] = field(
        default=lambda _reason: {"ok": True}
    )
    get_scale_is_local_override: Callable[[], bool] = field(default=lambda: False)
    set_scale_is_local_override: Callable[[bool], None] = field(default=lambda _v: None)
    get_roi_is_local_override: Callable[[], bool] = field(default=lambda: False)
    set_roi_is_local_override: Callable[[bool], None] = field(default=lambda _v: None)
    get_roi_polygons: Callable[[], Any] = field(default=lambda: [])
    set_roi_polygons: Callable[[Any], None] = field(default=lambda _v: None)
    refresh_metrics_status: Callable[[], None] = field(default=lambda: None)
