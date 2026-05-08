from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
import subprocess
from threading import Lock
from typing import Callable, Iterable, Optional

import cv2
import numpy as np
from PIL import Image, ImageDraw
import tifffile
from sdapp.analysis.core.metrics import (
    compute_frame_metrics,
    extract_primary_boundary,
    roi_mask_from_polygons,
    roi_mask_from_points,
    smooth_boundary_fft,
)
from sdapp.analysis.core.object_tracking import TrackingConfig, build_object_lineage
from sdapp.shared.frame_source import EventScopedFrameSource, PreparedFrameSource, SDStackFrameSource
from sdapp.shared.image_overlay import apply_mask_overlay
from sdapp.shared.models import clone_analysis_payload
from sdapp.shared.persistence.event_path import allocate_event_path_segment, sanitize_event_path_segment
from sdapp.shared.services import MetricsSettingsResolver
from sdapp.shared.errors import DataCorruptionError, InferenceRuntimeError
from sdapp.shared.app_metadata import detect_app_version
from .config import EventCandidate, ExportRecord, TraceResult
from .signal_analysis import event_to_dict
from .stack_reader import StackReader


_CONTOUR_MAP_LINE_WIDTH_PX = 6


class _PreparedVisualSequence:
    def __init__(self, prepared_source: PreparedFrameSource) -> None:
        self._prepared_source = prepared_source

    def __len__(self) -> int:
        return int(getattr(self._prepared_source, "frame_count", 0) or 0)

    def __getitem__(self, idx: int) -> np.ndarray:
        return np.asarray(self._prepared_source.get_visual_frame(int(idx)), dtype=np.uint8)

    @property
    def stats(self):
        return self._prepared_source.stats()


def _event_output_name(event: EventCandidate) -> str:
    label = str(getattr(event, "label", "") or "").strip()
    return label or str(event.event_id)


def _event_file_suffix(event: EventCandidate) -> str:
    return f"_{sanitize_event_path_segment(_event_output_name(event))}"


def _load_pyplot():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def export_analysis(
    reader: StackReader,
    events: list[EventCandidate],
    output_dir: str | Path,
    baseline_pre_frames: int,
    trace: Optional[TraceResult] = None,
    selected_event_ids: Optional[Iterable[str]] = None,
    progress_callback: Optional[Callable[[dict], None]] = None,
    *,
    include_event_images: bool = True,
    include_baseline_images: bool = True,
    include_analysis_images: bool = False,
    include_binary_masks: bool = False,
    include_mask_overlay_images: bool = False,
    include_analysis_overlay_images: bool = False,
    include_contour_map: bool = False,
    analysis_sidecar: Optional[dict[str, dict]] = None,
    analysis_image_cache: Optional[dict[tuple, object]] = None,
    include_metric_propagation_speed: bool = False,
    include_metric_area_recruited: bool = False,
    include_metric_relative_area_recruited: bool = False,
    include_metric_lineage_object_metrics: bool = False,
    include_metric_lineage_track_tables: bool = False,
    include_metric_combined_spreadsheet: bool = False,
    project_metadata: Optional[dict[str, object]] = None,
    propagation_gap_decision: Optional[Callable[[dict[str, object]], list[str]]] = None,
) -> dict:
    analysis_sidecar_snapshot: dict[str, dict[str, object]] = {}
    if isinstance(analysis_sidecar, dict):
        for event_id, payload in dict(analysis_sidecar).items():
            if not isinstance(payload, dict):
                continue
            analysis_sidecar_snapshot[str(event_id)] = clone_analysis_payload(payload)

    include_any_metrics = (
        bool(include_metric_propagation_speed)
        or bool(include_metric_area_recruited)
        or bool(include_metric_relative_area_recruited)
        or bool(include_metric_lineage_object_metrics)
    )
    include_any_mask_exports = (
        bool(include_binary_masks)
        or bool(include_mask_overlay_images)
        or bool(include_analysis_overlay_images)
    )
    include_any_image_exports = (
        bool(include_event_images)
        or bool(include_baseline_images)
        or bool(include_analysis_images)
        or bool(include_contour_map)
    )
    if not include_any_image_exports and not include_any_mask_exports and not include_any_metrics:
        raise ValueError("Select at least one export target (images, masks, overlays, or metrics).")

    selected_ids = set(selected_event_ids) if selected_event_ids else {e.event_id for e in events}
    selected_events = [e for e in events if e.event_id in selected_ids]
    _validate_metric_export_prerequisites(
        events=selected_events,
        analysis_sidecar=analysis_sidecar_snapshot,
        project_metadata=project_metadata if isinstance(project_metadata, dict) else {},
        include_metric_propagation_speed=bool(include_metric_propagation_speed),
        include_metric_area_recruited=bool(include_metric_area_recruited),
        include_metric_relative_area_recruited=bool(include_metric_relative_area_recruited),
        include_metric_lineage_object_metrics=bool(include_metric_lineage_object_metrics),
    )

    out_dir = Path(output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    used_event_segments: set[str] = set()
    event_output_segment_by_id: dict[str, str] = {}
    for event in selected_events:
        key = str(event.event_id)
        if key not in event_output_segment_by_id:
            event_output_segment_by_id[key] = allocate_event_path_segment(_event_output_name(event), used_event_segments)

    has_trace = trace is not None and (
        bool(trace.frame_indices) or bool(trace.mean) or bool(trace.median) or bool(trace.std) or bool(trace.time_sec)
    )
    if has_trace:
        _write_trace_data_csv(out_dir / "trace_data.csv", trace)
        _write_trace_plot(out_dir / "trace_plot.png", trace, selected_events)

    manifest_records: list[ExportRecord] = []
    event_summaries: list[dict] = []
    analysis_images_exported = 0
    masks_exported = 0
    mask_overlay_images_exported = 0
    analysis_overlay_images_exported = 0
    contour_maps_exported = 0
    metrics_files_exported = 0
    total_frames_to_export = 0
    for event in selected_events:
        baseline_end = int(event.start_idx) - 1
        if baseline_end >= 0:
            baseline_start = max(0, baseline_end - int(baseline_pre_frames) + 1)
            baseline_count = baseline_end - baseline_start + 1
        else:
            baseline_count = 0
        if not bool(include_baseline_images):
            baseline_count = 0
        event_count = max(0, event.end_idx - event.start_idx + 1) if bool(include_event_images) else 0
        total_frames_to_export += baseline_count + event_count
    frame_progress = 0
    progress_lock = Lock()
    max_workers = 4
    include_analysis_visual_stack = bool(include_analysis_images) or bool(include_analysis_overlay_images)
    stack_frame_source = SDStackFrameSource(reader=reader) if include_analysis_visual_stack else None

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for event_idx, event in enumerate(selected_events, start=1):
            if progress_callback is not None:
                progress_callback(
                    {
                        "phase": "event",
                        "current": event_idx,
                        "total": len(selected_events),
                        "event_id": event.event_id,
                    }
                )
            event_dir = out_dir / event_output_segment_by_id[str(event.event_id)]
            event_dir.mkdir(parents=True, exist_ok=True)
            baseline_dir = event_dir / "baseline"
            extent_dir = event_dir / "event_extent"
            analysis_dir: Path | None = None
            if bool(include_baseline_images):
                baseline_dir.mkdir(parents=True, exist_ok=True)
            if bool(include_event_images):
                extent_dir.mkdir(parents=True, exist_ok=True)
            if bool(include_analysis_images):
                analysis_dir = event_dir / "analysis_images"
                analysis_dir.mkdir(parents=True, exist_ok=True)
            analysis_overlay_dir: Path | None = None
            if bool(include_analysis_overlay_images):
                analysis_overlay_dir = event_dir / "analysis_mask_overlays"
                analysis_overlay_dir.mkdir(parents=True, exist_ok=True)
            masks_dir: Path | None = None
            if bool(include_binary_masks):
                masks_dir = event_dir / "binary_masks"
                masks_dir.mkdir(parents=True, exist_ok=True)
            overlay_dir: Path | None = None
            if bool(include_mask_overlay_images):
                overlay_dir = event_dir / "mask_overlays"
                overlay_dir.mkdir(parents=True, exist_ok=True)
            contour_map_dir: Path | None = event_dir / "contour_map" if bool(include_contour_map) else None

            baseline_end = int(event.start_idx) - 1
            baseline_start: int | None = None
            event_records: list[tuple[int, str, ExportRecord]] = []
            if baseline_end >= 0:
                baseline_start = max(0, baseline_end - int(baseline_pre_frames) + 1)
                baseline_scope_indices = list(range(baseline_start, baseline_end + 1))
            else:
                baseline_scope_indices = []
            baseline_indices = list(baseline_scope_indices) if bool(include_baseline_images) else []
            event_scope_indices = list(range(event.start_idx, event.end_idx + 1))
            event_indices = list(event_scope_indices) if bool(include_event_images) else []

            future_map = {}
            for frame_idx in baseline_indices:
                fut = pool.submit(_export_frame, reader, frame_idx, baseline_dir, event.event_id, "baseline", trace)
                future_map[fut] = (frame_idx, "baseline")
            for frame_idx in event_indices:
                fut = pool.submit(_export_frame, reader, frame_idx, extent_dir, event.event_id, "event", trace)
                future_map[fut] = (frame_idx, "event")

            for fut in as_completed(future_map):
                frame_idx, role = future_map[fut]
                rec = fut.result()
                event_records.append((int(frame_idx), str(role), rec))
                with progress_lock:
                    frame_progress += 1
                    current_progress = frame_progress
                if progress_callback is not None:
                    progress_callback(
                        {
                            "phase": "frame",
                            "current": current_progress,
                            "total": total_frames_to_export,
                            "event_id": event.event_id,
                            "role": role,
                        }
                    )

            event_records.sort(key=lambda x: (0 if x[1] == "baseline" else 1, x[0]))
            manifest_records.extend([rec for _idx, _role, rec in event_records])

            event_sidecar = dict(analysis_sidecar_snapshot.get(str(event.event_id), {}) or {})
            mask_map = _build_event_global_mask_map(
                event=event,
                masks_payload=event_sidecar.get("masks_committed"),
                baseline_pre_frames=int(baseline_pre_frames),
                analysis_sidecar_payload=event_sidecar,
            )
            analysis_viz_frames = None
            analysis_scope_start: int | None = None
            analysis_scope_end: int | None = None
            if (analysis_dir is not None or analysis_overlay_dir is not None) and stack_frame_source is not None:
                analysis_scope_start, analysis_scope_end, analysis_baseline_pre, processing = analysis_image_export_plan(
                    event,
                    default_baseline_pre_frames=int(baseline_pre_frames),
                )

                def _notify_analysis_prepare(progress: dict, *, event_id=str(event.event_id)) -> None:
                    if not callable(progress_callback):
                        return
                    payload = {
                        "phase": "analysis_prepare",
                        "event_id": str(event_id),
                        "event_label": str(getattr(event, "label", "") or ""),
                        "current": int(progress.get("current", 0) or 0),
                        "total": int(progress.get("total", 0) or 0),
                        "stage": str(progress.get("stage", "prepare") or "prepare"),
                    }
                    progress_callback(payload)

                analysis_viz_frames = resolve_analysis_image_stack(
                    stack_frame_source,
                    event,
                    default_baseline_pre_frames=int(baseline_pre_frames),
                    cache=analysis_image_cache,
                    progress_callback=_notify_analysis_prepare,
                )
                _write_analysis_preprocessing_sidecar(
                    event_dir,
                    event=event,
                    scope_start=int(analysis_scope_start),
                    scope_end=int(analysis_scope_end),
                    baseline_pre=int(analysis_baseline_pre),
                    processing=processing,
                    analysis_viz_frames=analysis_viz_frames,
                )
            if analysis_dir is not None and analysis_viz_frames is not None:
                for local_idx, global_idx in enumerate(range(analysis_scope_start, analysis_scope_end + 1)):
                    role = "baseline" if int(global_idx) < int(event.start_idx) else "event"
                    _export_analysis_frame(
                        reader=reader,
                        frame_idx=int(global_idx),
                        out_dir=analysis_dir,
                        role=str(role),
                        analysis_frame=np.asarray(analysis_viz_frames[local_idx], dtype=np.uint8),
                    )
                    analysis_images_exported += 1
            if analysis_overlay_dir is not None and analysis_viz_frames is not None:
                for local_idx, global_idx in enumerate(range(analysis_scope_start, analysis_scope_end + 1)):
                    mask = mask_map.get(int(global_idx))
                    if mask is None or not np.any(mask):
                        continue
                    role = "baseline" if int(global_idx) < int(event.start_idx) else "event"
                    _export_analysis_overlay_frame(
                        reader=reader,
                        frame_idx=int(global_idx),
                        out_dir=analysis_overlay_dir,
                        role=str(role),
                        analysis_frame=np.asarray(analysis_viz_frames[local_idx], dtype=np.uint8),
                        mask=mask,
                    )
                    analysis_overlay_images_exported += 1
            if masks_dir is not None:
                for frame_idx in sorted(set(baseline_scope_indices + event_scope_indices)):
                    mask = mask_map.get(int(frame_idx))
                    if mask is None:
                        continue
                    if not np.any(mask):
                        continue
                    role = "baseline" if int(frame_idx) in baseline_scope_indices else "event"
                    mask_name = f"{int(frame_idx):06d}_{role}_mask.tiff"
                    _write_mask(masks_dir / mask_name, mask)
                    masks_exported += 1
            if overlay_dir is not None:
                overlay_indices = sorted(set(baseline_scope_indices + event_scope_indices))
                for frame_idx in overlay_indices:
                    mask = mask_map.get(int(frame_idx))
                    if mask is None or not np.any(mask):
                        continue
                    role = "baseline" if int(frame_idx) in baseline_scope_indices else "event"
                    _export_mask_overlay_frame(
                        reader=reader,
                        frame_idx=int(frame_idx),
                        out_dir=overlay_dir,
                        role=str(role),
                        mask=mask,
                    )
                    mask_overlay_images_exported += 1
            if contour_map_dir is not None:
                if _export_contour_map_frame(
                    reader=reader,
                    event=event,
                    frame_indices=event_scope_indices,
                    mask_map=mask_map,
                    out_dir=contour_map_dir,
                ):
                    contour_maps_exported += 1

            if include_any_metrics:
                metrics_settings = MetricsSettingsResolver.resolve_for_event(
                    event_id=str(event.event_id),
                    analysis_sidecar={str(event.event_id): event_sidecar},
                    project_metadata=project_metadata if isinstance(project_metadata, dict) else {},
                )
                metric_result = _export_event_metrics(
                    reader=reader,
                    event=event,
                    event_dir=event_dir,
                    masks_payload=event_sidecar.get("masks_committed"),
                    metrics_settings=metrics_settings,
                    include_metric_propagation_speed=bool(include_metric_propagation_speed),
                    include_metric_area_recruited=bool(include_metric_area_recruited),
                    include_metric_relative_area_recruited=bool(include_metric_relative_area_recruited),
                    include_metric_lineage_object_metrics=bool(include_metric_lineage_object_metrics),
                    include_metric_lineage_track_tables=bool(include_metric_lineage_track_tables),
                    include_metric_combined_spreadsheet=bool(include_metric_combined_spreadsheet),
                    propagation_gap_decision=propagation_gap_decision,
                    analysis_sidecar_payload=event_sidecar,
                )
                metrics_files_exported += int(metric_result.get("files_written", 0))

            summary = event_to_dict(event)
            summary["baseline_start_idx"] = baseline_start
            summary["baseline_end_idx"] = baseline_end if baseline_end >= 0 else None
            summary_path = event_dir / "event_summary.json"
            summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
            _write_event_summary_markdown(event_dir / "event_summary.md", summary)
            event_summaries.append(summary)

    _write_manifest_csv(out_dir / "events_manifest.csv", manifest_records)
    export_metadata = _build_export_metadata(
        reader=reader,
        events=selected_events,
        analysis_sidecar=analysis_sidecar_snapshot,
        project_metadata=project_metadata if isinstance(project_metadata, dict) else {},
        baseline_pre_frames=int(baseline_pre_frames),
    )
    _write_manifest_json(out_dir / "events_manifest.json", manifest_records, event_summaries, export_metadata=export_metadata)
    _write_manifest_markdown(
        out_dir / "events_manifest.md",
        records=manifest_records,
        events=event_summaries,
        event_output_segment_by_id=event_output_segment_by_id,
    )

    return {
        "output_dir": str(out_dir),
        "events_exported": len(selected_events),
        "frames_exported": len(manifest_records),
        "analysis_images_exported": int(analysis_images_exported),
        "masks_exported": int(masks_exported),
        "mask_overlay_images_exported": int(mask_overlay_images_exported),
        "analysis_overlay_images_exported": int(analysis_overlay_images_exported),
        "contour_maps_exported": int(contour_maps_exported),
        "metrics_files_exported": int(metrics_files_exported),
        "manifest_csv": str(out_dir / "events_manifest.csv"),
        "manifest_json": str(out_dir / "events_manifest.json"),
        "manifest_markdown": str(out_dir / "events_manifest.md"),
    }


def _safe_float(value, default: float | None = None) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if not np.isfinite(v):
        return default
    return v


def _finite_optional(value: object) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if np.isfinite(out) else None


def _scale_unit_is_px_per_mm(value: object) -> bool:
    unit = str(value or "").strip().lower()
    return unit in {"px_per_mm", "pixels_per_mm", "pixel_per_mm"}


def _metrics_need_scale(
    *,
    include_metric_propagation_speed: bool,
    include_metric_area_recruited: bool,
    include_metric_lineage_object_metrics: bool,
) -> bool:
    return (
        bool(include_metric_propagation_speed)
        or bool(include_metric_area_recruited)
        or bool(include_metric_lineage_object_metrics)
    )


def _require_metric_fps(metrics_settings: dict[str, object], *, event_id: str) -> float:
    fps = _safe_float(metrics_settings.get("frames_per_sec"), default=None)
    if fps is None or fps <= 0:
        raise ValueError(f"Event {event_id} metrics export requires explicit frames_per_sec > 0.")
    return float(fps)


def _require_px_per_mm_scale(metrics_settings: dict[str, object], *, event_id: str) -> float:
    scale = _safe_float(metrics_settings.get("scale_px_per_mm"), default=None)
    if scale is None or scale <= 0:
        raise ValueError(f"Event {event_id} physical-unit metrics require scale_px_per_mm > 0.")
    if not _scale_unit_is_px_per_mm(metrics_settings.get("scale_unit")):
        raise ValueError(f"Event {event_id} physical-unit metrics require scale_unit='px_per_mm'.")
    return float(scale)


def _validate_metric_export_prerequisites(
    *,
    events: list[EventCandidate],
    analysis_sidecar: dict[str, dict[str, object]],
    project_metadata: dict[str, object] | None,
    include_metric_propagation_speed: bool,
    include_metric_area_recruited: bool,
    include_metric_relative_area_recruited: bool,
    include_metric_lineage_object_metrics: bool,
) -> None:
    if not (
        bool(include_metric_propagation_speed)
        or bool(include_metric_area_recruited)
        or bool(include_metric_relative_area_recruited)
        or bool(include_metric_lineage_object_metrics)
    ):
        return
    need_scale = _metrics_need_scale(
        include_metric_propagation_speed=bool(include_metric_propagation_speed),
        include_metric_area_recruited=bool(include_metric_area_recruited),
        include_metric_lineage_object_metrics=bool(include_metric_lineage_object_metrics),
    )
    for event in events:
        event_id = str(event.event_id)
        metrics_settings = MetricsSettingsResolver.resolve_for_event(
            event_id=event_id,
            analysis_sidecar={event_id: dict(analysis_sidecar.get(event_id, {}) or {})},
            project_metadata=project_metadata if isinstance(project_metadata, dict) else {},
        )
        _require_metric_fps(metrics_settings, event_id=event_id)
        if need_scale:
            _require_px_per_mm_scale(metrics_settings, event_id=event_id)


def _resolve_roi_mask(metrics_settings: dict[str, object], frame_shape: tuple[int, int]) -> np.ndarray | None:
    normalized = MetricsSettingsResolver.normalize(metrics_settings)
    raw_mask = normalized.get("roi_mask")
    if raw_mask is not None:
        arr = np.asarray(raw_mask, dtype=bool)
        if arr.ndim == 2 and arr.shape == frame_shape and np.any(arr):
            return arr.copy()
    raw_points = normalized.get("roi_points")
    raw_polygons = normalized.get("roi_polygons")
    if isinstance(raw_polygons, list) and raw_polygons:
        try:
            mask = roi_mask_from_polygons(raw_polygons, frame_shape)
        except Exception as e:
            raise DataCorruptionError(f"Failed to generate ROI mask from polygons: {e}")
        if mask is not None and mask.shape == frame_shape and np.any(mask):
            return np.asarray(mask, dtype=bool).copy()
    if isinstance(raw_points, list) and raw_points:
        try:
            mask = roi_mask_from_points(raw_points, frame_shape)
        except Exception as e:
            raise DataCorruptionError(f"Failed to generate ROI mask from points: {e}")
        if mask is not None and mask.shape == frame_shape and np.any(mask):
            return np.asarray(mask, dtype=bool).copy()
    return None


def _write_metric_csv(path: Path, frame_indices: list[int], time_sec: list[float], values: np.ndarray, value_column: str) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        rows = _metric_table_rows(frame_indices, time_sec, values, value_column)
        writer.writerow(rows["columns"])
        writer.writerows(rows["rows"])


def _metric_table_rows(
    frame_indices: list[int],
    time_sec: list[float],
    values: np.ndarray,
    value_column: str,
) -> dict[str, object]:
    rows: list[list[object]] = []
    for frame_idx, t_sec, val in zip(frame_indices, time_sec, values):
        out_val = "" if not np.isfinite(float(val)) else float(val)
        rows.append([int(frame_idx), int(frame_idx) + 1, float(t_sec), out_val])
    return {
        "columns": ["frame_index", "frame_display", "time_sec", str(value_column)],
        "rows": rows,
    }


def _write_rows_csv(path: Path, *, columns: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[str(v) for v in columns])
        writer.writeheader()
        for row in rows:
            payload = {str(key): row.get(str(key), "") for key in columns}
            writer.writerow(payload)


def _rows_table(sheet_name: str, *, columns: list[str], rows: list[dict[str, object]]) -> dict[str, object]:
    return {
        "sheet_name": str(sheet_name),
        "columns": [str(v) for v in columns],
        "rows": [[row.get(str(key), "") for key in columns] for row in rows],
    }


def _write_metric_plot(path: Path, time_sec: list[float], values: np.ndarray, title: str, ylabel: str) -> None:
    plt = _load_pyplot()
    plt.figure()
    plt.plot(np.asarray(time_sec, dtype=np.float64), np.asarray(values, dtype=np.float64), color="k", linewidth=2)
    plt.xlabel("Time (sec)")
    plt.ylabel(str(ylabel))
    plt.title(str(title))
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()


def _contour_map_colors(count: int) -> list[tuple[int, int, int]]:
    if count <= 0:
        return []
    plt = _load_pyplot()
    try:
        cmap = plt.get_cmap("parula")
    except ValueError:
        cmap = plt.get_cmap("viridis")
    if count == 1:
        samples = [0.0]
    else:
        samples = [i / float(count - 1) for i in range(count)]
    colors: list[tuple[int, int, int]] = []
    for sample in samples:
        rgba = cmap(float(sample))
        colors.append(tuple(int(round(float(channel) * 255.0)) for channel in rgba[:3]))
    return colors


def _export_contour_map_frame(
    *,
    reader: StackReader,
    event: EventCandidate,
    frame_indices: list[int],
    mask_map: dict[int, np.ndarray],
    out_dir: Path,
) -> bool:
    mask_items: list[tuple[int, np.ndarray]] = []
    for frame_idx in list(frame_indices or []):
        mask = mask_map.get(int(frame_idx))
        if mask is None:
            continue
        mask_arr = np.asarray(mask, dtype=bool)
        if mask_arr.ndim != 2 or not np.any(mask_arr):
            continue
        mask_items.append((int(frame_idx), mask_arr.copy()))
    if not mask_items:
        return False

    background_frame_idx = int(mask_items[0][0])
    background = reader.read_frame(background_frame_idx, use_cache=True)
    frame_shape = np.asarray(background).shape[:2]
    base_rgb = apply_mask_overlay(background, np.zeros(frame_shape, dtype=bool))
    image = Image.fromarray(np.asarray(base_rgb, dtype=np.uint8)).convert("RGB")
    draw = ImageDraw.Draw(image)
    colors = _contour_map_colors(len(mask_items))
    contours_drawn = 0
    for (_frame_idx, mask), color in zip(mask_items, colors):
        boundary = extract_primary_boundary(mask)
        if boundary is None or len(boundary) < 3:
            continue
        smoothed = smooth_boundary_fft(boundary, n_keep=25)
        if smoothed is None or len(smoothed) < 3:
            continue
        points = [(float(x), float(y)) for y, x in np.asarray(smoothed, dtype=np.float64)]
        draw.line(points + [points[0]], fill=tuple(int(v) for v in color), width=_CONTOUR_MAP_LINE_WIDTH_PX)
        contours_drawn += 1

    if contours_drawn <= 0:
        return False
    out_dir.mkdir(parents=True, exist_ok=True)
    event_id = sanitize_event_path_segment(str(getattr(event, "event_id", "") or "event"))
    image.save(out_dir / f"contour_map_{event_id}.png")
    return True


def _track_color_rgb(track_id: int, root_track_id: int) -> tuple[int, int, int]:
    seed = int(root_track_id or track_id)
    palette = [
        (255, 99, 71),
        (65, 105, 225),
        (60, 179, 113),
        (255, 165, 0),
        (186, 85, 211),
        (255, 215, 0),
        (70, 130, 180),
        (220, 20, 60),
    ]
    return palette[(max(1, seed) - 1) % len(palette)]


def _draw_lineage_overlay(
    frame: np.ndarray,
    rows_for_frame: list[dict[str, object]],
    *,
    mask_by_track_id: dict[int, np.ndarray],
) -> np.ndarray:
    base = np.asarray(apply_mask_overlay(frame, np.zeros(np.asarray(frame).shape[:2], dtype=bool)), dtype=np.uint8)
    overlay = np.asarray(base, dtype=np.uint8).copy()
    for row in list(rows_for_frame or []):
        track_id = int(row.get("track_id", 0) or 0)
        root_track_id = int(row.get("root_track_id", track_id) or track_id)
        mask = np.asarray(mask_by_track_id.get(int(track_id)), dtype=bool)
        if mask.ndim != 2 or not np.any(mask):
            continue
        color = _track_color_rgb(track_id, root_track_id)
        tint = overlay.copy()
        tint[mask] = color
        overlay = cv2.addWeighted(overlay, 0.75, tint, 0.25, 0.0)
        ys, xs = np.where(mask)
        if ys.size <= 0 or xs.size <= 0:
            continue
        anchor_x = int(np.clip(np.min(xs), 0, max(0, overlay.shape[1] - 1)))
        anchor_y = int(np.clip(np.min(ys), 12, max(12, overlay.shape[0] - 1)))
        label = f"T{track_id}"
        if int(root_track_id) != int(track_id):
            label = f"T{track_id}/R{root_track_id}"
        cv2.putText(
            overlay,
            label,
            (anchor_x, anchor_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            color,
            1,
            cv2.LINE_AA,
        )
    return overlay


def _write_lineage_overview_montage(
    path: Path,
    *,
    rendered_frames: list[tuple[int, np.ndarray]],
) -> None:
    if not rendered_frames:
        return
    cards: list[Image.Image] = []
    card_width = 220
    card_height = 220
    for frame_index, frame_rgb in rendered_frames:
        image = Image.fromarray(np.asarray(frame_rgb, dtype=np.uint8))
        image.thumbnail((card_width - 16, card_height - 36))
        card = Image.new("RGB", (card_width, card_height), color=(24, 28, 34))
        draw = ImageDraw.Draw(card)
        draw.text((10, 8), f"Frame {int(frame_index) + 1}", fill=(240, 240, 240))
        paste_x = int((card_width - image.width) / 2)
        paste_y = 28 + int((card_height - 36 - image.height) / 2)
        card.paste(image, (paste_x, paste_y))
        cards.append(card)
    columns = min(3, max(1, len(cards)))
    rows = int(np.ceil(len(cards) / float(columns)))
    canvas = Image.new("RGB", (columns * card_width, rows * card_height), color=(16, 20, 26))
    for idx, card in enumerate(cards):
        x = (idx % columns) * card_width
        y = (idx // columns) * card_height
        canvas.paste(card, (x, y))
    canvas.save(path)


def _track_speed_rows(
    *,
    tracks: dict[int, object],
    event_start_idx: int,
    scale_px_per_mm: float | None,
    sec_per_frame: float,
    mask_by_track_frame: dict[tuple[int, int], np.ndarray] | None = None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for track_id in sorted(tracks):
        track = tracks[int(track_id)]
        assignments = list(getattr(track, "frame_assignments", []) or [])
        if not assignments:
            continue
        boundaries: list[np.ndarray | None] = []
        for assignment in assignments:
            mask = None
            if isinstance(mask_by_track_frame, dict):
                mask = mask_by_track_frame.get((int(track_id), int(getattr(assignment, "frame_index", 0))))
            if mask is None:
                mask = getattr(assignment, "mask", None)
            boundary = extract_primary_boundary(np.asarray(mask, dtype=bool))
            if boundary is not None:
                boundary = smooth_boundary_fft(boundary, n_keep=25)
            boundaries.append(boundary)
        metrics = compute_frame_metrics(boundaries, min_dist_px=2.0)
        avg_dist_px = np.asarray(metrics.get("avg_dist_px", []), dtype=np.float64)
        if scale_px_per_mm is not None and scale_px_per_mm > 0:
            speed_values = (avg_dist_px * (1000.0 / float(scale_px_per_mm))) / float(sec_per_frame)
        else:
            speed_values = np.full(len(assignments), np.nan, dtype=np.float64)
        root_track_id = int(getattr(track, "root_track_id", None) or int(track_id))
        for assignment, speed_value in zip(assignments, speed_values):
            frame_index = int(getattr(assignment, "frame_index", 0))
            rows.append(
                {
                    "track_id": int(track_id),
                    "root_track_id": int(root_track_id),
                    "frame_index": int(frame_index),
                    "frame_display": int(frame_index) + 1,
                    "time_sec": float(frame_index - int(event_start_idx)) * float(sec_per_frame),
                    "area_px": int(getattr(assignment, "area_px", 0)),
                    "speed_um_per_sec": "" if not np.isfinite(speed_value) else float(speed_value),
                }
            )
    return rows


def _weighted_track_speed_rows(
    *,
    frame_indices: list[int],
    time_sec: list[float],
    track_speed_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    grouped: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in list(track_speed_rows or []):
        grouped[int(row.get("frame_index", 0))].append(dict(row))
    rows: list[dict[str, object]] = []
    for frame_index, t_sec in zip(frame_indices, time_sec):
        candidates = []
        for row in grouped.get(int(frame_index), []):
            try:
                speed_value = float(row.get("speed_um_per_sec"))
                area_px = float(row.get("area_px", 0))
            except (TypeError, ValueError):
                continue
            if not np.isfinite(speed_value) or area_px <= 0:
                continue
            candidates.append((speed_value, area_px))
        if candidates:
            total_area = float(sum(area for _speed, area in candidates))
            weighted_speed = float(sum(speed * (area / total_area) for speed, area in candidates))
            active_track_count = int(len(candidates))
        else:
            weighted_speed = float("nan")
            active_track_count = 0
        rows.append(
            {
                "frame_index": int(frame_index),
                "frame_display": int(frame_index) + 1,
                "time_sec": float(t_sec),
                "active_track_count": int(active_track_count),
                "area_weighted_speed_um_per_sec": "" if not np.isfinite(weighted_speed) else float(weighted_speed),
            }
        )
    return rows


def _find_interior_false_runs(mask: np.ndarray) -> list[tuple[int, int]]:
    arr = np.asarray(mask, dtype=bool)
    runs: list[tuple[int, int]] = []
    idx = 0
    n = int(arr.size)
    while idx < n:
        if arr[idx]:
            idx += 1
            continue
        start = idx
        while idx < n and not arr[idx]:
            idx += 1
        end = idx - 1
        if start > 0 and idx < n and arr[start - 1] and arr[idx]:
            runs.append((start, end))
    return runs


def _find_interior_nan_runs(values: np.ndarray) -> list[tuple[int, int]]:
    arr = np.asarray(values, dtype=np.float64)
    return _find_interior_false_runs(np.isfinite(arr))


def _propagation_warning_entries(warning: dict[str, object] | None) -> list[dict[str, object]]:
    if not isinstance(warning, dict) or not warning:
        return []
    nested = warning.get("warnings")
    if isinstance(nested, list):
        return [dict(entry) for entry in nested if isinstance(entry, dict)]
    return [dict(warning)]


def _apply_propagation_gap_policy(
    values: np.ndarray,
    runs: list[tuple[int, int]],
    actions: list[str],
) -> np.ndarray:
    arr = np.asarray(values, dtype=np.float64).copy()
    if not runs:
        return arr
    for (start, end), action in zip(runs, actions):
        normalized = str(action or "ignore").strip().lower()
        if normalized == "stop":
            arr[start:] = np.nan
            return arr
        if normalized == "zero":
            arr[start : end + 1] = 0.0
            continue
        if normalized == "interpolate":
            left_idx = start - 1
            right_idx = end + 1
            if left_idx < 0 or right_idx >= arr.size:
                continue
            left_val = float(arr[left_idx])
            right_val = float(arr[right_idx])
            if not np.isfinite(left_val) or not np.isfinite(right_val):
                continue
            span = right_idx - left_idx
            for idx in range(start, end + 1):
                arr[idx] = left_val + ((right_val - left_val) * ((idx - left_idx) / float(span)))
            continue
    return arr


def _write_metrics_combined_workbook(
    path: Path,
    *,
    summary: dict[str, object],
    metric_tables: list[dict[str, object]],
) -> None:
    try:
        from openpyxl import Workbook
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Combined spreadsheet export requires openpyxl. Install openpyxl or disable spreadsheet export."
        ) from exc

    workbook = Workbook()
    summary_sheet = workbook.active
    summary_sheet.title = "Summary"
    summary_sheet.append(["Metric", "Value"])
    summary_rows: list[tuple[str, object]] = [
        ("Event ID", summary.get("event_id")),
        ("Frames per second", summary.get("frames_per_sec")),
        ("Event start time (sec)", summary.get("event_start_time_sec")),
        ("Event end time (sec)", summary.get("event_end_time_sec")),
        ("Scale available", summary.get("has_scale")),
        ("ROI available", summary.get("has_roi")),
        ("ROI pixels", summary.get("roi_pixels")),
        ("Selected metrics", summary.get("selected_metrics")),
        ("Overall average speed (um/sec)", summary.get("overall_avg_speed_um_per_sec")),
        ("Overall max speed (um/sec)", summary.get("overall_max_speed_um_per_sec")),
        ("Max area (mm^2)", summary.get("max_area_mm2")),
        ("Max relative area (%)", summary.get("max_relative_area_pct")),
        ("Written files", summary.get("written_files")),
    ]
    lineage_summary = summary.get("object_lineage_summary")
    if isinstance(lineage_summary, dict) and lineage_summary:
        summary_rows.extend(
            [
                ("Tracked objects kept", lineage_summary.get("kept_track_count")),
                ("Noise-filtered objects", lineage_summary.get("noise_filtered_track_count")),
                ("Merge events", lineage_summary.get("merge_event_count")),
                ("Lineage weighted average speed (um/sec)", lineage_summary.get("area_weighted_avg_speed_um_per_sec")),
                ("Lineage weighted max speed (um/sec)", lineage_summary.get("area_weighted_max_speed_um_per_sec")),
                ("Tracks with speed", lineage_summary.get("tracks_with_speed_count")),
            ]
        )
    warning = summary.get("propagation_gap_warning")
    for index, entry in enumerate(_propagation_warning_entries(warning), start=1):
        prefix = "Propagation warning" if index == 1 else f"Propagation warning {index}"
        summary_rows.extend(
            [
                (f"{prefix} type", entry.get("kind", "gap")),
                (f"{prefix} actions applied", entry.get("actions", entry.get("action"))),
                (f"{prefix} frame runs", entry.get("frame_runs")),
            ]
        )
    for label, value in summary_rows:
        summary_sheet.append([str(label), _format_summary_value(value)])

    for table in metric_tables:
        sheet = workbook.create_sheet(title=str(table.get("sheet_name", "Metric"))[:31] or "Metric")
        columns = list(table.get("columns", []) or [])
        rows = list(table.get("rows", []) or [])
        sheet.append(columns)
        for row in rows:
            sheet.append(list(row))

    workbook.save(path)


def _export_event_metrics(
    *,
    reader: StackReader,
    event: EventCandidate,
    event_dir: Path,
    masks_payload,
    metrics_settings: dict[str, object],
    include_metric_propagation_speed: bool,
    include_metric_area_recruited: bool,
    include_metric_relative_area_recruited: bool,
    include_metric_lineage_object_metrics: bool,
    include_metric_lineage_track_tables: bool,
    include_metric_combined_spreadsheet: bool,
    propagation_gap_decision: Optional[Callable[[dict[str, object]], list[str]]] = None,
    analysis_sidecar_payload: Optional[dict[str, object]] = None,
) -> dict[str, object]:
    frame0 = np.asarray(reader.read_frame(0, use_cache=True))
    if frame0.ndim == 3:
        frame_shape = (int(frame0.shape[0]), int(frame0.shape[1]))
    else:
        frame_shape = (int(frame0.shape[0]), int(frame0.shape[1]))
    frame_indices = list(range(int(event.start_idx), int(event.end_idx) + 1))
    if not frame_indices:
        return {"files_written": 0}

    need_scale = _metrics_need_scale(
        include_metric_propagation_speed=bool(include_metric_propagation_speed),
        include_metric_area_recruited=bool(include_metric_area_recruited),
        include_metric_lineage_object_metrics=bool(include_metric_lineage_object_metrics),
    )
    fps = _require_metric_fps(metrics_settings, event_id=str(event.event_id))
    scale_px_per_mm = (
        _require_px_per_mm_scale(metrics_settings, event_id=str(event.event_id))
        if need_scale
        else _safe_float(metrics_settings.get("scale_px_per_mm"), default=None)
    )
    has_scale = scale_px_per_mm is not None and scale_px_per_mm > 0 and _scale_unit_is_px_per_mm(metrics_settings.get("scale_unit"))
    sec_per_frame = 1.0 / float(fps)
    local_index_by_frame = {int(frame_index): int(local_idx) for local_idx, frame_index in enumerate(frame_indices)}

    roi_mask = _resolve_roi_mask(metrics_settings, frame_shape)
    has_roi = roi_mask is not None and np.any(roi_mask)

    mask_map = _build_event_global_mask_map(
        event=event,
        masks_payload=masks_payload,
        baseline_pre_frames=0,
        analysis_sidecar_payload=analysis_sidecar_payload,
    )
    full_masks: list[np.ndarray] = []
    for idx in frame_indices:
        raw_mask = mask_map.get(int(idx))
        if raw_mask is None:
            full_masks.append(np.zeros(frame_shape, dtype=bool))
            continue
        arr = np.asarray(raw_mask, dtype=bool)
        if arr.ndim != 2 or arr.shape != frame_shape:
            full_masks.append(np.zeros(frame_shape, dtype=bool))
            continue
        full_masks.append(arr.copy())
    roi_masks = [(m & roi_mask) for m in full_masks] if has_roi else []

    boundaries_full = []
    for m in full_masks:
        boundary = extract_primary_boundary(m)
        if boundary is not None:
            boundary = smooth_boundary_fft(boundary, n_keep=25)
        boundaries_full.append(boundary)
    frame_metrics_full = compute_frame_metrics(boundaries_full, min_dist_px=2.0)

    boundaries_roi = []
    frame_metrics_roi = None
    if has_roi:
        for m in roi_masks:
            boundary = extract_primary_boundary(m)
            if boundary is not None:
                boundary = smooth_boundary_fft(boundary, n_keep=25)
            boundaries_roi.append(boundary)
        frame_metrics_roi = compute_frame_metrics(boundaries_roi, min_dist_px=2.0)

    avg_dist_px = np.asarray(frame_metrics_full["avg_dist_px"], dtype=np.float64)
    if has_scale:
        speed_um_per_sec = (avg_dist_px * (1000.0 / float(scale_px_per_mm))) / float(sec_per_frame)
    else:
        speed_um_per_sec = np.full_like(avg_dist_px, np.nan, dtype=np.float64)

    if has_roi and frame_metrics_roi is not None:
        area_px = np.asarray(frame_metrics_roi["areas_px"], dtype=np.float64)
    else:
        area_px = np.full(len(frame_indices), np.nan, dtype=np.float64)
    if has_scale:
        area_mm2 = area_px * (1.0 / float(scale_px_per_mm)) ** 2
    else:
        area_mm2 = np.full_like(area_px, np.nan, dtype=np.float64)
    roi_pixels = int(np.count_nonzero(roi_mask)) if has_roi else 0
    if roi_pixels > 0:
        relative_area_pct = (area_px / float(roi_pixels)) * 100.0
    else:
        relative_area_pct = np.full_like(area_px, np.nan, dtype=np.float64)

    time_sec = [(idx - frame_indices[0]) * sec_per_frame for idx in frame_indices]
    metrics_dir = event_dir / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    suffix = _event_file_suffix(event)
    files_written = 0
    written: list[str] = []
    metric_tables: list[dict[str, object]] = []
    propagation_gap_warning: dict[str, object] | None = None
    transition_valid = np.asarray(frame_metrics_full.get("transition_valid", np.zeros_like(avg_dist_px, dtype=bool)), dtype=bool)
    all_nan_runs = _find_interior_nan_runs(speed_um_per_sec) if bool(include_metric_propagation_speed and has_scale) else []
    zero_runs: list[tuple[int, int]] = []
    gap_runs: list[tuple[int, int]] = []
    for start, end in all_nan_runs:
        if bool(np.all(transition_valid[start : end + 1])):
            zero_runs.append((start, end))
        else:
            gap_runs.append((start, end))

    warning_entries: list[dict[str, object]] = []

    def _resolve_actions(
        runs_local: list[tuple[int, int]],
        frame_runs_local: list[list[int]],
        warning_kind: str,
        supported: list[str],
        default: str,
    ) -> list[str]:
        count = len(runs_local)
        if count == 0:
            return []
        allowed = set(supported)
        resolved = [default] * count
        if callable(propagation_gap_decision):
            try:
                decision_payload = {
                    "event_id": str(event.event_id),
                    "event_label": str(getattr(event, "label", "") or ""),
                    "gap_frame_runs": frame_runs_local,
                    "metric": "propagation_speed",
                    "warning_kind": warning_kind,
                    "supported_actions": list(supported),
                    "preview_frame_indices": [int(idx) for idx in frame_indices],
                    "preview_speed_values": [None if not np.isfinite(val) else float(val) for val in speed_um_per_sec],
                }
                raw = propagation_gap_decision(decision_payload)
            except Exception as e:
                raise DataCorruptionError(f"Propagation gap policy failed: {e}")
            if isinstance(raw, str):
                raw = [raw] * count
            if isinstance(raw, (list, tuple)):
                for i in range(min(count, len(raw))):
                    value = str(raw[i] or default).strip().lower()
                    resolved[i] = value if value in allowed else default
        return resolved

    if zero_runs:
        zero_frame_runs = [[int(frame_indices[start]), int(frame_indices[end])] for start, end in zero_runs]
        zero_actions = _resolve_actions(
            zero_runs,
            zero_frame_runs,
            "zero_growth",
            ["zero", "interpolate", "stop"],
            "zero",
        )
        speed_um_per_sec = _apply_propagation_gap_policy(speed_um_per_sec, zero_runs, zero_actions)
        warning_entries.append(
            {
                "metric": "propagation_speed",
                "kind": "zero_growth",
                "event_id": str(event.event_id),
                "event_label": str(getattr(event, "label", "") or ""),
                "frame_runs": zero_frame_runs,
                "actions": list(zero_actions),
            }
        )
        if "stop" in zero_actions:
            gap_runs = []

    if gap_runs:
        gap_frame_runs = [[int(frame_indices[start]), int(frame_indices[end])] for start, end in gap_runs]
        gap_actions = _resolve_actions(
            gap_runs,
            gap_frame_runs,
            "gap",
            ["ignore", "interpolate", "stop"],
            "ignore",
        )
        speed_um_per_sec = _apply_propagation_gap_policy(speed_um_per_sec, gap_runs, gap_actions)
        warning_entries.append(
            {
                "metric": "propagation_speed",
                "kind": "gap",
                "event_id": str(event.event_id),
                "event_label": str(getattr(event, "label", "") or ""),
                "frame_runs": gap_frame_runs,
                "actions": list(gap_actions),
            }
        )

    if warning_entries:
        if len(warning_entries) == 1:
            propagation_gap_warning = dict(warning_entries[0])
        else:
            propagation_gap_warning = {
                "metric": "propagation_speed",
                "event_id": str(event.event_id),
                "event_label": str(getattr(event, "label", "") or ""),
                "warnings": warning_entries,
            }
        warning_json_path = metrics_dir / "propagation_speed_warning.json"
        warning_json_path.write_text(
            json.dumps(propagation_gap_warning, indent=2),
            encoding="utf-8",
        )
        _write_metrics_warning_markdown(metrics_dir / "propagation_speed_warning.md", propagation_gap_warning)
        files_written += 2
        written.append("propagation_speed_warning.json")
        written.append("propagation_speed_warning.md")

    if include_metric_propagation_speed and has_scale:
        speed_table = _metric_table_rows(frame_indices, time_sec, speed_um_per_sec, "speed_um_per_sec")
        _write_metric_csv(metrics_dir / f"propagation_speed{suffix}.csv", frame_indices, time_sec, speed_um_per_sec, "speed_um_per_sec")
        _write_metric_plot(
            metrics_dir / "propagation_speed.png",
            time_sec,
            speed_um_per_sec,
            "Propagation Speed",
            "Propagation Speed (um/sec)",
        )
        metric_tables.append(
            {
                "sheet_name": "Propagation Speed",
                "columns": speed_table["columns"],
                "rows": speed_table["rows"],
            }
        )
        files_written += 2
        written.extend([f"propagation_speed{suffix}.csv", "propagation_speed.png"])
    if include_metric_area_recruited and has_scale and has_roi:
        area_table = _metric_table_rows(frame_indices, time_sec, area_mm2, "area_mm2")
        _write_metric_csv(metrics_dir / f"area_recruited{suffix}.csv", frame_indices, time_sec, area_mm2, "area_mm2")
        _write_metric_plot(metrics_dir / "area_recruited.png", time_sec, area_mm2, "Area Recruited", "Area (mm^2)")
        metric_tables.append(
            {
                "sheet_name": "Area Recruited",
                "columns": area_table["columns"],
                "rows": area_table["rows"],
            }
        )
        files_written += 2
        written.extend([f"area_recruited{suffix}.csv", "area_recruited.png"])
    if include_metric_relative_area_recruited and has_roi:
        relative_area_table = _metric_table_rows(frame_indices, time_sec, relative_area_pct, "relative_area_pct")
        _write_metric_csv(
            metrics_dir / f"relative_area_recruited{suffix}.csv",
            frame_indices,
            time_sec,
            relative_area_pct,
            "relative_area_pct",
        )
        _write_metric_plot(
            metrics_dir / "relative_area_recruited.png",
            time_sec,
            relative_area_pct,
            "Relative Area Recruited",
            "Area (% ROI)",
        )
        metric_tables.append(
            {
                "sheet_name": "Relative Area Recruited",
                "columns": relative_area_table["columns"],
                "rows": relative_area_table["rows"],
            }
        )
        files_written += 2
        written.extend([f"relative_area_recruited{suffix}.csv", "relative_area_recruited.png"])

    lineage_summary: dict[str, object] | None = None
    if include_metric_lineage_object_metrics and has_roi:
        tracker_result = build_object_lineage(
            frame_indices,
            full_masks,
            config=TrackingConfig(),
        )
        lineage_summary = dict(tracker_result.get("summary", {}) or {})
        object_track_rows = list(tracker_result.get("object_track_rows", []) or [])
        lineage_rows = list(tracker_result.get("lineage_rows", []) or [])
        track_area_rows: list[dict[str, object]] = []
        track_relative_rows: list[dict[str, object]] = []
        lineage_visual_frames: list[tuple[int, np.ndarray]] = []
        tracks = dict(tracker_result.get("tracks", {}) or {})
        mask_rows_by_frame: dict[int, list[dict[str, object]]] = defaultdict(list)
        mask_by_frame_track: dict[tuple[int, int], np.ndarray] = {}
        export_mask_by_track_frame: dict[tuple[int, int], np.ndarray] = {}
        for track_id in sorted(tracks):
            track = tracks[int(track_id)]
            root_track_id = int(getattr(track, "root_track_id", None) or int(track_id))
            for assignment in list(getattr(track, "frame_assignments", []) or []):
                frame_index = int(getattr(assignment, "frame_index", 0))
                local_idx = local_index_by_frame[int(frame_index)]
                original_mask = np.asarray(getattr(assignment, "mask", None), dtype=bool)
                export_mask = (
                    np.asarray(original_mask & roi_mask, dtype=bool).copy()
                    if has_roi and roi_mask is not None
                    else np.asarray(original_mask, dtype=bool).copy()
                )
                export_mask_by_track_frame[(int(track_id), int(frame_index))] = export_mask
                area_px_value = float(np.count_nonzero(export_mask))
                time_value = float(time_sec[local_idx])
                area_mm2_value = (
                    float(area_px_value * (1.0 / float(scale_px_per_mm)) ** 2)
                    if has_scale and scale_px_per_mm is not None
                    else float("nan")
                )
                relative_area_value = (
                    float((area_px_value / float(roi_pixels)) * 100.0)
                    if roi_pixels > 0
                    else float("nan")
                )
                track_area_rows.append(
                    {
                        "track_id": int(track_id),
                        "root_track_id": int(root_track_id),
                        "frame_index": int(frame_index),
                        "frame_display": int(frame_index) + 1,
                        "time_sec": float(time_value),
                        "area_mm2": "" if not np.isfinite(area_mm2_value) else float(area_mm2_value),
                    }
                )
                track_relative_rows.append(
                    {
                        "track_id": int(track_id),
                        "root_track_id": int(root_track_id),
                        "frame_index": int(frame_index),
                        "frame_display": int(frame_index) + 1,
                        "time_sec": float(time_value),
                        "relative_area_pct": "" if not np.isfinite(relative_area_value) else float(relative_area_value),
                    }
                )
                mask_rows_by_frame[int(frame_index)].append(
                    {
                        "track_id": int(track_id),
                        "root_track_id": int(root_track_id),
                    }
                )
                mask_by_frame_track[(int(frame_index), int(track_id))] = np.asarray(original_mask, dtype=bool).copy()
        track_speed_rows = _track_speed_rows(
            tracks=tracks,
            event_start_idx=int(event.start_idx),
            scale_px_per_mm=scale_px_per_mm,
            sec_per_frame=float(sec_per_frame),
            mask_by_track_frame=export_mask_by_track_frame,
        )
        weighted_track_speed_rows = _weighted_track_speed_rows(
            frame_indices=frame_indices,
            time_sec=time_sec,
            track_speed_rows=track_speed_rows,
        )
        weighted_track_speed_values = np.asarray(
            [
                float(row["area_weighted_speed_um_per_sec"])
                for row in weighted_track_speed_rows
                if str(row.get("area_weighted_speed_um_per_sec", "")) != ""
            ],
            dtype=np.float64,
        )
        lineage_summary["area_weighted_avg_speed_um_per_sec"] = (
            float(np.nanmean(weighted_track_speed_values))
            if weighted_track_speed_values.size > 0 and np.isfinite(weighted_track_speed_values).any()
            else None
        )
        lineage_summary["area_weighted_max_speed_um_per_sec"] = (
            float(np.nanmax(weighted_track_speed_values))
            if weighted_track_speed_values.size > 0 and np.isfinite(weighted_track_speed_values).any()
            else None
        )
        lineage_summary["tracks_with_speed_count"] = int(
            len({int(row["track_id"]) for row in track_speed_rows if str(row.get("speed_um_per_sec", "")) != ""})
        )
        lineage_visual_dir = metrics_dir / "object_lineage_frames"
        lineage_visual_dir.mkdir(parents=True, exist_ok=True)
        for frame_index in frame_indices:
            rows_for_frame = list(mask_rows_by_frame.get(int(frame_index), []))
            if not rows_for_frame:
                continue
            mask_by_track_id = {
                int(row["track_id"]): np.asarray(mask_by_frame_track[(int(frame_index), int(row["track_id"]))], dtype=bool)
                for row in rows_for_frame
                if (int(frame_index), int(row["track_id"])) in mask_by_frame_track
            }
            rendered = _draw_lineage_overlay(
                reader.read_frame(int(frame_index), use_cache=True),
                rows_for_frame,
                mask_by_track_id=mask_by_track_id,
            )
            output_name = f"{int(frame_index):06d}_object_lineage.png"
            _write_frame(lineage_visual_dir / output_name, rendered, ".png")
            lineage_visual_frames.append((int(frame_index), np.asarray(rendered, dtype=np.uint8)))
        _write_lineage_overview_montage(
            metrics_dir / "object_lineage_overview.png",
            rendered_frames=lineage_visual_frames,
        )
        _write_rows_csv(
            metrics_dir / f"track_area_recruited{suffix}.csv",
            columns=["track_id", "root_track_id", "frame_index", "frame_display", "time_sec", "area_mm2"],
            rows=track_area_rows,
        )
        _write_rows_csv(
            metrics_dir / f"track_propagation_speed{suffix}.csv",
            columns=["track_id", "root_track_id", "frame_index", "frame_display", "time_sec", "area_px", "speed_um_per_sec"],
            rows=track_speed_rows,
        )
        _write_rows_csv(
            metrics_dir / f"track_relative_area_recruited{suffix}.csv",
            columns=["track_id", "root_track_id", "frame_index", "frame_display", "time_sec", "relative_area_pct"],
            rows=track_relative_rows,
        )
        _write_rows_csv(
            metrics_dir / f"lineage_weighted_propagation_speed{suffix}.csv",
            columns=["frame_index", "frame_display", "time_sec", "active_track_count", "area_weighted_speed_um_per_sec"],
            rows=weighted_track_speed_rows,
        )
        (metrics_dir / "object_lineage_summary.json").write_text(
            json.dumps(lineage_summary, indent=2),
            encoding="utf-8",
        )
        metric_tables.append(
            _rows_table(
                "Track Speed",
                columns=["track_id", "root_track_id", "frame_index", "frame_display", "time_sec", "area_px", "speed_um_per_sec"],
                rows=track_speed_rows,
            )
        )
        metric_tables.append(
            _rows_table(
                "Weighted Track Speed",
                columns=["frame_index", "frame_display", "time_sec", "active_track_count", "area_weighted_speed_um_per_sec"],
                rows=weighted_track_speed_rows,
            )
        )
        metric_tables.append(
            _rows_table(
                "Track Area",
                columns=["track_id", "root_track_id", "frame_index", "frame_display", "time_sec", "area_mm2"],
                rows=track_area_rows,
            )
        )
        metric_tables.append(
            _rows_table(
                "Track Relative Area",
                columns=["track_id", "root_track_id", "frame_index", "frame_display", "time_sec", "relative_area_pct"],
                rows=track_relative_rows,
            )
        )
        lineage_visual_written = 1 + int(len(lineage_visual_frames))
        files_written += 5 + int(lineage_visual_written)
        written.extend(
            [
                f"track_propagation_speed{suffix}.csv",
                f"track_area_recruited{suffix}.csv",
                f"track_relative_area_recruited{suffix}.csv",
                f"lineage_weighted_propagation_speed{suffix}.csv",
                "object_lineage_summary.json",
                "object_lineage_overview.png",
                "object_lineage_frames/",
            ]
        )
        if include_metric_lineage_track_tables:
            _write_rows_csv(
                metrics_dir / f"object_tracks{suffix}.csv",
                columns=["track_id", "root_track_id", "frame_index", "area_px", "centroid_x", "centroid_y", "bbox_x", "bbox_y", "bbox_w", "bbox_h"],
                rows=object_track_rows,
            )
            _write_rows_csv(
                metrics_dir / f"object_lineage{suffix}.csv",
                columns=[
                    "track_id",
                    "root_track_id",
                    "parent_track_ids",
                    "child_track_ids",
                    "birth_frame",
                    "end_frame",
                    "merge_frame",
                    "merged_into_track_id",
                    "terminal_status",
                    "persistence_frames",
                    "max_area_px",
                ],
                rows=lineage_rows,
            )
            metric_tables.append(
                _rows_table(
                    "Object Tracks",
                    columns=["track_id", "root_track_id", "frame_index", "area_px", "centroid_x", "centroid_y", "bbox_x", "bbox_y", "bbox_w", "bbox_h"],
                    rows=object_track_rows,
                )
            )
            metric_tables.append(
                _rows_table(
                    "Object Lineage",
                    columns=[
                        "track_id",
                        "root_track_id",
                        "parent_track_ids",
                        "child_track_ids",
                        "birth_frame",
                        "end_frame",
                        "merge_frame",
                        "merged_into_track_id",
                        "terminal_status",
                        "persistence_frames",
                        "max_area_px",
                    ],
                    rows=lineage_rows,
                )
            )
            files_written += 2
            written.extend([f"object_tracks{suffix}.csv", f"object_lineage{suffix}.csv"])

    summary = {
        "event_id": str(event.event_id),
        "frames_per_sec": float(fps),
        "frames_per_sec_source": str(metrics_settings.get("frames_per_sec_source", "explicit") or "explicit"),
        "event_start_time_sec": float(int(event.start_idx) / float(fps)),
        "event_end_time_sec": float(int(event.end_idx) / float(fps)),
        "has_scale": bool(has_scale),
        "scale_px_per_mm": None if scale_px_per_mm is None else float(scale_px_per_mm),
        "scale_unit": str(metrics_settings.get("scale_unit", "") or ""),
        "scale_source": str(metrics_settings.get("scale_source", "") or ""),
        "has_roi": bool(has_roi),
        "roi_pixels": int(roi_pixels),
        "selected_metrics": {
            "propagation_speed": bool(include_metric_propagation_speed),
            "area_recruited": bool(include_metric_area_recruited),
            "relative_area_recruited": bool(include_metric_relative_area_recruited),
            "lineage_object_metrics": bool(include_metric_lineage_object_metrics),
        },
        "propagation_gap_warning": dict(propagation_gap_warning) if propagation_gap_warning is not None else None,
        "object_lineage_summary": dict(lineage_summary or {}),
        "written_files": list(written),
        "overall_avg_speed_um_per_sec": float(np.nanmean(speed_um_per_sec)) if np.isfinite(speed_um_per_sec).any() else None,
        "overall_max_speed_um_per_sec": float(np.nanmax(speed_um_per_sec)) if np.isfinite(speed_um_per_sec).any() else None,
        "max_area_mm2": float(np.nanmax(area_mm2)) if np.isfinite(area_mm2).any() else None,
        "max_relative_area_pct": float(np.nanmax(relative_area_pct)) if np.isfinite(relative_area_pct).any() else None,
    }
    if include_metric_combined_spreadsheet and metric_tables:
        xlsx_name = f"metrics_combined{suffix}.xlsx"
        written.append(xlsx_name)
        summary["written_files"] = list(written)
        _write_metrics_combined_workbook(
            metrics_dir / xlsx_name,
            summary=summary,
            metric_tables=metric_tables,
        )
        files_written += 1
    written.extend(["metrics_summary.json", "metrics_summary.md"])
    summary["written_files"] = list(written)
    (metrics_dir / "metrics_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    _write_metrics_summary_markdown(metrics_dir / "metrics_summary.md", summary, event_title=_event_output_name(event))
    files_written += 2
    return {"files_written": int(files_written)}


def _build_event_global_mask_map(
    *,
    event: EventCandidate,
    masks_payload,
    baseline_pre_frames: int,
    analysis_sidecar_payload: dict[str, object] | None = None,
) -> dict[int, np.ndarray]:
    out: dict[int, np.ndarray] = {}
    if masks_payload is None:
        return out
    sidecar = dict(analysis_sidecar_payload or {})
    if isinstance(masks_payload, dict):
        flags = dict(getattr(event, "flags", {}) or {})
        try:
            scope_start = int(flags.get("analysis_scope_start_idx", int(event.start_idx)))
            scope_end = int(flags.get("analysis_scope_end_idx", int(event.end_idx)))
            local_event_start = int(flags.get("analysis_local_event_start_idx", int(event.start_idx) - scope_start))
        except (TypeError, ValueError):
            scope_start = int(event.start_idx)
            scope_end = int(event.end_idx)
            local_event_start = 0
        scope_len = max(0, int(scope_end) - int(scope_start) + 1)
        event_len = max(0, int(event.end_idx) - int(event.start_idx) + 1)
        origin_hint = str(sidecar.get("masks_committed_frame_origin", "") or "").strip().lower()
        for raw_idx, mask in masks_payload.items():
            try:
                idx = int(raw_idx)
            except Exception:
                continue
            global_idx = None
            if origin_hint == "global":
                global_idx = idx
            elif origin_hint == "event_local":
                if 0 <= idx < event_len:
                    global_idx = int(event.start_idx) + idx
            elif origin_hint == "analysis_scope_local":
                if 0 <= idx < scope_len:
                    global_idx = scope_start + idx
            else:
                if 0 <= idx < scope_len:
                    if local_event_start > 0 and 0 <= idx < event_len and idx < local_event_start:
                        global_idx = int(event.start_idx) + idx
                    else:
                        global_idx = scope_start + idx
                elif 0 <= idx < event_len:
                    global_idx = int(event.start_idx) + idx
                else:
                    global_idx = idx
            arr = np.asarray(mask, dtype=bool)
            if arr.ndim != 2 or global_idx is None:
                continue
            out[int(global_idx)] = arr.copy()
        return out

    arr = np.asarray(masks_payload)
    if arr.ndim != 3:
        return out
    frame_count = int(arr.shape[0])
    if frame_count <= 0:
        return out

    flags = dict(getattr(event, "flags", {}) or {})
    scope_start = None
    scope_end = None
    try:
        raw_scope_start = flags.get("analysis_scope_start_idx")
        raw_scope_end = flags.get("analysis_scope_end_idx")
        if raw_scope_start is not None and raw_scope_end is not None:
            scope_start = int(raw_scope_start)
            scope_end = int(raw_scope_end)
    except (TypeError, ValueError):
        scope_start = None
        scope_end = None

    if scope_start is None or scope_end is None or int(scope_end) < int(scope_start):
        baseline_pre = max(0, int(flags.get("baseline_pre_frames", baseline_pre_frames) or 0))
        scope_start = max(0, int(event.start_idx) - baseline_pre)
        scope_end = int(event.end_idx)

    scope_len = max(0, int(scope_end) - int(scope_start) + 1)
    event_len = max(0, int(event.end_idx) - int(event.start_idx) + 1)
    origin_hint = str(sidecar.get("masks_committed_frame_origin", "") or "").strip().lower()

    # Project sidecars may persist analysis-scope-local arrays where index 0 is
    # analysis_scope_start_idx rather than event.start_idx.
    if origin_hint == "analysis_scope_local" or (scope_len > 0 and frame_count == scope_len):
        for local_idx in range(frame_count):
            global_idx = int(scope_start) + int(local_idx)
            mask = np.asarray(arr[local_idx], dtype=bool)
            if mask.ndim == 2:
                out[int(global_idx)] = mask.copy()
        return out

    if origin_hint == "event_local" or (event_len > 0 and frame_count == event_len):
        for local_idx in range(frame_count):
            global_idx = int(event.start_idx) + int(local_idx)
            mask = np.asarray(arr[local_idx], dtype=bool)
            if mask.ndim == 2:
                out[int(global_idx)] = mask.copy()
        return out

    # If payload looks global, keep indices as-is; otherwise treat it as event-scope local.
    if origin_hint == "global" or frame_count > int(event.end_idx):
        for idx in range(frame_count):
            mask = np.asarray(arr[idx], dtype=bool)
            if mask.ndim == 2:
                out[int(idx)] = mask.copy()
        return out

    for local_idx in range(frame_count):
        global_idx = int(event.start_idx) + int(local_idx)
        mask = np.asarray(arr[local_idx], dtype=bool)
        if mask.ndim == 2:
            out[int(global_idx)] = mask.copy()
    return out


def _export_frame(
    reader: StackReader,
    frame_idx: int,
    out_dir: Path,
    event_id: str,
    role: str,
    trace: Optional[TraceResult],
) -> ExportRecord:
    frame = reader.read_frame(frame_idx, use_cache=True)
    ref = reader.get_frame_ref(frame_idx)

    frame_name = ref.frame_name
    stem = Path(frame_name).stem
    source_ext = ref.source_ext

    if np.issubdtype(frame.dtype, np.integer) and frame.dtype == np.uint8 and source_ext in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}:
        out_ext = source_ext
    elif np.issubdtype(frame.dtype, np.floating):
        # Floating images can be ambiguous in common formats; preserve in TIFF.
        out_ext = ".tiff"
    else:
        out_ext = ".tiff"

    output_name = f"{frame_idx:06d}_{stem}{out_ext}"
    output_path = out_dir / output_name

    _write_frame(output_path, frame, out_ext)

    timestamp_sec = None
    if trace is not None and frame_idx < len(trace.time_sec):
        timestamp_sec = _finite_optional(trace.time_sec[frame_idx])

    return ExportRecord(
        event_id=event_id,
        role=role,
        frame_idx=int(frame_idx),
        frame_name=frame_name,
        source_path=str(ref.source_path),
        output_path=str(output_path),
        timestamp_sec=timestamp_sec,
    )


def analysis_image_export_plan(event: EventCandidate, *, default_baseline_pre_frames: int) -> tuple[int, int, int, dict[str, bool]]:
    flags = dict(getattr(event, "flags", {}) or {})
    baseline_pre = max(1, int(flags.get("baseline_pre_frames", default_baseline_pre_frames)))
    processing_raw = dict(flags.get("analysis_processing", {})) if isinstance(flags.get("analysis_processing"), dict) else {}
    processing = {
        "horizontal_bar_denoise": bool(processing_raw.get("horizontal_bar_denoise", False)),
        "smoothing": bool(processing_raw.get("smoothing", True)),
        "baseline_subtraction": bool(processing_raw.get("baseline_subtraction", True)),
        "global_normalization": bool(processing_raw.get("global_normalization", True)),
        "stabilization": bool(processing_raw.get("stabilization", False)),
    }
    scope_start = int(flags.get("analysis_scope_start_idx", max(0, int(event.start_idx) - baseline_pre)))
    scope_end = int(flags.get("analysis_scope_end_idx", int(event.end_idx)))
    scope_start = max(0, min(scope_start, int(event.end_idx)))
    scope_end = max(scope_start, int(scope_end))
    return scope_start, scope_end, baseline_pre, processing


def analysis_image_cache_key(event: EventCandidate, *, default_baseline_pre_frames: int) -> tuple:
    scope_start, scope_end, baseline_pre, processing = analysis_image_export_plan(
        event,
        default_baseline_pre_frames=int(default_baseline_pre_frames),
    )
    return (
        str(event.event_id),
        int(scope_start),
        int(scope_end),
        int(baseline_pre),
        bool(processing["horizontal_bar_denoise"]),
        bool(processing["smoothing"]),
        bool(processing["baseline_subtraction"]),
        bool(processing["global_normalization"]),
        bool(processing["stabilization"]),
    )


def _cached_analysis_image_sequence(cache_entry: object, *, expected_count: int):
    if isinstance(cache_entry, np.ndarray):
        arr = np.asarray(cache_entry, dtype=np.uint8)
        if arr.ndim == 3 and int(arr.shape[0]) == int(expected_count):
            return arr
        return None
    if isinstance(cache_entry, dict):
        frames_viz = cache_entry.get("frames_viz")
        cached_count = cache_entry.get("frame_count")
        try:
            resolved_count = int(cached_count if cached_count is not None else len(frames_viz))
        except Exception:
            return None
        if resolved_count != int(expected_count):
            return None
        return frames_viz
    return None


def resolve_analysis_image_stack(
    frame_source,
    event: EventCandidate,
    *,
    default_baseline_pre_frames: int,
    cache: dict[tuple, object] | None = None,
    progress_callback: Callable[[dict], None] | None = None,
) -> object:
    cache_key = analysis_image_cache_key(event, default_baseline_pre_frames=int(default_baseline_pre_frames))
    scope_start, scope_end, baseline_pre, processing = analysis_image_export_plan(
        event,
        default_baseline_pre_frames=int(default_baseline_pre_frames),
    )
    expected_count = max(0, int(scope_end - scope_start + 1))
    if isinstance(cache, dict):
        cached = _cached_analysis_image_sequence(cache.get(cache_key), expected_count=expected_count)
        if cached is not None:
            return cached
    scoped_source = EventScopedFrameSource(frame_source, int(scope_start), int(scope_end))
    prepared_source = PreparedFrameSource(
        scoped_source,
        baseline_frames=int(baseline_pre),
        apply_horizontal_bar_denoise=bool(processing["horizontal_bar_denoise"]),
        apply_smoothing=bool(processing["smoothing"]),
        apply_baseline_subtraction=bool(processing["baseline_subtraction"]),
        apply_global_normalization=bool(processing["global_normalization"]),
        apply_stabilization=bool(processing["stabilization"]),
    )
    prepared_source.prepare(progress_callback=progress_callback)
    frames_viz = _PreparedVisualSequence(prepared_source)
    if isinstance(cache, dict):
        cache[cache_key] = {
            "frames_viz": frames_viz,
            "frame_count": int(len(frames_viz)),
            "stats": frames_viz.stats,
        }
    return frames_viz


def _sha256_array(arr: np.ndarray) -> str:
    contiguous = np.ascontiguousarray(arr)
    h = hashlib.sha256()
    h.update(str(contiguous.dtype).encode("utf-8"))
    h.update(json.dumps([int(v) for v in contiguous.shape]).encode("utf-8"))
    h.update(contiguous.tobytes())
    return h.hexdigest()


def _analysis_preprocessing_payload(
    *,
    event: EventCandidate,
    scope_start: int,
    scope_end: int,
    baseline_pre: int,
    processing: dict[str, bool],
    stats: object | None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "event_id": str(event.event_id),
        "scope_start_idx": int(scope_start),
        "scope_end_idx": int(scope_end),
        "baseline_pre_frames": int(baseline_pre),
        "processing": {str(key): bool(value) for key, value in dict(processing or {}).items()},
        "stats_available": stats is not None,
    }
    if stats is None:
        return payload

    baseline = getattr(stats, "baseline", None)
    baseline_payload: dict[str, object] | None = None
    if baseline is not None:
        baseline_arr = np.asarray(baseline, dtype=np.float32)
        baseline_payload = {
            "sha256": _sha256_array(baseline_arr),
            "shape": [int(v) for v in baseline_arr.shape],
            "median": float(np.median(baseline_arr)) if baseline_arr.size > 0 else None,
        }
    offsets = getattr(stats, "stabilization_offsets_px", None)
    offsets_payload = None
    if offsets is not None:
        offsets_arr = np.asarray(offsets, dtype=np.float32)
        offsets_payload = offsets_arr.tolist()
    payload.update(
        {
            "frame_count": int(getattr(stats, "frame_count", 0) or 0),
            "frame_shape": [int(v) for v in tuple(getattr(stats, "frame_shape", (0, 0)))[:2]],
            "baseline_frames_used": int(getattr(stats, "baseline_frames", 0) or 0),
            "normalization": {
                "global": bool(getattr(stats, "apply_global_normalization", False)),
                "p1": None if getattr(stats, "p1", None) is None else float(getattr(stats, "p1")),
                "p99": None if getattr(stats, "p99", None) is None else float(getattr(stats, "p99")),
            },
            "baseline": baseline_payload,
            "stabilization": {
                "enabled": bool(getattr(stats, "apply_stabilization", False)),
                "reference_index": int(getattr(stats, "stabilization_reference_index", 0) or 0),
                "offsets_px": offsets_payload,
                "fallback_frame_indices": [int(v) for v in list(getattr(stats, "stabilization_fallback_frame_indices", []) or [])],
                "used_fallback_offsets": bool(list(getattr(stats, "stabilization_fallback_frame_indices", []) or [])),
            },
        }
    )
    return payload


def _write_analysis_preprocessing_sidecar(
    event_dir: Path,
    *,
    event: EventCandidate,
    scope_start: int,
    scope_end: int,
    baseline_pre: int,
    processing: dict[str, bool],
    analysis_viz_frames: object,
) -> None:
    stats = getattr(analysis_viz_frames, "stats", None)
    if callable(stats):
        stats = stats()
    payload = _analysis_preprocessing_payload(
        event=event,
        scope_start=int(scope_start),
        scope_end=int(scope_end),
        baseline_pre=int(baseline_pre),
        processing=processing,
        stats=stats,
    )
    (event_dir / "analysis_preprocessing_sidecar.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


def _export_analysis_frame(
    reader: StackReader,
    frame_idx: int,
    out_dir: Path,
    role: str,
    analysis_frame: np.ndarray,
) -> None:
    ref = reader.get_frame_ref(frame_idx)
    frame_name = ref.frame_name
    stem = Path(frame_name).stem
    source_ext = ref.source_ext
    output_ext = source_ext if source_ext in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"} else ".tiff"
    output_name = f"{int(frame_idx):06d}_{role}_{stem}{output_ext}"
    _write_frame(out_dir / output_name, np.asarray(analysis_frame, dtype=np.uint8), output_ext)


def _export_mask_overlay_frame(
    reader: StackReader,
    frame_idx: int,
    out_dir: Path,
    role: str,
    mask: np.ndarray,
) -> None:
    frame = reader.read_frame(frame_idx, use_cache=True)
    ref = reader.get_frame_ref(frame_idx)
    frame_name = ref.frame_name
    stem = Path(frame_name).stem
    source_ext = ref.source_ext
    output_ext = source_ext if source_ext in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"} else ".tiff"
    output_name = f"{int(frame_idx):06d}_{role}_overlay_{stem}{output_ext}"
    _write_frame(out_dir / output_name, apply_mask_overlay(frame, mask), output_ext)


def _export_analysis_overlay_frame(
    reader: StackReader,
    frame_idx: int,
    out_dir: Path,
    role: str,
    analysis_frame: np.ndarray,
    mask: np.ndarray,
) -> None:
    ref = reader.get_frame_ref(frame_idx)
    frame_name = ref.frame_name
    stem = Path(frame_name).stem
    source_ext = ref.source_ext
    output_ext = source_ext if source_ext in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"} else ".tiff"
    output_name = f"{int(frame_idx):06d}_{role}_analysis_overlay_{stem}{output_ext}"
    _write_frame(out_dir / output_name, apply_mask_overlay(analysis_frame, mask), output_ext)


def _write_frame(path: Path, frame: np.ndarray, ext: str) -> None:
    if ext in {".tif", ".tiff"}:
        tifffile.imwrite(str(path), frame)
        return

    if frame.dtype != np.uint8:
        # Fallback to TIFF to preserve original precision.
        tifffile.imwrite(str(path.with_suffix(".tiff")), frame)
        return

    img = Image.fromarray(frame)
    img.save(path)


def _write_mask(path: Path, mask: np.ndarray) -> None:
    mask_u8 = np.where(np.asarray(mask, dtype=bool), 255, 0).astype(np.uint8)
    tifffile.imwrite(str(path), mask_u8)


def _write_trace_data_csv(path: Path, trace: TraceResult) -> None:
    headers = [
        "frame_idx",
        "time_sec",
        "mean",
        "median",
        "std",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        n = len(trace.frame_indices)
        for i in range(n):
            writer.writerow(
                [
                    trace.frame_indices[i],
                    "" if i >= len(trace.time_sec) or _finite_optional(trace.time_sec[i]) is None else _finite_optional(trace.time_sec[i]),
                    trace.mean[i] if i < len(trace.mean) else None,
                    trace.median[i] if i < len(trace.median) else None,
                    trace.std[i] if i < len(trace.std) else None,
                ]
            )


def _write_trace_plot(path: Path, trace: TraceResult, events: list[EventCandidate]) -> None:
    plt = _load_pyplot()
    x = np.asarray(trace.frame_indices)
    y_mean = np.asarray(trace.mean) if trace.mean else np.array([])

    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
    if y_mean.size > 0:
        axes[0].plot(x, y_mean, color="black", linewidth=1)
    axes[0].set_ylabel("Mean intensity")
    axes[0].set_title("Global Signal")

    for ev in events:
        axes[1].axvspan(ev.start_idx, ev.end_idx, color="tab:red", alpha=0.2)
    axes[1].set_xlabel("Frame index")
    axes[1].set_ylabel("Event labels")
    axes[1].set_yticks([])
    axes[1].set_title("Marked SD Events")

    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _write_manifest_csv(path: Path, records: list[ExportRecord]) -> None:
    headers = [
        "event_id",
        "role",
        "frame_idx",
        "frame_name",
        "source_path",
        "output_path",
        "timestamp_sec",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for rec in records:
            writer.writerow(
                [
                    rec.event_id,
                    rec.role,
                    rec.frame_idx,
                    rec.frame_name,
                    rec.source_path,
                    rec.output_path,
                    rec.timestamp_sec,
                ]
            )


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _run_git(args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(_repo_root()), *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    return result.stdout.strip()


def _git_metadata() -> dict[str, object]:
    status = _run_git(["status", "--porcelain"])
    return {
        "commit": _run_git(["rev-parse", "HEAD"]),
        "branch": _run_git(["rev-parse", "--abbrev-ref", "HEAD"]),
        "dirty": None if status is None else bool(status),
    }


def _file_sha256(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _source_file_metadata(reader: StackReader) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    seen: set[str] = set()
    for frame_idx in range(int(reader.get_frame_count())):
        try:
            ref = reader.get_frame_ref(int(frame_idx))
        except Exception:
            continue
        path = Path(ref.source_path)
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        sha = _file_sha256(path)
        out.append(
            {
                "path": key,
                "sha256": sha,
                "hash_status": "ok" if sha else "unavailable",
            }
        )
    return out


def _stack_metadata(reader: StackReader) -> dict[str, object]:
    try:
        info = reader.get_stack_info()
    except Exception:
        info = None
    return {
        "input_dir": None if info is None else str(getattr(info, "input_dir", "") or ""),
        "frame_count": int(reader.get_frame_count()),
        "frame_height": None if info is None else int(getattr(info, "frame_height", 0) or 0),
        "frame_width": None if info is None else int(getattr(info, "frame_width", 0) or 0),
        "dtype": None if info is None else str(getattr(info, "dtype", "") or ""),
        "channel_mode": str(getattr(reader, "channel_mode", "unknown") or "unknown"),
    }


def _roi_mask_hash_from_settings(metrics_settings: dict[str, object]) -> str | None:
    raw = metrics_settings.get("roi_mask")
    if raw is None:
        return None
    try:
        arr = np.asarray(raw, dtype=bool)
    except Exception:
        return None
    if arr.ndim != 2 or arr.size <= 0:
        return None
    return _sha256_array(arr.astype(np.uint8))


def _build_export_metadata(
    *,
    reader: StackReader,
    events: list[EventCandidate],
    analysis_sidecar: dict[str, dict[str, object]],
    project_metadata: dict[str, object] | None,
    baseline_pre_frames: int,
) -> dict[str, object]:
    calibration_by_event: dict[str, object] = {}
    roi_hash_by_event: dict[str, str] = {}
    preprocessing_by_event: dict[str, object] = {}
    for event in events:
        event_id = str(event.event_id)
        event_sidecar = dict(analysis_sidecar.get(event_id, {}) or {})
        metrics_settings = MetricsSettingsResolver.resolve_for_event(
            event_id=event_id,
            analysis_sidecar={event_id: event_sidecar},
            project_metadata=project_metadata if isinstance(project_metadata, dict) else {},
        )
        roi_hash = _roi_mask_hash_from_settings(metrics_settings)
        if roi_hash:
            roi_hash_by_event[event_id] = roi_hash
        scope_start, scope_end, analysis_baseline_pre, processing = analysis_image_export_plan(
            event,
            default_baseline_pre_frames=int(baseline_pre_frames),
        )
        preprocessing_by_event[event_id] = {
            "scope_start_idx": int(scope_start),
            "scope_end_idx": int(scope_end),
            "baseline_pre_frames": int(analysis_baseline_pre),
            "processing": {str(key): bool(value) for key, value in processing.items()},
        }
        calibration_by_event[event_id] = {
            "frames_per_sec": _finite_optional(metrics_settings.get("frames_per_sec")),
            "frames_per_sec_source": str(metrics_settings.get("frames_per_sec_source", "explicit") or "explicit")
            if "frames_per_sec" in metrics_settings
            else None,
            "scale_px_per_mm": _finite_optional(metrics_settings.get("scale_px_per_mm")),
            "scale_unit": str(metrics_settings.get("scale_unit", "") or "") or None,
            "scale_source": str(metrics_settings.get("scale_source", "") or "") or None,
            "scale_points": metrics_settings.get("scale_points"),
            "scale_image_path": metrics_settings.get("scale_image_path"),
            "roi_mask_sha256": roi_hash,
        }
    roi_hash_values = sorted(set(roi_hash_by_event.values()))
    return {
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "app_version": detect_app_version(),
        "git": _git_metadata(),
        "stack": _stack_metadata(reader),
        "baseline_pre_frames": int(baseline_pre_frames),
        "calibration": {"events": calibration_by_event},
        "preprocessing": {"events": preprocessing_by_event},
        "source_files": _source_file_metadata(reader),
        "roi_mask_sha256": roi_hash_values[0] if len(roi_hash_values) == 1 else None,
        "roi_mask_sha256_by_event": roi_hash_by_event,
    }


def _write_manifest_json(
    path: Path,
    records: list[ExportRecord],
    events: list[dict],
    *,
    export_metadata: dict[str, object] | None = None,
) -> None:
    payload = {
        "events": events,
        "frames": [asdict(rec) for rec in records],
        "export_metadata": dict(export_metadata or {}),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _format_summary_value(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        if not np.isfinite(value):
            return "n/a"
        return f"{value:.4f}".rstrip("0").rstrip(".")
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (list, tuple)):
        return ", ".join(_format_summary_value(item) for item in value) if value else "none"
    return str(value)


def _markdown_bullet(label: str, value: object) -> str:
    return f"- {label}: {_format_summary_value(value)}"


def _write_event_summary_markdown(path: Path, summary: dict[str, object]) -> None:
    label = str(summary.get("label", "") or "").strip()
    title = f"# Event {label}" if label else f"# Event {summary.get('event_id', 'unknown')}"
    lines = [
        title,
        "",
        "## Timing",
        _markdown_bullet("Event ID", summary.get("event_id")),
    ]
    if label:
        lines.append(_markdown_bullet("Label", label))
    lines.extend(
        [
        _markdown_bullet("Start frame", summary.get("start_idx")),
        _markdown_bullet("End frame", summary.get("end_idx")),
        _markdown_bullet("Duration (frames)", summary.get("duration_frames")),
        _markdown_bullet("Duration (sec)", summary.get("duration_sec")),
        _markdown_bullet("Baseline start frame", summary.get("baseline_start_idx")),
        _markdown_bullet("Baseline end frame", summary.get("baseline_end_idx")),
        ]
    )
    flags = summary.get("flags")
    if isinstance(flags, dict) and flags:
        lines.extend(
            [
                "",
                "## Flags",
                "```json",
                json.dumps(flags, indent=2, sort_keys=True),
                "```",
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_manifest_markdown(
    path: Path,
    *,
    records: list[ExportRecord],
    events: list[dict[str, object]],
    event_output_segment_by_id: dict[str, str],
) -> None:
    record_counts: dict[str, dict[str, int]] = {}
    for rec in records:
        counts = record_counts.setdefault(str(rec.event_id), {"baseline": 0, "event": 0})
        counts[str(rec.role)] = counts.get(str(rec.role), 0) + 1

    lines = [
        "# Export Manifest",
        "",
        _markdown_bullet("Events exported", len(events)),
        _markdown_bullet("Frames exported", len(records)),
        "",
        "## Events",
    ]
    if not events:
        lines.append("- none")
    else:
        for event in events:
            event_id = str(event.get("event_id", "unknown"))
            label = str(event.get("label", "") or "").strip()
            counts = record_counts.get(event_id, {})
            segment = event_output_segment_by_id.get(event_id, event_id)
            heading = label or event_id
            event_lines = [
                f"### {heading}",
                _markdown_bullet("Event ID", event_id),
            ]
            if label:
                event_lines.append(_markdown_bullet("Label", label))
            event_lines.extend(
                [
                    _markdown_bullet("Output folder", segment),
                    _markdown_bullet("Start frame", event.get("start_idx")),
                    _markdown_bullet("End frame", event.get("end_idx")),
                    _markdown_bullet("Duration (frames)", event.get("duration_frames")),
                    _markdown_bullet("Duration (sec)", event.get("duration_sec")),
                    _markdown_bullet("Baseline start frame", event.get("baseline_start_idx")),
                    _markdown_bullet("Baseline end frame", event.get("baseline_end_idx")),
                    _markdown_bullet("Baseline frames exported", counts.get("baseline", 0)),
                    _markdown_bullet("Event frames exported", counts.get("event", 0)),
                    "",
                ]
            )
            lines.extend(event_lines)

    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_metrics_summary_markdown(path: Path, summary: dict[str, object], *, event_title: str | None = None) -> None:
    selected_metrics = summary.get("selected_metrics")
    enabled_metrics = []
    if isinstance(selected_metrics, dict):
        enabled_metrics = [name for name, enabled in selected_metrics.items() if bool(enabled)]
    title = str(event_title or "").strip() or str(summary.get("event_id", "unknown"))
    lines = [
        f"# Metrics Summary: {title}",
        "",
        _markdown_bullet("Event ID", summary.get("event_id")),
        _markdown_bullet("Frames per second", summary.get("frames_per_sec")),
        _markdown_bullet("Event start time (sec)", summary.get("event_start_time_sec")),
        _markdown_bullet("Event end time (sec)", summary.get("event_end_time_sec")),
        _markdown_bullet("Scale available", summary.get("has_scale")),
        _markdown_bullet("ROI available", summary.get("has_roi")),
        _markdown_bullet("ROI pixels", summary.get("roi_pixels")),
        _markdown_bullet("Selected metrics", enabled_metrics),
        _markdown_bullet("Overall average speed (um/sec)", summary.get("overall_avg_speed_um_per_sec")),
        _markdown_bullet("Overall max speed (um/sec)", summary.get("overall_max_speed_um_per_sec")),
        _markdown_bullet("Max area (mm^2)", summary.get("max_area_mm2")),
        _markdown_bullet("Max relative area (%)", summary.get("max_relative_area_pct")),
        _markdown_bullet("Written files", summary.get("written_files")),
    ]
    lineage_summary = summary.get("object_lineage_summary")
    if isinstance(lineage_summary, dict) and lineage_summary:
        lines.extend(
            [
                _markdown_bullet("Tracked objects kept", lineage_summary.get("kept_track_count")),
                _markdown_bullet("Noise-filtered objects", lineage_summary.get("noise_filtered_track_count")),
                _markdown_bullet("Merge events", lineage_summary.get("merge_event_count")),
                _markdown_bullet("Lineage weighted average speed (um/sec)", lineage_summary.get("area_weighted_avg_speed_um_per_sec")),
                _markdown_bullet("Lineage weighted max speed (um/sec)", lineage_summary.get("area_weighted_max_speed_um_per_sec")),
                _markdown_bullet("Tracks with speed", lineage_summary.get("tracks_with_speed_count")),
            ]
        )
    warning_entries = _propagation_warning_entries(summary.get("propagation_gap_warning"))
    if warning_entries:
        lines.extend(
            [
                "",
                "## Propagation Gap Warning",
            ]
        )
        for index, entry in enumerate(warning_entries, start=1):
            prefix = "Warning" if len(warning_entries) == 1 else f"Warning {index}"
            lines.extend(
                [
                    _markdown_bullet(f"{prefix} type", entry.get("kind", "gap")),
                    _markdown_bullet(f"{prefix} actions applied", entry.get("actions", entry.get("action"))),
                    _markdown_bullet(f"{prefix} frame runs", entry.get("frame_runs")),
                ]
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_metrics_warning_markdown(path: Path, warning: dict[str, object]) -> None:
    event_label = str(warning.get("event_label", "") or "").strip()
    event_id = str(warning.get("event_id", "unknown") or "unknown")
    warning_entries = _propagation_warning_entries(warning)
    lines = [
        f"# Propagation Speed Warning: {event_label or event_id}",
        "",
        _markdown_bullet("Event ID", event_id),
        _markdown_bullet("Metric", warning.get("metric")),
    ]
    for index, entry in enumerate(warning_entries, start=1):
        prefix = "Warning" if len(warning_entries) == 1 else f"Warning {index}"
        lines.extend(
            [
                _markdown_bullet(f"{prefix} type", entry.get("kind", "gap")),
                _markdown_bullet(f"{prefix} actions applied", entry.get("actions", entry.get("action"))),
                _markdown_bullet(f"{prefix} frame runs", entry.get("frame_runs")),
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
