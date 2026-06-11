from __future__ import annotations

import math

import numpy as np

from sdapp.analysis.core.overlay_state import frame_spans

# --- Tunable constants (calibrate on real SD events) ---------------------
TROUBLE_FLOOR = 0.25       # frames below this are "calm", excluded from regions
LEVERAGE_FLOOR = 0.30      # calibration reference for "clearly actionable" leverage
IOU_WEIGHT = 0.5
CENTROID_WEIGHT = 0.3
AREA_WEIGHT = 0.2
PEAK_BIAS = 0.35           # fraction-of-region offset of the peak, upstream of center
REF_LEN = 8.0              # region length at which the length factor saturates
LENGTH_FLOOR = 0.6         # min length-factor so short sharp jumps aren't crushed
TROUBLE_SAMPLE_MAX = 256   # cap mask dimension for the instability computation


def _mask_stats(mask: np.ndarray) -> tuple[float, float, float] | None:
    """Return (area_px, centroid_x, centroid_y) for a bool 2D mask, or None if empty."""
    m = np.asarray(mask, dtype=bool)
    if m.ndim != 2:
        m = np.squeeze(m)
        if m.ndim != 2:
            return None
    area = float(m.sum())
    if area <= 0.0:
        return None
    ys, xs = np.nonzero(m)
    return area, float(xs.mean()), float(ys.mean())


def _pair_trouble(prev: np.ndarray, cur: np.ndarray, diag: float) -> float:
    """Instability score in [0,1] for one consecutive mask pair."""
    a = np.asarray(prev, dtype=bool)
    b = np.asarray(cur, dtype=bool)
    if a.shape != b.shape:
        return 1.0

    stats_a = _mask_stats(a)
    stats_b = _mask_stats(b)
    if stats_a is None or stats_b is None:
        # One frame empty, the other not -> maximally unstable.
        return 0.0 if (stats_a is None and stats_b is None) else 1.0

    union = float((a | b).sum())
    iou = float((a & b).sum()) / union if union > 0.0 else 1.0
    inst_iou = 1.0 - iou

    area_a, cx_a, cy_a = stats_a
    area_b, cx_b, cy_b = stats_b
    centroid_jump = math.hypot(cx_a - cx_b, cy_a - cy_b) / diag if diag > 0.0 else 0.0
    area_swing = abs(area_a - area_b) / max(area_a, area_b)

    blended = (
        IOU_WEIGHT * inst_iou
        + CENTROID_WEIGHT * min(1.0, centroid_jump)
        + AREA_WEIGHT * min(1.0, area_swing)
    )
    return float(min(1.0, max(0.0, blended)))


def compute_trouble(
    masks: dict[int, np.ndarray],
    frame_count: int,
    frame_shape: tuple[int, int],
    user_frames: set[int],
) -> dict[int, float]:
    """Per-frame temporal-instability score for frames with a mask and >=1 neighbor.

    Masks are downsampled to <= TROUBLE_SAMPLE_MAX per side first — the
    instability metrics are scale-invariant, so this keeps the per-run cost
    bounded regardless of source resolution.
    """
    if frame_count <= 0 or not masks:
        return {}

    sample: dict[int, np.ndarray] = {}
    for f, m in masks.items():
        a = np.asarray(m, dtype=bool)
        if a.ndim != 2:
            a = np.squeeze(a)
            if a.ndim != 2:
                continue
        step = max(1, int(max(a.shape) // TROUBLE_SAMPLE_MAX))
        sample[int(f)] = a[::step, ::step] if step > 1 else a
    if not sample:
        return {}
    diag = math.hypot(*next(iter(sample.values())).shape) or 1.0
    nonempty = {int(f) for f, mask in sample.items() if _mask_stats(mask) is not None}
    if not nonempty:
        return {}

    pair_cache: dict[tuple[int, int], float] = {}

    def pair(i: int, j: int) -> float | None:
        if i not in sample or j not in sample:
            return None
        if i not in nonempty or j not in nonempty:
            return None
        key = (i, j)
        if key not in pair_cache:
            pair_cache[key] = _pair_trouble(sample[i], sample[j], diag)
        return pair_cache[key]

    trouble: dict[int, float] = {}
    for f in sample:
        if not (0 <= int(f) < frame_count):
            continue
        if int(f) not in nonempty:
            continue
        if int(f) in user_frames:
            trouble[int(f)] = 0.0
            continue
        scores = [s for s in (pair(f - 1, f), pair(f, f + 1)) if s is not None]
        if not scores:
            continue
        # A frame is as troubled as its worst transition: a clean one-frame jump
        # is a genuine correction site even though the opposite neighbor is calm.
        trouble[int(f)] = float(max(scores))
    return trouble


def compute_leverage(
    trouble: dict[int, float],
    frame_count: int,
) -> tuple[dict[int, float], int | None]:
    """Group troubled frames into regions and spread an absolute leverage score.

    Returns (leverage_per_frame, suggested_correction_frame).
    """
    if frame_count <= 0 or not trouble:
        return {}, None

    troubled = {f for f, t in trouble.items() if t >= TROUBLE_FLOOR}
    if not troubled:
        return {}, None

    leverage: dict[int, float] = {}
    best_region_leverage = -1.0
    suggested: int | None = None

    for start, end in frame_spans(troubled):
        start = max(0, int(start))
        end = min(frame_count - 1, int(end))
        if end < start:
            continue
        length = end - start + 1
        span_scores = [trouble.get(f, 0.0) for f in range(start, end + 1)]
        mean_trouble = sum(span_scores) / length
        # Length boosts sustained instability but never crushes a short sharp
        # region below LENGTH_FLOOR of its trouble.
        length_factor = LENGTH_FLOOR + (1.0 - LENGTH_FLOOR) * min(1.0, length / REF_LEN)
        region_leverage = mean_trouble * length_factor

        peak = start + int(round((length - 1) * (0.5 - PEAK_BIAS)))
        peak = max(start, min(end, peak))

        for f in range(start, end + 1):
            if length > 1:
                span = max(peak - start, end - peak, 1)
                falloff = 1.0 - (abs(f - peak) / span)
            else:
                falloff = 1.0
            leverage[f] = region_leverage * max(0.0, falloff)

        if region_leverage > best_region_leverage:
            best_region_leverage = region_leverage
            suggested = peak

    # Regions only form from frames above TROUBLE_FLOOR, so the best region is
    # always a real correction site — surface it as the suggested frame.
    return leverage, suggested
