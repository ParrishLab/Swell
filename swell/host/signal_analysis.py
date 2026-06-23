from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    return np.asarray(frame, dtype=np.float32)


def _compute_trace_stats_batch(reader: StackReader, start_idx: int, end_idx: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    frames = [_read_trace_frame(reader, idx) for idx in range(int(start_idx), int(end_idx))]
    if not frames:
        return (
            np.zeros((0,), dtype=np.float32),
            np.zeros((0,), dtype=np.float32),
            np.zeros((0,), dtype=np.float32),
        )
    stack = np.asarray(frames, dtype=np.float32)
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

    batch_size = max(1, min(int(TRACE_BATCH_SIZE), max(1, n_frames)))
    max_workers = min(os.cpu_count() or 4, 8)

    def _process_batch(start_idx: int) -> tuple[int, np.ndarray, np.ndarray, np.ndarray]:
        end_idx = min(n_frames, start_idx + batch_size)
        batch_means, batch_medians, batch_stds = _compute_trace_stats_batch(reader, start_idx, end_idx)
        return int(start_idx), batch_means, batch_medians, batch_stds

    batches = []
    completed_frames = 0
    next_progress_marker = 1
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_process_batch, start_idx) for start_idx in range(0, n_frames, batch_size)]
        for future in as_completed(futures):
            item = future.result()
            batches.append(item)
            completed_frames += int(item[1].shape[0])
            if progress_callback is not None:
                while next_progress_marker <= n_frames and completed_frames >= next_progress_marker:
                    progress_callback(next_progress_marker, n_frames)
                    next_progress_marker += 50
                if completed_frames >= n_frames and (not batches or next_progress_marker - 50 != n_frames):
                    progress_callback(n_frames, n_frames)
                    next_progress_marker = n_frames + 50

    batches.sort(key=lambda item: int(item[0]))
    means = np.concatenate([item[1] for item in batches], axis=0) if batches else np.zeros((0,), dtype=np.float64)
    medians = np.concatenate([item[2] for item in batches], axis=0) if batches else np.zeros((0,), dtype=np.float64)
    stds = np.concatenate([item[3] for item in batches], axis=0) if batches else np.zeros((0,), dtype=np.float64)

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
    label = str(getattr(event, "label", "") or "").strip()
    if label:
        payload["label"] = label
    if event.flags:
        payload["flags"] = dict(event.flags)
    return payload
