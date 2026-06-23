from __future__ import annotations

import cv2
import numpy as np


class DownsampledFrameSource:
    """Wraps any FrameSource and returns frames downsampled by a fixed scale factor.

    Used to speed up stats computation for preview purposes; the resulting
    VisualizationStats can be upsampled back to full resolution before use.
    """

    def __init__(self, base_source, scale: float = 0.25) -> None:
        self._base = base_source
        self._scale = max(0.01, min(1.0, float(scale)))
        base_shape = tuple(int(v) for v in tuple(getattr(base_source, "frame_shape", (0, 0)))[:2])
        h, w = base_shape
        self._frame_shape: tuple[int, int] = (max(1, int(round(h * self._scale))), max(1, int(round(w * self._scale))))

    @property
    def frame_count(self) -> int:
        return int(getattr(self._base, "frame_count", 0) or 0)

    @property
    def frame_shape(self) -> tuple[int, int]:
        return self._frame_shape

    @property
    def frame_names(self) -> list[str]:
        return list(getattr(self._base, "frame_names", []) or [])

    @property
    def source_paths(self) -> list[str]:
        return list(getattr(self._base, "source_paths", []) or [])

    def get_raw_frame(self, idx: int) -> np.ndarray:
        raw = self._base.get_raw_frame(int(idx))
        arr = np.asarray(raw, dtype=np.float32)
        th, tw = self._frame_shape
        if arr.shape[:2] == (th, tw):
            return arr
        return cv2.resize(arr, (tw, th), interpolation=cv2.INTER_AREA).astype(np.float32)
