from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any
import uuid

try:
    from .host_models import EventMeta, HostSessionState, SDSetState, StackRef
    from .host_project_store import HOST_PERSISTENCE_OWNER
except ImportError:
    from host_models import EventMeta, HostSessionState, SDSetState, StackRef
    from host_project_store import HOST_PERSISTENCE_OWNER
from sdapp.shared.services import UnifiedProjectService


SESSION_SCHEMA_VERSION = 1
ANALYSIS_BRIDGE_MODE = "set_scoped_analysis_payload_v1"
ANALYSIS_BRIDGE_VERSION = 1


class ProjectSessionService:
    def __init__(self) -> None:
        self._service = UnifiedProjectService()

    def state(self) -> HostSessionState:
        state = self._service.state()
        return HostSessionState(
            active_sd_set_id=state.active_sd_set_id,
            sd_sets=state.sd_sets,
            project_path=state.project_path,
            dirty=state.dirty,
            metadata=state.metadata,
        )

    def new_project(self, stack_ref: StackRef) -> HostSessionState:
        self._service.new_project(stack_ref)
        return self.state()

    def create_sd_set(self, stack_ref: StackRef) -> str:
        return self._service.create_sd_set(stack_ref)

    def select_sd_set(self, sd_set_id: str) -> bool:
        return self._service.select_sd_set(sd_set_id)

    def delete_sd_set(self, sd_set_id: str) -> bool:
        return self._service.delete_sd_set(sd_set_id)

    def list_sd_sets(self) -> list[SDSetState]:
        return self._service.list_sd_sets()

    def rename_sd_set(self, sd_set_id: str, display_name: str) -> bool:
        return self._service.rename_sd_set(sd_set_id, display_name)

    def get_active_sd_set_id(self) -> str | None:
        return self._service.get_active_sd_set_id()

    def open_project(self, path: str | Path) -> HostSessionState:
        p = Path(path).expanduser().resolve()
        if p.suffix.lower() == ".sdsession":
            self._service.open_legacy_sdsession(str(p))
        elif p.suffix.lower() == ".sdproj":
            try:
                self._service.open_project(str(p))
            except Exception:
                self._service.open_legacy_sdproj(str(p))
        else:
            self._service.open_legacy_sdsession(str(p))
        return self.state()

    def save_project(self, path: str | Path | None = None) -> HostSessionState:
        target = Path(path or self.state().project_path or "session.sdproj").expanduser().resolve()
        if target.suffix.lower() != ".sdproj":
            target = target.with_suffix(".sdproj")
        self._service.save_project(str(target))
        return self.state()

    def set_events(self, events: list[EventMeta], active_event_id: str | None, mark_dirty: bool = True) -> None:
        state = self.state()
        active_set_id = state.active_sd_set_id
        if active_set_id is None:
            return
        for ev in state.events:
            if str(ev.event_id) not in {str(e.event_id) for e in events}:
                self._service.delete_event(active_set_id, ev.event_id)
        for ev in events:
            self._service.upsert_event(
                active_set_id,
                EventMeta(
                    event_id=str(ev.event_id),
                    label=str(ev.label),
                    start_idx=int(ev.start_idx),
                    end_idx=int(ev.end_idx),
                    flags=dict(ev.flags),
                ),
            )
        self._service.set_active_event(active_event_id, active_set_id)
        if not mark_dirty:
            current = self._service.state()
            current.dirty = False
            self._service.replace_state(current, mark_dirty=False)

    def upsert_event_meta(self, event: EventMeta) -> None:
        self._service.upsert_event(self.get_active_sd_set_id(), event)

    def load_event_meta(self, event_id: str) -> EventMeta | None:
        event = self._service.get_event(self.get_active_sd_set_id(), event_id)
        if event is None:
            return None
        return EventMeta(**asdict(event))

    def delete_event_meta(self, event_id: str) -> None:
        self._service.delete_event(self.get_active_sd_set_id(), event_id)

    def set_stack_ref(self, stack_ref: StackRef) -> None:
        active_set_id = self.get_active_sd_set_id()
        if active_set_id is None:
            self.create_sd_set(stack_ref)
            return
        state = self.state()
        sd_set = state.sd_sets.get(active_set_id)
        if sd_set is None:
            self.create_sd_set(stack_ref)
            return
        sd_set.stack_ref = stack_ref
        sd_set.metadata["stack_id"] = self._service.get_stack_id(active_set_id)
        self._service.replace_state(state, mark_dirty=True)

    def set_metadata(self, **kwargs: Any) -> None:
        self._service.set_metadata(**kwargs)

    def upsert_analysis_sidecar(self, event_id: str, payload: dict[str, Any]) -> None:
        self._service.update_event_analysis(self.get_active_sd_set_id(), str(event_id), dict(payload or {}))

    def load_analysis_sidecar(self, event_id: str) -> dict[str, Any] | None:
        analysis = self._service.get_event_analysis(self.get_active_sd_set_id(), str(event_id))
        if analysis is None:
            return None
        return {
            "prompts": dict(analysis.prompts),
            "masks_committed": analysis.masks_committed,
            "masks_draft": analysis.masks_draft,
            "propagation_completed": bool(analysis.propagation_completed),
            "analysis_output_dir": analysis.analysis_output_dir,
            "ui_hints": dict(analysis.ui_hints),
        }

    def get_session_id(self) -> str:
        return self._service.get_session_id()

    def get_stack_id(self) -> str:
        return self._service.get_stack_id(self.get_active_sd_set_id())

    @property
    def _state(self) -> HostSessionState:
        return self.state()

    @staticmethod
    def _new_session_id() -> str:
        return f"session_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _stack_id_from_stack_ref(stack_ref: StackRef | None) -> str:
        if stack_ref is None:
            return ""
        return (
            f"stack::{stack_ref.input_dir}::"
            f"{stack_ref.frame_count}x{stack_ref.frame_height}x{stack_ref.frame_width}::{stack_ref.dtype}"
        )

    def _default_metadata(self) -> dict[str, Any]:
        return {
            "schema_version": SESSION_SCHEMA_VERSION,
            "bridge_target": "sdproj",
            "session_id": self.get_session_id(),
            "persistence_owner": HOST_PERSISTENCE_OWNER,
            "analysis_bridge_mode": ANALYSIS_BRIDGE_MODE,
            "analysis_bridge_version": ANALYSIS_BRIDGE_VERSION,
        }

    def _active_set(self) -> SDSetState | None:
        return self.state().active_sd_set

    def _allocate_sd_set_id(self) -> str:
        seen = {str(k) for k in self.state().sd_sets.keys()}
        next_num = 1
        while True:
            candidate = f"sd_set_{next_num:04d}"
            if candidate not in seen:
                return candidate
            next_num += 1

    def _normalize_loaded_state(self) -> None:
        current = self._service.state()
        self._service.replace_state(current, mark_dirty=False)
