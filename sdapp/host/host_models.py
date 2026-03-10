from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from .config import EventCandidate
except ImportError:
    from config import EventCandidate
from sdapp.shared.models import SDSetState, StackRef, UnifiedProjectState


@dataclass
class EventMeta:
    event_id: str
    label: str
    start_idx: int
    end_idx: int
    flags: dict[str, Any]

    @property
    def duration_frames(self) -> int:
        return int(self.end_idx) - int(self.start_idx) + 1

    @property
    def duration_sec(self) -> float | None:
        return None

    def to_event_candidate(self) -> EventCandidate:
        return EventCandidate(
            event_id=str(self.event_id),
            start_idx=int(self.start_idx),
            end_idx=int(self.end_idx),
            duration_frames=self.duration_frames,
            duration_sec=None,
        )


class HostSessionState(UnifiedProjectState):
    pass


def event_meta_from_candidate(event: EventCandidate, label: str | None = None) -> EventMeta:
    return EventMeta(
        event_id=str(event.event_id),
        label=str(label if label is not None else event.event_id),
        start_idx=int(event.start_idx),
        end_idx=int(event.end_idx),
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
    "SDSetState",
    "StackRef",
    "event_meta_from_candidate",
    "stack_ref_from_stack_info",
]
