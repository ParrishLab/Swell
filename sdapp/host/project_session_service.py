from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

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
        payload = dict(self.state().analysis_sidecar.get(str(event_id)) or {})
        if not payload:
            return None
        loaded = dict(payload)
        if "prompts" in loaded and isinstance(loaded.get("prompts"), dict):
            loaded["prompts"] = dict(loaded.get("prompts"))
        if "ui_hints" in loaded and isinstance(loaded.get("ui_hints"), dict):
            loaded["ui_hints"] = dict(loaded.get("ui_hints"))
        if "masks_committed" in loaded and loaded.get("masks_committed") is not None:
            loaded["masks_committed"] = np.asarray(loaded.get("masks_committed")).copy()
        if "masks_draft" in loaded and loaded.get("masks_draft") is not None:
            loaded["masks_draft"] = np.asarray(loaded.get("masks_draft")).copy()
        metrics_settings = loaded.get("metrics_settings")
        if isinstance(metrics_settings, dict):
            copied_metrics = dict(metrics_settings)
            if "roi_mask" in copied_metrics and copied_metrics.get("roi_mask") is not None:
                copied_metrics["roi_mask"] = np.asarray(copied_metrics.get("roi_mask"), dtype=bool).copy()
            loaded["metrics_settings"] = copied_metrics
        return loaded

    def get_session_id(self) -> str:
        return self._service.get_session_id()

    def get_stack_id(self) -> str:
        return self._service.get_stack_id()

    @staticmethod
    def _normalize_metrics_settings(payload: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {}
        normalized: dict[str, Any] = {}
        if "frames_per_sec" in payload:
            try:
                frames_per_sec = float(payload.get("frames_per_sec"))
                if frames_per_sec > 0:
                    normalized["frames_per_sec"] = frames_per_sec
            except (TypeError, ValueError):
                pass
        if "scale_px_per_mm" in payload:
            try:
                scale = float(payload.get("scale_px_per_mm"))
                if scale > 0:
                    normalized["scale_px_per_mm"] = scale
            except (TypeError, ValueError):
                pass
        if "roi_points" in payload:
            roi_points = payload.get("roi_points")
            if isinstance(roi_points, list):
                points: list[list[float]] = []
                for pt in roi_points:
                    if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                        try:
                            points.append([float(pt[0]), float(pt[1])])
                        except (TypeError, ValueError):
                            continue
                if points:
                    normalized["roi_points"] = points
        if "roi_mask" in payload and payload.get("roi_mask") is not None:
            try:
                roi_mask = np.asarray(payload.get("roi_mask"), dtype=bool)
                if roi_mask.ndim == 2:
                    normalized["roi_mask"] = roi_mask.copy()
            except Exception:
                pass
        return normalized

    @staticmethod
    def _has_metrics_value(payload: dict[str, Any], key: str) -> bool:
        if key not in payload:
            return False
        value = payload.get(key)
        if key in {"frames_per_sec", "scale_px_per_mm"}:
            try:
                return float(value) > 0
            except (TypeError, ValueError):
                return False
        if key == "roi_points":
            return isinstance(value, list) and len(value) > 0
        if key == "roi_mask":
            return isinstance(value, np.ndarray) and value.ndim == 2
        return value is not None

    @staticmethod
    def _metrics_values_equal(key: str, lhs: Any, rhs: Any) -> bool:
        if key == "roi_mask":
            return isinstance(lhs, np.ndarray) and isinstance(rhs, np.ndarray) and np.array_equal(lhs, rhs)
        return lhs == rhs

    def _merge_metrics_settings(
        self,
        existing: dict[str, Any] | None,
        incoming: dict[str, Any] | None,
        *,
        merge_missing_only: bool,
    ) -> tuple[dict[str, Any], bool]:
        merged = self._normalize_metrics_settings(existing)
        normalized_incoming = self._normalize_metrics_settings(incoming)
        changed = False
        for key, value in normalized_incoming.items():
            if merge_missing_only and self._has_metrics_value(merged, key):
                continue
            current = merged.get(key)
            if self._metrics_values_equal(key, current, value):
                continue
            if key == "roi_mask":
                merged[key] = np.asarray(value, dtype=bool).copy()
            elif key == "roi_points":
                merged[key] = [[float(pt[0]), float(pt[1])] for pt in list(value)]
            else:
                merged[key] = value
            changed = True
        return merged, changed

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
        defaults = self.get_global_metrics_defaults()
        if not defaults:
            return 0
        applied = 0
        for event in self.state().events:
            changed = self.upsert_event_metrics_settings(
                str(event.event_id),
                defaults,
                merge_missing_only=True,
            )
            if changed:
                applied += 1
        return applied
