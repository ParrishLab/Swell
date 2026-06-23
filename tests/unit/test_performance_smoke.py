from __future__ import annotations

import time

import numpy as np

from swell.analysis.app import SwellAnalysisApp
from swell.shared.frame_source import build_visualization_stack


class _DummyFrameSource:
    def __init__(self, frames: list[np.ndarray]) -> None:
        self._frames = [np.asarray(f, dtype=np.float32) for f in frames]

    @property
    def frame_count(self) -> int:
        return len(self._frames)

    @property
    def frame_shape(self) -> tuple[int, int]:
        return tuple(self._frames[0].shape[:2]) if self._frames else (0, 0)

    @property
    def frame_names(self) -> list[str]:
        return [f"f{i:04d}.tif" for i in range(self.frame_count)]

    @property
    def source_paths(self) -> list[str]:
        return [f"/tmp/f{i:04d}.tif" for i in range(self.frame_count)]

    def get_raw_frame(self, idx: int) -> np.ndarray:
        return self._frames[int(idx)]

    def get_subtracted_frame(self, idx: int):
        return None

    def get_visual_frame(self, idx: int):
        return None


def test_visualization_stack_smoke_latency() -> None:
    rng = np.random.default_rng(123)
    frames = [rng.normal(100, 6, size=(64, 64)).astype(np.float32) for _ in range(40)]
    src = _DummyFrameSource(frames)
    start = time.perf_counter()
    raw, sub, viz = build_visualization_stack(src, baseline_frames=10)
    elapsed = time.perf_counter() - start
    assert raw.shape == (40, 64, 64)
    assert sub.shape == (40, 64, 64)
    assert viz.shape == (40, 64, 64)
    assert elapsed < 3.0


def test_analysis_prepare_buffers_smoke_latency() -> None:
    rng = np.random.default_rng(7)
    frames = [rng.normal(120, 8, size=(48, 48)).astype(np.float32) for _ in range(50)]
    src = _DummyFrameSource(frames)

    app = SwellAnalysisApp.__new__(SwellAnalysisApp)
    app._host_mode = False
    app._host_processing_options = None
    app._host_buffer_sync_limit = 200
    app._host_buffer_cache_key = None
    app.frames_sub_viz = None
    app.log_info = lambda *_args, **_kwargs: None

    start = time.perf_counter()
    ready = app._prepare_host_mode_buffers(src)
    elapsed = time.perf_counter() - start

    assert ready is True
    assert app.frames_raw is not None
    assert app.frames_sub is not None
    assert app.frames_sub_viz is not None
    assert len(app.frame_names) == 50
    assert elapsed < 3.0
