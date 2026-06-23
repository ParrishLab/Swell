from __future__ import annotations

from types import SimpleNamespace

from swell.shared.config import AppConfig
from swell.host.controllers.update_controller import HostUpdateController
from swell.shared.services.update_service import ReleaseInfo, UpdateCheckResult


class _Root:
    def __init__(self) -> None:
        self.after_calls: list[tuple[int, object]] = []

    def after(self, delay: int, callback):
        self.after_calls.append((delay, callback))
        return callback


class _Service:
    def __init__(self, result: UpdateCheckResult | None = None):
        self.result = result or UpdateCheckResult(status="current", current_version="0.1.3")
        self.should_auto = True
        self.calls: list[bool] = []
        self.opened: list[str] = []

    def should_check_automatically(self, config: AppConfig) -> bool:  # noqa: ARG002
        return self.should_auto

    def check_for_updates(self, config: AppConfig, *, automatic: bool) -> UpdateCheckResult:  # noqa: ARG002
        self.calls.append(automatic)
        return self.result

    def ignore_release(self, config: AppConfig, version: str) -> None:
        config.ignored_version = version

    def open_release(self, config: AppConfig, release: ReleaseInfo) -> bool:  # noqa: ARG002
        self.opened.append(release.version)
        return True


def _build_app() -> SimpleNamespace:
    config = AppConfig.load()
    config.save = lambda: None
    return SimpleNamespace(root=_Root(), config=config, _log_warn=lambda _msg: None)


def test_schedule_startup_check_only_queues_when_due() -> None:
    app = _build_app()
    service = _Service()
    controller = HostUpdateController(app, service=service)

    controller.schedule_startup_check()

    assert app.root.after_calls
    assert app.root.after_calls[0][0] == 1200


def test_schedule_startup_check_skips_when_not_due() -> None:
    app = _build_app()
    service = _Service()
    service.should_auto = False
    controller = HostUpdateController(app, service=service)

    controller.schedule_startup_check()

    assert app.root.after_calls == []


def test_manual_check_invokes_service_without_automatic_throttling() -> None:
    app = _build_app()
    service = _Service()
    controller = HostUpdateController(app, service=service)

    controller._run_check(automatic=False)

    assert service.calls == [False]
