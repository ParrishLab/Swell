from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

try:
    from .host_models import EventMeta, HostSessionState, StackRef
except ImportError:
    from host_models import EventMeta, HostSessionState, StackRef
from sdapp.shared.services import UnifiedProjectService


class ProjectSessionService:
    def __init__(self) -> None:
        self._service = UnifiedProjectService()

    def state(self) -> HostSessionState:
        state = self._service.state()
        return HostSessionState(
            stack_ref=state.stack_ref,
            events=state.events,
            active_event_id=state.active_event_id,
            analysis_sidecar=state.analysis_sidecar,
            project_path=state.project_path,
            dirty=state.dirty,
            metadata=state.metadata,
        )

    def new_project(self, stack_ref: StackRef) -> HostSessionState:
        self._service.new_project(stack_ref)
        return self.state()

    def open_project(self, path: str | Path) -> HostSessionState:
        p = Path(path).expanduser().resolve()
        if p.suffix.lower() != ".sdproj":
            raise ValueError("Unsupported project format. Expected .sdproj")
        self._service.open_project(str(p))
        return self.state()

    def save_project(self, path: str | Path | None = None) -> HostSessionState:
        target = Path(path or self.state().project_path or "session.sdproj").expanduser().resolve()
        if target.suffix.lower() != ".sdproj":
            target = target.with_suffix(".sdproj")
        self._service.save_project(str(target))
        return self.state()

    def set_events(self, events: list[EventMeta], active_event_id: str | None, mark_dirty: bool = True) -> None:
        state = self.state()
        for ev in state.events:
            if str(ev.event_id) not in {str(e.event_id) for e in events}:
                self._service.delete_event(ev.event_id)
        for ev in events:
            self._service.upsert_event(
                EventMeta(
                    event_id=str(ev.event_id),
                    label=str(ev.label),
                    global_start_idx=int(ev.global_start_idx),
                    global_end_idx=int(ev.global_end_idx),
                    flags=dict(ev.flags),
                )
            )
        self._service.set_active_event(active_event_id)
        if not mark_dirty:
            current = self._service.state()
            current.dirty = False
            self._service.replace_state(current, mark_dirty=False)

    def upsert_event_meta(self, event: EventMeta) -> None:
        self._service.upsert_event(event)

    def load_event_meta(self, event_id: str) -> EventMeta | None:
        event = self._service.get_event(event_id)
        if event is None:
            return None
        return EventMeta(**asdict(event))

    def delete_event_meta(self, event_id: str) -> None:
        self._service.delete_event(event_id)

    def set_stack_ref(self, stack_ref: StackRef) -> None:
        state = self._service.state()
        state.stack_ref = stack_ref
        self._service.replace_state(state, mark_dirty=True)

    def set_metadata(self, **kwargs: Any) -> None:
        self._service.set_metadata(**kwargs)

    def set_project_path(self, project_path: str | Path | None) -> HostSessionState:
        state = self._service.state()
        if project_path is None:
            state.project_path = None
            state.metadata.pop("project_path", None)
        else:
            resolved = str(Path(project_path).expanduser().resolve())
            state.project_path = resolved
            state.metadata["project_path"] = resolved
        self._service.replace_state(state, mark_dirty=False)
        return self.state()

    def upsert_analysis_sidecar(self, event_id: str, payload: dict[str, Any]) -> None:
        self._service.update_event_analysis(str(event_id), dict(payload or {}))

    def load_analysis_sidecar(self, event_id: str) -> dict[str, Any] | None:
        analysis = self._service.get_event_analysis(str(event_id))
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
        return self._service.get_stack_id()
