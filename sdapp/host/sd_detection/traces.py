"""Extract and detrend per-cell traces using the Combined Tool's StackReader.

Copied verbatim from:
  Recovery Metric/src/recovery_metric/sd_trace_extraction.py

Changes from the original:
  1. stack_source.get_raw_frame(frame_idx)
     → reader.read_frame(frame_idx, use_cache=False)
  2. _load_analysis_batch gains intra_batch_workers: parallel frame reads
     within a batch via a thread pool (safe for per-frame TIFF directories
     because StackReader uses per-file locks; reads on different files
     run concurrently once the brief global pool-management lock is released).
"""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import numpy as np
import scipy.ndimage as ndimage

from .grid import AnalysisGeometry

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[float, str], None]


# ---------------------------------------------------------------------------
# Per-frame worker (module-level so ThreadPoolExecutor can call it)
# ---------------------------------------------------------------------------

def _read_one_frame(args: tuple) -> np.ndarray:
    """Read, cast, resize, and crop a single frame. Called from thread pool."""
    import cv2
    reader, frame_idx, crop_y0, crop_y1, crop_x0, crop_x1, analysis_scale, down_h, down_w = args
    raw = reader.read_frame(frame_idx, use_cache=False)
    frame = np.asarray(raw, dtype=np.float32)
    if analysis_scale != 1.0:
        frame = cv2.resize(frame, (down_w, down_h), interpolation=cv2.INTER_AREA)
    # .copy() so the slice owns its memory after 'frame' is released
    return frame[crop_y0:crop_y1, crop_x0:crop_x1].copy()


# ---------------------------------------------------------------------------
# Batch frame loader (adapted from sd_trace_extraction._load_analysis_batch)
# Changes: reader.read_frame() instead of stack_source.get_raw_frame();
#          intra_batch_workers > 1 parallelises reads within the batch.
# ---------------------------------------------------------------------------

def _load_analysis_batch(
    reader,
    geometry: AnalysisGeometry,
    batch_start: int,
    batch_end: int,
    *,
    intra_batch_workers: int = 1,
) -> np.ndarray:
    import time

    crop_y0, crop_y1, crop_x0, crop_x1 = geometry.crop_box
    down_h, down_w = geometry.resized_shape
    n = batch_end - batch_start
    batch = np.empty((n, crop_y1 - crop_y0, crop_x1 - crop_x0), dtype=np.float32)

    t_wall_start = time.perf_counter()

    if intra_batch_workers > 1:
        frame_args = [
            (reader, frame_idx, crop_y0, crop_y1, crop_x0, crop_x1,
             geometry.analysis_scale, down_h, down_w)
            for frame_idx in range(batch_start, batch_end)
        ]
        with ThreadPoolExecutor(max_workers=intra_batch_workers) as pool:
            for out_idx, result in enumerate(pool.map(_read_one_frame, frame_args)):
                batch[out_idx] = result
    else:
        import cv2
        for out_idx, frame_idx in enumerate(range(batch_start, batch_end)):
            raw = reader.read_frame(frame_idx, use_cache=False)
            frame = np.asarray(raw, dtype=np.float32)
            if geometry.analysis_scale != 1.0:
                frame = cv2.resize(frame, (down_w, down_h), interpolation=cv2.INTER_AREA)
            batch[out_idx] = frame[crop_y0:crop_y1, crop_x0:crop_x1]

    if batch_start == 0:
        import sys
        t_wall = time.perf_counter() - t_wall_start
        msg = (
            f"[DIAG] Batch 0 timing ({n} frames, {intra_batch_workers} workers): "
            f"wall={t_wall:.3f}s | per-frame wall={t_wall / n * 1000:.1f}ms"
        )
        print(msg, flush=True, file=sys.stderr)
        logger.info(
            "Batch 0: %d frames, %d workers, wall=%.3fs (%.1f ms/frame)",
            n, intra_batch_workers, t_wall, t_wall / n * 1000,
        )

    return batch


# ---------------------------------------------------------------------------
# Numpy extraction (copied verbatim from sd_trace_extraction)
# ---------------------------------------------------------------------------

def _extract_lower_median_traces_numpy(
    reader,
    cell_flat_indices: list[np.ndarray],
    geometry: AnalysisGeometry,
    *,
    frame_count: int,
    batch_size: int,
    intra_batch_workers: int,
    progress_callback: ProgressCallback | None,
) -> np.ndarray:
    raw_traces = np.zeros((len(cell_flat_indices), frame_count), dtype=np.float32)
    for batch_start in range(0, frame_count, batch_size):
        batch_end = min(frame_count, batch_start + batch_size)
        batch = _load_analysis_batch(
            reader, geometry, batch_start, batch_end,
            intra_batch_workers=intra_batch_workers,
        )
        flat = batch.reshape(batch.shape[0], -1)
        for cell_idx, indices in enumerate(cell_flat_indices):
            kth = (len(indices) - 1) // 2
            raw_traces[cell_idx, batch_start:batch_end] = np.partition(flat[:, indices], kth, axis=1)[:, kth]
        if progress_callback:
            progress_callback(batch_end / max(1, frame_count), f"Processed frames {batch_end}/{frame_count}")
    return raw_traces


# ---------------------------------------------------------------------------
# Torch extraction (copied verbatim from sd_trace_extraction)
# ---------------------------------------------------------------------------

def _extract_lower_median_traces_torch(
    reader,
    cell_flat_indices: list[np.ndarray],
    geometry: AnalysisGeometry,
    *,
    frame_count: int,
    batch_size: int,
    prefetch_batches: bool,
    frame_loader_workers: int | None,
    intra_batch_workers: int,
    progress_callback: ProgressCallback | None,
) -> np.ndarray:
    import torch

    num_cells = len(cell_flat_indices)
    cell_pixel_counts = np.asarray([len(idx) for idx in cell_flat_indices], dtype=np.int64)
    max_cell_pixels = int(cell_pixel_counts.max())
    padded_indices = np.zeros((num_cells, max_cell_pixels), dtype=np.int64)
    valid_pixels = np.zeros((num_cells, max_cell_pixels), dtype=bool)
    for c_idx, idx in enumerate(cell_flat_indices):
        padded_indices[c_idx, : len(idx)] = idx
        valid_pixels[c_idx, : len(idx)] = True

    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    padded_indices_t = torch.as_tensor(padded_indices, dtype=torch.long, device=device)
    valid_pixels_t = torch.as_tensor(valid_pixels, dtype=torch.bool, device=device)
    median_indices_t = torch.as_tensor((cell_pixel_counts - 1) // 2, dtype=torch.long, device=device)
    raw_traces = np.zeros((num_cells, frame_count), dtype=np.float32)

    batch_ranges = [(start, min(start + batch_size, frame_count)) for start in range(0, frame_count, batch_size)]
    use_prefetch = bool(prefetch_batches and len(batch_ranges) > 1)
    loader_workers = int(frame_loader_workers if frame_loader_workers is not None else min(4, os.cpu_count() or 1))
    loader_workers = max(1, loader_workers)
    executor = ThreadPoolExecutor(max_workers=loader_workers) if use_prefetch else None
    future = None

    try:
        for batch_idx, (batch_start, batch_end) in enumerate(batch_ranges):
            if executor is not None:
                if future is None:
                    future = executor.submit(
                        _load_analysis_batch, reader, geometry, batch_start, batch_end,
                        intra_batch_workers=intra_batch_workers,
                    )
                if batch_idx + 1 < len(batch_ranges):
                    next_start, next_end = batch_ranges[batch_idx + 1]
                    next_future = executor.submit(
                        _load_analysis_batch, reader, geometry, next_start, next_end,
                        intra_batch_workers=intra_batch_workers,
                    )
                else:
                    next_future = None
                batch = future.result()
                future = next_future
            else:
                batch = _load_analysis_batch(
                    reader, geometry, batch_start, batch_end,
                    intra_batch_workers=intra_batch_workers,
                )

            with torch.inference_mode():
                batch_t = torch.from_numpy(batch).to(device)
                flat = batch_t.reshape(batch_t.shape[0], -1)
                cell_pixels = flat[:, padded_indices_t]
                cell_pixels = cell_pixels.masked_fill(~valid_pixels_t.unsqueeze(0), float("inf"))
                sorted_pixels = torch.sort(cell_pixels, dim=2).values
                gather_idx = median_indices_t.view(1, num_cells, 1).expand(batch_t.shape[0], -1, -1)
                medians = sorted_pixels.gather(2, gather_idx).squeeze(2)
                raw_traces[:, batch_start:batch_end] = medians.T.cpu().numpy()
            if progress_callback:
                progress_callback(batch_end / max(1, frame_count), f"Processed frames {batch_end}/{frame_count}")
    finally:
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)
    return raw_traces


# ---------------------------------------------------------------------------
# Public extraction function (copied from sd_trace_extraction)
# ---------------------------------------------------------------------------

def extract_lower_median_traces(
    reader,
    cell_masks: list[np.ndarray],
    geometry: AnalysisGeometry,
    *,
    frame_count: int,
    backend: str = "torch",
    batch_size: int = 100,
    prefetch_batches: bool = True,
    frame_loader_workers: int | None = None,
    intra_batch_workers: int | None = None,
    progress_callback: ProgressCallback | None = None,
) -> np.ndarray:
    """Extract per-cell lower medians from cropped detector-analysis frames.

    Args:
        reader: StackReader (read_frame(idx, use_cache=False) called per frame).
        cell_masks: from GridExtraction.cell_masks.
        geometry: from GridExtraction.geometry.
        frame_count: total frames in the recording.
        backend: "torch" (default, uses MPS/CPU) or "numpy".
        batch_size: frames per batch.
        prefetch_batches: prefetch next batch while GPU processes current.
        frame_loader_workers: threads for between-batch prefetch (default: min(4, cpu_count)).
        intra_batch_workers: threads for parallel frame reads within each batch.
            None (default) = min(4, cpu_count). Set to 1 to disable.
            Effective for per-frame TIFF directories; for single multi-page TIFFs
            all reads share one file handle and will serialise on its lock.
        progress_callback: called as callback(fraction_done, message).

    Returns:
        raw_traces: float32 array [n_cells, frame_count].
    """
    if not cell_masks:
        raise ValueError("At least one cell mask is required.")
    frame_count = int(frame_count)
    batch_size = int(batch_size)
    if frame_count <= 0:
        raise ValueError("frame_count must be greater than 0.")
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than 0.")

    cell_flat_indices = [np.flatnonzero(np.asarray(m, dtype=bool).ravel()) for m in cell_masks]
    cell_pixel_counts = np.asarray([len(idx) for idx in cell_flat_indices], dtype=np.int64)
    if np.any(cell_pixel_counts <= 0):
        raise ValueError("One or more cell masks are empty.")

    backend = str(backend or "torch").strip().lower()
    if backend not in {"torch", "numpy"}:
        raise ValueError("backend must be 'torch' or 'numpy'.")

    cpu_count = max(1, os.cpu_count() or 1)
    if intra_batch_workers is not None:
        # Honour the caller's request but never exceed the logical CPU count —
        # even for I/O-bound work, more threads than CPUs gives diminishing returns
        # and can thrash the OS scheduler on the shared _tiff_lock.
        resolved_intra = max(1, min(int(intra_batch_workers), cpu_count))
    else:
        # Auto: try up to 8 parallel readers, bounded by what the system has.
        resolved_intra = min(8, cpu_count)

    if backend == "torch":
        try:
            return _extract_lower_median_traces_torch(
                reader,
                cell_flat_indices,
                geometry,
                frame_count=frame_count,
                batch_size=batch_size,
                prefetch_batches=bool(prefetch_batches),
                frame_loader_workers=frame_loader_workers,
                intra_batch_workers=resolved_intra,
                progress_callback=progress_callback,
            )
        except Exception as torch_exc:
            if progress_callback:
                progress_callback(0.0, f"Torch extraction failed ({torch_exc}); retrying with NumPy")
            logger.warning("Torch trace extraction failed; retrying with NumPy: %s", torch_exc)
            try:
                return _extract_lower_median_traces_numpy(
                    reader,
                    cell_flat_indices,
                    geometry,
                    frame_count=frame_count,
                    batch_size=batch_size,
                    intra_batch_workers=resolved_intra,
                    progress_callback=progress_callback,
                )
            except Exception as numpy_exc:
                raise RuntimeError(
                    f"Torch extraction failed ({torch_exc}); NumPy fallback also failed ({numpy_exc})"
                ) from numpy_exc

    return _extract_lower_median_traces_numpy(
        reader,
        cell_flat_indices,
        geometry,
        frame_count=frame_count,
        batch_size=batch_size,
        intra_batch_workers=resolved_intra,
        progress_callback=progress_callback,
    )


# ---------------------------------------------------------------------------
# Detrending (copied from sd_trace_extraction.compute_detector_trace_products)
# ---------------------------------------------------------------------------

def detrend_traces(raw_traces: np.ndarray, *, detrend_window_frames: int = 120) -> np.ndarray:
    """Subtract a rolling median baseline to remove slow drift.

    Copied from compute_detector_trace_products() in sd_trace_extraction.py.

    Args:
        raw_traces: float32 array [n_cells, n_frames].
        detrend_window_frames: median filter window width.

    Returns:
        detrended float32 array, same shape.
    """
    raw = np.asarray(raw_traces, dtype=np.float32)
    smoothed = ndimage.median_filter(raw, size=(1, int(detrend_window_frames)), mode="nearest")
    return (raw - smoothed).astype(np.float32)
