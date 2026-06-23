from __future__ import annotations

from collections import OrderedDict


def normalize_overlay_bounds(
    start_idx: int | None, end_idx: int | None, frame_count: int
) -> tuple[int | None, int | None]:
    if frame_count <= 0:
        return None, None
    max_idx = frame_count - 1

    s = None if start_idx is None else max(0, min(int(start_idx), max_idx))
    e = None if end_idx is None else max(0, min(int(end_idx), max_idx))

    if s is not None and e is not None and e < s:
        s, e = e, s
    return s, e


def clamp_popup_range(
    start_idx: int,
    end_idx: int,
    frame_count: int,
    current_idx: int,
    cache: OrderedDict[int, object] | dict[int, object] | None = None,
) -> tuple[int, int, int, list[int]]:
    if frame_count <= 0:
        return 0, 0, 0, []
    max_idx = frame_count - 1
    s = max(0, min(int(start_idx), max_idx))
    e = max(0, min(int(end_idx), max_idx))
    if e < s:
        s, e = e, s

    cur = max(s, min(int(current_idx), e))
    removed: list[int] = []
    if cache is not None:
        for k in list(cache.keys()):
            if k < s or k > e:
                removed.append(int(k))
                cache.pop(k, None)
    return s, e, cur, removed


def linear_value_to_x(value: int, start_idx: int, end_idx: int, width: float) -> float:
    if end_idx <= start_idx or width <= 1:
        return 0.0
    clamped = max(start_idx, min(int(value), end_idx))
    span = float(end_idx - start_idx)
    x = ((clamped - start_idx) / span) * max(1.0, float(width) - 1.0)
    return max(0.0, min(float(width), x))


def linear_x_to_value(x_px: float, width: float, start_idx: int, end_idx: int) -> int:
    if end_idx <= start_idx or width <= 1:
        return int(start_idx)
    frac = max(0.0, min(1.0, float(x_px) / max(1.0, float(width) - 1.0)))
    idx = int(round(start_idx + frac * float(end_idx - start_idx)))
    return max(start_idx, min(end_idx, idx))


def adjust_baseline_end_for_start(
    start_idx: int,
    frame_count: int,
    baseline_end: int,
    force_match_start: bool = False,
) -> tuple[int, bool]:
    if frame_count <= 0:
        return 0, baseline_end != 0
    max_idx = frame_count - 1
    start = max(0, min(int(start_idx), max_idx))
    end = max(0, min(int(baseline_end), max_idx))
    target_end = max(0, start - 1)

    if force_match_start or start <= end:
        return target_end, target_end != end
    return end, False
