from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from app.core.project_schema import SCHEMA_VERSION


def migrate_project_state(state: Dict[str, Any]) -> Dict[str, Any]:
    migrated = deepcopy(state)
    version = int(migrated.get("schema_version", 1))

    if version < 2:
        migrated["schema_version"] = 2
        version = 2
    if version < 3:
        events = migrated.get("events", [])
        if isinstance(events, list):
            for ev in events:
                if not isinstance(ev, dict):
                    continue
                event_id = str(ev.get("id", "sd_event_001"))
                ev.setdefault("masks_ref", f"events/{event_id}/masks.npz")
                ev.setdefault("prompts_ref", f"events/{event_id}/prompts.json")
                if "propagation_completed" not in ev:
                    ev["propagation_completed"] = bool(ev.get("masks_ref"))
                ev.setdefault("masks_draft_ref", None)
                ev.setdefault("analysis_output_dir", None)
        migrated["schema_version"] = 3
        version = 3

    if version > SCHEMA_VERSION:
        raise ValueError(f"Unsupported schema_version={version}; app supports <= {SCHEMA_VERSION}")

    return migrated
