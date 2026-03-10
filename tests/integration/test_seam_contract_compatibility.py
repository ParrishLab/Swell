from __future__ import annotations

from seam_contract import ValidatorErrorCode as LegacyCode
from seam_contract import load_contract_fixture as legacy_load_fixture
from seam_contract import validate_handoff_payload as legacy_validate_handoff
from seam_contract import validate_sync_payload as legacy_validate_sync
from sdapp.shared.contracts import ValidatorErrorCode, load_contract_fixture, validate_handoff_payload, validate_sync_payload


def test_seam_contract_wrapper_parity_for_handoff_invalid_fixture() -> None:
    payload = legacy_load_fixture("invalid_handoff_payload_invalid")
    legacy = legacy_validate_handoff(payload)
    shared = validate_handoff_payload(payload)
    assert legacy == shared
    assert shared["code"] == ValidatorErrorCode.PAYLOAD_INVALID


def test_seam_contract_wrapper_parity_for_sync_version_mismatch() -> None:
    payload = load_contract_fixture("invalid_sync_version_mismatch")
    legacy = legacy_validate_sync(payload)
    shared = validate_sync_payload(payload)
    assert legacy == shared
    assert shared["code"] == ValidatorErrorCode.VERSION_MISMATCH
    assert shared["code"] == LegacyCode.VERSION_MISMATCH
