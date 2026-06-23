from __future__ import annotations

from typing import Protocol

import numpy as np


class FrameSource(Protocol):
    @property
    def frame_count(self) -> int: ...

    @property
    def frame_shape(self) -> tuple[int, int]: ...

    @property
    def frame_names(self) -> list[str]: ...

    @property
    def source_paths(self) -> list[str]: ...

    @property
    def capabilities(self) -> dict[str, bool]: ...

    def get_raw_frame(self, idx: int) -> np.ndarray: ...

    def get_subtracted_frame(self, idx: int) -> np.ndarray | None: ...

    def get_visual_frame(self, idx: int) -> np.ndarray | None: ...
