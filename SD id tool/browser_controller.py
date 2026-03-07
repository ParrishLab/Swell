from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

from analysis_handoff import AnalysisHandoffAdapter
from event_catalog_service import EventCatalogService
from frame_source_adapter import SDStackFrameSource
from host_models import EventMeta, stack_ref_from_stack_info
from project_session_service import ProjectSessionService

try:
    from seam_contract import validate_sync_payload as _validate_sync_payload
except ModuleNotFoundError:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.append(str(repo_root))
    from seam_contract import validate_sync_payload as _validate_sync_payload


class BrowserController:
    def __init__(self) -> None:
        self.events = EventCatalogService()
        self.session = ProjectSessionService()
        self._frame_source: SDStackFrameSource | None = None
        self._frame_sources: dict[str, SDStackFrameSource] = {}
        self.handoff = AnalysisHandoffAdapter(
            session_provider=self.session.state,
            frame_source_provider=lambda: self._frame_source,
            event_provider=self.selected_event,
        )

    def on_stack_loaded(self, reader, stack_info) -> None:
        frame_source = SDStackFrameSource(reader=reader)
        stack_ref = stack_ref_from_stack_info(stack_info)
        if not self.session.state().sd_sets:
            self.session.new_project(stack_ref)
        else:
            self.session.create_sd_set(stack_ref)
        active_set_id = self.session.get_active_sd_set_id()
        if active_set_id is not None:
            self._frame_sources[str(active_set_id)] = frame_source
        self._frame_source = frame_source
        self.events.reset()
        self._sync_session(mark_dirty=False)

    def select_sd_set(self, sd_set_id: str) -> bool:
        selected = self.session.select_sd_set(sd_set_id)
        if not selected:
            return False
        state = self.session.state()
        self.events.reset(events=state.events, active_event_id=state.active_event_id)
        self._frame_source = self._frame_sources.get(str(sd_set_id))
        return True

    def list_events(self) -> list[EventMeta]:
        return self.events.list_events()

    def list_sd_sets(self):
        return self.session.list_sd_sets()

    def get_active_sd_set_id(self) -> str | None:
        return self.session.get_active_sd_set_id()

    def rename_sd_set(self, sd_set_id: str, display_name: str) -> bool:
        return self.session.rename_sd_set(sd_set_id, display_name)

    def delete_sd_set(self, sd_set_id: str) -> bool:
        deleted = self.session.delete_sd_set(sd_set_id)
        if not deleted:
            return False
        self._frame_sources.pop(str(sd_set_id), None)
        active = self.session.get_active_sd_set_id()
        if active is not None:
            self.events.reset(events=self.session.state().events, active_event_id=self.session.state().active_event_id)
            self._frame_source = self._frame_sources.get(str(active))
        else:
            self.events.reset()
            self._frame_source = None
        return True

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
        self._sync_session()

    def create_event(self, start_idx: int, end_idx: int, frame_count: int, label: str | None = None) -> EventMeta:
        event = self.events.create_event(
            start_idx=start_idx,
            end_idx=end_idx,
            label=label,
            frame_count=frame_count,
        )
        self._sync_session()
        return event

    def update_event(
        self,
        event_id: str,
        *,
        start_idx: int | None,
        end_idx: int | None,
        label: str | None,
        frame_count: int,
    ) -> EventMeta:
        event = self.events.update_event(
            event_id,
            start_idx=start_idx,
            end_idx=end_idx,
            label=label,
            frame_count=frame_count,
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
        return [ev.to_event_candidate() for ev in events]

    def save_session(self, path: str | None = None):
        self._sync_session()
        return self.session.save_project(path)

    def open_session(self, path: str):
        state = self.session.open_project(path)
        self.events.reset(events=state.events, active_event_id=state.active_event_id)
        self._frame_source = self._frame_sources.get(str(state.active_sd_set_id)) if state.active_sd_set_id else None
        return state

    def bind_frame_source_for_set(self, sd_set_id: str, reader) -> None:
        frame_source = SDStackFrameSource(reader=reader)
        self._frame_sources[str(sd_set_id)] = frame_source
        if self.session.get_active_sd_set_id() == str(sd_set_id):
            self._frame_source = frame_source

    def reset_project(self) -> None:
        self.events.reset()
        self.session = ProjectSessionService()
        self._frame_source = None
        self._frame_sources.clear()
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
            "frame_shape": list(self._frame_source.frame_shape),
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

    def _sync_session(self, mark_dirty: bool = True) -> None:
        events = self.events.list_events()
        self.session.set_events(events, self.get_active_event_id(), mark_dirty=mark_dirty)
