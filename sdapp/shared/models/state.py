from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass(frozen=True)
class StackRef:
    input_dir: str
    frame_count: int
    frame_height: int
    frame_width: int
    dtype: str


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


@dataclass
class EventAnalysisState:
    prompts: dict[str, Any] = field(default_factory=dict)
    masks_committed: np.ndarray | None = None
    masks_draft: np.ndarray | None = None
    propagation_completed: bool = True
    analysis_output_dir: str | None = None
    ui_hints: dict[str, Any] = field(default_factory=dict)


@dataclass
class SDSetState:
    sd_set_id: str
    stack_ref: StackRef | None
    events: list[EventMeta]
    active_event_id: str | None
    analysis_sidecar: dict[str, dict[str, Any]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class UnifiedProjectState:
    active_sd_set_id: str | None
    sd_sets: dict[str, SDSetState]
    project_path: str | None
    dirty: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def active_sd_set(self) -> SDSetState | None:
        if self.active_sd_set_id is None:
            return None
        return self.sd_sets.get(str(self.active_sd_set_id))

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


def _clone_np_array(value: Any) -> Any:
    if value is None:
        return None
    arr = np.asarray(value)
    return np.array(arr, copy=True)


def clone_project_state(state: UnifiedProjectState) -> UnifiedProjectState:
    copied_sets: dict[str, SDSetState] = {}
    for sd_set_id, sd_set in state.sd_sets.items():
        copied_events = [
            EventMeta(
                event_id=str(ev.event_id),
                label=str(ev.label),
                start_idx=int(ev.start_idx),
                end_idx=int(ev.end_idx),
                flags=dict(ev.flags),
            )
            for ev in sd_set.events
        ]
        copied_sidecar: dict[str, dict[str, Any]] = {}
        for event_id, payload in dict(sd_set.analysis_sidecar or {}).items():
            entry = dict(payload or {})
            if "masks_committed" in entry:
                entry["masks_committed"] = _clone_np_array(entry.get("masks_committed"))
            if "masks_draft" in entry:
                entry["masks_draft"] = _clone_np_array(entry.get("masks_draft"))
            copied_sidecar[str(event_id)] = entry
        copied_sets[str(sd_set_id)] = SDSetState(
            sd_set_id=str(sd_set.sd_set_id),
            stack_ref=sd_set.stack_ref,
            events=copied_events,
            active_event_id=None if sd_set.active_event_id is None else str(sd_set.active_event_id),
            analysis_sidecar=copied_sidecar,
            metadata=dict(sd_set.metadata or {}),
        )
    return UnifiedProjectState(
        active_sd_set_id=None if state.active_sd_set_id is None else str(state.active_sd_set_id),
        sd_sets=copied_sets,
        project_path=None if state.project_path is None else str(state.project_path),
        dirty=bool(state.dirty),
        metadata=dict(state.metadata or {}),
    )
