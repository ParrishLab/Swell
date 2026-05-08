#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import importlib
import json
import math
import shutil
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator

import h5py
import numpy as np
import pandas as pd


DEFAULT_DATA_DIR = Path("/Users/claydunford/Development/Recovery Metric/data/whole_slice_rois")
DEFAULT_RECOVERY_ROOT = Path("/Users/claydunford/Development/Recovery Metric")
DEFAULT_SDAPP_ROOT = Path("/Users/claydunford/Development/Combined tool test")
DEFAULT_OUTPUT_DIR = Path("benchmarks/sd_auto_detection")


@dataclass
class Timings:
    values: dict[str, float] = field(default_factory=dict)

    @contextmanager
    def measure(self, name: str) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            self.values[name] = self.values.get(name, 0.0) + (time.perf_counter() - start)


@dataclass(frozen=True)
class DatasetBenchmark:
    dataset: str
    sdproj_path: str
    frame_count: int
    frame_shape: tuple[int, int]
    roi_pixels: int
    cell_count: int
    raw_candidate_count_research: int
    raw_candidate_count_vendored: int
    accepted_count_research: int
    accepted_count_vendored: int
    candidates_match: bool
    accepted_match: bool
    raw_trace_max_abs_diff: float
    detrended_max_abs_diff: float
    lag1_max_abs_diff: float | None
    timings: dict[str, float]


def _ensure_import_paths(sdapp_root: Path, recovery_root: Path) -> None:
    for root in (sdapp_root, recovery_root, recovery_root / "src"):
        root_str = str(root.expanduser().resolve())
        if root_str not in sys.path:
            sys.path.insert(0, root_str)


def _public_candidate(row: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "candidate_id",
        "start_frame",
        "end_frame",
        "peak_frame",
        "duration_frames",
        "peak_active_count",
        "peak_active_fraction",
        "num_cells",
        "was_split",
        "split_parent_id",
        "split_index",
        "split_count",
        "split_signal",
        "split_boundary_frame",
    ]
    out: dict[str, Any] = {}
    for key in keys:
        value = row.get(key)
        if isinstance(value, np.generic):
            value = value.item()
        if isinstance(value, float) and math.isnan(value):
            value = None
        out[key] = value
    return out


def _candidate_signature(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_public_candidate(row) for row in rows]


def _accepted_signature(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "candidate_id": str(row["candidate_id"]),
            "start_frame": int(row["start_frame"]),
            "end_frame": int(row["end_frame"]),
            "peak_frame": int(row["peak_frame"]),
        }
        for row in rows
    ]


def _float_or_none(value: float) -> float | None:
    if not np.isfinite(value):
        return None
    return float(value)


def _write_h5_for_research_detector(tmp_root: Path, dataset: str, detrended: np.ndarray, frame_indices: np.ndarray) -> None:
    dataset_dir = tmp_root / "datasets" / dataset
    dataset_dir.mkdir(parents=True, exist_ok=True)
    with h5py.File(dataset_dir / "traces.h5", "w") as h5:
        h5.create_dataset("detrended", data=np.asarray(detrended, dtype=np.float32))
        h5.create_dataset("frame_indices", data=np.asarray(frame_indices, dtype=np.int64))


def _cells_dataframe(cell_row_cols: list[tuple[int, int]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "cell_id": [f"r{int(r)}c{int(c)}" for r, c in cell_row_cols],
            "row": [int(r) for r, _c in cell_row_cols],
            "col": [int(c) for _r, c in cell_row_cols],
        }
    )


def _research_gate(
    *,
    dataset: str,
    candidates: list[dict[str, Any]],
    detrended: np.ndarray,
    frame_indices: np.ndarray,
    cell_row_cols: list[tuple[int, int]],
    coherence_module: Any,
    threshold: float,
    active_threshold_mad: float,
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    cells = _cells_dataframe(cell_row_cols)
    pairs = coherence_module.neighbor_pairs(cells)
    accepted: list[dict[str, Any]] = []
    lag1_by_id: dict[str, float] = {}
    for candidate in candidates:
        window = {
            "source": "detector",
            "window_id": str(candidate["candidate_id"]),
            "match_label": "",
            "matched_event_id": "",
            "start_frame": int(candidate["start_frame"]),
            "end_frame": int(candidate["end_frame"]),
            "detector_peak_active": float(candidate.get("peak_active_count", np.nan)),
        }
        row = coherence_module.analyze_window(
            dataset,
            cells,
            np.asarray(detrended, dtype=np.float32),
            np.asarray(frame_indices, dtype=int),
            pairs,
            window,
            float(active_threshold_mad),
        )
        lag1 = float(row["active_count_lag1_corr"])
        lag1_by_id[str(candidate["candidate_id"])] = lag1
        if np.isfinite(lag1) and lag1 >= float(threshold):
            accepted_row = dict(candidate)
            accepted_row["lag1_corr"] = lag1
            accepted.append(accepted_row)
    return accepted, lag1_by_id


def _max_lag1_diff(vendored_rows: list[dict[str, Any]], research_lag1: dict[str, float]) -> float | None:
    diffs: list[float] = []
    for row in vendored_rows:
        candidate_id = str(row["candidate_id"])
        if candidate_id not in research_lag1:
            continue
        lhs = float(row.get("lag1_corr", np.nan))
        rhs = float(research_lag1[candidate_id])
        if np.isfinite(lhs) and np.isfinite(rhs):
            diffs.append(abs(lhs - rhs))
    return max(diffs) if diffs else None


def benchmark_dataset(
    sdproj_path: Path,
    *,
    sdapp_root: Path,
    recovery_root: Path,
    backend: str,
    tmp_root: Path,
) -> tuple[DatasetBenchmark, dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    timings = Timings()
    dataset = sdproj_path.stem

    from sdapp.host.stack_reader import StackReader
    from sdapp.host.sd_detection import detector as vendored_detector
    from sdapp.host.sd_detection.grid import build_detector_grid as vendored_build_grid
    from sdapp.host.sd_detection.traces import detrend_traces as vendored_detrend_traces
    from sdapp.host.sd_detection.traces import extract_lower_median_traces as vendored_extract_traces

    recovery_sdproj = importlib.import_module("recovery_metric.sdproj_resolver")
    recovery_proto = importlib.import_module("recovery_metric.prototype")
    recovery_traces = importlib.import_module("recovery_metric.sd_trace_extraction")
    research_validate = importlib.import_module("scripts.validate_detector_v2")
    research_coherence = importlib.import_module("scripts.explore_spatial_coherence")

    with timings.measure("resolve_inputs"):
        resolved = recovery_sdproj.resolve_sdproj_all_events(sdproj_path, sdapp_root=sdapp_root)
        if resolved.project_roi_mask is None:
            raise ValueError(f"{sdproj_path.name}: project has no ROI mask")
        roi_mask = np.asarray(resolved.project_roi_mask, dtype=bool)
        frame_shape = (int(resolved.frame_height), int(resolved.frame_width))
        stack_dir = Path(resolved.stack_input_dir).expanduser().resolve()

    with timings.measure("research_stack_open"):
        research_stack = recovery_proto.open_stack_source(stack_dir, sdapp_root)

    with timings.measure("vendored_stack_open"):
        vendored_reader = StackReader()
        vendored_info = vendored_reader.open_stack(stack_dir)

    if int(vendored_info.frame_count) != int(research_stack.frame_count):
        raise ValueError(f"{dataset}: frame count mismatch between stack readers")

    with timings.measure("research_grid"):
        research_grid = recovery_traces.build_detector_grid(roi_mask, frame_shape, 40, 40)

    with timings.measure("vendored_grid"):
        vendored_grid = vendored_build_grid(roi_mask, frame_shape, 40, 40)

    if research_grid.cell_row_cols != vendored_grid.cell_row_cols:
        raise ValueError(f"{dataset}: grid cell row/col mismatch")

    with timings.measure("research_trace_extract"):
        research_raw = recovery_traces.extract_lower_median_traces(
            research_stack,
            research_grid.cell_masks,
            research_grid.geometry,
            frame_count=int(research_stack.frame_count),
            backend=backend,
            progress_callback=None,
        )

    with timings.measure("vendored_trace_extract"):
        vendored_raw = vendored_extract_traces(
            vendored_reader,
            vendored_grid.cell_masks,
            vendored_grid.geometry,
            frame_count=int(vendored_info.frame_count),
            backend=backend,
            progress_callback=None,
        )

    with timings.measure("research_detrend"):
        research_products = recovery_traces.compute_detector_trace_products(
            research_raw,
            detrend_window_frames=120,
            detection_k_mad=vendored_detector.PRESET["diff_k_mad"],
        )
        research_detrended = np.asarray(research_products.detrended, dtype=np.float32)

    with timings.measure("vendored_detrend"):
        vendored_detrended = vendored_detrend_traces(vendored_raw, detrend_window_frames=120)

    frame_indices = np.arange(int(vendored_info.frame_count), dtype=np.int64)

    _write_h5_for_research_detector(tmp_root, dataset, research_detrended, frame_indices)
    detector_kwargs = {
        "diff_k_mad": vendored_detector.PRESET["diff_k_mad"],
        "peak_height_fraction": vendored_detector.PRESET["peak_height_fraction"],
        "quiet_fraction": vendored_detector.PRESET["quiet_fraction"],
        "smoothing_window": vendored_detector.PRESET["smoothing_window"],
        "peak_distance_frames": vendored_detector.PRESET["peak_distance_frames"],
        "lookback_frames": vendored_detector.PRESET["lookback_frames"],
        "lookahead_frames": vendored_detector.PRESET["lookahead_frames"],
        "min_duration_frames": vendored_detector.PRESET["min_duration_frames"],
        "legacy_exact": vendored_detector.PRESET["legacy_exact"],
        "overlap_mode": vendored_detector.PRESET["overlap_mode"],
        "split_broad_windows": vendored_detector.PRESET["split_broad_windows"],
        "split_signal": vendored_detector.PRESET["split_signal"],
        "split_min_candidate_frames": vendored_detector.PRESET["split_min_candidate_frames"],
        "split_min_peak_distance_frames": vendored_detector.PRESET["split_min_peak_distance_frames"],
        "split_min_peak_height_fraction": vendored_detector.PRESET["split_min_peak_height_fraction"],
        "split_valley_fraction": vendored_detector.PRESET["split_valley_fraction"],
        "split_quiet_gap_frames": vendored_detector.PRESET["split_quiet_gap_frames"],
        "split_refractory_frames": vendored_detector.PRESET["split_refractory_frames"],
        "split_max_segments": vendored_detector.PRESET["split_max_segments"],
    }

    with timings.measure("research_find_candidates"):
        research_candidates = research_validate.detect_events(dataset, data_root=tmp_root, **detector_kwargs)

    with timings.measure("vendored_find_candidates"):
        vendored_raw_candidates = vendored_detector.find_candidates(vendored_detrended, frame_indices)

    with timings.measure("research_coherence_gate"):
        research_accepted, research_lag1 = _research_gate(
            dataset=dataset,
            candidates=research_candidates,
            detrended=research_detrended,
            frame_indices=frame_indices,
            cell_row_cols=research_grid.cell_row_cols,
            coherence_module=research_coherence,
            threshold=vendored_detector.PRESET["coherence_threshold"],
            active_threshold_mad=vendored_detector.PRESET["coherence_active_threshold_mad"],
        )

    with timings.measure("vendored_coherence_gate"):
        vendored_accepted = vendored_detector.apply_coherence_gate(
            vendored_raw_candidates,
            vendored_detrended,
            frame_indices,
            active_threshold_mad=vendored_detector.PRESET["coherence_active_threshold_mad"],
            coherence_threshold=vendored_detector.PRESET["coherence_threshold"],
            quiet_pre_frames=vendored_detector.PRESET["quiet_pre_frames"],
        )

    raw_trace_diff = float(np.max(np.abs(np.asarray(research_raw) - np.asarray(vendored_raw))))
    detrended_diff = float(np.max(np.abs(research_detrended - vendored_detrended)))
    candidates_match = _candidate_signature(research_candidates) == _candidate_signature(vendored_raw_candidates)
    accepted_match = _accepted_signature(research_accepted) == _accepted_signature(vendored_accepted)

    detail = {
        "dataset": dataset,
        "research_candidates": _candidate_signature(research_candidates),
        "vendored_candidates": _candidate_signature(vendored_raw_candidates),
        "research_accepted": _accepted_signature(research_accepted),
        "vendored_accepted": _accepted_signature(vendored_accepted),
        "research_lag1": {k: _float_or_none(v) for k, v in research_lag1.items()},
        "vendored_lag1": {str(r["candidate_id"]): _float_or_none(float(r.get("lag1_corr", np.nan))) for r in vendored_accepted},
    }

    candidate_rows = [
        {
            "dataset": dataset,
            "implementation": "research",
            **_public_candidate(row),
            "coherence_pass": any(str(row["candidate_id"]) == str(a["candidate_id"]) for a in research_accepted),
            "lag1_corr": _float_or_none(research_lag1.get(str(row["candidate_id"]), float("nan"))),
        }
        for row in research_candidates
    ] + [
        {
            "dataset": dataset,
            "implementation": "vendored",
            **_public_candidate(row),
            "coherence_pass": any(str(row["candidate_id"]) == str(a["candidate_id"]) for a in vendored_accepted),
            "lag1_corr": _float_or_none(float(next((a.get("lag1_corr", np.nan) for a in vendored_accepted if str(a["candidate_id"]) == str(row["candidate_id"])), np.nan))),
        }
        for row in vendored_raw_candidates
    ]

    benchmark = DatasetBenchmark(
        dataset=dataset,
        sdproj_path=str(sdproj_path),
        frame_count=int(vendored_info.frame_count),
        frame_shape=(int(vendored_info.frame_height), int(vendored_info.frame_width)),
        roi_pixels=int(np.count_nonzero(roi_mask)),
        cell_count=int(len(vendored_grid.cell_masks)),
        raw_candidate_count_research=int(len(research_candidates)),
        raw_candidate_count_vendored=int(len(vendored_raw_candidates)),
        accepted_count_research=int(len(research_accepted)),
        accepted_count_vendored=int(len(vendored_accepted)),
        candidates_match=bool(candidates_match),
        accepted_match=bool(accepted_match),
        raw_trace_max_abs_diff=raw_trace_diff,
        detrended_max_abs_diff=detrended_diff,
        lag1_max_abs_diff=_max_lag1_diff(vendored_accepted, research_lag1),
        timings={k: round(float(v), 6) for k, v in sorted(timings.values.items())},
    )
    return benchmark, detail, candidate_rows, [
        {"dataset": dataset, "stage": stage, "seconds": seconds}
        for stage, seconds in benchmark.timings.items()
    ]


def write_outputs(
    output_dir: Path,
    results: list[DatasetBenchmark],
    details: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
    timing_rows: list[dict[str, Any]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = [asdict(result) for result in results]
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (output_dir / "mismatches.json").write_text(
        json.dumps(
            [d for d, r in zip(details, results) if not r.candidates_match or not r.accepted_match],
            indent=2,
        ),
        encoding="utf-8",
    )

    pd.DataFrame(summary).drop(columns=["timings"], errors="ignore").to_csv(output_dir / "per_dataset.csv", index=False)
    pd.DataFrame(candidate_rows).to_csv(output_dir / "candidates.csv", index=False)
    pd.DataFrame(timing_rows).to_csv(output_dir / "timings_long.csv", index=False)

    timing_fieldnames = ["dataset"] + sorted({stage for row in timing_rows for stage in [row["stage"]]})
    with (output_dir / "timings_wide.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=timing_fieldnames)
        writer.writeheader()
        for result in results:
            writer.writerow({"dataset": result.dataset, **result.timings})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark vendored SD auto-detection against the Recovery Metric research pipeline.")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help="Directory containing whole-slice .sdproj datasets.")
    parser.add_argument("--recovery-root", default=str(DEFAULT_RECOVERY_ROOT), help="Recovery Metric repo root.")
    parser.add_argument("--sdapp-root", default=str(DEFAULT_SDAPP_ROOT), help="Combined Tool repo root.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for benchmark CSV/JSON outputs.")
    parser.add_argument("--backend", choices=["torch", "numpy"], default="torch", help="Trace extraction backend for both implementations.")
    parser.add_argument("--limit", type=int, default=None, help="Optional maximum number of .sdproj files to benchmark.")
    parser.add_argument("--keep-temp", action="store_true", help="Keep temporary HDF5 files used for the research detector.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data_dir = Path(args.data_dir).expanduser().resolve()
    recovery_root = Path(args.recovery_root).expanduser().resolve()
    sdapp_root = Path(args.sdapp_root).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()

    _ensure_import_paths(sdapp_root, recovery_root)
    sdproj_paths = sorted(p for p in data_dir.glob("*.sdproj") if p.is_file())
    if args.limit is not None:
        sdproj_paths = sdproj_paths[: max(0, int(args.limit))]
    if not sdproj_paths:
        raise FileNotFoundError(f"No .sdproj files found in {data_dir}")

    tmp_root = Path(tempfile.mkdtemp(prefix="sd_detection_benchmark_"))
    results: list[DatasetBenchmark] = []
    details: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    timing_rows: list[dict[str, Any]] = []
    try:
        for index, sdproj_path in enumerate(sdproj_paths, start=1):
            print(f"[{index}/{len(sdproj_paths)}] {sdproj_path.name}", flush=True)
            result, detail, candidates, timings = benchmark_dataset(
                sdproj_path,
                sdapp_root=sdapp_root,
                recovery_root=recovery_root,
                backend=str(args.backend),
                tmp_root=tmp_root,
            )
            results.append(result)
            details.append(detail)
            candidate_rows.extend(candidates)
            timing_rows.extend(timings)
            status = "OK" if result.candidates_match and result.accepted_match else "MISMATCH"
            print(
                f"  {status}: raw {result.raw_candidate_count_vendored}, accepted {result.accepted_count_vendored}, "
                f"trace diff {result.raw_trace_max_abs_diff:g}, detrended diff {result.detrended_max_abs_diff:g}",
                flush=True,
            )
    finally:
        if args.keep_temp:
            print(f"Temporary research detector data kept at: {tmp_root}", flush=True)
        else:
            shutil.rmtree(tmp_root, ignore_errors=True)

    write_outputs(output_dir, results, details, candidate_rows, timing_rows)
    mismatch_count = sum(1 for result in results if not result.candidates_match or not result.accepted_match)
    print(f"Wrote benchmark outputs to {output_dir}", flush=True)
    print(f"Datasets: {len(results)}; mismatches: {mismatch_count}", flush=True)
    return 1 if mismatch_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
