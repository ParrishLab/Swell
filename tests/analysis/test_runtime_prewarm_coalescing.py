from __future__ import annotations

import threading

from swell.analysis.controllers.runtime_controller import AnalysisRuntimeController


class _BlockingFrameSource:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.generations: list[int] = []
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def prewarm(self, _indices, *, generation=None, should_continue=None) -> None:
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.generations.append(int(generation))
            call_number = len(self.generations)
        try:
            if call_number == 1:
                self.started.set()
                assert self.release.wait(timeout=2.0)
            if callable(should_continue):
                should_continue()
        finally:
            with self._lock:
                self.active -= 1


class _App:
    def __init__(self, source) -> None:
        self.frame_source = source
        self.current_frame_idx = 0
        self._analysis_prewarm_window = 4
        self._analysis_prewarm_generation = 0
        self._last_prewarm_frame_idx = None
        self.root = None
        self.logs = []

    @staticmethod
    def _get_frame_count() -> int:
        return 100

    def log_debug(self, context, message) -> None:
        self.logs.append((context, message))


def test_navigation_prewarm_coalesces_to_one_worker_and_latest_request() -> None:
    source = _BlockingFrameSource()
    app = _App(source)
    controller = AnalysisRuntimeController(app)

    controller.schedule_analysis_prewarm(1)
    assert source.started.wait(timeout=2.0)

    for idx in range(2, 12):
        controller.schedule_analysis_prewarm(idx)

    source.release.set()
    worker = app._analysis_prewarm_thread
    assert worker is not None
    worker.join(timeout=3.0)

    assert not worker.is_alive()
    assert source.max_active == 1
    assert source.generations == [1, 11]
