from __future__ import annotations

"""Frame-source abstractions for analysis workspace consumers."""

from dataclasses import dataclass, field

import numpy as np
from sdapp.shared.frame_source.protocols import FrameSource


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
        return {"raw": True, "subtracted": True, "visual": True}

    def _validate_index(self, idx: int) -> int:
        idx = int(idx)
        if idx < 0 or idx >= self.frame_count:
            raise IndexError(f"Frame index out of range: {idx}")
        return idx

    def get_raw_frame(self, idx: int) -> np.ndarray:
        return self.raw_frames[self._validate_index(idx)]

    def get_subtracted_frame(self, idx: int) -> np.ndarray:
        return self.subtracted_frames[self._validate_index(idx)]

    def get_visual_frame(self, idx: int) -> np.ndarray:
        return self.visual_frames[self._validate_index(idx)]
