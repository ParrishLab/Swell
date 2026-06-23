"""Analysis model runtime services."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from swell.analysis.model.cpu_fallback_predictor import DeterministicCpuFallbackPredictor
    from swell.analysis.model.sam2_frame_cache import SAM2FrameCache, SAM2FrameExportResult, build_sam2_frame_cache_key
    from swell.analysis.model.sam2_runtime import ModelState, SAM2RuntimeService

_EXPORTS = {
    "ModelState": ("swell.analysis.model.sam2_runtime", "ModelState"),
    "SAM2RuntimeService": ("swell.analysis.model.sam2_runtime", "SAM2RuntimeService"),
    "DeterministicCpuFallbackPredictor": (
        "swell.analysis.model.cpu_fallback_predictor",
        "DeterministicCpuFallbackPredictor",
    ),
    "SAM2FrameCache": ("swell.analysis.model.sam2_frame_cache", "SAM2FrameCache"),
    "SAM2FrameExportResult": ("swell.analysis.model.sam2_frame_cache", "SAM2FrameExportResult"),
    "build_sam2_frame_cache_key": ("swell.analysis.model.sam2_frame_cache", "build_sam2_frame_cache_key"),
}

__all__ = [
    "ModelState",
    "SAM2RuntimeService",
    "DeterministicCpuFallbackPredictor",
    "SAM2FrameCache",
    "SAM2FrameExportResult",
    "build_sam2_frame_cache_key",
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
