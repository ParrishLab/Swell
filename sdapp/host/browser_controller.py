from __future__ import annotations

from typing import Iterable

from sdapp.host.analysis_handoff import AnalysisHandoffAdapter, resolve_host_frame_shape
from sdapp.host.analysis_payload_mapper import (
    EventBounds,
    RemapContext,
    annotate_payload_origins,
    recompute_scope_flags,
    remap_analysis_payload_for_bounds_change,
)
from sdapp.host.config import EventCandidate
from sdapp.host.event_catalog_service import EventCatalogService
from sdapp.host.host_models import EventMeta, stack_ref_from_stack_info
from sdapp.host.project_session_service import ProjectSessionService
from sdapp.shared.frame_source import SDStackFrameSource

from sdapp.shared.contracts import validate_sync_payload as _validate_sync_payload

HOST_FULL_STACK_EVENT_FLAG = "host_full_stack_event"
HOST_FULL_STACK_EVENT_LABEL = "Full Stack Analysis"
HOST_FULL_STACK_EVENT_ID = "event_full_stack"


class BrowserController:
    def __init__(self) -> None:
        self.events = EventCatalogService()
        self.session = ProjectSessionService()
        self._frame_source: SDStackFrameSource | None = None
        self.handoff = AnalysisHandoffAdapter(
            session_provider=self.session.state,
            frame_source_provider=lambda: self._frame_source,
            event_provider=self.selected_event,
        )

    def on_stack_loaded(self, reader, stack_info) -> None:
        frame_source = SDStackFrameSource(reader=reader)
        stack_ref = stack_ref_from_stack_info(stack_info)
        self.session.new_project(stack_ref)
        self._frame_source = frame_source
        self.events.reset()
        self._sync_session(mark_dirty=False)

    def list_events(self) -> list[EventMeta]:
        return self.events.list_events()

    def get_event(self, event_id: str | None) -> EventMeta | None:
        return self.events.get_event(event_id)

    def get_active_event_id(self) -> str | None:
        return self.events.get_active_event_id()

    def normalize_bounds(self, start_idx: int, end_idx: int, frame_count: int) -> tuple[int, int]:
        return self.events.normalize_bounds(start_idx, end_idx, frame_count)

    def get_frame_source(self) -> SDStackFrameSource | None:
        return self._frame_source

    def selected_event(self) -> EventMeta | None:
        return self.get_event(self.get_active_event_id())

    def set_active_event(self, event_id: str | None) -> None:
        self.events.set_active_event(event_id)
        self._sync_session(mark_dirty=False)

    def create_event(
        self,
        start_idx: int,
        end_idx: int,
        frame_count: int,
        label: str | None = None,
        flags: dict | None = None,
    ) -> EventMeta:
        event = self.events.create_event(
            start_idx=start_idx,
            end_idx=end_idx,
            label=label,
            frame_count=frame_count,
            flags=flags,
        )
        self._sync_session()
        return event

    def ensure_full_stack_analysis_event(self, *, frame_count: int) -> EventMeta:
        start_idx, end_idx = self.events.normalize_bounds(0, max(0, int(frame_count) - 1), int(frame_count))
        canonical_flags = {HOST_FULL_STACK_EVENT_FLAG: True}
        canonical_event = EventMeta(
            event_id=HOST_FULL_STACK_EVENT_ID,
            label=HOST_FULL_STACK_EVENT_LABEL,
            global_start_idx=int(start_idx),
            global_end_idx=int(end_idx),
            flags=canonical_flags,
        )
        existing_canonical = self.events.get_event(HOST_FULL_STACK_EVENT_ID)
        if existing_canonical is not None:
            if (
                int(existing_canonical.start_idx) != int(start_idx)
                or int(existing_canonical.end_idx) != int(end_idx)
                or not bool(dict(existing_canonical.flags or {}).get(HOST_FULL_STACK_EVENT_FLAG))
                or str(existing_canonical.label) != HOST_FULL_STACK_EVENT_LABEL
            ):
                self.events.upsert_event_meta(canonical_event, set_active=True)
            else:
                self.events.set_active_event(HOST_FULL_STACK_EVENT_ID)
            self._sync_session()
            current = self.events.get_event(HOST_FULL_STACK_EVENT_ID)
            return current if current is not None else canonical_event

        for event in self.events.list_events():
            flags = dict(event.flags or {})
            if not bool(flags.get(HOST_FULL_STACK_EVENT_FLAG)):
                continue
            if int(event.start_idx) != int(start_idx) or int(event.end_idx) != int(end_idx):
                continue
            legacy_sidecar = self.session.load_analysis_sidecar(str(event.event_id))
            if str(event.event_id) != HOST_FULL_STACK_EVENT_ID:
                self.events.delete_event(str(event.event_id))
                self.events.upsert_event_meta(canonical_event, set_active=True)
                self._sync_session()
                if isinstance(legacy_sidecar, dict) and legacy_sidecar:
                    self.session.upsert_analysis_sidecar(HOST_FULL_STACK_EVENT_ID, legacy_sidecar)
                current = self.events.get_event(HOST_FULL_STACK_EVENT_ID)
                return current if current is not None else canonical_event
            self.events.set_active_event(HOST_FULL_STACK_EVENT_ID)
            self._sync_session()
            current = self.events.get_event(HOST_FULL_STACK_EVENT_ID)
            return current if current is not None else event
        self.events.upsert_event_meta(canonical_event, set_active=True)
        self._sync_session()
        current = self.events.get_event(HOST_FULL_STACK_EVENT_ID)
        return current if current is not None else canonical_event

    def update_event(
        self,
        event_id: str,
        *,
        start_idx: int | None,
        end_idx: int | None,
        label: str | None,
        frame_count: int,
        flags: dict | None = None,
    ) -> EventMeta:
        existing = self.events.get_event(event_id)
        if existing is None:
            raise KeyError(f"Event not found: {event_id}")
        old_start = int(existing.start_idx)
        old_end = int(existing.end_idx)
        next_start = int(old_start if start_idx is None else start_idx)
        next_end = int(old_end if end_idx is None else end_idx)
        next_start, next_end = self.events.normalize_bounds(next_start, next_end, frame_count)
        next_flags = dict(existing.flags if flags is None else flags)
        if int(next_start) != old_start or int(next_end) != old_end:
            next_flags = recompute_scope_flags(
                next_flags,
                old_bounds=EventBounds(
                    start_idx=old_start,
                    end_idx=old_end,
                    flags=dict(existing.flags),
                ),
                new_start=int(next_start),
                new_end=int(next_end),
            )
        event = self.events.update_event(
            event_id,
            start_idx=next_start,
            end_idx=next_end,
            label=label,
            frame_count=frame_count,
            flags=next_flags,
        )
        if int(next_start) != old_start or int(next_end) != old_end:
            self._remap_analysis_sidecar_for_event_bounds_change(
                str(event_id),
                old_start=old_start,
                old_end=old_end,
                old_flags=dict(existing.flags),
                new_start=int(next_start),
                new_end=int(next_end),
                new_flags=dict(next_flags),
            )
        self._sync_session()
        return event

    def delete_events(self, event_ids: Iterable[str]) -> int:
        count = self.events.delete_many([str(eid) for eid in event_ids])
        self._sync_session()
        return count

    def export_candidates(self, selected_event_ids: list[str] | None = None):
        selected = set(selected_event_ids or [])
        events = self.list_events()
        if selected:
            events = [ev for ev in events if ev.event_id in selected]
        out: list[EventCandidate] = []
        for ev in events:
            out.append(
                EventCandidate(
                    event_id=str(ev.event_id),
                    start_idx=int(ev.start_idx),
                    end_idx=int(ev.end_idx),
                    duration_frames=(int(ev.end_idx) - int(ev.start_idx) + 1),
                    duration_sec=None,
                    flags=dict(ev.flags),
                    label=str(ev.label),
                )
            )
        return out

    def save_session(self, path: str | None = None):
        self._sync_session()
        return self.session.save_project(path)

    def open_session(self, path: str):
        state = self.session.open_project(path)
        self.events.reset(events=state.events, active_event_id=state.active_event_id)
        return state

    def bind_frame_source(self, reader) -> None:
        self._frame_source = SDStackFrameSource(reader=reader)

    def reset_project(self) -> None:
        self.events.reset()
        self.session = ProjectSessionService()
        self._frame_source = None
        self.handoff = AnalysisHandoffAdapter(
            session_provider=self.session.state,
            frame_source_provider=lambda: self._frame_source,
            event_provider=self.selected_event,
        )

    def validate_sync_payload(self, payload: dict) -> dict:
        if self._frame_source is None:
            return {
                "ok": False,
                "code": "PAYLOAD_INVALID",
                "message": "No active frame source; host stack context is unavailable.",
            }
        context = {
            "session_id": self.session.get_session_id(),
            "stack_id": self.session.get_stack_id(),
            "frame_shape": resolve_host_frame_shape(self._frame_source),
            "event_ids": [ev.event_id for ev in self.events.list_events()],
        }
        return _validate_sync_payload(payload, context)

    def apply_analysis_sync(self, payload: dict) -> dict:
        result = self.validate_sync_payload(payload)
        if not bool(result.get("ok")):
            return result
        normalized = result["normalized"]
        event_id = normalized["event_id"]
        self.session.upsert_analysis_sidecar(event_id, normalized["analysis"])
        self.session.set_metadata(last_sync_event_id=event_id)
        return {"ok": True, "normalized": result["normalized"]}

    def apply_direct_analysis_update(self, payload_or_event_id, analysis_payload: dict | None = None) -> dict:
        if isinstance(payload_or_event_id, dict):
            event_id = str(payload_or_event_id.get("event_id", "")).strip()
            payload = dict(payload_or_event_id)
            if analysis_payload is None:
                analysis_payload = payload.get("analysis")
                if analysis_payload is None:
                    analysis_payload = {k: v for k, v in payload.items() if k != "event_id"}
        else:
            event_id = str(payload_or_event_id)
        if not event_id:
            return {
                "ok": False,
                "code": "PAYLOAD_INVALID",
                "message": "Missing event_id in analysis update payload.",
            }
        event = self.events.get_event(event_id)
        if event is None:
            return {
                "ok": False,
                "code": "EVENT_NOT_FOUND",
                "message": f"event_id not found in host event catalog: {event_id}",
            }
        normalized_payload = annotate_payload_origins(
            dict(analysis_payload or {}),
            bounds=EventBounds(
                start_idx=int(event.start_idx),
                end_idx=int(event.end_idx),
                flags=dict(getattr(event, "flags", {}) or {}),
            ),
        )
        self.session.upsert_analysis_sidecar(str(event_id), normalized_payload)
        self.session.set_metadata(last_sync_event_id=str(event_id))
        return {"ok": True, "event_id": str(event_id)}

    def set_global_metrics_defaults(self, payload: dict) -> dict:
        return self.session.set_global_metrics_defaults(dict(payload or {}))

    def set_model_checkpoint_metadata(self, payload: dict | None) -> None:
        self.session.set_model_checkpoint_metadata(dict(payload or {}) if isinstance(payload, dict) else None)

    def get_model_checkpoint_metadata(self) -> dict | None:
        return self.session.get_model_checkpoint_metadata()

    def set_dc_trace_attachment(self, payload: dict | None) -> None:
        self.session.set_dc_trace_attachment(dict(payload or {}) if isinstance(payload, dict) else None)

    def get_dc_trace_attachment(self) -> dict | None:
        return self.session.get_dc_trace_attachment()

    def get_global_metrics_defaults(self) -> dict:
        return self.session.get_global_metrics_defaults()

    def materialize_metrics_defaults_to_events(self) -> int:
        return int(self.session.materialize_metrics_defaults_to_events())

    def upsert_event_metrics_settings(
        self,
        event_id: str,
        payload: dict,
        *,
        merge_missing_only: bool = False,
    ) -> bool:
        return bool(
            self.session.upsert_event_metrics_settings(
                str(event_id),
                dict(payload or {}),
                merge_missing_only=bool(merge_missing_only),
            )
        )

    def clear_event_metrics_settings_keys(self, event_id: str, keys: list[str]) -> bool:
        return bool(self.session.clear_event_metrics_settings_keys(str(event_id), list(keys or [])))

    def load_event_metrics_settings(self, event_id: str) -> dict | None:
        return self.session.load_event_metrics_settings(str(event_id))

    def resolve_event_metrics_settings(self, event_id: str) -> dict:
        return self.session.resolve_event_metrics_settings(str(event_id))

    def host_context_for_event(self, event_id: str) -> dict:
        event = self.events.get_event(event_id)
        if event is None:
            raise KeyError(f"Event not found: {event_id}")
        state = self.session.state()
        analysis_state = state.analysis_sidecar.get(str(event.event_id))
        if isinstance(analysis_state, dict):
            analysis_state = annotate_payload_origins(
                dict(analysis_state),
                bounds=EventBounds(
                    start_idx=int(event.start_idx),
                    end_idx=int(event.end_idx),
                    flags=dict(getattr(event, "flags", {}) or {}),
                ),
            )
        return {
            "session_id": self.session.get_session_id(),
            "stack_id": self.session.get_stack_id(),
            "project_path": state.project_path,
            "project_metadata": dict(state.metadata or {}),
            "event": {
                "event_id": event.event_id,
                "label": event.label,
                "start_idx": int(event.start_idx),
                "end_idx": int(event.end_idx),
                "flags": dict(event.flags),
            },
            "analysis_state": analysis_state,
            "local_metrics_settings": self.load_event_metrics_settings(str(event.event_id)),
            "metrics_settings": self.resolve_event_metrics_settings(str(event.event_id)),
        }

    def _sync_session(self, mark_dirty: bool = True) -> None:
        events = self.events.list_events()
        self.session.set_events(events, self.get_active_event_id(), mark_dirty=mark_dirty)

    def _remap_analysis_sidecar_for_event_bounds_change(
        self,
        event_id: str,
        *,
        old_start: int,
        old_end: int,
        old_flags: dict,
        new_start: int,
        new_end: int,
        new_flags: dict,
    ) -> None:
        sidecar = self.session.load_analysis_sidecar(event_id)
        updated = remap_analysis_payload_for_bounds_change(
            sidecar,
            event_id=event_id,
            context=RemapContext(
                old_bounds=EventBounds(start_idx=old_start, end_idx=old_end, flags=dict(old_flags or {})),
                new_bounds=EventBounds(start_idx=new_start, end_idx=new_end, flags=dict(new_flags or {})),
            ),
        )
        if isinstance(updated, dict):
            self.session.upsert_analysis_sidecar(event_id, updated)
