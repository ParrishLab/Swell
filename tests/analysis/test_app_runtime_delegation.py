from __future__ import annotations

from swell.analysis.app import SwellAnalysisApp


class _RuntimeStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def set_runtime_status(self, text: str, color: str) -> None:
        self.calls.append(("set_runtime_status", (text, color)))

    def queue_display_update(self, update_preview: bool = True) -> None:
        self.calls.append(("queue_display_update", bool(update_preview)))

    def schedule_analysis_prewarm(self, current_idx: int | None = None) -> None:
        self.calls.append(("schedule_analysis_prewarm", current_idx))


def test_analysis_app_delegates_runtime_methods_to_runtime_controller() -> None:
    app = SwellAnalysisApp.__new__(SwellAnalysisApp)
    runtime = _RuntimeStub()
    app._get_runtime_controller = lambda: runtime

    app._set_runtime_status("Propagating...", "orange")
    app._queue_display_update(update_preview=False)
    app._schedule_analysis_prewarm(current_idx=4)

    assert runtime.calls == [
        ("set_runtime_status", ("Propagating...", "orange")),
        ("queue_display_update", False),
        ("schedule_analysis_prewarm", 4),
    ]
