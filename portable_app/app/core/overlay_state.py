from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass
class OverlayState:
    propagated_history_indices: set[int]
    largest_propagated_span: tuple[int, int] | None
    propagated_frame_indices: set[int]
    propagated_frame_spans: list[tuple[int, int]]


def frame_spans(indices: Iterable[int]) -> list[tuple[int, int]]:
    clean = sorted({int(i) for i in indices})
    if not clean:
        return []
    spans: list[tuple[int, int]] = []
    start = clean[0]
    end = start
    for idx in clean[1:]:
        if idx == end + 1:
            end = idx
        else:
            spans.append((start, end))
            start = idx
            end = idx
    spans.append((start, end))
    return spans


def span_length(span: tuple[int, int] | None) -> int:
    if span is None:
        return 0
    return max(0, int(span[1]) - int(span[0]) + 1)


def largest_contiguous_span(indices: Iterable[int]) -> tuple[int, int] | None:
    spans = frame_spans(indices)
    if not spans:
        return None
    largest = spans[0]
    largest_len = span_length(largest)
    for span in spans[1:]:
        cur_len = span_length(span)
        if cur_len > largest_len:
            largest = span
            largest_len = cur_len
    return largest


def compute_propagated_state(
    indices: Iterable[int],
    previous_history_indices: Iterable[int],
    frame_count: int,
) -> OverlayState:
    max_idx = max(0, int(frame_count) - 1)
    cleaned = {int(idx) for idx in indices if 0 <= int(idx) <= max_idx}
    previous = {int(idx) for idx in previous_history_indices if 0 <= int(idx) <= max_idx}
    history = previous | cleaned
    largest = largest_contiguous_span(history)
    if largest is None:
        propagated = set()
    else:
        propagated = set(range(int(largest[0]), int(largest[1]) + 1))
    return OverlayState(
        propagated_history_indices=history,
        largest_propagated_span=largest,
        propagated_frame_indices=propagated,
        propagated_frame_spans=frame_spans(propagated),
    )
