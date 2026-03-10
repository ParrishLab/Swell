from __future__ import annotations

from dataclasses import asdict
from typing import Callable, Optional

import numpy as np

try:
    from .config import EventCandidate, TraceResult
    from .stack_reader import StackReader
except ImportError:
    from config import EventCandidate, TraceResult
    from stack_reader import StackReader


def compute_trace(
    reader: StackReader,
    seconds_per_frame: Optional[float] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> TraceResult:
    n_frames = reader.get_frame_count()
    means = np.zeros(n_frames, dtype=np.float64)
    medians = np.zeros(n_frames, dtype=np.float64)
    stds = np.zeros(n_frames, dtype=np.float64)

    for idx in range(n_frames):
        frame = reader.read_frame(idx, use_cache=False).astype(np.float64, copy=False)
        means[idx] = float(np.mean(frame))
        medians[idx] = float(np.median(frame))
        stds[idx] = float(np.std(frame))
        if progress_callback is not None and (idx % 50 == 0 or idx == n_frames - 1):
            progress_callback(idx + 1, n_frames)

    frame_indices = list(range(n_frames))
    if seconds_per_frame and seconds_per_frame > 0:
        time_sec = [float(i * seconds_per_frame) for i in frame_indices]
    else:
        time_sec = [None for _ in frame_indices]

    return TraceResult(
        frame_indices=frame_indices,
        time_sec=time_sec,
        mean=means.tolist(),
        median=medians.tolist(),
        std=stds.tolist(),
    )

def event_to_dict(event: EventCandidate) -> dict:
    return asdict(event)
