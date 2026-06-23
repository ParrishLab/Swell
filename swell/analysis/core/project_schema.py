from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from swell.shared.persistence.event_path import sanitize_event_path_segment


SCHEMA_VERSION = 6


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def default_project_state(app_version: str = "dev") -> Dict[str, Any]:
    now = utc_now_iso()
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": now,
        "last_saved": now,
        "app_version": str(app_version),
        "ui_state": {
            "last_frame": 0,
            "active_event_id": "event_001",
            "active_tool": "select",
            "zoom_level": 1.0,
            "canvas_offset": [0, 0],
            "analysis_start": 1,
            "analysis_end": 1,
            "prop_start": 1,
            "prop_end": 1,
            "export_start": 1,
            "export_end": 1,
        },
        "global": {
            "scale_px_per_mm": None,
            "scale_points": [],
            "scale_axis_lock": True,
            "scale_image_path": "",
            "roi": {"ref": "roi.json"},
            "baseline_frame_count": 30,
        },
        "image_manifest": {"ref": "images.json"},
        "events": [],
    }


def validate_project_state(state: Dict[str, Any]) -> None:
    if not isinstance(state, dict):
        raise ValueError("Project state must be a JSON object.")
    required = ("schema_version", "app_version", "events", "image_manifest")
    missing = [key for key in required if key not in state]
    if missing:
        raise ValueError(f"Project state missing required key(s): {', '.join(missing)}")
    if int(state["schema_version"]) < 1:
        raise ValueError("Invalid schema_version.")
    if not isinstance(state["events"], list):
        raise ValueError("events must be a list.")
    for idx, event in enumerate(state["events"]):
        if not isinstance(event, dict):
            raise ValueError(f"events[{idx}] must be an object.")
        event_id = str(event.get("id", "")).strip()
        if not event_id:
            raise ValueError(f"events[{idx}] missing non-empty id.")
        sanitized = sanitize_event_path_segment(event_id)
        if sanitized != event_id:
            raise ValueError(
                f"events[{idx}].id is not cross-platform filesystem-safe: {event_id!r} (normalized: {sanitized!r})."
            )
        for key in ("masks_ref", "prompts_ref"):
            if key in event and event[key] is not None and not isinstance(event[key], str):
                raise ValueError(f"events[{idx}].{key} must be a string or null.")
        if "masks_draft_ref" in event and event["masks_draft_ref"] is not None and not isinstance(
            event["masks_draft_ref"], str
        ):
            raise ValueError(f"events[{idx}].masks_draft_ref must be a string or null.")
        if "propagation_completed" in event and not isinstance(event["propagation_completed"], bool):
            raise ValueError(f"events[{idx}].propagation_completed must be a boolean.")
        if "analysis_output_dir" in event and event["analysis_output_dir"] is not None and not isinstance(
            event["analysis_output_dir"], str
        ):
            raise ValueError(f"events[{idx}].analysis_output_dir must be a string or null.")
