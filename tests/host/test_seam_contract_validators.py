from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import numpy as np

from sdapp.host.browser_controller import BrowserController
from sdapp.host.config import FrameRef
from sdapp.shared.contracts import ValidatorErrorCode, load_contract_fixture, validate_handoff_payload


class _FakeReader:
    def __init__(self) -> None:
        self._frames = [np.zeros((64, 64), dtype=np.uint8), np.ones((64, 64), dtype=np.uint8)]
        self._refs = [
            FrameRef(0, source_path=Path("/tmp/a.tif"), page_index=None, source_ext=".tif", frame_name="a.tif"),
            FrameRef(1, source_path=Path("/tmp/b.tif"), page_index=None, source_ext=".tif", frame_name="b.tif"),
        ]

    def get_frame_count(self) -> int:
        return len(self._frames)

    def get_stack_info(self):
        class _Info:
            frame_height = 64
            frame_width = 64

        return _Info()

    def get_frame_name(self, idx: int) -> str:
        return self._refs[idx].frame_name

    def get_frame_ref(self, idx: int):
        return self._refs[idx]

    def read_frame(self, idx: int, use_cache: bool = True):  # noqa: ARG002
        return self._frames[idx]


class _FakeStackInfo:
    input_dir = "/tmp/in"
    frame_count = 2
    frame_height = 64
    frame_width = 64
    dtype = "uint8"


def _controller_with_event() -> BrowserController:
    c = BrowserController()
    c.on_stack_loaded(_FakeReader(), _FakeStackInfo())
    ev = c.create_event(start_idx=0, end_idx=1, frame_count=2)
    c.set_active_event(ev.event_id)
    return c


def _sync_payload_for_context(c: BrowserController) -> dict:
    payload = load_contract_fixture("valid_sync")
    payload = deepcopy(payload)
    payload["session_id"] = c.session.get_session_id()
    payload["stack_id"] = c.session.get_stack_id()
    payload["event_id"] = c.events.get_active_event_id()
    payload["analysis_state_ref"]["ref_id"] = f"{payload['session_id']}:{payload['event_id']}"
    return payload


def test_validate_handoff_invalid_fixture_returns_payload_invalid() -> None:
    payload = load_contract_fixture("invalid_handoff_payload_invalid")
    result = validate_handoff_payload(payload)
    assert result["ok"] is False
    assert result["code"] == ValidatorErrorCode.PAYLOAD_INVALID


def test_validate_sync_payload_accepts_valid_contextual_payload() -> None:
    c = _controller_with_event()
    payload = _sync_payload_for_context(c)
    result = c.validate_sync_payload(payload)
    assert result["ok"] is True
    applied = c.apply_analysis_sync(payload)
    assert applied["ok"] is True
    assert c.session.load_analysis_sidecar(payload["event_id"]) is not None


def test_validate_sync_payload_invalid_fixture_returns_payload_invalid() -> None:
    c = _controller_with_event()
    payload = load_contract_fixture("invalid_sync_payload_invalid")
    payload = deepcopy(payload)
    payload["session_id"] = c.session.get_session_id()
    payload["stack_id"] = c.session.get_stack_id()
    payload["event_id"] = c.events.get_active_event_id()
    result = c.validate_sync_payload(payload)
    assert result["ok"] is False
    assert result["code"] == ValidatorErrorCode.PAYLOAD_INVALID


def test_validate_sync_payload_rejects_version_mismatch() -> None:
    c = _controller_with_event()
    payload = load_contract_fixture("invalid_sync_version_mismatch")
    payload = deepcopy(payload)
    payload["session_id"] = c.session.get_session_id()
    payload["stack_id"] = c.session.get_stack_id()
    payload["event_id"] = c.events.get_active_event_id()
    result = c.validate_sync_payload(payload)
    assert result["ok"] is False
    assert result["code"] == ValidatorErrorCode.VERSION_MISMATCH


def test_validate_sync_payload_rejects_session_mismatch() -> None:
    c = _controller_with_event()
    payload = load_contract_fixture("invalid_sync_session_mismatch")
    payload = deepcopy(payload)
    payload["stack_id"] = c.session.get_stack_id()
    payload["event_id"] = c.events.get_active_event_id()
    result = c.validate_sync_payload(payload)
    assert result["ok"] is False
    assert result["code"] == ValidatorErrorCode.SESSION_MISMATCH


def test_validate_sync_payload_rejects_stack_mismatch() -> None:
    c = _controller_with_event()
    payload = load_contract_fixture("invalid_sync_stack_mismatch")
    payload = deepcopy(payload)
    payload["session_id"] = c.session.get_session_id()
    payload["event_id"] = c.events.get_active_event_id()
    result = c.validate_sync_payload(payload)
    assert result["ok"] is False
    assert result["code"] == ValidatorErrorCode.STACK_MISMATCH


def test_validate_sync_payload_rejects_event_not_found() -> None:
    c = _controller_with_event()
    payload = load_contract_fixture("invalid_sync_event_not_found")
    payload = deepcopy(payload)
    payload["session_id"] = c.session.get_session_id()
    payload["stack_id"] = c.session.get_stack_id()
    result = c.validate_sync_payload(payload)
    assert result["ok"] is False
    assert result["code"] == ValidatorErrorCode.EVENT_NOT_FOUND


def test_validate_sync_payload_rejects_mask_shape_mismatch() -> None:
    c = _controller_with_event()
    payload = load_contract_fixture("invalid_sync_mask_shape_mismatch")
    payload = deepcopy(payload)
    payload["session_id"] = c.session.get_session_id()
    payload["stack_id"] = c.session.get_stack_id()
    payload["event_id"] = c.events.get_active_event_id()
    result = c.validate_sync_payload(payload)
    assert result["ok"] is False
    assert result["code"] == ValidatorErrorCode.MASK_SHAPE_MISMATCH


def test_shared_invalid_sync_fixtures_match_expected_codes() -> None:
    c = _controller_with_event()
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
        payload = deepcopy(load_contract_fixture(fixture_name))
        if fixture_name not in ("invalid_sync_session_mismatch",):
            payload["session_id"] = c.session.get_session_id()
        if fixture_name not in ("invalid_sync_stack_mismatch", "invalid_sync_active_set_stack_mismatch"):
            payload["stack_id"] = c.session.get_stack_id()
        if fixture_name not in ("invalid_sync_event_not_found", "invalid_sync_active_set_event_not_found"):
            payload["event_id"] = c.events.get_active_event_id()
        result = c.validate_sync_payload(payload)
        assert result["ok"] is False
        assert result["code"] == code
