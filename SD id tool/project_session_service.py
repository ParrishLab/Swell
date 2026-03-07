from __future__ import annotations

import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from host_models import EventMeta, HostSessionState, SDSetState, StackRef
from host_project_store import HOST_PERSISTENCE_OWNER, HostProjectStore


SESSION_SCHEMA_VERSION = 1
ANALYSIS_BRIDGE_MODE = "set_scoped_analysis_payload_v1"
ANALYSIS_BRIDGE_VERSION = 1


class ProjectSessionService:
    def __init__(self) -> None:
        self._store = HostProjectStore()
        self._state = HostSessionState(
            active_sd_set_id=None,
            sd_sets={},
            project_path=None,
            dirty=False,
            metadata=self._default_metadata(),
        )
        self._next_sd_set_number = 1

    def state(self) -> HostSessionState:
        copied_sets: dict[str, SDSetState] = {}
        for sd_set_id, sd_set in self._state.sd_sets.items():
            copied_sets[str(sd_set_id)] = SDSetState(
                sd_set_id=str(sd_set.sd_set_id),
                stack_ref=sd_set.stack_ref,
                events=[EventMeta(**asdict(ev)) for ev in sd_set.events],
                active_event_id=sd_set.active_event_id,
                analysis_sidecar={k: dict(v) for k, v in sd_set.analysis_sidecar.items()},
                metadata=dict(sd_set.metadata),
            )
        return HostSessionState(
            active_sd_set_id=self._state.active_sd_set_id,
            sd_sets=copied_sets,
            project_path=self._state.project_path,
            dirty=self._state.dirty,
            metadata=dict(self._state.metadata),
        )

    def new_project(self, stack_ref: StackRef) -> HostSessionState:
        self._state = HostSessionState(
            active_sd_set_id=None,
            sd_sets={},
            project_path=None,
            dirty=False,
            metadata=self._default_metadata(),
        )
        self._next_sd_set_number = 1
        self.create_sd_set(stack_ref)
        return self.state()

    def create_sd_set(self, stack_ref: StackRef) -> str:
        sd_set_id = self._allocate_sd_set_id()
        self._state.sd_sets[sd_set_id] = SDSetState(
            sd_set_id=sd_set_id,
            stack_ref=stack_ref,
            events=[],
            active_event_id=None,
            analysis_sidecar={},
            metadata={"stack_id": self._stack_id_from_stack_ref(stack_ref)},
        )
        self._state.active_sd_set_id = sd_set_id
        self._state.dirty = True
        return sd_set_id

    def select_sd_set(self, sd_set_id: str) -> bool:
        key = str(sd_set_id)
        if key not in self._state.sd_sets:
            return False
        self._state.active_sd_set_id = key
        return True

    def delete_sd_set(self, sd_set_id: str) -> bool:
        key = str(sd_set_id)
        if key not in self._state.sd_sets:
            return False
        del self._state.sd_sets[key]
        if self._state.active_sd_set_id == key:
            self._state.active_sd_set_id = next(iter(self._state.sd_sets.keys()), None)
        self._state.dirty = True
        return True

    def list_sd_sets(self) -> list[SDSetState]:
        return [self.state().sd_sets[key] for key in self._state.sd_sets.keys()]

    def rename_sd_set(self, sd_set_id: str, display_name: str) -> bool:
        key = str(sd_set_id)
        sd_set = self._state.sd_sets.get(key)
        if sd_set is None:
            return False
        name = str(display_name).strip()
        if not name:
            return False
        sd_set.metadata["display_name"] = name
        self._state.dirty = True
        return True

    def get_active_sd_set_id(self) -> str | None:
        return self._state.active_sd_set_id

    def open_project(self, path: str | Path) -> HostSessionState:
        p = Path(path).expanduser().resolve()
        if p.suffix.lower() == ".sdsession":
            loaded = self._store.load_legacy_sdsession(p)
        elif p.suffix.lower() == ".sdproj":
            try:
                loaded = self._store.load(p)
            except Exception:
                loaded = self._store.load_legacy_sdproj(p)
        else:
            # Default to compatibility path for legacy JSON files.
            loaded = self._store.load_legacy_sdsession(p)
        self._state = loaded
        self._state.project_path = str(p)
        self._state.dirty = False
        self._normalize_loaded_state()
        return self.state()

    def save_project(self, path: str | Path | None = None) -> HostSessionState:
        target = Path(path or self._state.project_path or "session.sdproj").expanduser().resolve()
        if target.suffix.lower() != ".sdproj":
            target = target.with_suffix(".sdproj")
        self._normalize_loaded_state()
        self._store.save(target, self._state)
        self._state.project_path = str(target)
        self._state.dirty = False
        return self.state()

    def set_events(self, events: list[EventMeta], active_event_id: str | None, mark_dirty: bool = True) -> None:
        sd_set = self._active_set()
        if sd_set is None:
            return
        sd_set.events = [EventMeta(**asdict(ev)) for ev in events]
        sd_set.active_event_id = active_event_id
        if mark_dirty:
            self._state.dirty = True

    def upsert_event_meta(self, event: EventMeta) -> None:
        sd_set = self._active_set()
        if sd_set is None:
            return
        key = str(event.event_id)
        replaced = False
        for i, current in enumerate(sd_set.events):
            if str(current.event_id) == key:
                sd_set.events[i] = EventMeta(**asdict(event))
                replaced = True
                break
        if not replaced:
            sd_set.events.append(EventMeta(**asdict(event)))
        self._state.dirty = True

    def load_event_meta(self, event_id: str) -> EventMeta | None:
        sd_set = self._active_set()
        if sd_set is None:
            return None
        for event in sd_set.events:
            if str(event.event_id) == str(event_id):
                return EventMeta(**asdict(event))
        return None

    def delete_event_meta(self, event_id: str) -> None:
        sd_set = self._active_set()
        if sd_set is None:
            return
        key = str(event_id)
        sd_set.events = [ev for ev in sd_set.events if str(ev.event_id) != key]
        if sd_set.active_event_id == key:
            sd_set.active_event_id = None
        self._state.dirty = True

    def set_stack_ref(self, stack_ref: StackRef) -> None:
        sd_set = self._active_set()
        if sd_set is None:
            self.create_sd_set(stack_ref)
            return
        sd_set.stack_ref = stack_ref
        sd_set.metadata["stack_id"] = self._stack_id_from_stack_ref(stack_ref)
        self._state.dirty = True

    def set_metadata(self, **kwargs: Any) -> None:
        self._state.metadata.update(kwargs)
        self._state.dirty = True

    def upsert_analysis_sidecar(self, event_id: str, payload: dict[str, Any]) -> None:
        sd_set = self._active_set()
        if sd_set is None:
            return
        sd_set.analysis_sidecar[str(event_id)] = dict(payload)
        self._state.dirty = True

    def load_analysis_sidecar(self, event_id: str) -> dict[str, Any] | None:
        sd_set = self._active_set()
        if sd_set is None:
            return None
        payload = sd_set.analysis_sidecar.get(str(event_id))
        if not isinstance(payload, dict):
            return None
        return dict(payload)

    def get_session_id(self) -> str:
        session_id = self._state.metadata.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            session_id = self._new_session_id()
            self._state.metadata["session_id"] = session_id
        return session_id

    def get_stack_id(self) -> str:
        sd_set = self._active_set()
        if sd_set is None:
            return ""
        stack_id = sd_set.metadata.get("stack_id")
        if isinstance(stack_id, str) and stack_id:
            return stack_id
        stack_id = self._stack_id_from_stack_ref(sd_set.stack_ref)
        sd_set.metadata["stack_id"] = stack_id
        return stack_id

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
            "session_id": self._new_session_id(),
            "persistence_owner": HOST_PERSISTENCE_OWNER,
            "analysis_bridge_mode": ANALYSIS_BRIDGE_MODE,
            "analysis_bridge_version": ANALYSIS_BRIDGE_VERSION,
        }

    def _active_set(self) -> SDSetState | None:
        if self._state.active_sd_set_id is None:
            return None
        return self._state.sd_sets.get(str(self._state.active_sd_set_id))

    def _allocate_sd_set_id(self) -> str:
        while True:
            sd_set_id = f"sd_set_{self._next_sd_set_number:04d}"
            self._next_sd_set_number += 1
            if sd_set_id not in self._state.sd_sets:
                return sd_set_id

    def _normalize_loaded_state(self) -> None:
        self._state.metadata.setdefault("schema_version", SESSION_SCHEMA_VERSION)
        self._state.metadata.setdefault("session_id", self._new_session_id())
        self._state.metadata.setdefault("persistence_owner", HOST_PERSISTENCE_OWNER)
        self._state.metadata.setdefault("analysis_bridge_mode", ANALYSIS_BRIDGE_MODE)
        self._state.metadata.setdefault("analysis_bridge_version", ANALYSIS_BRIDGE_VERSION)
        if self._state.active_sd_set_id is None and self._state.sd_sets:
            self._state.active_sd_set_id = next(iter(self._state.sd_sets.keys()))
        max_seen = 0
        for sd_set_id, sd_set in self._state.sd_sets.items():
            parts = str(sd_set_id).split("_")
            if len(parts) == 3 and parts[2].isdigit():
                max_seen = max(max_seen, int(parts[2]))
            sd_set.metadata.setdefault("stack_id", self._stack_id_from_stack_ref(sd_set.stack_ref))
            if sd_set.analysis_sidecar is None:
                sd_set.analysis_sidecar = {}
        self._next_sd_set_number = max(max_seen + 1, self._next_sd_set_number)
