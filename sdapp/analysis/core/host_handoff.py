from __future__ import annotations

from typing import Any

from sdapp.shared.contracts import validate_handoff_payload as _validate_handoff_payload


def validate_handoff_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return _validate_handoff_payload(payload)


def intake_host_handoff_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Phase-1 host intake gate: validate and return normalized payload only."""
    result = validate_handoff_payload(payload)
    if not bool(result.get("ok")):
        return result
    return {"ok": True, "normalized": result["normalized"]}
