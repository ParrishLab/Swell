from __future__ import annotations

"""Frame-source abstractions for analysis workspace consumers."""

from dataclasses import dataclass, field
from typing import Iterator

import numpy as np
from sdapp.shared.frame_source.protocols import FrameSource


@dataclass
class FrameSequenceView:
    frame_source: FrameSource
    getter_name: str

    def _getter(self):
        return getattr(self.frame_source, self.getter_name)

    def _sample_frame(self) -> np.ndarray | None:
        if len(self) <= 0:
            return None
        try:
            return np.asarray(self._getter()(0))
        except Exception:
            return None

    def __len__(self) -> int:
        return int(getattr(self.frame_source, "frame_count", 0) or 0)

    def __iter__(self) -> Iterator[np.ndarray]:
        getter = self._getter()
        for idx in range(len(self)):
            yield getter(idx)

    def __getitem__(self, idx: int) -> np.ndarray:
        return self._getter()(int(idx))

    def __array__(self, dtype=None) -> np.ndarray:
        arr = np.asarray([np.asarray(frame) for frame in self])
        if dtype is not None:
            return np.asarray(arr, dtype=dtype)
        return arr

    @property
    def shape(self) -> tuple[int, ...]:
        sample = self._sample_frame()
        if sample is None:
            return (0,)
        return (len(self),) + tuple(int(v) for v in sample.shape)

    @property
    def dtype(self):
        sample = self._sample_frame()
        if sample is None:
            return np.dtype(np.float32)
        return np.asarray(sample).dtype

    @property
    def ndim(self) -> int:
        return len(self.shape)


@dataclass
class EagerFrameSource:
    raw_frames: list[np.ndarray] = field(default_factory=list)
    subtracted_frames: list[np.ndarray] = field(default_factory=list)
    visual_frames: list[np.ndarray] = field(default_factory=list)
    frame_names: list[str] = field(default_factory=list)
    source_paths: list[str] = field(default_factory=list)

    @property
    def frame_count(self) -> int:
        return len(self.raw_frames)

    @property
    def frame_shape(self) -> tuple[int, int]:
        if not self.raw_frames:
            return (0, 0)
        return tuple(self.raw_frames[0].shape[:2])

    @property
    def capabilities(self) -> dict[str, bool]:
        return {
            "raw": bool(self.raw_frames),
            "subtracted": bool(self.subtracted_frames),
            "visual": bool(self.visual_frames),
        }

    def _validate_index(self, idx: int) -> int:
        idx = int(idx)
        if idx < 0 or idx >= self.frame_count:
            raise IndexError(f"Frame index out of range: {idx}")
        return idx

    def get_raw_frame(self, idx: int) -> np.ndarray:
        return self.raw_frames[self._validate_index(idx)]

    def get_subtracted_frame(self, idx: int) -> np.ndarray:
        if not self.subtracted_frames:
            if not getattr(self, "_warned_subtracted", False):
                import tkinter.messagebox as messagebox
                messagebox.showwarning(
                    "Feature Not Available",
                    "Subtracted frames are not available for this session. Falling back to raw frames."
                )
                self._warned_subtracted = True
            return self.get_raw_frame(idx)
        return self.subtracted_frames[self._validate_index(idx)]

    def get_visual_frame(self, idx: int) -> np.ndarray:
        if not self.visual_frames:
            if not getattr(self, "_warned_visual", False):
                import tkinter.messagebox as messagebox
                messagebox.showwarning(
                    "Feature Not Available",
                    "Visualization frames are not available for this session. Falling back to raw frames."
                )
                self._warned_visual = True
            return self.get_raw_frame(idx)
        return self.visual_frames[self._validate_index(idx)]
