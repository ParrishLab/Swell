from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Callable

from sdapp.shared.models import (
    EventAnalysisState,
    EventMeta,
    StackRef,
    UnifiedProjectState,
    clone_analysis_payload,
    clone_event_meta,
    clone_project_state,
    chronological_event_sort_key,
)
from sdapp.shared.persistence import UnifiedProjectStore
from sdapp.shared.project_naming import derive_sdproj_filename

SESSION_SCHEMA_VERSION = 1
ANALYSIS_BRIDGE_MODE = "single_stack_analysis_payload_v1"
ANALYSIS_BRIDGE_VERSION = 1

Listener = Callable[[str, dict[str, Any]], None]


class UnifiedProjectService:
    """Canonical in-memory project state service for host + analysis windows."""

    def __init__(self, *, store: UnifiedProjectStore | None = None) -> None:
        self.store = store or UnifiedProjectStore()
        self._state = self._build_state()
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
        self._state = self._build_state(stack_ref=stack_ref)
        self._notify("project_new", {})
        return self.state()

    def list_events(self) -> list[EventMeta]:
        return [clone_event_meta(ev) for ev in sorted(self._state.events, key=chronological_event_sort_key)]

    def upsert_event(self, event_meta: EventMeta) -> None:
        key = str(event_meta.event_id)
        event_copy = clone_event_meta(event_meta)
        updated = False
        for idx, ev in enumerate(self._state.events):
            if str(ev.event_id) == key:
                self._state.events[idx] = event_copy
                updated = True
                break
        if not updated:
            self._state.events.append(event_copy)
        self._state.events.sort(key=chronological_event_sort_key)
        self._state.dirty = True
        self._notify("event_upserted", {"event_id": key})

    def delete_event(self, event_id: str) -> None:
        key = str(event_id)
        self._state.events = [ev for ev in self._state.events if str(ev.event_id) != key]
        self._state.analysis_sidecar.pop(key, None)
        if self._state.active_event_id == key:
            self._state.active_event_id = None
        self._state.dirty = True
        self._notify("event_deleted", {"event_id": key})

    def set_active_event(self, event_id: str | None) -> None:
        self._state.active_event_id = None if event_id is None else str(event_id)
        self._state.dirty = True
        self._notify("active_event_set", {"event_id": self._state.active_event_id})

    def get_event(self, event_id: str) -> EventMeta | None:
        key = str(event_id)
        for ev in self._state.events:
            if str(ev.event_id) == key:
                return clone_event_meta(ev)
        return None

    def get_event_analysis_payload(self, event_id: str) -> dict[str, Any] | None:
        payload = self._state.analysis_sidecar.get(str(event_id))
        if not isinstance(payload, dict):
            return None
        return clone_analysis_payload(payload)

    def get_event_analysis(self, event_id: str) -> EventAnalysisState | None:
        payload = self.get_event_analysis_payload(event_id)
        if payload is None:
            return None
        return EventAnalysisState(
            prompts=dict(payload.get("prompts", {})) if isinstance(payload.get("prompts"), dict) else {},
            masks_committed=payload.get("masks_committed"),
            masks_draft=payload.get("masks_draft"),
            propagation_completed=bool(payload.get("propagation_completed", True)),
            analysis_output_dir=payload.get("analysis_output_dir"),
            ui_hints=dict(payload.get("ui_hints", {})) if isinstance(payload.get("ui_hints"), dict) else {},
        )

    def update_event_analysis(self, event_id: str, patch: dict[str, Any]) -> None:
        key = str(event_id)
        current = clone_analysis_payload(self._state.analysis_sidecar.get(key, {}))
        current.update(clone_analysis_payload(dict(patch or {})))
        self._state.analysis_sidecar[key] = current
        self._state.dirty = True
        self._notify("event_analysis_updated", {"event_id": key})

    def replace_event_analysis(self, event_id: str, payload: dict[str, Any] | None) -> None:
        key = str(event_id)
        normalized = clone_analysis_payload(dict(payload or {}))
        if normalized:
            self._state.analysis_sidecar[key] = normalized
        else:
            self._state.analysis_sidecar.pop(key, None)
        self._state.dirty = True
        self._notify("event_analysis_updated", {"event_id": key})

    def open_project(self, path: str) -> UnifiedProjectState:
        loaded = self.store.load(path)
        self._state = clone_project_state(loaded)
        self._state.project_path = str(path)
        self._state.dirty = False
        self._normalize_loaded_state()
        self._notify("project_opened", {"path": str(path)})
        return self.state()

    def save_project(
        self,
        path: str | None = None,
        *,
        embedded_images_input_dir: str | Path | None = None,
    ) -> UnifiedProjectState:
        if path is None and self._state.project_path:
            current = str(self._state.project_path)
            try:
                current_path = Path(current).expanduser().resolve()
            except Exception as exc:
                raise RuntimeError(f"Invalid saved project path: {current}") from exc
            if not current_path.exists():
                raise FileNotFoundError(
                    "The saved project path no longer exists. It may have been renamed, moved, or deleted outside the app. "
                    "Use Save As to choose the current project location."
                )
            if not current_path.is_file():
                raise ValueError(f"Project save target is not a file: {current_path}")
        target = str(
            path
            or self._state.project_path
            or derive_sdproj_filename(
                default_base="session",
                input_dir=getattr(self._state.stack_ref, "input_dir", None),
            )
        )
        self._normalize_loaded_state()
        self.store.save(target, self._state, embedded_images_input_dir=embedded_images_input_dir)
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

    def get_stack_id(self) -> str:
        stack_id = self._state.metadata.get("stack_id")
        if isinstance(stack_id, str) and stack_id:
            return stack_id
        stack_id = self._stack_id_from_stack_ref(self._state.stack_ref)
        self._state.metadata["stack_id"] = stack_id
        return stack_id

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

    def _build_state(self, *, stack_ref: StackRef | None = None) -> UnifiedProjectState:
        return UnifiedProjectState(
            stack_ref=stack_ref,
            events=[],
            active_event_id=None,
            analysis_sidecar={},
            project_path=None,
            dirty=False,
            metadata=self._default_metadata(),
        )

    def _normalize_loaded_state(self) -> None:
        self._state.metadata.setdefault("schema_version", SESSION_SCHEMA_VERSION)
        self._state.metadata.setdefault("session_id", self._new_session_id())
        self._state.metadata.setdefault("persistence_owner", self.store.persistence_owner)
        self._state.metadata.setdefault("analysis_bridge_mode", ANALYSIS_BRIDGE_MODE)
        self._state.metadata.setdefault("analysis_bridge_version", ANALYSIS_BRIDGE_VERSION)
        self._state.metadata.setdefault("stack_id", self._stack_id_from_stack_ref(self._state.stack_ref))
        self._state.events.sort(key=chronological_event_sort_key)
        if self._state.active_event_id is None and self._state.events:
            self._state.active_event_id = str(self._state.events[0].event_id)
        if self._state.analysis_sidecar is None:
            self._state.analysis_sidecar = {}
