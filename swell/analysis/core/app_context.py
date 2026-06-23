from __future__ import annotations

"""Container for runtime service dependencies used by workflow modules."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class AppContext:
    app_root: Path
    project_store: Any
    project_session_service: Any
    mask_import_dialog: Any
    autosave_manager: Any
    session_state: Any | None = None
    analysis_workspace: Any | None = None
    frame_source: Any | None = None
    inference_manager: Any | None = None
    analysis_controller: Any | None = None
    host_handoff: Any | None = None
    host_sync_emitter: Any | None = None
