from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config import EventCandidate


@dataclass
class EventMeta:
    event_id: str
    label: str
    start_idx: int
    end_idx: int
    flags: dict[str, Any] = field(default_factory=dict)

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


@dataclass(frozen=True)
class StackRef:
    input_dir: str
    frame_count: int
    frame_height: int
    frame_width: int
    dtype: str


@dataclass
class SDSetState:
    sd_set_id: str
    stack_ref: StackRef | None
    events: list[EventMeta]
    active_event_id: str | None
    analysis_sidecar: dict[str, dict[str, Any]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class HostSessionState:
    active_sd_set_id: str | None
    sd_sets: dict[str, SDSetState]
    project_path: str | None
    dirty: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def stack_ref(self) -> StackRef | None:
        active = self.active_sd_set
        return None if active is None else active.stack_ref

    @property
    def events(self) -> list[EventMeta]:
        active = self.active_sd_set
        return [] if active is None else list(active.events)

    @property
    def active_event_id(self) -> str | None:
        active = self.active_sd_set
        return None if active is None else active.active_event_id

    @property
    def active_sd_set(self) -> SDSetState | None:
        if self.active_sd_set_id is None:
            return None
        return self.sd_sets.get(str(self.active_sd_set_id))


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
