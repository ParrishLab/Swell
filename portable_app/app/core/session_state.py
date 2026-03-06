from __future__ import annotations

"""Central mutable session state shared by app workflows."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionState:
    active_event_id: str = "sd_event_001"
    event_states: dict[str, dict[str, Any]] = field(default_factory=dict)
    propagation_committed_snapshot: dict[int, Any] | None = None
    export_range_auto_follow: bool = True
    analysis_range_auto_follow: bool = True
