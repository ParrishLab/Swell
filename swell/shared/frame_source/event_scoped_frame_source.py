from __future__ import annotations


class EventScopedFrameSource:
    """Frame source view bounded to an inclusive [start, end] event scope."""

    def __init__(self, base_source, start_idx: int, end_idx: int):
        self._base = base_source
        self._start = int(start_idx)
        self._end = int(end_idx)
        self._frame_names_cache: list[str] | None = None
        self._source_paths_cache: list[str] | None = None
        if self._end < self._start:
            self._start, self._end = self._end, self._start
        total = int(getattr(base_source, "frame_count", 0) or 0)
        if total <= 0:
            self._start = 0
            self._end = -1
        else:
            self._start = max(0, min(self._start, total - 1))
            self._end = max(0, min(self._end, total - 1))

    @property
    def frame_count(self) -> int:
        if self._end < self._start:
            return 0
        return int(self._end - self._start + 1)

    @property
    def frame_shape(self) -> tuple[int, int]:
        return tuple(getattr(self._base, "frame_shape", (0, 0)))

    @property
    def frame_names(self) -> list[str]:
        if self._frame_names_cache is None:
            names = list(getattr(self._base, "frame_names", []))
            self._frame_names_cache = names[self._start : self._end + 1]
        return list(self._frame_names_cache)

    @property
    def source_paths(self) -> list[str]:
        if self._source_paths_cache is None:
            paths = list(getattr(self._base, "source_paths", []))
            self._source_paths_cache = paths[self._start : self._end + 1]
        return list(self._source_paths_cache)

    @property
    def capabilities(self) -> dict[str, bool]:
        return dict(getattr(self._base, "capabilities", {"raw": True, "subtracted": False, "visual": False}))

    def _to_abs(self, idx: int) -> int:
        i = int(idx)
        if i < 0 or i >= self.frame_count:
            raise IndexError(i)
        return self._start + i

    def get_raw_frame(self, idx):
        return self._base.get_raw_frame(self._to_abs(idx))

    def get_subtracted_frame(self, idx):
        return self._base.get_subtracted_frame(self._to_abs(idx))

    def get_visual_frame(self, idx):
        return self._base.get_visual_frame(self._to_abs(idx))
