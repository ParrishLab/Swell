from __future__ import annotations

from typing import Any

from sdapp.shared.models import EventMeta, SDSetState, UnifiedProjectState


def to_legacy_event_meta_dict(event: EventMeta) -> dict[str, Any]:
    return {
        "event_id": str(event.event_id),
        "label": str(event.label),
        "start_idx": int(event.start_idx),
        "end_idx": int(event.end_idx),
        "flags": dict(event.flags),
    }


def to_legacy_sd_set_dict(sd_set: SDSetState) -> dict[str, Any]:
    return {
        "sd_set_id": str(sd_set.sd_set_id),
        "stack_ref": None if sd_set.stack_ref is None else dict(vars(sd_set.stack_ref)),
        "events": [to_legacy_event_meta_dict(ev) for ev in sd_set.events],
        "active_event_id": None if sd_set.active_event_id is None else str(sd_set.active_event_id),
        "analysis_sidecar": dict(sd_set.analysis_sidecar),
        "metadata": dict(sd_set.metadata),
    }


def to_legacy_state_dict(state: UnifiedProjectState) -> dict[str, Any]:
    return {
        "active_sd_set_id": state.active_sd_set_id,
        "sd_sets": {k: to_legacy_sd_set_dict(v) for k, v in state.sd_sets.items()},
        "project_path": state.project_path,
        "dirty": bool(state.dirty),
        "metadata": dict(state.metadata),
    }
