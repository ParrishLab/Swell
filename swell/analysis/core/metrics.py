import json
import os
from typing import TYPE_CHECKING, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw

if TYPE_CHECKING:
    import pandas as pd


def extract_primary_boundary(mask: np.ndarray) -> Optional[np.ndarray]:
    if mask is None:
        return None
    binary = (mask > 0).astype(np.uint8)
    if np.count_nonzero(binary) == 0:
        return None

    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    if contour is None or len(contour) < 3:
        return None
    contour_xy = contour[:, 0, :]
    x = contour_xy[:, 0].astype(np.float64)
    y = contour_xy[:, 1].astype(np.float64)
    return np.column_stack((y, x))


def smooth_boundary_fft(boundary_xy: np.ndarray, n_keep: int = 25) -> np.ndarray:
    if boundary_xy is None or len(boundary_xy) < 3:
        return boundary_xy

    x = boundary_xy[:, 1]
    y = boundary_xy[:, 0]
    z = x + 1j * y
    z_fft = np.fft.fft(z)

    n = len(z_fft)
    if 2 * n_keep >= n:
        return boundary_xy

    z_fft[n_keep : n - n_keep] = 0
    z_smooth = np.fft.ifft(z_fft)
    x_smooth = np.real(z_smooth)
    y_smooth = np.imag(z_smooth)
    return np.column_stack((y_smooth, x_smooth))


def compute_frame_metrics(boundaries: List[Optional[np.ndarray]], min_dist_px: float = 2.0) -> dict:
    n = len(boundaries)
    areas_px = np.full(n, np.nan, dtype=np.float64)
    avg_dist_px = np.full(n, np.nan, dtype=np.float64)
    transition_valid = np.zeros(n, dtype=bool)

    for i, b in enumerate(boundaries):
        if b is None or len(b) < 3:
            continue
        contour = b[:, [1, 0]].astype(np.float32).reshape(-1, 1, 2)
        area_val = cv2.contourArea(contour)
        if area_val > 0:
            areas_px[i] = area_val

    for q in range(1, n):
        inner_b = boundaries[q - 1]
        outer_b = boundaries[q]
        if inner_b is None or outer_b is None:
            continue
        transition_valid[q] = True
        outer_xy = outer_b[:, [1, 0]].astype(np.float64)
        if len(inner_b) < 3 or len(outer_xy) == 0:
            continue

        # Compute outward displacement by sampling frame q points against the frame q-1 boundary.
        inner_contour = inner_b[:, [1, 0]].astype(np.float32).reshape(-1, 1, 2)
        signed_to_prev = np.array(
            [cv2.pointPolygonTest(inner_contour, (float(x), float(y)), True) for x, y in outer_xy],
            dtype=np.float64,
        )
        outward_disp = np.maximum(0.0, -signed_to_prev)
        active_disp = outward_disp[outward_disp > float(min_dist_px)]
        if active_disp.size > 0:
            avg_dist_px[q] = float(np.mean(active_disp))

    return {
        "areas_px": areas_px,
        "avg_dist_px": avg_dist_px,
        "transition_valid": transition_valid,
    }


def compute_scale(px_points: Tuple[Tuple[float, float], Tuple[float, float]], mm_length: float) -> dict:
    (x1, y1), (x2, y2) = px_points
    scale_bar_pixels = float(np.hypot(x2 - x1, y2 - y1))
    px_per_mm = scale_bar_pixels / float(mm_length)
    um_per_px = 1000.0 / px_per_mm
    mm_per_px = 1.0 / px_per_mm
    return {
        "scale_bar_pixels": scale_bar_pixels,
        "px_per_mm": px_per_mm,
        "um_per_px": um_per_px,
        "mm_per_px": mm_per_px,
    }


def compute_roi_metrics(
    roi_mask: np.ndarray,
    areas_px: np.ndarray,
    avg_dist_px: np.ndarray,
    px_per_mm: float,
    sec_per_frame: float,
) -> dict:
    um_per_px = 1000.0 / px_per_mm
    mm_per_px = 1.0 / px_per_mm
    roi_pixels = int(np.count_nonzero(roi_mask))

    speed_um_per_sec = (avg_dist_px * um_per_px) / float(sec_per_frame)
    valid_speed = speed_um_per_sec[np.isfinite(speed_um_per_sec)]
    overall_avg_speed = float(np.mean(valid_speed)) if valid_speed.size > 0 else np.nan
    overall_max_speed = float(np.max(valid_speed)) if valid_speed.size > 0 else np.nan

    area_mm2 = areas_px * (mm_per_px**2)
    valid_area_px = areas_px[np.isfinite(areas_px)]
    max_area_px = float(np.max(valid_area_px)) if valid_area_px.size > 0 else np.nan
    max_area_mm2 = max_area_px * (mm_per_px**2) if np.isfinite(max_area_px) else np.nan
    relative_area_pct = (max_area_px / roi_pixels * 100.0) if roi_pixels > 0 and np.isfinite(max_area_px) else np.nan

    return {
        "roi_pixels": roi_pixels,
        "roi_area_mm2": roi_pixels * (mm_per_px**2),
        "speed_um_per_sec": speed_um_per_sec,
        "overall_avg_speed_um_per_sec": overall_avg_speed,
        "overall_max_speed_um_per_sec": overall_max_speed,
        "area_mm2": area_mm2,
        "max_area_px": max_area_px,
        "max_area_mm2": max_area_mm2,
        "relative_area_pct": relative_area_pct,
        "um_per_px": um_per_px,
        "mm_per_px": mm_per_px,
        "px_per_mm": px_per_mm,
        "sec_per_frame": float(sec_per_frame),
    }


def write_metrics_outputs(output_dir: str, frame_metrics_df: "pd.DataFrame", summary: dict) -> None:
    import pandas as pd

    os.makedirs(output_dir, exist_ok=True)
    frame_metrics_df.to_csv(os.path.join(output_dir, "frame_metrics.csv"), index=False)
    pd.DataFrame([summary]).to_csv(os.path.join(output_dir, "summary_metrics.csv"), index=False)
    with open(os.path.join(output_dir, "summary_metrics.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)


def generate_metrics_plots(output_dir: str, frame_metrics_df: "pd.DataFrame", summary: dict) -> None:
    from swell.shared.matplotlib_rendering import create_agg_figure, render_lock, save_agg_figure

    os.makedirs(output_dir, exist_ok=True)

    t = frame_metrics_df["time_sec"].to_numpy()
    speed = frame_metrics_df["speed_um_per_sec"].to_numpy()
    area_mm2 = frame_metrics_df["area_mm2"].to_numpy()
    rel_area_pct = frame_metrics_df["relative_area_pct"].to_numpy()

    with render_lock():
        fig = create_agg_figure()
        ax = fig.subplots()
        ax.plot(t, speed, color="k", linewidth=2)
        ax.set_xlabel("Time (sec)")
        ax.set_ylabel("Propagation Speed (um/sec)")
        ax.set_title("Propagation Speed")
        fig.tight_layout()
        save_agg_figure(fig, os.path.join(output_dir, "propagation_speed.png"), dpi=150)

        fig = create_agg_figure()
        ax = fig.subplots()
        ax.plot(t, area_mm2, color="k", linewidth=2)
        ax.set_xlabel("Time (sec)")
        ax.set_ylabel("Area (mm^2)")
        ax.set_title("Area Recruited")
        fig.tight_layout()
        save_agg_figure(fig, os.path.join(output_dir, "area_mm2.png"), dpi=150)

        fig = create_agg_figure()
        ax = fig.subplots()
        ax.plot(t, rel_area_pct, color="k", linewidth=2)
        ax.set_xlabel("Time (sec)")
        ax.set_ylabel("Area (% ROI)")
        ax.set_title("Relative Area Recruited")
        fig.tight_layout()
        save_agg_figure(fig, os.path.join(output_dir, "area_relative_pct.png"), dpi=150)

        fig = create_agg_figure()
        ax_left = fig.subplots()
        ax_right = ax_left.twinx()
        l1 = ax_right.plot(t, area_mm2, color="k", linewidth=2.5, linestyle="-", label="Area (mm^2)")
        l2 = ax_left.plot(t, speed, color="k", linewidth=2.5, linestyle=":", label="Propagation Speed (um/sec)")
        ax_left.set_xlabel("Time (sec)")
        ax_left.set_ylabel("Propagation Speed (um/sec)")
        ax_right.set_ylabel("Area (mm^2)")
        lines = l1 + l2
        labels = [l.get_label() for l in lines]
        ax_left.legend(lines, labels, loc="upper center")
        fig.tight_layout()
        save_agg_figure(fig, os.path.join(output_dir, "area_speed_combo.png"), dpi=150)


def roi_mask_from_points(
    roi_points: List[List[float]] | List[Tuple[float, float]] | None,
    frame_shape: Tuple[int, int],
) -> Optional[np.ndarray]:
    if not isinstance(roi_points, list) or len(roi_points) < 3:
        return None
    h = int(frame_shape[0]) if len(frame_shape) > 0 else 0
    w = int(frame_shape[1]) if len(frame_shape) > 1 else 0
    if h <= 0 or w <= 0:
        return None
    points: list[tuple[float, float]] = []
    for raw in roi_points:
        if not isinstance(raw, (list, tuple)) or len(raw) < 2:
            continue
        try:
            points.append((float(raw[0]), float(raw[1])))
        except (TypeError, ValueError):
            continue
    if len(points) < 3:
        return None
    canvas = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(canvas)
    draw.polygon(points, outline=1, fill=1)
    return np.asarray(canvas, dtype=bool)


def roi_mask_from_polygons(
    roi_polygons: list[list[list[float]]] | list[list[tuple[float, float]]] | None,
    frame_shape: Tuple[int, int],
) -> Optional[np.ndarray]:
    if not isinstance(roi_polygons, list) or not roi_polygons:
        return None
    h = int(frame_shape[0]) if len(frame_shape) > 0 else 0
    w = int(frame_shape[1]) if len(frame_shape) > 1 else 0
    if h <= 0 or w <= 0:
        return None
    canvas = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(canvas)
    drew_any = False
    for raw_polygon in roi_polygons:
        if not isinstance(raw_polygon, list) or len(raw_polygon) < 3:
            continue
        points: list[tuple[float, float]] = []
        for raw in raw_polygon:
            if not isinstance(raw, (list, tuple)) or len(raw) < 2:
                continue
            try:
                points.append((float(raw[0]), float(raw[1])))
            except (TypeError, ValueError):
                continue
        if len(points) >= 3:
            draw.polygon(points, outline=1, fill=1)
            drew_any = True
    if not drew_any:
        return None
    return np.asarray(canvas, dtype=bool)
