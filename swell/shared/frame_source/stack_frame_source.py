from __future__ import annotations

import numpy as np


class StackReaderFrameSource:
    """Lazy stack-backed frame source adapter for host and analysis windows."""

    def __init__(self, reader) -> None:
        self._reader = reader
        self._frame_names_cache: list[str] | None = None
        self._source_paths_cache: list[str] | None = None
        self._frame_shape_cache: tuple[int, int] | None = None

    @property
    def frame_count(self) -> int:
        return int(self._reader.get_frame_count())

    @property
    def frame_shape(self) -> tuple[int, int]:
        if self._frame_shape_cache is not None:
            return self._frame_shape_cache
        info = self._reader.get_stack_info()
        if info is not None:
            self._frame_shape_cache = (int(info.frame_height), int(info.frame_width))
            return self._frame_shape_cache
        first = np.asarray(self._reader.read_frame(0, use_cache=True))
        if first.ndim == 3 and first.shape[2] in (3, 4):
            first = first[:, :, :3].mean(axis=2)
        self._frame_shape_cache = (int(first.shape[0]), int(first.shape[1]))
        return self._frame_shape_cache

    @property
    def frame_names(self) -> list[str]:
        if self._frame_names_cache is None:
            self._frame_names_cache = [self._reader.get_frame_name(i) for i in range(self.frame_count)]
        return list(self._frame_names_cache)

    @property
    def source_paths(self) -> list[str]:
        if self._source_paths_cache is None:
            self._source_paths_cache = [str(self._reader.get_frame_ref(i).source_path) for i in range(self.frame_count)]
        return list(self._source_paths_cache)

    @property
    def capabilities(self) -> dict[str, bool]:
        return {"raw": True, "subtracted": False, "visual": False}

    def get_raw_frame(self, idx: int) -> np.ndarray:
        frame = np.asarray(self._reader.read_frame(int(idx), use_cache=True))
        if frame.ndim == 3 and frame.shape[2] in (3, 4):
            frame = frame[:, :, :3].mean(axis=2)
        return frame.astype(np.float32, copy=False)

    def get_subtracted_frame(self, idx: int) -> np.ndarray | None:
        raise NotImplementedError("Subtracted frame source is not wired in host seam prep.")

    def get_visual_frame(self, idx: int) -> np.ndarray | None:
        raise NotImplementedError("Visual frame source is not wired in host seam prep.")
