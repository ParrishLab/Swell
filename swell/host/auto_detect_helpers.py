from __future__ import annotations

from typing import Any

import numpy as np

from swell.shared.frame_source import normalize_visual_frame
from swell.shared.frame_source.preprocessing import _sample_percentile_pixels, finite_percentile_bounds

from .event_detection import detector as _detector


def normalize_to_uint8(frame: np.ndarray) -> np.ndarray:
    arr = np.asarray(frame, dtype=np.float32)
    sample = _sample_percentile_pixels(arr)
    p1, p99 = finite_percentile_bounds(sample, max_pixels=max(1, int(sample.size)))
    return normalize_visual_frame(arr, p1=p1, p99=p99)


def detail_window_bounds(frame_count: int, center_frame: int, half_width: int) -> tuple[int, int]:
    fc = int(frame_count)
    if fc <= 1:
        return 0, 0
    half = max(1, int(half_width))
    center = int(center_frame)
    start = max(0, center - half)
    end = min(fc - 1, center + half)
    if end - start < 1:
        end = min(fc - 1, start + 1)
        start = max(0, end - 1)
    return start, end


def frame_from_overview_x(x: float, *, canvas_width: int, frame_count: int) -> int:
    cw = max(1, int(canvas_width))
    fc = int(frame_count)
    if fc <= 1:
        return 0
    return int(max(0, min(fc - 1, round((float(x) / cw) * (fc - 1)))))


def frame_from_detail_x(
    x: float,
    *,
    canvas_width: int,
    window_bounds: tuple[int, int],
    frame_count: int,
) -> int:
    cw = max(1, int(canvas_width))
    fc = int(frame_count)
    if fc <= 1:
        return 0
    win_start, win_end = (int(window_bounds[0]), int(window_bounds[1]))
    span = max(1, win_end - win_start)
    return int(max(win_start, min(win_end, round(win_start + (float(x) / cw) * span))))


def detail_x_from_frame(frame: int, *, canvas_width: int, window_bounds: tuple[int, int]) -> float | None:
    win_start, win_end = (int(window_bounds[0]), int(window_bounds[1]))
    frame = int(frame)
    if frame < win_start or frame > win_end:
        return None
    span = max(1, win_end - win_start)
    return (float(frame) - win_start) / span * max(1, int(canvas_width))


def overview_x_from_frame(frame: int, *, canvas_width: int, frame_count: int) -> float:
    fc = int(frame_count)
    if fc <= 1:
        return 0.0
    return (int(frame) / (fc - 1)) * max(1, int(canvas_width))


def grid_bounds_for_layout(
    layout: tuple[int, int, int, int, int, int],
    extraction: Any | None,
) -> tuple[int, int, int, int] | None:
    _cw, _ch, dw, dh, ox, oy = layout
    if extraction is None:
        return ox, oy, dw, dh
    geometry = extraction.geometry
    resized_h, resized_w = geometry.resized_shape
    if resized_h <= 0 or resized_w <= 0:
        return None
    crop_y0, crop_y1, crop_x0, crop_x1 = geometry.crop_box
    grid_x = ox + int(round(crop_x0 * dw / resized_w))
    grid_y = oy + int(round(crop_y0 * dh / resized_h))
    grid_w = max(1, int(round((crop_x1 - crop_x0) * dw / resized_w)))
    grid_h = max(1, int(round((crop_y1 - crop_y0) * dh / resized_h)))
    return grid_x, grid_y, grid_w, grid_h


def frame_index_position(frame_indices: np.ndarray, frame: int) -> int | None:
    matches = np.flatnonzero(np.asarray(frame_indices) == int(frame))
    if matches.size == 0:
        return None
    return int(matches[0])


def onset_active_window(detrended: np.ndarray, start_idx: int, end_idx: int, params: dict) -> np.ndarray:
    window_len = max(0, int(end_idx) - int(start_idx) + 1)
    if window_len <= 0:
        return np.zeros((int(detrended.shape[0]), 0), dtype=bool)
    diffs = np.diff(np.asarray(detrended), axis=1)
    if diffs.shape[1] == 0:
        return np.zeros((int(detrended.shape[0]), window_len), dtype=bool)
    diff_center = np.nanmedian(diffs, axis=1, keepdims=True)
    mads = np.nanmedian(np.abs(diffs - diff_center), axis=1)

    polarity = params.get("polarity", "positive")
    k_mad = float(params.get("diff_k_mad", 2.5))
    persistence_frames = int(params.get("persistence_frames", 1))

    if polarity == "positive":
        active_diffs = diffs > (k_mad * mads[:, np.newaxis])
    elif polarity == "negative":
        active_diffs = diffs < -(k_mad * mads[:, np.newaxis])
    elif polarity in ("absolute", "both"):
        active_diffs = np.abs(diffs) > (k_mad * mads[:, np.newaxis])
    else:
        active_diffs = diffs > (k_mad * mads[:, np.newaxis])

    if persistence_frames > 1:
        from scipy.ndimage import binary_erosion

        structure = np.ones((1, persistence_frames), dtype=bool)
        active_diffs = binary_erosion(active_diffs, structure=structure)

    active_window = np.zeros((int(detrended.shape[0]), window_len), dtype=bool)
    for out_idx, frame_pos in enumerate(range(int(start_idx), int(end_idx) + 1)):
        diff_idx = frame_pos - 1
        if 0 <= diff_idx < active_diffs.shape[1]:
            active_window[:, out_idx] = active_diffs[:, diff_idx]
    return active_window


def active_cells_cache_key(
    *,
    selected_index: int,
    start_idx: int,
    end_idx: int,
    detrended: np.ndarray,
    frame_indices: np.ndarray,
    params: dict,
) -> tuple:
    return (
        "combined",
        int(selected_index),
        int(start_idx),
        int(end_idx),
        float(params.get("coherence_active_threshold_mad", 10.0)),
        int(params.get("quiet_pre_frames", 200)),
        float(params.get("diff_k_mad", 2.5)),
        params.get("polarity", "positive"),
        int(params.get("persistence_frames", 1)),
        id(detrended),
        id(frame_indices),
    )


def active_cells_for_frame(
    *,
    selected_cand: dict | None,
    selected_index: int | None,
    frame_idx: int,
    detrended: np.ndarray | None,
    frame_indices: np.ndarray | None,
    params: dict,
    cache: dict[tuple, tuple[int, int, np.ndarray]],
) -> np.ndarray | None:
    if selected_cand is None or selected_index is None or detrended is None or frame_indices is None:
        return None
    if detrended.ndim != 2 or frame_indices.ndim != 1 or detrended.shape[1] != frame_indices.size:
        return None
    try:
        start_frame = int(selected_cand["start_frame"])
        end_frame = int(selected_cand["end_frame"])
    except Exception:
        return None

    frame_pos = frame_index_position(frame_indices, int(frame_idx))
    start_idx = frame_index_position(frame_indices, start_frame)
    end_idx = frame_index_position(frame_indices, end_frame)
    if frame_pos is None or start_idx is None or end_idx is None:
        return None
    if end_idx < start_idx:
        start_idx, end_idx = end_idx, start_idx
    if frame_pos < start_idx or frame_pos > end_idx:
        return None

    cache_key = active_cells_cache_key(
        selected_index=int(selected_index),
        start_idx=start_idx,
        end_idx=end_idx,
        detrended=detrended,
        frame_indices=frame_indices,
        params=params,
    )
    cached = cache.get(cache_key)
    if cached is None:
        active_threshold = float(params.get("coherence_active_threshold_mad", 10.0))
        quiet_pre_frames = int(params.get("quiet_pre_frames", 200))
        polarity = params.get("polarity", "positive")
        mad = _detector.quiet_mad(detrended, start_idx, quiet_pre_frames=quiet_pre_frames)
        norm = detrended[:, start_idx : end_idx + 1] / mad[:, np.newaxis]
        if polarity == "positive":
            participation_window = norm > active_threshold
        elif polarity == "negative":
            participation_window = norm < -active_threshold
        elif polarity in ("absolute", "both"):
            participation_window = np.abs(norm) > active_threshold
        else:
            participation_window = norm > active_threshold
        cached = (start_idx, end_idx, participation_window | onset_active_window(detrended, start_idx, end_idx, params))
        cache[cache_key] = cached
    cached_start, cached_end, active_window = cached
    if frame_pos < cached_start or frame_pos > cached_end:
        return None
    return np.asarray(active_window[:, frame_pos - cached_start], dtype=bool)


def cell_border_rects_for_layout(
    *,
    layout: tuple[int, int, int, int, int, int],
    extraction: Any | None,
    grid_density: int,
) -> list[tuple[int, int, int, int]]:
    if extraction is None:
        return []
    grid_bounds = grid_bounds_for_layout(layout, extraction)
    if grid_bounds is None:
        return []
    grid_x, grid_y, grid_w, grid_h = grid_bounds

    rects: list[tuple[int, int, int, int]] = []
    cell_row_cols = getattr(extraction, "cell_row_cols", None)
    if isinstance(cell_row_cols, list) and len(cell_row_cols) == len(extraction.cell_masks):
        n = int(grid_density)
        for row, col in cell_row_cols:
            row_i = int(row)
            col_i = int(col)
            x0 = grid_x + int(grid_w * col_i / n)
            x1 = grid_x + int(grid_w * (col_i + 1) / n)
            y0 = grid_y + int(grid_h * row_i / n)
            y1 = grid_y + int(grid_h * (row_i + 1) / n)
            rects.append((x0, y0, max(x0, x1 - 1), max(y0, y1 - 1)))
    else:
        for cell_mask in extraction.cell_masks:
            mask = np.asarray(cell_mask, dtype=bool)
            if mask.ndim != 2 or not np.any(mask):
                rects.append((grid_x, grid_y, grid_x, grid_y))
                continue
            rows, cols = np.where(mask)
            r0, r1 = int(rows.min()), int(rows.max()) + 1
            c0, c1 = int(cols.min()), int(cols.max()) + 1
            mask_h, mask_w = mask.shape
            x0 = grid_x + int(np.floor(c0 * grid_w / max(1, mask_w)))
            x1 = grid_x + int(np.ceil(c1 * grid_w / max(1, mask_w)))
            y0 = grid_y + int(np.floor(r0 * grid_h / max(1, mask_h)))
            y1 = grid_y + int(np.ceil(r1 * grid_h / max(1, mask_h)))
            rects.append((x0, y0, max(x0, x1 - 1), max(y0, y1 - 1)))
    return rects
