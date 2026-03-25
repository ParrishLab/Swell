from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import json
from dataclasses import asdict
from pathlib import Path
from threading import Lock
from typing import Callable, Iterable, Optional

import numpy as np
from PIL import Image
import tifffile
from sdapp.analysis.core.metrics import (
    compute_frame_metrics,
    extract_primary_boundary,
    roi_mask_from_points,
    smooth_boundary_fft,
)
from sdapp.shared.image_overlay import apply_mask_overlay
from sdapp.shared.persistence.event_path import allocate_event_path_segment
from sdapp.shared.services import MetricsSettingsResolver

from .config import EventCandidate, ExportRecord, TraceResult
from .signal_analysis import event_to_dict
from .stack_reader import StackReader


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
    include_binary_masks: bool = False,
    include_mask_overlay_images: bool = False,
    analysis_sidecar: Optional[dict[str, dict]] = None,
    include_metric_propagation_speed: bool = False,
    include_metric_area_recruited: bool = False,
    include_metric_relative_area_recruited: bool = False,
    project_metadata: Optional[dict[str, object]] = None,
) -> dict:
    include_any_metrics = (
        bool(include_metric_propagation_speed)
        or bool(include_metric_area_recruited)
        or bool(include_metric_relative_area_recruited)
    )
    include_any_mask_exports = bool(include_binary_masks) or bool(include_mask_overlay_images)
    if not bool(include_event_images) and not bool(include_baseline_images) and not include_any_mask_exports and not include_any_metrics:
        raise ValueError("Select at least one export target (images, masks, overlays, or metrics).")

    out_dir = Path(output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    selected_ids = set(selected_event_ids) if selected_event_ids else {e.event_id for e in events}
    selected_events = [e for e in events if e.event_id in selected_ids]
    used_event_segments: set[str] = set()
    event_output_segment_by_id: dict[str, str] = {}
    for event in selected_events:
        key = str(event.event_id)
        if key not in event_output_segment_by_id:
            event_output_segment_by_id[key] = allocate_event_path_segment(key, used_event_segments)

    has_trace = trace is not None and (
        bool(trace.frame_indices) or bool(trace.mean) or bool(trace.median) or bool(trace.std) or bool(trace.time_sec)
    )
    if has_trace:
        _write_trace_data_csv(out_dir / "trace_data.csv", trace)
        _write_trace_plot(out_dir / "trace_plot.png", trace, selected_events)

    manifest_records: list[ExportRecord] = []
    event_summaries: list[dict] = []
    masks_exported = 0
    mask_overlay_images_exported = 0
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
        baseline_dir = event_dir / "baseline"
        extent_dir = event_dir / "event_extent"
        if bool(include_baseline_images):
            baseline_dir.mkdir(parents=True, exist_ok=True)
        if bool(include_event_images):
            extent_dir.mkdir(parents=True, exist_ok=True)
        masks_dir: Path | None = None
        if bool(include_binary_masks):
            masks_dir = event_dir / "binary_masks"
            masks_dir.mkdir(parents=True, exist_ok=True)
        overlay_dir: Path | None = None
        if bool(include_mask_overlay_images):
            overlay_dir = event_dir / "mask_overlays"
            overlay_dir.mkdir(parents=True, exist_ok=True)

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
        export_indices = set(baseline_indices + event_indices)

        work_items: list[tuple[int, str, int]] = []
        for frame_idx in baseline_indices:
            work_items.append((frame_idx, "baseline", 0))
        for frame_idx in event_indices:
            work_items.append((frame_idx, "event", 1))

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_map = {}
            for frame_idx, role, _order in work_items:
                target_dir = baseline_dir if role == "baseline" else extent_dir
                fut = pool.submit(_export_frame, reader, frame_idx, target_dir, event.event_id, role, trace)
                future_map[fut] = (frame_idx, role)

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

        event_sidecar = dict((analysis_sidecar or {}).get(str(event.event_id), {}) or {})
        mask_map = _build_event_global_mask_map(
            event=event,
            masks_payload=event_sidecar.get("masks_committed"),
            baseline_pre_frames=int(baseline_pre_frames),
        )
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
            )
            metrics_files_exported += int(metric_result.get("files_written", 0))

        summary = event_to_dict(event)
        summary["baseline_start_idx"] = baseline_start
        summary["baseline_end_idx"] = baseline_end if baseline_end >= 0 else None
        summary_path = event_dir / "event_summary.json"
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        event_summaries.append(summary)

    _write_manifest_csv(out_dir / "events_manifest.csv", manifest_records)
    _write_manifest_json(out_dir / "events_manifest.json", manifest_records, event_summaries)

    return {
        "output_dir": str(out_dir),
        "events_exported": len(selected_events),
        "frames_exported": len(manifest_records),
        "masks_exported": int(masks_exported),
        "mask_overlay_images_exported": int(mask_overlay_images_exported),
        "metrics_files_exported": int(metrics_files_exported),
        "manifest_csv": str(out_dir / "events_manifest.csv"),
        "manifest_json": str(out_dir / "events_manifest.json"),
    }


def _safe_float(value, default: float | None = None) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if not np.isfinite(v):
        return default
    return v


def _resolve_roi_mask(metrics_settings: dict[str, object], frame_shape: tuple[int, int]) -> np.ndarray | None:
    normalized = MetricsSettingsResolver.normalize(metrics_settings)
    raw_mask = normalized.get("roi_mask")
    if raw_mask is not None:
        arr = np.asarray(raw_mask, dtype=bool)
        if arr.ndim == 2 and arr.shape == frame_shape and np.any(arr):
            return arr.copy()
    raw_points = normalized.get("roi_points")
    if isinstance(raw_points, list) and raw_points:
        try:
            mask = roi_mask_from_points(raw_points, frame_shape)
        except Exception:
            mask = None
        if mask is not None and mask.shape == frame_shape and np.any(mask):
            return np.asarray(mask, dtype=bool).copy()
    return None


def _write_metric_csv(path: Path, frame_indices: list[int], time_sec: list[float], values: np.ndarray, value_column: str) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["frame_index", "frame_display", "time_sec", value_column])
        for frame_idx, t_sec, val in zip(frame_indices, time_sec, values):
            out_val = "" if not np.isfinite(float(val)) else float(val)
            writer.writerow([int(frame_idx), int(frame_idx) + 1, float(t_sec), out_val])


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
) -> dict[str, object]:
    frame0 = np.asarray(reader.read_frame(0, use_cache=True))
    if frame0.ndim == 3:
        frame_shape = (int(frame0.shape[0]), int(frame0.shape[1]))
    else:
        frame_shape = (int(frame0.shape[0]), int(frame0.shape[1]))
    frame_indices = list(range(int(event.start_idx), int(event.end_idx) + 1))
    if not frame_indices:
        return {"files_written": 0}

    scale_px_per_mm = _safe_float(metrics_settings.get("scale_px_per_mm"), default=None)
    has_scale = scale_px_per_mm is not None and scale_px_per_mm > 0
    fps = _safe_float(metrics_settings.get("frames_per_sec"), default=1.0)
    if fps is None or fps <= 0:
        fps = 1.0
    sec_per_frame = 1.0 / float(fps)

    roi_mask = _resolve_roi_mask(metrics_settings, frame_shape)
    has_roi = roi_mask is not None and np.any(roi_mask)

    mask_map = _build_event_global_mask_map(event=event, masks_payload=masks_payload, baseline_pre_frames=0)
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
    files_written = 0
    written: list[str] = []

    if include_metric_propagation_speed and has_scale:
        _write_metric_csv(metrics_dir / "propagation_speed.csv", frame_indices, time_sec, speed_um_per_sec, "speed_um_per_sec")
        _write_metric_plot(
            metrics_dir / "propagation_speed.png",
            time_sec,
            speed_um_per_sec,
            "Propagation Speed",
            "Propagation Speed (um/sec)",
        )
        files_written += 2
        written.extend(["propagation_speed.csv", "propagation_speed.png"])
    if include_metric_area_recruited and has_scale and has_roi:
        _write_metric_csv(metrics_dir / "area_recruited.csv", frame_indices, time_sec, area_mm2, "area_mm2")
        _write_metric_plot(metrics_dir / "area_recruited.png", time_sec, area_mm2, "Area Recruited", "Area (mm^2)")
        files_written += 2
        written.extend(["area_recruited.csv", "area_recruited.png"])
    if include_metric_relative_area_recruited and has_roi:
        _write_metric_csv(
            metrics_dir / "relative_area_recruited.csv",
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
        files_written += 2
        written.extend(["relative_area_recruited.csv", "relative_area_recruited.png"])

    summary = {
        "event_id": str(event.event_id),
        "frames_per_sec": float(fps),
        "has_scale": bool(has_scale),
        "has_roi": bool(has_roi),
        "roi_pixels": int(roi_pixels),
        "selected_metrics": {
            "propagation_speed": bool(include_metric_propagation_speed),
            "area_recruited": bool(include_metric_area_recruited),
            "relative_area_recruited": bool(include_metric_relative_area_recruited),
        },
        "written_files": list(written),
        "overall_avg_speed_um_per_sec": float(np.nanmean(speed_um_per_sec)) if np.isfinite(speed_um_per_sec).any() else None,
        "max_area_mm2": float(np.nanmax(area_mm2)) if np.isfinite(area_mm2).any() else None,
        "max_relative_area_pct": float(np.nanmax(relative_area_pct)) if np.isfinite(relative_area_pct).any() else None,
    }
    (metrics_dir / "metrics_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    files_written += 1
    return {"files_written": int(files_written)}


def _build_event_global_mask_map(
    *,
    event: EventCandidate,
    masks_payload,
    baseline_pre_frames: int,
) -> dict[int, np.ndarray]:
    out: dict[int, np.ndarray] = {}
    if masks_payload is None:
        return out
    if isinstance(masks_payload, dict):
        for raw_idx, mask in masks_payload.items():
            try:
                idx = int(raw_idx)
            except Exception:
                continue
            arr = np.asarray(mask, dtype=bool)
            if arr.ndim != 2:
                continue
            out[idx] = arr.copy()
        return out

    arr = np.asarray(masks_payload)
    if arr.ndim != 3:
        return out
    frame_count = int(arr.shape[0])
    if frame_count <= 0:
        return out

    # If payload looks global, keep indices as-is; otherwise treat it as event-scope local.
    if frame_count > int(event.end_idx):
        for idx in range(frame_count):
            mask = np.asarray(arr[idx], dtype=bool)
            if mask.ndim == 2:
                out[int(idx)] = mask
        return out

    scope_start = max(0, int(event.start_idx) - int(max(0, baseline_pre_frames)))
    for local_idx in range(frame_count):
        global_idx = scope_start + int(local_idx)
        mask = np.asarray(arr[local_idx], dtype=bool)
        if mask.ndim == 2:
            out[int(global_idx)] = mask
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
        timestamp_sec = trace.time_sec[frame_idx]

    return ExportRecord(
        event_id=event_id,
        role=role,
        frame_idx=int(frame_idx),
        frame_name=frame_name,
        source_path=str(ref.source_path),
        output_path=str(output_path),
        timestamp_sec=timestamp_sec,
    )


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
                    trace.time_sec[i] if i < len(trace.time_sec) else None,
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


def _write_manifest_json(path: Path, records: list[ExportRecord], events: list[dict]) -> None:
    payload = {
        "events": events,
        "frames": [asdict(rec) for rec in records],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
