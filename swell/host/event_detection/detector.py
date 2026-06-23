"""SD detector: candidate detection + coherence gate.

Functions copied verbatim from:
  - Recovery Metric/scripts/validate_detector_v2.py
        detect_events, _centered_average, _newly_active_counts,
        _split_signal_counts, split_candidate_window
  - Recovery Metric/scripts/explore_spatial_coherence.py
        quiet_mad (used for coherence MAD)

The only adaptation: detect_events takes (detrended, frame_indices) directly
instead of loading them from an HDF5 file.

PRESET mirrors recall_split_coherence_v1 from
Recovery Metric/scripts/run_event_detection_pipeline.py.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy.signal import find_peaks


# ---------------------------------------------------------------------------
# Preset parameters — copied from run_event_detection_pipeline.py
# (recall_split_coherence_v1)
# ---------------------------------------------------------------------------

PRESET: dict[str, Any] = {
    "diff_k_mad": 2.5,
    "peak_height_fraction": 0.05,
    "quiet_fraction": 0.01,
    "smoothing_window": 10,
    "peak_distance_frames": 50,
    "lookback_frames": 150,
    "lookahead_frames": 250,
    "min_duration_frames": 40,
    "legacy_exact": True,
    "overlap_mode": "skip",
    "split_broad_windows": True,
    "split_signal": "newly_active",
    "split_min_candidate_frames": None,
    "split_min_peak_distance_frames": None,
    "split_min_peak_height_fraction": None,
    "split_valley_fraction": 0.35,
    "split_quiet_gap_frames": None,
    "split_refractory_frames": None,
    "split_max_segments": 3,
    "coherence_metric": "active_count_lag1_corr",
    "coherence_active_threshold_mad": 10.0,
    "coherence_threshold": 0.8257435331730181,
    # Coherence quiet baseline (from explore_spatial_coherence.py)
    "quiet_pre_frames": 200,
    # Validated default: K+ SD is positive-going. Dark-going recordings can use
    # "negative" or "both" from the host workbench.
    "polarity": "positive",
    "persistence_frames": 1,
}


# ---------------------------------------------------------------------------
# Helpers — copied verbatim from validate_detector_v2.py
# ---------------------------------------------------------------------------

def _centered_average(values: np.ndarray, *, window: int, legacy_exact: bool = False) -> np.ndarray:
    roller = pd.Series(values).rolling(window=max(1, int(window)), center=True, min_periods=1 if not legacy_exact else None)
    return roller.mean().fillna(0).to_numpy(dtype=float)


def _newly_active_counts(active_matrix: np.ndarray, *, refractory_frames: int) -> np.ndarray:
    refractory_frames = max(1, int(refractory_frames))
    newly_active = np.zeros(active_matrix.shape[1], dtype=float)
    recent = np.zeros(active_matrix.shape[0], dtype=bool)
    history: list[np.ndarray] = []
    for frame_idx in range(active_matrix.shape[1]):
        current = active_matrix[:, frame_idx]
        newly_active[frame_idx] = int(np.sum(current & ~recent))
        history.append(current)
        if len(history) > refractory_frames:
            history.pop(0)
        recent = np.logical_or.reduce(history) if history else np.zeros(active_matrix.shape[0], dtype=bool)
    return newly_active


def _split_signal_counts(
    active_matrix: np.ndarray,
    *,
    signal: str,
    smoothing_window: int,
    refractory_frames: int | None,
    legacy_exact: bool,
) -> np.ndarray:
    if signal == "active":
        counts = np.sum(active_matrix, axis=0)
    elif signal == "newly_active":
        counts = _newly_active_counts(
            active_matrix,
            refractory_frames=max(1, int(refractory_frames if refractory_frames is not None else smoothing_window)),
        )
    else:
        raise ValueError(f"Unsupported split signal: {signal}")
    return _centered_average(counts, window=smoothing_window, legacy_exact=legacy_exact)


def split_candidate_window(
    candidate: dict[str, Any],
    *,
    smoothed_counts: np.ndarray,
    split_counts: np.ndarray,
    frame_indices: np.ndarray,
    num_cells: int,
    peak_height_fraction: float,
    min_duration_frames: int,
    peak_distance_frames: int,
    split_signal: str,
    split_min_candidate_frames: int | None,
    split_min_peak_distance_frames: int | None,
    split_min_peak_height_fraction: float | None,
    split_valley_fraction: float,
    split_quiet_gap_frames: int | None,
    split_max_segments: int,
) -> list[dict[str, Any]]:
    """Conservatively split one broad candidate when it contains separated recruitment episodes."""
    start_idx = int(candidate["_start_idx"])
    end_idx = int(candidate["_end_idx"])
    candidate_duration = int(candidate["end_frame"]) - int(candidate["start_frame"])
    min_candidate_frames = int(
        split_min_candidate_frames
        if split_min_candidate_frames is not None
        else max(
            2 * (int(min_duration_frames) + int(peak_distance_frames)),
            int(min_duration_frames) + 2 * int(peak_distance_frames),
        )
    )
    if candidate_duration < min_candidate_frames or end_idx <= start_idx:
        return [candidate]

    local_signal = split_counts[start_idx : end_idx + 1]
    if len(local_signal) < 3:
        return [candidate]

    min_peak_height_fraction = (
        float(split_min_peak_height_fraction)
        if split_min_peak_height_fraction is not None
        else float(peak_height_fraction)
    )
    peaks, _properties = find_peaks(
        local_signal,
        height=min_peak_height_fraction * int(num_cells),
        distance=max(1, int(split_min_peak_distance_frames or peak_distance_frames)),
    )
    if len(peaks) < 2:
        return [candidate]

    absolute_peaks = [start_idx + int(peak) for peak in peaks]
    boundaries: list[int] = []
    quiet_gap_frames = max(1, int(split_quiet_gap_frames if split_quiet_gap_frames is not None else max(1, peak_distance_frames // 5)))
    for left_peak, right_peak in zip(absolute_peaks[:-1], absolute_peaks[1:]):
        if right_peak <= left_peak + 1:
            continue
        valley_region = split_counts[left_peak : right_peak + 1]
        valley_idx = left_peak + int(np.argmin(valley_region))
        left_value = float(split_counts[left_peak])
        right_value = float(split_counts[right_peak])
        valley_value = float(split_counts[valley_idx])
        valley_limit = float(split_valley_fraction) * min(left_value, right_value)
        quiet_start = max(left_peak, valley_idx - quiet_gap_frames // 2)
        quiet_end = min(right_peak + 1, valley_idx + quiet_gap_frames // 2 + 1)
        quiet_median = float(np.median(split_counts[quiet_start:quiet_end])) if quiet_end > quiet_start else valley_value
        if valley_value <= valley_limit and quiet_median <= valley_limit:
            boundaries.append(int(valley_idx))

    if not boundaries:
        return [candidate]

    segment_bounds = []
    segment_start = start_idx
    for boundary in boundaries:
        segment_bounds.append((segment_start, boundary))
        segment_start = boundary + 1
    segment_bounds.append((segment_start, end_idx))
    if len(segment_bounds) > max(2, int(split_max_segments)):
        return [candidate]

    split_candidates: list[dict[str, Any]] = []
    boundary_frames = [str(int(frame_indices[min(max(boundary, 0), len(frame_indices) - 1)])) for boundary in boundaries]
    for split_idx, (seg_start, seg_end) in enumerate(segment_bounds, start=1):
        if seg_end <= seg_start:
            return [candidate]
        start_frame = int(frame_indices[max(0, seg_start)])
        end_frame = int(frame_indices[min(len(frame_indices) - 1, seg_end)])
        duration = end_frame - start_frame
        if duration <= int(min_duration_frames):
            return [candidate]
        segment_activity = smoothed_counts[seg_start : seg_end + 1]
        if len(segment_activity) == 0:
            return [candidate]
        peak_offset = int(np.argmax(segment_activity))
        peak_idx = seg_start + peak_offset
        peak_active_count = float(smoothed_counts[peak_idx])
        if peak_active_count < float(peak_height_fraction) * int(num_cells):
            return [candidate]
        row = dict(candidate)
        row.update(
            {
                "start_frame": start_frame,
                "end_frame": end_frame,
                "peak_frame": int(frame_indices[min(peak_idx, len(frame_indices) - 1)]),
                "duration_frames": int(duration),
                "peak_active_count": peak_active_count,
                "peak_active_fraction": float(peak_active_count / max(1, num_cells)),
                "was_split": True,
                "split_parent_id": str(candidate["candidate_id"]),
                "split_index": int(split_idx),
                "split_count": int(len(segment_bounds)),
                "split_signal": str(split_signal),
                "split_boundary_frame": ";".join(boundary_frames),
                "_start_idx": int(seg_start),
                "_end_idx": int(seg_end),
            }
        )
        split_candidates.append(row)

    return split_candidates if len(split_candidates) >= 2 else [candidate]


# ---------------------------------------------------------------------------
# Main detect_events — copied verbatim from validate_detector_v2.py,
# adapted to take (detrended, frame_indices) instead of loading from h5.
# ---------------------------------------------------------------------------

def detect_events(
    detrended: np.ndarray,
    frame_indices: np.ndarray,
    *,
    dataset_name: str = "stack",
    diff_k_mad: float = 2.5,
    peak_height_fraction: float = 0.05,
    quiet_fraction: float = 0.01,
    smoothing_window: int = 10,
    peak_distance_frames: int = 50,
    lookback_frames: int = 150,
    lookahead_frames: int = 250,
    min_duration_frames: int = 40,
    persistence_frames: int = 1,
    legacy_exact: bool = True,
    overlap_mode: str = "skip",
    split_broad_windows: bool = True,
    split_signal: str = "newly_active",
    split_min_candidate_frames: int | None = None,
    split_min_peak_distance_frames: int | None = None,
    split_min_peak_height_fraction: float | None = None,
    split_valley_fraction: float = 0.35,
    split_quiet_gap_frames: int | None = None,
    split_refractory_frames: int | None = None,
    split_max_segments: int = 3,
    polarity: str = "positive",
) -> list[dict[str, Any]]:
    """Detect candidate event windows from pre-computed detrended traces.

    Adapted from validate_detector_v2.detect_events: instead of loading
    from `traces.h5`, the caller passes `detrended` and `frame_indices`
    directly. All other logic is identical.
    """
    traces = np.asarray(detrended)
    frame_indices = np.asarray(frame_indices)
    if traces.ndim != 2:
        raise ValueError("detrended must be a 2D array shaped [num_cells, num_frames].")
    if frame_indices.ndim != 1:
        raise ValueError("frame_indices must be a 1D array.")
    num_cells, num_frames = traces.shape
    if int(frame_indices.size) != int(num_frames):
        raise ValueError(
            f"frame_indices length {int(frame_indices.size)} does not match detrended frame count {int(num_frames)}."
        )
    if num_cells <= 0 or num_frames < 2:
        return []
    diffs = np.diff(traces, axis=1)
    diff_center = np.nanmedian(diffs, axis=1, keepdims=True)
    mads = np.nanmedian(np.abs(diffs - diff_center), axis=1)
    if not legacy_exact:
        fallback = np.nanmedian(mads[np.isfinite(mads) & (mads > 0)]) if np.any(np.isfinite(mads) & (mads > 0)) else 1.0
        mads = np.where(np.isfinite(mads) & (mads > 0), mads, fallback)

    if polarity == "positive":
        active_matrix = diffs > (float(diff_k_mad) * mads[:, np.newaxis])
    elif polarity == "negative":
        active_matrix = diffs < -(float(diff_k_mad) * mads[:, np.newaxis])
    elif polarity in ("absolute", "both"):
        active_matrix = np.abs(diffs) > (float(diff_k_mad) * mads[:, np.newaxis])
    else:
        raise ValueError(f"Unsupported polarity: {polarity}")

    if int(persistence_frames) > 1:
        from scipy.ndimage import binary_erosion
        structure = np.ones((1, int(persistence_frames)), dtype=bool)
        active_matrix = binary_erosion(active_matrix, structure=structure)

    active_counts = np.sum(active_matrix, axis=0)

    smooth_win = max(1, int(smoothing_window))
    roller = pd.Series(active_counts).rolling(window=smooth_win, center=True, min_periods=1 if not legacy_exact else None)
    smoothed_counts = roller.mean().fillna(0).to_numpy(dtype=float)
    if split_broad_windows:
        split_counts = _split_signal_counts(
            active_matrix,
            signal=split_signal,
            smoothing_window=smooth_win,
            refractory_frames=split_refractory_frames,
            legacy_exact=legacy_exact,
        )
    else:
        split_counts = smoothed_counts
    peaks, _properties = find_peaks(
        smoothed_counts,
        height=float(peak_height_fraction) * num_cells,
        distance=max(1, int(peak_distance_frames)),
    )

    detected_events: list[dict[str, Any]] = []
    quiet_thresh = float(quiet_fraction) * num_cells
    for peak_idx in peaks:
        start_idx = int(peak_idx)
        while start_idx > max(0, int(peak_idx) - int(lookback_frames)) and smoothed_counts[start_idx] > quiet_thresh:
            start_idx -= 1

        end_idx = int(peak_idx)
        while end_idx < min(len(smoothed_counts) - 1, int(peak_idx) + int(lookahead_frames)) and smoothed_counts[end_idx] > quiet_thresh:
            end_idx += 1

        start_frame = int(frame_indices[max(0, start_idx)])
        end_frame = int(frame_indices[min(len(frame_indices) - 1, end_idx)])
        if (end_frame - start_frame) <= int(min_duration_frames):
            continue

        candidate = {
            "dataset": dataset_name,
            "candidate_id": f"det_{len(detected_events) + 1:04d}",
            "start_frame": start_frame,
            "end_frame": end_frame,
            "peak_frame": int(frame_indices[min(int(peak_idx), len(frame_indices) - 1)]),
            "duration_frames": int(end_frame - start_frame),
            "peak_active_count": float(smoothed_counts[int(peak_idx)]),
            "peak_active_fraction": float(smoothed_counts[int(peak_idx)] / max(1, num_cells)),
            "num_cells": int(num_cells),
            "source": "validate_detector_v2",
            "was_split": False,
            "split_parent_id": "",
            "split_index": 0,
            "split_count": 1,
            "split_signal": "",
            "split_boundary_frame": "",
            "_start_idx": int(start_idx),
            "_end_idx": int(end_idx),
        }

        candidates_to_add = [candidate]
        if split_broad_windows:
            candidates_to_add = split_candidate_window(
                candidate,
                smoothed_counts=smoothed_counts,
                split_counts=split_counts,
                frame_indices=frame_indices,
                num_cells=int(num_cells),
                peak_height_fraction=float(peak_height_fraction),
                min_duration_frames=int(min_duration_frames),
                peak_distance_frames=int(peak_distance_frames),
                split_signal=str(split_signal),
                split_min_candidate_frames=split_min_candidate_frames,
                split_min_peak_distance_frames=split_min_peak_distance_frames,
                split_min_peak_height_fraction=split_min_peak_height_fraction,
                split_valley_fraction=float(split_valley_fraction),
                split_quiet_gap_frames=split_quiet_gap_frames,
                split_max_segments=int(split_max_segments),
            )

        for candidate_to_add in candidates_to_add:
            if not detected_events or int(candidate_to_add["start_frame"]) > int(detected_events[-1]["end_frame"]):
                detected_events.append(candidate_to_add)
            elif overlap_mode == "skip":
                continue
            else:
                previous = detected_events[-1]
                previous["end_frame"] = max(int(previous["end_frame"]), int(candidate_to_add["end_frame"]))
                previous["duration_frames"] = int(previous["end_frame"] - previous["start_frame"])
                if candidate_to_add["peak_active_count"] > previous["peak_active_count"]:
                    previous["peak_frame"] = candidate_to_add["peak_frame"]
                    previous["peak_active_count"] = candidate_to_add["peak_active_count"]
                    previous["peak_active_fraction"] = candidate_to_add["peak_active_fraction"]
                previous["was_split"] = bool(previous.get("was_split", False) or candidate_to_add.get("was_split", False))

    for idx, event in enumerate(detected_events, start=1):
        event["candidate_id"] = f"det_{idx:04d}"
        # Keep _start_idx / _end_idx for the coherence gate downstream
    return detected_events


# ---------------------------------------------------------------------------
# Coherence gate — uses quiet_mad from explore_spatial_coherence.py
# ---------------------------------------------------------------------------

def quiet_mad(traces: np.ndarray, start_idx: int, *, quiet_pre_frames: int = 200) -> np.ndarray:
    """Per-cell MAD computed over the QUIET_PRE_FRAMES frames immediately before start_idx.

    Copied verbatim from explore_spatial_coherence.quiet_mad
    (with QUIET_PRE_FRAMES exposed as a parameter).
    """
    quiet_start = max(0, start_idx - quiet_pre_frames)
    quiet = traces[:, quiet_start:start_idx]
    if quiet.shape[1] == 0:
        quiet = traces[:, : max(1, min(quiet_pre_frames, traces.shape[1]))]
    med = np.nanmedian(quiet, axis=1, keepdims=True)
    mad = np.nanmedian(np.abs(quiet - med), axis=1)
    mad[(~np.isfinite(mad)) | (mad <= 0)] = 1e-6
    return mad


def compute_lag1_corr(
    detrended: np.ndarray,
    frame_indices: np.ndarray,
    candidate: dict,
    *,
    active_threshold_mad: float = 10.0,
    quiet_pre_frames: int = 200,
    polarity: str = "positive",
    _mad_cache: dict | None = None,
) -> float:
    """Compute lag-1 autocorrelation of active-cell-count signal within window.

    Mirrors the active_count_lag1_corr metric from analyze_window() in
    explore_spatial_coherence.py:
      1. mad = quiet_mad(traces, start_idx) — per-cell MAD over the 200 quiet
         frames immediately before the window.
      2. norm = traces[:, win] / mad[:, None]
      3. active_matrix = norm > active_threshold_mad (polarity-aware)
      4. active_count = active_matrix.sum(axis=0) per frame within the window
      5. return np.corrcoef(active_count[:-1], active_count[1:])[0, 1]
    """
    detrended = np.asarray(detrended)
    frame_indices = np.asarray(frame_indices)
    if detrended.ndim != 2 or frame_indices.ndim != 1 or frame_indices.size == 0:
        return float("nan")

    start_idx = candidate.get("_start_idx")
    end_idx = candidate.get("_end_idx")
    if start_idx is None or end_idx is None:
        # Fall back to looking up by frame number
        start_idx = int(np.argmin(np.abs(frame_indices - int(candidate["start_frame"]))))
        end_idx = int(np.argmin(np.abs(frame_indices - int(candidate["end_frame"]))))
    start_idx = int(start_idx)
    end_idx = int(end_idx)
    if end_idx < start_idx:
        start_idx, end_idx = end_idx, start_idx
    max_idx = int(detrended.shape[1]) - 1
    if max_idx < 0:
        return float("nan")
    start_idx = max(0, min(start_idx, max_idx))
    end_idx = max(0, min(end_idx, max_idx))
    if end_idx < start_idx:
        return float("nan")

    if polarity not in ("positive", "negative", "absolute", "both"):
        raise ValueError(f"Unsupported polarity: {polarity}")

    mad = None
    if _mad_cache is not None:
        mad = _mad_cache.get((start_idx, int(quiet_pre_frames)))
    if mad is None:
        mad = quiet_mad(detrended, start_idx, quiet_pre_frames=quiet_pre_frames)
        if _mad_cache is not None:
            _mad_cache[(start_idx, int(quiet_pre_frames))] = mad
    norm = detrended[:, start_idx : end_idx + 1] / mad[:, np.newaxis]
    threshold = float(active_threshold_mad)

    if polarity == "both":
        # Both polarities share the same mad/norm; only the thresholding differs.
        corr_pos = _lag1_corr_from_active(norm > threshold)
        corr_neg = _lag1_corr_from_active(norm < -threshold)
        if np.isnan(corr_pos):
            return corr_neg
        if np.isnan(corr_neg):
            return corr_pos
        return max(corr_pos, corr_neg)

    if polarity == "positive":
        active_matrix = norm > threshold
    elif polarity == "negative":
        active_matrix = norm < -threshold
    else:
        active_matrix = np.abs(norm) > threshold
    return _lag1_corr_from_active(active_matrix)


def _lag1_corr_from_active(active_matrix: np.ndarray) -> float:
    active_counts = active_matrix.sum(axis=0).astype(float)
    if len(active_counts) < 2:
        return float("nan")
    if np.std(active_counts[:-1]) <= 0 or np.std(active_counts[1:]) <= 0:
        return float("nan")
    return float(np.corrcoef(active_counts[:-1], active_counts[1:])[0, 1])


def apply_coherence_gate(
    candidates: list[dict],
    detrended: np.ndarray,
    frame_indices: np.ndarray,
    *,
    active_threshold_mad: float = 10.0,
    coherence_threshold: float = 0.8257435331730181,
    quiet_pre_frames: int = 200,
    polarity: str = "positive",
) -> list[dict]:
    """Filter candidates by lag-1 coherence; adds 'lag1_corr' to each accepted dict."""
    accepted: list[dict] = []
    # Candidates frequently share a window start; reuse the per-cell quiet MAD
    # across them instead of recomputing the nanmedians for every candidate.
    mad_cache: dict = {}
    for cand in candidates:
        lag1 = compute_lag1_corr(
            detrended,
            frame_indices,
            cand,
            active_threshold_mad=active_threshold_mad,
            quiet_pre_frames=quiet_pre_frames,
            polarity=polarity,
            _mad_cache=mad_cache,
        )
        if not np.isfinite(lag1) or lag1 < float(coherence_threshold):
            continue
        clean = {k: v for k, v in cand.items() if not k.startswith("_")}
        clean["lag1_corr"] = float(lag1)
        accepted.append(clean)
    return accepted


# ---------------------------------------------------------------------------
# Backwards-compat alias for the workbench
# ---------------------------------------------------------------------------

def find_candidates(
    detrended: np.ndarray,
    frame_indices: np.ndarray,
    **overrides: Any,
) -> list[dict]:
    """Run detect_events with PRESET defaults overridden by `overrides`."""
    params = {
        "diff_k_mad": PRESET["diff_k_mad"],
        "peak_height_fraction": PRESET["peak_height_fraction"],
        "quiet_fraction": PRESET["quiet_fraction"],
        "smoothing_window": PRESET["smoothing_window"],
        "peak_distance_frames": PRESET["peak_distance_frames"],
        "lookback_frames": PRESET["lookback_frames"],
        "lookahead_frames": PRESET["lookahead_frames"],
        "min_duration_frames": PRESET["min_duration_frames"],
        "legacy_exact": PRESET["legacy_exact"],
        "overlap_mode": PRESET["overlap_mode"],
        "split_broad_windows": PRESET["split_broad_windows"],
        "split_signal": PRESET["split_signal"],
        "split_min_candidate_frames": PRESET["split_min_candidate_frames"],
        "split_min_peak_distance_frames": PRESET["split_min_peak_distance_frames"],
        "split_min_peak_height_fraction": PRESET["split_min_peak_height_fraction"],
        "split_valley_fraction": PRESET["split_valley_fraction"],
        "split_quiet_gap_frames": PRESET["split_quiet_gap_frames"],
        "split_refractory_frames": PRESET["split_refractory_frames"],
        "split_max_segments": PRESET["split_max_segments"],
        "polarity": PRESET["polarity"],
        "persistence_frames": PRESET["persistence_frames"],
    }
    params.update({k: v for k, v in overrides.items() if k in params})
    return detect_events(detrended, frame_indices, **params)
