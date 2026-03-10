from __future__ import annotations

import uuid
from typing import Any, Callable

from sdapp.shared.models import EventAnalysisState, EventMeta, SDSetState, StackRef, UnifiedProjectState, clone_project_state
from sdapp.shared.persistence import UnifiedProjectStore

SESSION_SCHEMA_VERSION = 1
ANALYSIS_BRIDGE_MODE = "set_scoped_analysis_payload_v1"
ANALYSIS_BRIDGE_VERSION = 1

Listener = Callable[[str, dict[str, Any]], None]


class UnifiedProjectService:
    """Canonical in-memory project state service for host + analysis windows."""

    def __init__(self, *, store: UnifiedProjectStore | None = None) -> None:
        self.store = store or UnifiedProjectStore()
        self._state = UnifiedProjectState(
            active_sd_set_id=None,
            sd_sets={},
            project_path=None,
            dirty=False,
            metadata=self._default_metadata(),
        )
        self._next_sd_set_number = 1
        self._listeners: list[Listener] = []

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        self._listeners.append(listener)

        def _unsubscribe() -> None:
            try:
                self._listeners.remove(listener)
            except ValueError:
                pass

        return _unsubscribe

    def _notify(self, event: str, payload: dict[str, Any]) -> None:
        for listener in list(self._listeners):
            try:
                listener(event, payload)
            except Exception:
                continue

    def state(self) -> UnifiedProjectState:
        return clone_project_state(self._state)

    def replace_state(self, state: UnifiedProjectState, *, mark_dirty: bool = False) -> UnifiedProjectState:
        self._state = clone_project_state(state)
        if mark_dirty:
            self._state.dirty = True
        self._normalize_loaded_state()
        self._notify("state_replaced", {"dirty": self._state.dirty})
        return self.state()

    def new_project(self, stack_ref: StackRef) -> UnifiedProjectState:
        self._state = UnifiedProjectState(
            active_sd_set_id=None,
            sd_sets={},
            project_path=None,
            dirty=False,
            metadata=self._default_metadata(),
        )
        self._next_sd_set_number = 1
        self.create_sd_set(stack_ref)
        self._notify("project_new", {})
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
        self._notify("sd_set_created", {"sd_set_id": sd_set_id})
        return sd_set_id

    def select_sd_set(self, sd_set_id: str) -> bool:
        key = str(sd_set_id)
        if key not in self._state.sd_sets:
            return False
        self._state.active_sd_set_id = key
        self._notify("sd_set_selected", {"sd_set_id": key})
        return True

    def delete_sd_set(self, sd_set_id: str) -> bool:
        key = str(sd_set_id)
        if key not in self._state.sd_sets:
            return False
        del self._state.sd_sets[key]
        if self._state.active_sd_set_id == key:
            self._state.active_sd_set_id = next(iter(self._state.sd_sets.keys()), None)
        self._state.dirty = True
        self._notify("sd_set_deleted", {"sd_set_id": key})
        return True

    def list_sd_sets(self) -> list[SDSetState]:
        return [clone_project_state(self._state).sd_sets[k] for k in self._state.sd_sets.keys()]

    def rename_sd_set(self, sd_set_id: str, display_name: str) -> bool:
        sd_set = self._state.sd_sets.get(str(sd_set_id))
        if sd_set is None:
            return False
        name = str(display_name).strip()
        if not name:
            return False
        sd_set.metadata["display_name"] = name
        self._state.dirty = True
        self._notify("sd_set_renamed", {"sd_set_id": str(sd_set_id), "display_name": name})
        return True

    def get_active_sd_set_id(self) -> str | None:
        return self._state.active_sd_set_id

    def list_events(self, sd_set_id: str | None = None) -> list[EventMeta]:
        sd_set = self._resolve_set(sd_set_id)
        if sd_set is None:
            return []
        return [EventMeta(**vars(ev)) for ev in sd_set.events]

    def upsert_event(self, sd_set_id: str | None, event_meta: EventMeta) -> None:
        sd_set = self._resolve_set(sd_set_id)
        if sd_set is None:
            return
        key = str(event_meta.event_id)
        updated = False
        for idx, ev in enumerate(sd_set.events):
            if str(ev.event_id) == key:
                sd_set.events[idx] = EventMeta(
                    event_id=key,
                    label=str(event_meta.label),
                    start_idx=int(event_meta.start_idx),
                    end_idx=int(event_meta.end_idx),
                    flags=dict(event_meta.flags),
                )
                updated = True
                break
        if not updated:
            sd_set.events.append(
                EventMeta(
                    event_id=key,
                    label=str(event_meta.label),
                    start_idx=int(event_meta.start_idx),
                    end_idx=int(event_meta.end_idx),
                    flags=dict(event_meta.flags),
                )
            )
        self._state.dirty = True
        self._notify("event_upserted", {"sd_set_id": sd_set.sd_set_id, "event_id": key})

    def delete_event(self, sd_set_id: str | None, event_id: str) -> None:
        sd_set = self._resolve_set(sd_set_id)
        if sd_set is None:
            return
        key = str(event_id)
        sd_set.events = [ev for ev in sd_set.events if str(ev.event_id) != key]
        sd_set.analysis_sidecar.pop(key, None)
        if sd_set.active_event_id == key:
            sd_set.active_event_id = None
        self._state.dirty = True
        self._notify("event_deleted", {"sd_set_id": sd_set.sd_set_id, "event_id": key})

    def set_active_event(self, event_id: str | None, sd_set_id: str | None = None) -> None:
        sd_set = self._resolve_set(sd_set_id)
        if sd_set is None:
            return
        sd_set.active_event_id = None if event_id is None else str(event_id)
        self._state.dirty = True
        self._notify("active_event_set", {"sd_set_id": sd_set.sd_set_id, "event_id": sd_set.active_event_id})

    def get_event(self, sd_set_id: str | None, event_id: str) -> EventMeta | None:
        sd_set = self._resolve_set(sd_set_id)
        if sd_set is None:
            return None
        key = str(event_id)
        for ev in sd_set.events:
            if str(ev.event_id) == key:
                return EventMeta(**vars(ev))
        return None

    def get_event_analysis(self, sd_set_id: str | None, event_id: str) -> EventAnalysisState | None:
        sd_set = self._resolve_set(sd_set_id)
        if sd_set is None:
            return None
        payload = sd_set.analysis_sidecar.get(str(event_id))
        if not isinstance(payload, dict):
            return None
        return EventAnalysisState(
            prompts=dict(payload.get("prompts", {})) if isinstance(payload.get("prompts"), dict) else {},
            masks_committed=payload.get("masks_committed"),
            masks_draft=payload.get("masks_draft"),
            propagation_completed=bool(payload.get("propagation_completed", True)),
            analysis_output_dir=payload.get("analysis_output_dir"),
            ui_hints=dict(payload.get("ui_hints", {})) if isinstance(payload.get("ui_hints"), dict) else {},
        )

    def update_event_analysis(self, sd_set_id: str | None, event_id: str, patch: dict[str, Any]) -> None:
        sd_set = self._resolve_set(sd_set_id)
        if sd_set is None:
            return
        key = str(event_id)
        current = dict(sd_set.analysis_sidecar.get(key, {}))
        current.update(dict(patch or {}))
        sd_set.analysis_sidecar[key] = current
        self._state.dirty = True
        self._notify("event_analysis_updated", {"sd_set_id": sd_set.sd_set_id, "event_id": key})

    def open_project(self, path: str) -> UnifiedProjectState:
        loaded = self.store.load(path)
        self._state = clone_project_state(loaded)
        self._state.project_path = str(path)
        self._state.dirty = False
        self._normalize_loaded_state()
        self._notify("project_opened", {"path": str(path)})
        return self.state()

    def open_legacy_sdsession(self, path: str) -> UnifiedProjectState:
        loaded = self.store.load_legacy_sdsession(path)
        self._state = clone_project_state(loaded)
        self._state.project_path = str(path)
        self._state.dirty = False
        self._normalize_loaded_state()
        self._notify("project_opened", {"path": str(path), "legacy": "sdsession"})
        return self.state()

    def open_legacy_sdproj(self, path: str) -> UnifiedProjectState:
        loaded = self.store.load_legacy_portable_sdproj(path)
        self._state = clone_project_state(loaded)
        self._state.project_path = str(path)
        self._state.dirty = False
        self._normalize_loaded_state()
        self._notify("project_opened", {"path": str(path), "legacy": "sdproj"})
        return self.state()

    def save_project(self, path: str | None = None) -> UnifiedProjectState:
        target = str(path or self._state.project_path or "session.sdproj")
        self._normalize_loaded_state()
        self.store.save(target, self._state)
        self._state.project_path = target
        self._state.dirty = False
        self._notify("project_saved", {"path": target})
        return self.state()

    def set_metadata(self, **kwargs: Any) -> None:
        self._state.metadata.update(kwargs)
        self._state.dirty = True
        self._notify("metadata_updated", {"keys": list(kwargs.keys())})

    def get_session_id(self) -> str:
        sid = self._state.metadata.get("session_id")
        if not isinstance(sid, str) or not sid:
            sid = self._new_session_id()
            self._state.metadata["session_id"] = sid
        return sid

    def get_stack_id(self, sd_set_id: str | None = None) -> str:
        sd_set = self._resolve_set(sd_set_id)
        if sd_set is None:
            return ""
        stack_id = sd_set.metadata.get("stack_id")
        if isinstance(stack_id, str) and stack_id:
            return stack_id
        stack_id = self._stack_id_from_stack_ref(sd_set.stack_ref)
        sd_set.metadata["stack_id"] = stack_id
        return stack_id

    def _resolve_set(self, sd_set_id: str | None) -> SDSetState | None:
        key = str(sd_set_id) if sd_set_id is not None else self._state.active_sd_set_id
        if key is None:
            return None
        return self._state.sd_sets.get(key)

    def _allocate_sd_set_id(self) -> str:
        while True:
            sd_set_id = f"sd_set_{self._next_sd_set_number:04d}"
            self._next_sd_set_number += 1
            if sd_set_id not in self._state.sd_sets:
                return sd_set_id

    @staticmethod
    def _stack_id_from_stack_ref(stack_ref: StackRef | None) -> str:
        if stack_ref is None:
            return ""
        return (
            f"stack::{stack_ref.input_dir}::"
            f"{stack_ref.frame_count}x{stack_ref.frame_height}x{stack_ref.frame_width}::{stack_ref.dtype}"
        )

    @staticmethod
    def _new_session_id() -> str:
        return f"session_{uuid.uuid4().hex[:12]}"

    def _default_metadata(self) -> dict[str, Any]:
        return {
            "schema_version": SESSION_SCHEMA_VERSION,
            "bridge_target": "sdproj",
            "session_id": self._new_session_id(),
            "persistence_owner": self.store.persistence_owner,
            "analysis_bridge_mode": ANALYSIS_BRIDGE_MODE,
            "analysis_bridge_version": ANALYSIS_BRIDGE_VERSION,
        }

    def _normalize_loaded_state(self) -> None:
        self._state.metadata.setdefault("schema_version", SESSION_SCHEMA_VERSION)
        self._state.metadata.setdefault("session_id", self._new_session_id())
        self._state.metadata.setdefault("persistence_owner", self.store.persistence_owner)
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
