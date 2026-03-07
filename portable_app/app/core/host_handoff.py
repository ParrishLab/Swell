from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

try:
    from seam_contract import validate_handoff_payload as _validate_handoff_payload
except ModuleNotFoundError:
    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.append(str(repo_root))
    from seam_contract import validate_handoff_payload as _validate_handoff_payload


def validate_handoff_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return _validate_handoff_payload(payload)


def intake_host_handoff_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Phase-1 host intake gate: validate and return normalized payload only."""
    result = validate_handoff_payload(payload)
    if not bool(result.get("ok")):
        return result
    return {"ok": True, "normalized": result["normalized"]}
