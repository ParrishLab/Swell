from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sdapp.host.controllers.model_setup_controller import HostModelSetupController
from sdapp.shared.services import CheckpointRuntimeService


class _Root:
    def wait_window(self, _dialog):
        return None


def _build_app(tmp_path: Path, *, model_token: str) -> SimpleNamespace:
    statuses: list[str] = []
    logs_info: list[str] = []
    logs_warn: list[str] = []
    metadata_updates: list[dict] = []
    app = SimpleNamespace()
    app.root = _Root()
    app.checkpoint_runtime = CheckpointRuntimeService()
    app._active_model_token = str(model_token or "")
    app._manual_model_override = None
    app._active_model_path = None
    app._active_checkpoint_id = None
    app._active_model_metadata = None
    app._model_setup_ready = False
    app._model_setup_disabled = False
    app._model_setup_reason = ""
    app._set_status = lambda text: statuses.append(str(text))
    app._log_info = lambda text: logs_info.append(str(text))
    app._log_warn = lambda text: logs_warn.append(str(text))
    app._log_error = lambda _text: None
    app._center_window_on_screen = lambda _window: None
    app._refresh_model_gate_ui = lambda: None
    app.browser_controller = SimpleNamespace(
        set_model_checkpoint_metadata=lambda payload: metadata_updates.append(dict(payload or {}))
    )
    app._status_messages = statuses
    app._info_logs = logs_info
    app._warn_logs = logs_warn
    app._metadata_updates = metadata_updates
    return app


def test_startup_preflight_with_existing_model_sets_ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SDAPP_MODELS_DIR", str((tmp_path / "managed").resolve()))
    model_path = tmp_path / "local_model.pt"
    model_path.write_bytes(b"model")
    app = _build_app(tmp_path, model_token=str(model_path))
    controller = HostModelSetupController(app)

    result = controller.run_startup_preflight()

    assert result["ok"] is True
    assert app._model_setup_ready is True
    assert app._model_setup_disabled is False
    assert app._active_model_path == str(model_path.resolve())
    assert app._metadata_updates


def test_startup_preflight_cancel_enters_review_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SDAPP_MODELS_DIR", str((tmp_path / "managed").resolve()))
    app = _build_app(tmp_path, model_token="")
    controller = HostModelSetupController(app)

    with patch("sdapp.host.controllers.model_setup_controller.messagebox.askyesnocancel", return_value=None):
        result = controller.run_startup_preflight()

    assert result["ok"] is False
    assert app._model_setup_ready is False
    assert app._model_setup_disabled is True
    assert "review-only" in str(app._model_setup_reason).lower()
