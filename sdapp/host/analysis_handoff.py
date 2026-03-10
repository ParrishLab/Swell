from __future__ import annotations

try:
    from .frame_source_adapter import SDStackFrameSource
    from .host_models import EventMeta, HostSessionState
except ImportError:
    from frame_source_adapter import SDStackFrameSource
    from host_models import EventMeta, HostSessionState

from sdapp.shared.contracts import CONTRACT_VERSION, validate_handoff_payload as _validate_handoff_payload


def validate_handoff_payload(payload: dict) -> dict:
    return _validate_handoff_payload(payload)


def build_handoff_payload(event: EventMeta, frame_source: SDStackFrameSource, session: HostSessionState) -> dict:
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
            "frame_shape": list(frame_source.frame_shape),
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
    def serialize_payload(event: EventMeta, frame_source: SDStackFrameSource, session: HostSessionState) -> dict:
        return build_handoff_payload(event, frame_source, session)
