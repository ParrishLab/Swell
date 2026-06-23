from __future__ import annotations

import numpy as np

from swell.host.host_models import EventMeta, HostSessionState
from swell.shared.frame_source import StackReaderFrameSource

from swell.shared.contracts import CONTRACT_VERSION, validate_handoff_payload as _validate_handoff_payload


def validate_handoff_payload(payload: dict) -> dict:
    return _validate_handoff_payload(payload)


def resolve_host_frame_shape(frame_source) -> list[int]:
    shape = getattr(frame_source, "frame_shape", None)
    normalized = _normalize_frame_shape_tuple(shape)
    raw_shape = _sample_frame_shape(frame_source)
    if raw_shape is not None:
        return [int(raw_shape[0]), int(raw_shape[1])]
    if normalized is not None:
        return [int(normalized[0]), int(normalized[1])]
    return [0, 0]


def _normalize_frame_shape_tuple(shape) -> tuple[int, int] | None:
    if not isinstance(shape, (list, tuple)) or len(shape) != 2:
        return None
    try:
        height = int(shape[0])
        width = int(shape[1])
    except Exception:
        return None
    if height <= 0 or width <= 0:
        return None
    return height, width


def _sample_frame_shape(frame_source) -> tuple[int, int] | None:
    getter = getattr(frame_source, "get_raw_frame", None)
    if not callable(getter):
        return None
    try:
        frame = np.asarray(getter(0))
    except Exception:
        return None
    if frame.ndim < 2:
        return None
    return int(frame.shape[0]), int(frame.shape[1])


def build_handoff_payload(event: EventMeta, frame_source: StackReaderFrameSource, session: HostSessionState) -> dict:
    metadata = dict(session.metadata)
    session_id = str(metadata.get("session_id", "") or "")
    stack_id = str(metadata.get("stack_id", "") or "")
    active_event_id = str(session.active_event_id or event.event_id)
    return {
        "contract_version": CONTRACT_VERSION,
        "session": {
            "session_id": session_id,
            "project_path": session.project_path,
            "active_event_id": active_event_id,
            "dirty": bool(session.dirty),
            "metadata": metadata,
        },
        "stack": {
            "stack_id": stack_id,
            "frame_count": int(frame_source.frame_count),
            "frame_shape": resolve_host_frame_shape(frame_source),
            "frame_names": list(frame_source.frame_names),
            "source_paths": list(frame_source.source_paths),
            "capabilities": dict(frame_source.capabilities),
        },
        "event": {
            "event_id": str(event.event_id),
            "label": str(event.label),
            "start_idx": int(event.start_idx),
            "end_idx": int(event.end_idx),
            "flags": dict(event.flags),
        },
        "analysis_state_ref": {
            "storage": "host_session",
            "ref_id": f"{session_id}:{event.event_id}",
        },
    }


class AnalysisHandoffAdapter:
    def __init__(self, session_provider, frame_source_provider, event_provider) -> None:
        self._session_provider = session_provider
        self._frame_source_provider = frame_source_provider
        self._event_provider = event_provider

    def selected_event_payload(self) -> dict | None:
        event = self._event_provider()
        if event is None:
            return None
        frame_source = self._frame_source_provider()
        if frame_source is None:
            return None
        session = self._session_provider()
        payload = build_handoff_payload(event, frame_source, session)
        result = validate_handoff_payload(payload)
        if not bool(result.get("ok")):
            return result
        return result["normalized"]

    @staticmethod
    def serialize_payload(event: EventMeta, frame_source: StackReaderFrameSource, session: HostSessionState) -> dict:
        return build_handoff_payload(event, frame_source, session)
