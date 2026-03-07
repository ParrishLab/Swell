import unittest

from app.core.host_handoff import intake_host_handoff_payload, validate_handoff_payload
from seam_contract import ValidatorErrorCode, load_contract_fixture, validate_sync_payload


class HostHandoffContractTests(unittest.TestCase):
    def test_valid_handoff_fixture_is_accepted(self):
        payload = load_contract_fixture("valid_handoff")
        result = validate_handoff_payload(payload)
        self.assertTrue(result["ok"])

    def test_payload_invalid_fixture_is_rejected(self):
        payload = load_contract_fixture("invalid_handoff_payload_invalid")
        result = validate_handoff_payload(payload)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], ValidatorErrorCode.PAYLOAD_INVALID)

    def test_version_mismatch_fixture_is_rejected(self):
        payload = load_contract_fixture("invalid_handoff_version_mismatch")
        result = validate_handoff_payload(payload)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], ValidatorErrorCode.VERSION_MISMATCH)

    def test_raw_false_fixture_is_rejected(self):
        payload = load_contract_fixture("invalid_handoff_raw_false")
        result = validate_handoff_payload(payload)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], ValidatorErrorCode.PAYLOAD_INVALID)

    def test_host_intake_entrypoint_returns_normalized_payload(self):
        payload = load_contract_fixture("valid_handoff")
        result = intake_host_handoff_payload(payload)
        self.assertTrue(result["ok"])
        self.assertIn("normalized", result)

    def test_fixture_sync_version_mismatch_code(self):
        payload = load_contract_fixture("invalid_sync_version_mismatch")
        result = validate_sync_payload(payload)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], ValidatorErrorCode.VERSION_MISMATCH)

    def test_shared_invalid_sync_fixtures_match_expected_codes(self):
        context = {
            "session_id": "session_abc",
            "stack_id": "stack_abc",
            "frame_shape": [64, 64],
            "event_ids": ["event_0001"],
        }
        expected = {
            "invalid_sync_version_mismatch": ValidatorErrorCode.VERSION_MISMATCH,
            "invalid_sync_session_mismatch": ValidatorErrorCode.SESSION_MISMATCH,
            "invalid_sync_stack_mismatch": ValidatorErrorCode.STACK_MISMATCH,
            "invalid_sync_event_not_found": ValidatorErrorCode.EVENT_NOT_FOUND,
            "invalid_sync_mask_shape_mismatch": ValidatorErrorCode.MASK_SHAPE_MISMATCH,
            "invalid_sync_active_set_event_not_found": ValidatorErrorCode.EVENT_NOT_FOUND,
            "invalid_sync_active_set_stack_mismatch": ValidatorErrorCode.STACK_MISMATCH,
        }
        for fixture_name, code in expected.items():
            payload = load_contract_fixture(fixture_name)
            result = validate_sync_payload(payload, context)
            self.assertFalse(result["ok"])
            self.assertEqual(result["code"], code)


if __name__ == "__main__":
    unittest.main()
