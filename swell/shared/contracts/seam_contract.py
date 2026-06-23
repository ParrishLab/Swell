from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any

CONTRACT_VERSION = 1


class ValidatorErrorCode(StrEnum):
    VERSION_MISMATCH = "VERSION_MISMATCH"
    SESSION_MISMATCH = "SESSION_MISMATCH"
    STACK_MISMATCH = "STACK_MISMATCH"
    EVENT_NOT_FOUND = "EVENT_NOT_FOUND"
    MASK_SHAPE_MISMATCH = "MASK_SHAPE_MISMATCH"
    PAYLOAD_INVALID = "PAYLOAD_INVALID"


def ok(normalized: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "normalized": normalized}


def err(code: ValidatorErrorCode | str, message: str) -> dict[str, Any]:
    return {"ok": False, "code": str(code), "message": str(message)}


def load_contract_fixture(name: str) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[3]
    fixture_path = repo_root / "seam_contract_fixtures" / f"{name}.json"
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def _expect_dict(payload: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(f"{field} must be an object")
    return payload


def _expect_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _expect_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return int(value)


def _expect_bool(payload: dict[str, Any], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return bool(value)


def _expect_list(payload: dict[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list")
    return value


def _expect_optional_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string or null")
    return value


def _expect_contract_version(payload: dict[str, Any]) -> int:
    version = payload.get("contract_version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise ValueError("contract_version must be an integer")
    if int(version) != CONTRACT_VERSION:
        raise RuntimeError(ValidatorErrorCode.VERSION_MISMATCH)
    return int(version)


def _normalize_frame_shape(shape_value: Any) -> list[int]:
    if not isinstance(shape_value, (list, tuple)) or len(shape_value) != 2:
        raise ValueError("frame_shape must be a two-item list")
    height = shape_value[0]
    width = shape_value[1]
    if isinstance(height, bool) or isinstance(width, bool) or not isinstance(height, int) or not isinstance(width, int):
        raise ValueError("frame_shape values must be integers")
    if int(height) < 0 or int(width) < 0:
        raise ValueError("frame_shape values must be >= 0")
    return [int(height), int(width)]


def _normalize_analysis_state_ref(payload: dict[str, Any]) -> dict[str, Any]:
    ref = _expect_dict(payload.get("analysis_state_ref"), field="analysis_state_ref")
    storage = _expect_str(ref, "storage")
    if storage != "host_session":
        raise ValueError("analysis_state_ref.storage must be 'host_session'")
    ref_id = _expect_str(ref, "ref_id")
    return {"storage": storage, "ref_id": ref_id}


def validate_handoff_payload(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        root = _expect_dict(payload, field="payload")
        contract_version = _expect_contract_version(root)

        session = _expect_dict(root.get("session"), field="session")
        session_norm = {
            "session_id": _expect_str(session, "session_id"),
            "project_path": _expect_optional_str(session, "project_path"),
            "active_event_id": _expect_str(session, "active_event_id"),
            "dirty": _expect_bool(session, "dirty"),
            "metadata": _expect_dict(session.get("metadata"), field="metadata"),
        }

        stack = _expect_dict(root.get("stack"), field="stack")
        capabilities = _expect_dict(stack.get("capabilities"), field="capabilities")
        raw_capability = _expect_bool(capabilities, "raw")
        if not raw_capability:
            raise ValueError("capabilities.raw must be true")
        stack_norm = {
            "stack_id": _expect_str(stack, "stack_id"),
            "frame_count": _expect_int(stack, "frame_count"),
            "frame_shape": _normalize_frame_shape(stack.get("frame_shape")),
            "frame_names": [str(v) for v in _expect_list(stack, "frame_names")],
            "source_paths": [str(v) for v in _expect_list(stack, "source_paths")],
            "capabilities": {
                "raw": raw_capability,
                "subtracted": _expect_bool(capabilities, "subtracted"),
                "visual": _expect_bool(capabilities, "visual"),
            },
        }

        event = _expect_dict(root.get("event"), field="event")
        start_idx = _expect_int(event, "start_idx")
        end_idx = _expect_int(event, "end_idx")
        if end_idx < start_idx:
            start_idx, end_idx = end_idx, start_idx
        event_norm = {
            "event_id": _expect_str(event, "event_id"),
            "label": _expect_str(event, "label"),
            "start_idx": start_idx,
            "end_idx": end_idx,
            "flags": _expect_dict(event.get("flags", {}), field="flags"),
        }

        normalized = {
            "contract_version": contract_version,
            "session": session_norm,
            "stack": stack_norm,
            "event": event_norm,
            "analysis_state_ref": _normalize_analysis_state_ref(root),
        }
        return ok(normalized)
    except RuntimeError as exc:
        if exc.args and exc.args[0] == ValidatorErrorCode.VERSION_MISMATCH:
            return err(ValidatorErrorCode.VERSION_MISMATCH, "contract_version does not match v1")
        return err(ValidatorErrorCode.PAYLOAD_INVALID, str(exc))
    except Exception as exc:  # noqa: BLE001
        return err(ValidatorErrorCode.PAYLOAD_INVALID, str(exc))


def _validate_sync_shapes(analysis: dict[str, Any], active_context: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    masks_committed = _expect_dict(analysis.get("masks_committed"), field="masks_committed")
    masks_shape = _normalize_frame_shape(masks_committed.get("shape"))
    masks_norm = {
        "encoding": _expect_str(masks_committed, "encoding"),
        "frame_count": _expect_int(masks_committed, "frame_count"),
        "shape": masks_shape,
        "blob_ref": _expect_str(masks_committed, "blob_ref"),
    }

    masks_draft = analysis.get("masks_draft")
    if masks_draft is not None:
        masks_draft = _expect_dict(masks_draft, field="masks_draft")

    prompts = _expect_dict(analysis.get("prompts"), field="prompts")
    prompts_norm = {
        "encoding": _expect_str(prompts, "encoding"),
        "blob_ref": _expect_str(prompts, "blob_ref"),
    }

    if active_context is not None:
        expected_shape = _normalize_frame_shape(active_context.get("frame_shape"))
        if expected_shape != masks_shape:
            raise RuntimeError(ValidatorErrorCode.MASK_SHAPE_MISMATCH)

    return {
        "masks_committed": masks_norm,
        "masks_draft": masks_draft,
        "prompts": prompts_norm,
        "propagation_completed": _expect_bool(analysis, "propagation_completed"),
        "analysis_output_dir": _expect_optional_str(analysis, "analysis_output_dir"),
    }, masks_draft


def validate_sync_payload(payload: dict[str, Any], active_context: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        root = _expect_dict(payload, field="payload")
        contract_version = _expect_contract_version(root)
        session_id = _expect_str(root, "session_id")
        stack_id = _expect_str(root, "stack_id")
        event_id = _expect_str(root, "event_id")

        if active_context is not None:
            expected_session_id = str(active_context.get("session_id", ""))
            expected_stack_id = str(active_context.get("stack_id", ""))
            event_ids = {str(v) for v in active_context.get("event_ids", [])}

            if expected_session_id and session_id != expected_session_id:
                raise RuntimeError(ValidatorErrorCode.SESSION_MISMATCH)
            if expected_stack_id and stack_id != expected_stack_id:
                raise RuntimeError(ValidatorErrorCode.STACK_MISMATCH)
            if event_ids and event_id not in event_ids:
                raise RuntimeError(ValidatorErrorCode.EVENT_NOT_FOUND)

        analysis = _expect_dict(root.get("analysis"), field="analysis")
        analysis_norm, _ = _validate_sync_shapes(analysis, active_context)

        ui_hints = root.get("ui_hints")
        if ui_hints is not None:
            ui_hints = _expect_dict(ui_hints, field="ui_hints")

        normalized = {
            "contract_version": contract_version,
            "session_id": session_id,
            "stack_id": stack_id,
            "event_id": event_id,
            "analysis_state_ref": _normalize_analysis_state_ref(root),
            "analysis": analysis_norm,
            "ui_hints": ui_hints,
        }
        return ok(normalized)
    except RuntimeError as exc:
        code = exc.args[0] if exc.args else ValidatorErrorCode.PAYLOAD_INVALID
        if code == ValidatorErrorCode.VERSION_MISMATCH:
            return err(ValidatorErrorCode.VERSION_MISMATCH, "contract_version does not match v1")
        if code == ValidatorErrorCode.SESSION_MISMATCH:
            return err(ValidatorErrorCode.SESSION_MISMATCH, "session_id does not match active host session")
        if code == ValidatorErrorCode.STACK_MISMATCH:
            return err(ValidatorErrorCode.STACK_MISMATCH, "stack_id does not match active host stack")
        if code == ValidatorErrorCode.EVENT_NOT_FOUND:
            return err(ValidatorErrorCode.EVENT_NOT_FOUND, "event_id not found in host event catalog")
        if code == ValidatorErrorCode.MASK_SHAPE_MISMATCH:
            return err(ValidatorErrorCode.MASK_SHAPE_MISMATCH, "mask shape does not match host frame_shape")
        return err(ValidatorErrorCode.PAYLOAD_INVALID, str(exc))
    except Exception as exc:  # noqa: BLE001
        return err(ValidatorErrorCode.PAYLOAD_INVALID, str(exc))
