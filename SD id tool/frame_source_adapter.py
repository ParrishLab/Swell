from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from stack_reader import StackReader


@dataclass
class SDStackFrameSource:
    reader: StackReader

    @property
    def frame_count(self) -> int:
        return int(self.reader.get_frame_count())

    @property
    def frame_shape(self) -> tuple[int, int]:
        info = self.reader.get_stack_info()
        return (int(info.frame_height), int(info.frame_width))

    @property
    def frame_names(self) -> Sequence[str]:
        return [self.reader.get_frame_name(i) for i in range(self.frame_count)]

    @property
    def source_paths(self) -> Sequence[str]:
        return [str(self.reader.get_frame_ref(i).source_path) for i in range(self.frame_count)]

    @property
    def capabilities(self) -> dict[str, bool]:
        return {
            "raw": True,
            "subtracted": False,
            "visual": False,
        }

    def get_raw_frame(self, idx: int) -> np.ndarray:
        return self.reader.read_frame(int(idx), use_cache=True)

    def get_subtracted_frame(self, idx: int) -> np.ndarray:
        raise NotImplementedError("Subtracted frame source is not wired in host seam prep.")

    def get_visual_frame(self, idx: int) -> np.ndarray:
        raise NotImplementedError("Visual frame source is not wired in host seam prep.")
