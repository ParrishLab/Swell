from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class AnalysisModelState:
    predictor: Any = None
    inference_state: Any = None
    model_ready: bool = False
    temp_dir: str | None = None
    checkpoint_metadata: dict[str, Any] | None = None
    manual_model_override: str | None = None


@dataclass
class HostModeState:
    host_mode: bool = False
    analysis_updater: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None
    project_saved_notifier: Callable[[str], None] | None = None
    sync_result_notifier: Callable[[dict[str, Any]], None] | None = None
    project_saver: Callable[..., Any] | None = None
    project_path_provider: Callable[[], str | None] | None = None
    log_notifier: Callable[[str, str, str], None] | None = None
    metrics_updater: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None
    global_metrics_updater: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None
    checkpoint_updater: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None
    open_model_manager: Callable[[], None] | None = None
    processing_options: dict[str, Any] | None = None
    project_metadata: dict[str, Any] | None = None
    saved_project_masks_by_event: dict[str, bool] = field(default_factory=dict)
    suppress_metrics_emit: bool = False
    buffer_generation: int = 0
    buffer_cache_key: tuple[Any, ...] | None = None
    buffer_sync_limit: int = 240


@dataclass
class AnalysisRuntimeState:
    loading_task_count: int = 0


@dataclass
class AnalysisFrameState:
    raw_frames: Any = None
    subtracted_frames: Any = None
    visual_frames: Any = None
    frame_names: list[str] = field(default_factory=list)
    selected_import_files: list[Any] | None = None
    current_image_source_paths: list[str] = field(default_factory=list)
    image_manifest_entries: list[dict[str, Any]] = field(default_factory=list)
    frame_source: Any = None
