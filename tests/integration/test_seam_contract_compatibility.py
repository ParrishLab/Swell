from __future__ import annotations

from swell.shared.contracts import ValidatorErrorCode, load_contract_fixture, validate_handoff_payload, validate_sync_payload


def test_handoff_invalid_fixture_returns_reserved_code() -> None:
    payload = load_contract_fixture("invalid_handoff_payload_invalid")
    result = validate_handoff_payload(payload)
    assert result["code"] == ValidatorErrorCode.PAYLOAD_INVALID


def test_sync_version_mismatch_returns_reserved_code() -> None:
    payload = load_contract_fixture("invalid_sync_version_mismatch")
    result = validate_sync_payload(payload)
    assert result["code"] == ValidatorErrorCode.VERSION_MISMATCH
