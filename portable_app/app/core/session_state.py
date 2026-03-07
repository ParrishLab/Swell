from __future__ import annotations

"""Central mutable session state shared by app workflows."""

from dataclasses import dataclass, field
from typing import Any

from app.core.project_session import EventRecord


@dataclass
class SessionState:
    active_event_id: str = "sd_event_001"
    event_records: dict[str, EventRecord] = field(default_factory=dict)
    propagation_committed_snapshot: dict[int, Any] | None = None
    export_range_auto_follow: bool = True
    analysis_range_auto_follow: bool = True
