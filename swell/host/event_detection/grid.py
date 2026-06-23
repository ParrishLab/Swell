"""Build detector grid from an ROI mask.

Copied verbatim from:
  Recovery Metric/src/recovery_metric/sd_trace_extraction.py  (build_detector_grid, AnalysisGeometry, GridExtraction)
  Recovery Metric/src/recovery_metric/recovery_core.py        (generate_grid_cells)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


# ---------------------------------------------------------------------------
# Data classes (copied from sd_trace_extraction.py)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AnalysisGeometry:
    original_frame_shape: tuple[int, int]
    resized_shape: tuple[int, int]
    analysis_scale: float
    crop_box: tuple[int, int, int, int]
    cropped_roi_shape: tuple[int, int]

    @property
    def crop_origin(self) -> tuple[int, int]:
        y0, _y1, x0, _x1 = self.crop_box
        return int(y0), int(x0)


@dataclass(frozen=True)
class GridExtraction:
    roi_analysis: np.ndarray
    cell_masks: list[np.ndarray]
    cell_labels: list[str]
    cell_row_cols: list[tuple[int, int]]
    geometry: AnalysisGeometry


# ---------------------------------------------------------------------------
# generate_grid_cells (copied from recovery_core.py)
# ---------------------------------------------------------------------------

def generate_grid_cells(
    roi_mask: np.ndarray,
    n_rows: int,
    n_cols: int,
) -> tuple[list[np.ndarray], list[str], list[tuple[int, int]]]:
    """Subdivide the ROI's bounding box into n_rows × n_cols rectangles.

    Returns (masks, labels, row_col) where row 0 / col 0 is top-left.
    Empty cells are dropped.
    """
    roi = np.asarray(roi_mask, dtype=bool)
    if roi.ndim != 2 or not np.any(roi):
        raise ValueError("ROI mask must be a non-empty 2D boolean array.")
    n_rows = int(n_rows)
    n_cols = int(n_cols)
    if n_rows < 1 or n_cols < 1:
        raise ValueError("n_rows and n_cols must be >= 1.")

    H, W = roi.shape
    rs, cs = np.where(roi)
    r0, r1 = int(rs.min()), int(rs.max()) + 1
    c0, c1 = int(cs.min()), int(cs.max()) + 1

    # Even integer slicing: mirrors np.array_split for arbitrary divisions.
    row_edges = [r0 + (r1 - r0) * i // n_rows for i in range(n_rows + 1)]
    col_edges = [c0 + (c1 - c0) * j // n_cols for j in range(n_cols + 1)]

    masks: list[np.ndarray] = []
    labels: list[str] = []
    row_col: list[tuple[int, int]] = []
    for ri in range(n_rows):
        for ci in range(n_cols):
            rect = np.zeros_like(roi, dtype=bool)
            rs0, rs1 = row_edges[ri], row_edges[ri + 1]
            cs0, cs1 = col_edges[ci], col_edges[ci + 1]
            if rs1 <= rs0 or cs1 <= cs0:
                continue
            rect[rs0:rs1, cs0:cs1] = True
            cell = roi & rect
            if not np.any(cell):
                continue
            masks.append(cell)
            n_px = int(np.count_nonzero(cell))
            labels.append(f"R{ri}C{ci} ({n_px}px)")
            row_col.append((ri, ci))
    if not masks:
        raise ValueError("Grid produced no non-empty cells.")
    return masks, labels, row_col


# ---------------------------------------------------------------------------
# build_detector_grid (copied from sd_trace_extraction.py)
# ---------------------------------------------------------------------------

def build_detector_grid(
    roi_mask: np.ndarray,
    frame_shape: tuple[int, int],
    n_rows: int,
    n_cols: int,
    *,
    downsample_threshold_px: int = 800,
    downsample_scale: float = 0.25,
) -> GridExtraction:
    """Apply detector-equivalent downsample/crop, then build grid cells."""
    import cv2

    roi = np.asarray(roi_mask, dtype=bool)
    if roi.ndim != 2 or not np.any(roi):
        raise ValueError("ROI mask must be a non-empty 2D boolean array.")

    height, width = int(frame_shape[0]), int(frame_shape[1])
    if roi.shape != (height, width):
        raise ValueError(f"ROI shape {roi.shape} does not match frame shape {(height, width)}.")

    analysis_scale = 1.0
    resized_shape = (height, width)
    analysis_roi = roi
    if height > int(downsample_threshold_px) or width > int(downsample_threshold_px):
        analysis_scale = float(downsample_scale)
        down_w = max(1, int(width * analysis_scale))
        down_h = max(1, int(height * analysis_scale))
        resized = cv2.resize(roi.astype(np.float32), (down_w, down_h), interpolation=cv2.INTER_AREA)
        analysis_roi = resized > 0.5
        resized_shape = (int(down_h), int(down_w))

    ys, xs = np.where(analysis_roi)
    if ys.size == 0:
        raise ValueError("ROI mask is empty after preprocessing.")
    crop_y0 = int(ys.min())
    crop_y1 = int(ys.max()) + 1
    crop_x0 = int(xs.min())
    crop_x1 = int(xs.max()) + 1
    cropped_roi = analysis_roi[crop_y0:crop_y1, crop_x0:crop_x1]
    cell_masks, cell_labels, cell_row_cols = generate_grid_cells(cropped_roi, n_rows, n_cols)

    geometry = AnalysisGeometry(
        original_frame_shape=(height, width),
        resized_shape=resized_shape,
        analysis_scale=float(analysis_scale),
        crop_box=(crop_y0, crop_y1, crop_x0, crop_x1),
        cropped_roi_shape=(int(cropped_roi.shape[0]), int(cropped_roi.shape[1])),
    )
    return GridExtraction(
        roi_analysis=cropped_roi,
        cell_masks=[np.asarray(m, dtype=bool) for m in cell_masks],
        cell_labels=cell_labels,
        cell_row_cols=[(int(r), int(c)) for r, c in cell_row_cols],
        geometry=geometry,
    )
