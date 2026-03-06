from __future__ import annotations

from threading import Event
from time import sleep

import numpy as np

from processing_engine import PopupProcessRequest, PopupProcessingEngine


class SlowReader:
    def __init__(self, frames: list[np.ndarray], delay: float = 0.01):
        self.frames = frames
        self.delay = delay

    def read_frame(self, frame_idx: int, use_cache: bool = True) -> np.ndarray:  # noqa: ARG002
        sleep(self.delay)
        return self.frames[frame_idx]


def test_stale_job_is_canceled_and_latest_completes() -> None:
    frames = [np.full((16, 16), i, dtype=np.uint8) for i in range(60)]
    reader = SlowReader(frames, delay=0.004)
    engine = PopupProcessingEngine(smoothed_cache_max=64)
    engine.set_reader(reader)  # type: ignore[arg-type]

    done = Event()
    completed: list[int] = []

    def callback(result, error):
        assert error is None
        assert result is not None
        completed.append(result.job_id)
        if result.job_id == 2:
            done.set()

    req1 = PopupProcessRequest(1, 0, 40, 10, 12, 18)
    req2 = PopupProcessRequest(2, 5, 45, 10, 14, 20)
    engine.submit_popup_job(req1, callback)
    sleep(0.01)
    engine.submit_popup_job(req2, callback)

    assert done.wait(3.0)
    assert completed[-1] == 2
    assert 2 in completed
