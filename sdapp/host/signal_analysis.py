from __future__ import annotations

from typing import Callable, Optional

import numpy as np

from .config import EventCandidate, TraceResult
from .stack_reader import StackReader

TRACE_BATCH_SIZE = 16


def _read_trace_frame(reader: StackReader, frame_idx: int) -> np.ndarray:
    try:
        frame = reader.read_frame(int(frame_idx), use_cache=True)
    except TypeError:
        frame = reader.read_frame(int(frame_idx))
    return np.asarray(frame, dtype=np.float64)


def _compute_trace_stats_batch(reader: StackReader, start_idx: int, end_idx: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    frames = [_read_trace_frame(reader, idx) for idx in range(int(start_idx), int(end_idx))]
    if not frames:
        return (
            np.zeros((0,), dtype=np.float64),
            np.zeros((0,), dtype=np.float64),
            np.zeros((0,), dtype=np.float64),
        )
    stack = np.asarray(frames, dtype=np.float64)
    flattened = stack.reshape(stack.shape[0], -1)
    means = np.mean(flattened, axis=1)
    medians = np.median(flattened, axis=1)
    stds = np.std(flattened, axis=1)
    return means, medians, stds


def compute_trace(
    reader: StackReader,
    seconds_per_frame: Optional[float] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> TraceResult:
    n_frames = reader.get_frame_count()
    means = np.zeros(n_frames, dtype=np.float64)
    medians = np.zeros(n_frames, dtype=np.float64)
    stds = np.zeros(n_frames, dtype=np.float64)

    batch_size = max(1, min(int(TRACE_BATCH_SIZE), max(1, n_frames)))
    for start_idx in range(0, n_frames, batch_size):
        end_idx = min(n_frames, start_idx + batch_size)
        batch_means, batch_medians, batch_stds = _compute_trace_stats_batch(reader, start_idx, end_idx)
        means[start_idx:end_idx] = batch_means
        medians[start_idx:end_idx] = batch_medians
        stds[start_idx:end_idx] = batch_stds
        if progress_callback is not None:
            for idx in range(start_idx, end_idx):
                if idx % 50 == 0 or idx == n_frames - 1:
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
    payload = {
        "event_id": str(event.event_id),
        "start_idx": int(event.start_idx),
        "end_idx": int(event.end_idx),
        "duration_frames": int(event.duration_frames),
        "duration_sec": event.duration_sec,
    }
    if event.flags:
        payload["flags"] = dict(event.flags)
    return payload
