from __future__ import annotations

from collections import OrderedDict
from threading import Lock

import numpy as np

from sdapp.shared.frame_source.preprocessing import (
    VisualizationStats,
    compute_visualization_stats,
    render_visualization_frame,
)
from sdapp.shared.frame_source.protocols import FrameSource


class PreparedFrameSource:
    """Lazy frame-source adapter that exposes shared raw/subtracted/visual frames."""

    def __init__(
        self,
        base_source: FrameSource,
        *,
        baseline_frames: int = 30,
        apply_horizontal_bar_denoise: bool = False,
        apply_smoothing: bool = True,
        apply_baseline_subtraction: bool = True,
        apply_global_normalization: bool = True,
        apply_stabilization: bool = False,
        stats: VisualizationStats | None = None,
        frame_cache_max: int = 24,
    ) -> None:
        self._base_source = base_source
        self._baseline_frames = max(1, int(baseline_frames))
        self._apply_horizontal_bar_denoise = bool(apply_horizontal_bar_denoise)
        self._apply_smoothing = bool(apply_smoothing)
        self._apply_baseline_subtraction = bool(apply_baseline_subtraction)
        self._apply_global_normalization = bool(apply_global_normalization)
        self._apply_stabilization = bool(apply_stabilization)
        self._frame_cache_max = max(4, int(frame_cache_max))
        self._stats = stats
        self._frame_cache: OrderedDict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = OrderedDict()
        self._lock = Lock()

    @property
    def frame_count(self) -> int:
        return int(getattr(self._base_source, "frame_count", 0) or 0)

    @property
    def frame_shape(self) -> tuple[int, int]:
        return tuple(int(v) for v in tuple(getattr(self._base_source, "frame_shape", (0, 0)))[:2])

    @property
    def frame_names(self) -> list[str]:
        return list(getattr(self._base_source, "frame_names", []) or [])

    @property
    def source_paths(self) -> list[str]:
        return list(getattr(self._base_source, "source_paths", []) or [])

    @property
    def capabilities(self) -> dict[str, bool]:
        return {"raw": True, "subtracted": True, "visual": True}

    def _validate_index(self, idx: int) -> int:
        idx = int(idx)
        if idx < 0 or idx >= self.frame_count:
            raise IndexError(f"Frame index out of range: {idx}")
        return idx

    def stats(self, *, should_cancel=None, progress_callback=None) -> VisualizationStats:
        with self._lock:
            if self._stats is not None:
                return self._stats
        stats = compute_visualization_stats(
            self._base_source,
            baseline_frames=self._baseline_frames,
            apply_horizontal_bar_denoise=self._apply_horizontal_bar_denoise,
            apply_smoothing=self._apply_smoothing,
            apply_baseline_subtraction=self._apply_baseline_subtraction,
            apply_global_normalization=self._apply_global_normalization,
            apply_stabilization=self._apply_stabilization,
            should_cancel=should_cancel,
            progress_callback=progress_callback,
        )
        with self._lock:
            if self._stats is None:
                self._stats = stats
            return self._stats

    def prepare(self, *, should_cancel=None, progress_callback=None) -> VisualizationStats:
        return self.stats(should_cancel=should_cancel, progress_callback=progress_callback)

    def _cache_put(self, idx: int, value: tuple[np.ndarray, np.ndarray, np.ndarray]) -> None:
        self._frame_cache[idx] = value
        self._frame_cache.move_to_end(idx)
        while len(self._frame_cache) > self._frame_cache_max:
            self._frame_cache.popitem(last=False)

    def _prepared_frame(self, idx: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        idx = self._validate_index(idx)
        with self._lock:
            cached = self._frame_cache.get(idx)
            if cached is not None:
                self._frame_cache.move_to_end(idx)
                return cached
        prepared = render_visualization_frame(
            self._base_source,
            idx,
            stats=self.stats(),
            baseline_frames=self._baseline_frames,
            apply_horizontal_bar_denoise=self._apply_horizontal_bar_denoise,
            apply_smoothing=self._apply_smoothing,
            apply_baseline_subtraction=self._apply_baseline_subtraction,
            apply_global_normalization=self._apply_global_normalization,
            apply_stabilization=self._apply_stabilization,
        )
        with self._lock:
            cached = self._frame_cache.get(idx)
            if cached is not None:
                self._frame_cache.move_to_end(idx)
                return cached
            self._cache_put(idx, prepared)
            return prepared

    def prewarm(self, indices: list[int], generation: int | None = None, should_continue=None) -> None:
        del generation  # Kept for compatibility with existing callers/tests.
        total = int(self.frame_count)
        if total <= 0:
            return
        for raw_idx in list(indices or []):
            if callable(should_continue) and not bool(should_continue()):
                return
            try:
                idx = self._validate_index(int(raw_idx))
            except Exception:
                continue
            self._prepared_frame(idx)
            if callable(should_continue) and not bool(should_continue()):
                return

    def get_raw_frame(self, idx: int) -> np.ndarray:
        return self._prepared_frame(idx)[0]

    def get_subtracted_frame(self, idx: int) -> np.ndarray:
        return self._prepared_frame(idx)[1]

    def get_visual_frame(self, idx: int) -> np.ndarray:
        return self._prepared_frame(idx)[2]
