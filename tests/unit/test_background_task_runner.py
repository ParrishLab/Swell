from __future__ import annotations

import threading

from swell.shared.ui import BackgroundTaskRunner


class _Root:
    def __init__(self) -> None:
        self.after_calls: list[int] = []

    def after(self, delay: int, callback):
        self.after_calls.append(int(delay))
        callback()
        return callback


def test_background_task_runner_dispatches_success_to_ui() -> None:
    root = _Root()
    runner = BackgroundTaskRunner(root)
    seen: list[str] = []
    done = threading.Event()

    runner.start(
        lambda: "ok",
        on_success=lambda result: (seen.append(str(result)), done.set()),
    )

    assert done.wait(timeout=1.0)
    assert seen == ["ok"]
    assert root.after_calls == [0]


def test_background_task_runner_dispatches_error_to_ui() -> None:
    root = _Root()
    runner = BackgroundTaskRunner(root)
    seen: list[str] = []
    done = threading.Event()

    def _boom():
        raise RuntimeError("fail")

    runner.start(
        _boom,
        on_error=lambda exc: (seen.append(str(exc)), done.set()),
    )

    assert done.wait(timeout=1.0)
    assert seen == ["fail"]
    assert root.after_calls == [0]


def test_background_task_runner_can_drop_duplicate_keyed_work() -> None:
    root = _Root()
    runner = BackgroundTaskRunner(root)
    release = threading.Event()

    def _block():
        release.wait(timeout=1.0)

    first = runner.start(_block, key="job", drop_if_running=True)
    second = runner.start(lambda: None, key="job", drop_if_running=True)
    assert first is not None
    assert second is None

    release.set()
    first.join(timeout=1.0)
    assert runner.is_running("job") is False
