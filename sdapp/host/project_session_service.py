from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from sdapp.shared.models import clone_analysis_payload
from sdapp.shared.project_naming import derive_sdproj_filename
from sdapp.shared.services import MetricsSettingsResolver, UnifiedProjectService
from sdapp.shared.services import MODEL_CHECKPOINT_METADATA_KEY
from sdapp.shared.trace import TraceAttachment
from sdapp.shared.persistence.schema import METADATA_DC_TRACE_ATTACHMENT_KEY

from .host_models import EventMeta, HostSessionState, StackRef


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
        state = self.state()
        if path is None and state.project_path:
            current = Path(state.project_path).expanduser().resolve()
            if not current.exists():
                raise FileNotFoundError(
                    "The saved project path no longer exists. It may have been renamed, moved, or deleted outside the app. "
                    "Use Save As to choose the current project location."
                )
            if not current.is_file():
                raise ValueError(f"Project save target is not a file: {current}")
        target = Path(
            path
            or state.project_path
            or derive_sdproj_filename(
                default_base="session",
                input_dir=getattr(state.stack_ref, "input_dir", None),
            )
        ).expanduser().resolve()
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
        state.metadata.pop("stack_id", None)
        self._service.replace_state(state, mark_dirty=True)

    def set_metadata(self, **kwargs: Any) -> None:
        self._service.set_metadata(**kwargs)

    def set_model_checkpoint_metadata(self, payload: dict[str, Any] | None) -> None:
        state = self._service.state()
        metadata = dict(state.metadata or {})
        if isinstance(payload, dict) and payload:
            metadata[MODEL_CHECKPOINT_METADATA_KEY] = dict(payload)
        else:
            metadata.pop(MODEL_CHECKPOINT_METADATA_KEY, None)
        state.metadata = metadata
        self._service.replace_state(state, mark_dirty=True)

    def get_model_checkpoint_metadata(self) -> dict[str, Any] | None:
        metadata = dict(self.state().metadata or {})
        value = metadata.get(MODEL_CHECKPOINT_METADATA_KEY)
        if isinstance(value, dict):
            return dict(value)
        return None

    def set_dc_trace_attachment(self, payload: dict[str, Any] | None) -> None:
        state = self._service.state()
        metadata = dict(state.metadata or {})
        normalized = TraceAttachment.from_metadata_dict(dict(payload or {}) if isinstance(payload, dict) else None)
        if normalized is None:
            metadata.pop(METADATA_DC_TRACE_ATTACHMENT_KEY, None)
        else:
            metadata[METADATA_DC_TRACE_ATTACHMENT_KEY] = normalized.to_metadata_dict()
        state.metadata = metadata
        self._service.replace_state(state, mark_dirty=True)

    def get_dc_trace_attachment(self) -> dict[str, Any] | None:
        metadata = dict(self.state().metadata or {})
        value = metadata.get(METADATA_DC_TRACE_ATTACHMENT_KEY)
        normalized = TraceAttachment.from_metadata_dict(dict(value or {}) if isinstance(value, dict) else None)
        if normalized is None:
            return None
        return normalized.to_metadata_dict()

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

    def replace_analysis_sidecar(self, event_id: str, payload: dict[str, Any] | None) -> None:
        self._service.replace_event_analysis(str(event_id), dict(payload or {}) if isinstance(payload, dict) else None)

    def load_analysis_sidecar(self, event_id: str) -> dict[str, Any] | None:
        payload = self._service.get_event_analysis_payload(str(event_id))
        if payload is None:
            return None
        loaded = clone_analysis_payload(payload, coerce_metrics_roi_mask_to_bool=True)
        return loaded or None

    def get_session_id(self) -> str:
        return self._service.get_session_id()

    def get_stack_id(self) -> str:
        return self._service.get_stack_id()

    @staticmethod
    def _normalize_metrics_settings(payload: dict[str, Any] | None) -> dict[str, Any]:
        return dict(MetricsSettingsResolver.normalize(payload))

    def _merge_metrics_settings(
        self,
        existing: dict[str, Any] | None,
        incoming: dict[str, Any] | None,
        *,
        merge_missing_only: bool,
    ) -> tuple[dict[str, Any], bool]:
        merged, changed = MetricsSettingsResolver.merge(
            existing,
            incoming,
            merge_missing_only=bool(merge_missing_only),
        )
        return dict(merged), bool(changed)

    def set_global_metrics_defaults(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize_metrics_settings(payload)
        state = self._service.state()
        metadata = dict(state.metadata or {})
        if normalized:
            metadata["global_metrics_defaults"] = normalized
        else:
            metadata.pop("global_metrics_defaults", None)
        state.metadata = metadata
        self._service.replace_state(state, mark_dirty=True)
        return self.get_global_metrics_defaults()

    def get_global_metrics_defaults(self) -> dict[str, Any]:
        state = self._service.state()
        metadata = dict(state.metadata or {})
        defaults = metadata.get("global_metrics_defaults")
        return self._normalize_metrics_settings(defaults if isinstance(defaults, dict) else {})

    def upsert_event_metrics_settings(
        self,
        event_id: str,
        payload: dict[str, Any],
        *,
        merge_missing_only: bool = False,
    ) -> bool:
        event_key = str(event_id or "")
        if not event_key:
            return False
        if self.load_event_meta(event_key) is None:
            return False
        sidecar = dict(self.load_analysis_sidecar(event_key) or {})
        merged, changed = self._merge_metrics_settings(
            sidecar.get("metrics_settings"),
            payload,
            merge_missing_only=bool(merge_missing_only),
        )
        if not changed:
            return False
        sidecar["metrics_settings"] = merged
        self.upsert_analysis_sidecar(event_key, sidecar)
        return True

    def clear_event_metrics_settings_keys(self, event_id: str, keys: list[str]) -> bool:
        event_key = str(event_id or "")
        if not event_key:
            return False
        if self.load_event_meta(event_key) is None:
            return False
        sidecar = dict(self.load_analysis_sidecar(event_key) or {})
        metrics_settings = dict(sidecar.get("metrics_settings") or {})
        if not metrics_settings:
            return False
        changed = False
        for key in [str(v) for v in list(keys or [])]:
            if key in metrics_settings:
                metrics_settings.pop(key, None)
                changed = True
        if not changed:
            return False
        if metrics_settings:
            sidecar["metrics_settings"] = self._normalize_metrics_settings(metrics_settings)
        else:
            sidecar.pop("metrics_settings", None)
        self.replace_analysis_sidecar(event_key, sidecar)
        return True

    def load_event_metrics_settings(self, event_id: str) -> dict[str, Any] | None:
        sidecar = self.load_analysis_sidecar(str(event_id))
        if not isinstance(sidecar, dict):
            return None
        metrics_settings = sidecar.get("metrics_settings")
        if not isinstance(metrics_settings, dict):
            return None
        return self._normalize_metrics_settings(metrics_settings)

    def resolve_event_metrics_settings(self, event_id: str) -> dict[str, Any]:
        resolved = self.get_global_metrics_defaults()
        local = self.load_event_metrics_settings(str(event_id)) or {}
        merged, _changed = self._merge_metrics_settings(resolved, local, merge_missing_only=False)
        return merged

    def materialize_metrics_defaults_to_events(self) -> int:
        # Global metrics defaults are resolved at read/export/open time and should
        # not be copied into per-event local metrics. Persisting them locally
        # collapses the distinction between global defaults and true event-level
        # overrides, which causes ROI/scale precedence bugs.
        return 0
