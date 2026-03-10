from __future__ import annotations

from pathlib import Path

try:
    from .host_models import HostSessionState
except ImportError:
    from host_models import HostSessionState
from sdapp.shared.persistence import HOST_PROJECT_SCHEMA_VERSION, HOST_PERSISTENCE_OWNER, UnifiedProjectStore


def _as_host_state(state) -> HostSessionState:
    return HostSessionState(
        stack_ref=state.stack_ref,
        events=state.events,
        active_event_id=state.active_event_id,
        analysis_sidecar=state.analysis_sidecar,
        project_path=state.project_path,
        dirty=state.dirty,
        metadata=state.metadata,
    )


class HostProjectStore(UnifiedProjectStore):
    def load(self, source_path: str | Path) -> HostSessionState:
        return _as_host_state(super().load(source_path))
