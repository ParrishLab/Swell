from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from swell.shared.models import StackRef, UnifiedProjectState

from .config import EventCandidate


@dataclass(init=False)
class EventMeta:
    event_id: str
    label: str
    start_idx: int
    end_idx: int
    flags: dict[str, Any]

    def __init__(
        self,
        event_id: str,
        label: str,
        start_idx: int | None = None,
        end_idx: int | None = None,
        flags: dict[str, Any] | None = None,
        *,
        global_start_idx: int | None = None,
        global_end_idx: int | None = None,
    ) -> None:
        if start_idx is None:
            start_idx = global_start_idx if global_start_idx is not None else 0
        if end_idx is None:
            end_idx = global_end_idx if global_end_idx is not None else int(start_idx)
        self.event_id = str(event_id)
        self.label = str(label)
        self.start_idx = int(start_idx)
        self.end_idx = int(end_idx)
        self.flags = dict(flags or {})

    @property
    def duration_frames(self) -> int:
        return int(self.end_idx) - int(self.start_idx) + 1

    @property
    def global_start_idx(self) -> int:
        return int(self.start_idx)

    @property
    def global_end_idx(self) -> int:
        return int(self.end_idx)

    @property
    def duration_sec(self) -> float | None:
        return None

    def to_event_candidate(self) -> EventCandidate:
        return EventCandidate(
            event_id=str(self.event_id),
            start_idx=self.start_idx,
            end_idx=self.end_idx,
            duration_frames=self.duration_frames,
            duration_sec=None,
            label=str(self.label),
        )


class HostSessionState(UnifiedProjectState):
    pass


def event_meta_from_candidate(event: EventCandidate, label: str | None = None) -> EventMeta:
    return EventMeta(
        event_id=str(event.event_id),
        label=str(label if label is not None else getattr(event, "label", None) or event.event_id),
        global_start_idx=int(event.start_idx),
        global_end_idx=int(event.end_idx),
        flags={},
    )


def stack_ref_from_stack_info(info) -> StackRef:
    return StackRef(
        input_dir=str(Path(info.input_dir)),
        frame_count=int(info.frame_count),
        frame_height=int(info.frame_height),
        frame_width=int(info.frame_width),
        dtype=str(info.dtype),
    )


__all__ = [
    "EventMeta",
    "HostSessionState",
    "StackRef",
    "event_meta_from_candidate",
    "stack_ref_from_stack_info",
]
