from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from swell.shared.services.analysis_window_manager import (
        AnalysisWindowCloseResult,
        AnalysisWindowManager,
        AnalysisWindowRef,
    )
    from swell.shared.services.checkpoint_runtime_service import (
        CheckpointDescriptor,
        CheckpointResolution,
        CheckpointRuntimeService,
        MODEL_CHECKPOINT_METADATA_KEY,
        managed_models_dir,
    )
    from swell.shared.services.instance_bridge import SingleInstanceBridge
    from swell.shared.services.metrics_settings_resolver import MetricsSettingsResolver
    from swell.shared.services.unified_project_service import UnifiedProjectService

_EXPORTS = {
    "AnalysisWindowCloseResult": ("swell.shared.services.analysis_window_manager", "AnalysisWindowCloseResult"),
    "AnalysisWindowManager": ("swell.shared.services.analysis_window_manager", "AnalysisWindowManager"),
    "AnalysisWindowRef": ("swell.shared.services.analysis_window_manager", "AnalysisWindowRef"),
    "CheckpointDescriptor": ("swell.shared.services.checkpoint_runtime_service", "CheckpointDescriptor"),
    "CheckpointResolution": ("swell.shared.services.checkpoint_runtime_service", "CheckpointResolution"),
    "CheckpointRuntimeService": ("swell.shared.services.checkpoint_runtime_service", "CheckpointRuntimeService"),
    "MODEL_CHECKPOINT_METADATA_KEY": ("swell.shared.services.checkpoint_runtime_service", "MODEL_CHECKPOINT_METADATA_KEY"),
    "managed_models_dir": ("swell.shared.services.checkpoint_runtime_service", "managed_models_dir"),
    "SingleInstanceBridge": ("swell.shared.services.instance_bridge", "SingleInstanceBridge"),
    "MetricsSettingsResolver": ("swell.shared.services.metrics_settings_resolver", "MetricsSettingsResolver"),
    "UnifiedProjectService": ("swell.shared.services.unified_project_service", "UnifiedProjectService"),
}

__all__ = [
    "AnalysisWindowCloseResult",
    "AnalysisWindowManager",
    "AnalysisWindowRef",
    "SingleInstanceBridge",
    "MetricsSettingsResolver",
    "UnifiedProjectService",
    "CheckpointDescriptor",
    "CheckpointResolution",
    "CheckpointRuntimeService",
    "MODEL_CHECKPOINT_METADATA_KEY",
    "managed_models_dir",
]


def __getattr__(name: str):
    target = _EXPORTS.get(str(name))
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    module = __import__(module_name, fromlist=[attr_name])
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
