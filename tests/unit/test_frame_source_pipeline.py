from __future__ import annotations

import numpy as np

from sdapp.shared.frame_source import EventScopedFrameSource, build_visualization_stack


class DummyFrameSource:
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
        return [f"f{i}.tif" for i in range(self.frame_count)]

    @property
    def source_paths(self) -> list[str]:
        return [f"/tmp/f{i}.tif" for i in range(self.frame_count)]

    @property
    def capabilities(self) -> dict[str, bool]:
        return {"raw": True, "subtracted": False, "visual": False}

    def get_raw_frame(self, idx: int) -> np.ndarray:
        return self._frames[int(idx)]

    def get_subtracted_frame(self, idx: int):
        return None

    def get_visual_frame(self, idx: int):
        return None


def test_event_scoped_source_maps_indices() -> None:
    src = DummyFrameSource([np.full((8, 8), i, dtype=np.float32) for i in range(6)])
    scoped = EventScopedFrameSource(src, start_idx=2, end_idx=4)
    assert scoped.frame_count == 3
    assert scoped.frame_names == ["f2.tif", "f3.tif", "f4.tif"]
    assert int(scoped.get_raw_frame(0)[0, 0]) == 2
    assert int(scoped.get_raw_frame(2)[0, 0]) == 4


def test_shared_visualization_stack_pipeline_shapes() -> None:
    frames = [np.random.default_rng(0).normal(100, 5, size=(16, 16)).astype(np.float32) for _ in range(10)]
    src = DummyFrameSource(frames)
    raw, sub, viz = build_visualization_stack(src, baseline_frames=4)
    assert raw.shape == (10, 16, 16)
    assert sub.shape == (10, 16, 16)
    assert viz.shape == (10, 16, 16)
    assert viz.dtype == np.uint8
