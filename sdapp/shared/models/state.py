from __future__ import annotations

import copy
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


@dataclass(init=False)
class EventMeta:
    event_id: str
    label: str
    start_idx: int
    end_idx: int
    flags: dict[str, Any] = field(default_factory=dict)

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
    def global_start_idx(self) -> int:
        return int(self.start_idx)

    @property
    def global_end_idx(self) -> int:
        return int(self.end_idx)

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
class UnifiedProjectState:
    stack_ref: StackRef | None
    events: list[EventMeta]
    active_event_id: str | None
    analysis_sidecar: dict[str, dict[str, Any]] = field(default_factory=dict)
    project_path: str | None = None
    dirty: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


def _clone_np_array(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return copy.deepcopy(value)
    if isinstance(value, np.ndarray):
        return np.array(value, copy=True)
    if isinstance(value, (list, tuple)):
        try:
            arr = np.asarray(value)
        except Exception:
            return copy.deepcopy(value)
        return np.array(arr, copy=True)
    try:
        arr = np.asarray(value)
    except Exception:
        return copy.deepcopy(value)
    if arr.ndim == 0 and arr.dtype == object:
        try:
            item = arr.item()
        except Exception:
            item = value
        if isinstance(item, (dict, list, tuple)):
            return copy.deepcopy(item)
    return np.array(arr, copy=True)


def clone_project_state(state: UnifiedProjectState) -> UnifiedProjectState:
    copied_events = [
        EventMeta(
            event_id=str(ev.event_id),
            label=str(ev.label),
            start_idx=int(ev.start_idx),
            end_idx=int(ev.end_idx),
            flags=dict(ev.flags),
        )
        for ev in state.events
    ]
    copied_sidecar: dict[str, dict[str, Any]] = {}
    for event_id, payload in dict(state.analysis_sidecar or {}).items():
        entry = dict(payload or {})
        if "masks_committed" in entry:
            entry["masks_committed"] = _clone_np_array(entry.get("masks_committed"))
        if "masks_draft" in entry:
            entry["masks_draft"] = _clone_np_array(entry.get("masks_draft"))
        metrics_settings = entry.get("metrics_settings")
        if isinstance(metrics_settings, dict):
            copied_metrics = dict(metrics_settings)
            if "roi_mask" in copied_metrics:
                copied_metrics["roi_mask"] = _clone_np_array(copied_metrics.get("roi_mask"))
            entry["metrics_settings"] = copied_metrics
        copied_sidecar[str(event_id)] = entry
    return UnifiedProjectState(
        stack_ref=state.stack_ref,
        events=copied_events,
        active_event_id=None if state.active_event_id is None else str(state.active_event_id),
        analysis_sidecar=copied_sidecar,
        project_path=None if state.project_path is None else str(state.project_path),
        dirty=bool(state.dirty),
        metadata=copy.deepcopy(dict(state.metadata or {})),
    )
