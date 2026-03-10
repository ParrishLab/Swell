from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import json
from dataclasses import asdict
from pathlib import Path
from threading import Lock
from typing import Callable, Iterable, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image
import tifffile

try:
    from .config import EventCandidate, ExportRecord, TraceResult
    from .signal_analysis import event_to_dict
    from .stack_reader import StackReader
except ImportError:
    from config import EventCandidate, ExportRecord, TraceResult
    from signal_analysis import event_to_dict
    from stack_reader import StackReader


def export_analysis(
    reader: StackReader,
    events: list[EventCandidate],
    output_dir: str | Path,
    baseline_pre_frames: int,
    trace: Optional[TraceResult] = None,
    selected_event_ids: Optional[Iterable[str]] = None,
    progress_callback: Optional[Callable[[dict], None]] = None,
) -> dict:
    out_dir = Path(output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    selected_ids = set(selected_event_ids) if selected_event_ids else {e.event_id for e in events}
    selected_events = [e for e in events if e.event_id in selected_ids]

    has_trace = trace is not None and (
        bool(trace.frame_indices) or bool(trace.mean) or bool(trace.median) or bool(trace.std) or bool(trace.time_sec)
    )
    if has_trace:
        _write_trace_data_csv(out_dir / "trace_data.csv", trace)
        _write_trace_plot(out_dir / "trace_plot.png", trace, selected_events)

    manifest_records: list[ExportRecord] = []
    event_summaries: list[dict] = []
    total_frames_to_export = 0
    for event in selected_events:
        baseline_end = int(event.start_idx) - 1
        if baseline_end >= 0:
            baseline_start = max(0, baseline_end - int(baseline_pre_frames) + 1)
            baseline_count = baseline_end - baseline_start + 1
        else:
            baseline_count = 0
        event_count = max(0, event.end_idx - event.start_idx + 1)
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
        event_dir = out_dir / event.event_id
        baseline_dir = event_dir / "baseline"
        extent_dir = event_dir / "event_extent"
        baseline_dir.mkdir(parents=True, exist_ok=True)
        extent_dir.mkdir(parents=True, exist_ok=True)

        baseline_end = int(event.start_idx) - 1
        baseline_start: int | None = None
        event_records: list[tuple[int, str, ExportRecord]] = []
        if baseline_end >= 0:
            baseline_start = max(0, baseline_end - int(baseline_pre_frames) + 1)
            baseline_indices = list(range(baseline_start, baseline_end + 1))
        else:
            baseline_indices = []
        event_indices = list(range(event.start_idx, event.end_idx + 1))

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
        "manifest_csv": str(out_dir / "events_manifest.csv"),
        "manifest_json": str(out_dir / "events_manifest.json"),
    }


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
