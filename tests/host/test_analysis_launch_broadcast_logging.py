from __future__ import annotations

from types import SimpleNamespace

from sdapp.host.controllers.analysis_launch_controller import AnalysisLaunchController


def test_broadcast_checkpoint_update_falls_back_to_info_log_when_debug_logger_missing() -> None:
    logs: list[str] = []
    updates: list[dict] = []
    app = SimpleNamespace(
        _analysis_windows=[(object(), SimpleNamespace(_set_active_checkpoint_metadata=lambda payload, **_kwargs: updates.append(payload)))],
        _log_info=lambda message: logs.append(str(message)),
        _log_warn=lambda _message: None,
    )
    controller = AnalysisLaunchController(app)

    controller.broadcast_checkpoint_update({"checkpoint_id": "abc123"})

    assert updates == [{"checkpoint_id": "abc123"}]
    assert logs and "Broadcasting checkpoint update" in logs[-1]

