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
    frame_names_digest: str | None = None
    source_fingerprint: str | None = None


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


def clone_event_meta(event: EventMeta) -> EventMeta:
    return EventMeta(
        event_id=str(event.event_id),
        label=str(event.label),
        start_idx=int(event.start_idx),
        end_idx=int(event.end_idx),
        flags=dict(event.flags),
    )


def chronological_event_sort_key(event: EventMeta) -> tuple[int, int, str]:
    return (int(event.start_idx), int(event.end_idx), str(event.event_id))


def clone_analysis_payload(
    payload: dict[str, Any] | None,
    *,
    coerce_metrics_roi_mask_to_bool: bool = False,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}

    cloned: dict[str, Any] = {}
    for key, value in payload.items():
        if key in {"masks_committed", "masks_draft"}:
            cloned[key] = _clone_np_array(value)
            continue
        if key == "metrics_settings" and isinstance(value, dict):
            metrics_settings = copy.deepcopy(value)
            if "roi_mask" in metrics_settings and metrics_settings.get("roi_mask") is not None:
                roi_mask = metrics_settings.get("roi_mask")
                if coerce_metrics_roi_mask_to_bool:
                    metrics_settings["roi_mask"] = np.asarray(roi_mask, dtype=bool).copy()
                else:
                    metrics_settings["roi_mask"] = _clone_np_array(roi_mask)
            cloned[key] = metrics_settings
            continue
        cloned[key] = copy.deepcopy(value)
    return cloned


def clone_project_state(state: UnifiedProjectState) -> UnifiedProjectState:
    copied_events = [clone_event_meta(ev) for ev in state.events]
    copied_sidecar: dict[str, dict[str, Any]] = {}
    for event_id, payload in dict(state.analysis_sidecar or {}).items():
        copied_sidecar[str(event_id)] = clone_analysis_payload(payload)
    return UnifiedProjectState(
        stack_ref=state.stack_ref,
        events=copied_events,
        active_event_id=None if state.active_event_id is None else str(state.active_event_id),
        analysis_sidecar=copied_sidecar,
        project_path=None if state.project_path is None else str(state.project_path),
        dirty=bool(state.dirty),
        metadata=copy.deepcopy(dict(state.metadata or {})),
    )
