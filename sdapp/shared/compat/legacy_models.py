from __future__ import annotations

from typing import Any

from sdapp.shared.models import EventMeta, UnifiedProjectState


def to_legacy_event_meta_dict(event: EventMeta) -> dict[str, Any]:
    return {
        "event_id": str(event.event_id),
        "label": str(event.label),
        "start_idx": int(event.start_idx),
        "end_idx": int(event.end_idx),
        "flags": dict(event.flags),
    }


def to_legacy_state_dict(state: UnifiedProjectState) -> dict[str, Any]:
    return {
        "stack_ref": None if state.stack_ref is None else dict(vars(state.stack_ref)),
        "events": [to_legacy_event_meta_dict(ev) for ev in state.events],
        "active_event_id": state.active_event_id,
        "analysis_sidecar": dict(state.analysis_sidecar),
        "project_path": state.project_path,
        "dirty": bool(state.dirty),
        "metadata": dict(state.metadata),
    }
