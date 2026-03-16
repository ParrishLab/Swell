from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class AnalysisModelState:
    predictor: Any = None
    inference_state: Any = None
    model_ready: bool = False
    temp_dir: str | None = None


@dataclass
class HostModeState:
    host_mode: bool = True
    analysis_updater: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None
    project_saved_notifier: Callable[[str], None] | None = None
    sync_result_notifier: Callable[[dict[str, Any]], None] | None = None
    project_saver: Callable[..., Any] | None = None
    project_path_provider: Callable[[], str | None] | None = None
    log_notifier: Callable[[str, str, str], None] | None = None
    metrics_updater: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None
    processing_options: dict[str, Any] | None = None
    saved_project_masks_by_event: dict[str, bool] = field(default_factory=dict)
    suppress_metrics_emit: bool = False
    buffer_generation: int = 0
    buffer_cache_key: tuple[Any, ...] | None = None
    buffer_sync_limit: int = 240


@dataclass
class AnalysisRuntimeState:
    loading_task_count: int = 0
