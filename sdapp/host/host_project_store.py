from __future__ import annotations

from pathlib import Path

try:
    from .host_models import HostSessionState
except ImportError:
    from host_models import HostSessionState
from sdapp.shared.persistence import (
    HOST_PROJECT_SCHEMA_VERSION,
    HOST_PERSISTENCE_OWNER,
    UnifiedProjectStore,
)


def _as_host_state(state) -> HostSessionState:
    return HostSessionState(
        active_sd_set_id=state.active_sd_set_id,
        sd_sets=state.sd_sets,
        project_path=state.project_path,
        dirty=state.dirty,
        metadata=state.metadata,
    )


class HostProjectStore(UnifiedProjectStore):
    def load(self, source_path: str | Path) -> HostSessionState:
        return _as_host_state(super().load(source_path))

    def load_legacy_sdsession(self, source_path: str | Path) -> HostSessionState:
        return _as_host_state(super().load_legacy_sdsession(source_path))

    def load_legacy_sdproj(self, source_path: str | Path) -> HostSessionState:
        return _as_host_state(super().load_legacy_portable_sdproj(source_path))
