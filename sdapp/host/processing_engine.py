from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from threading import Event, Lock, Thread
from time import perf_counter
from typing import Callable

import numpy as np

from sdapp.shared.frame_source.preprocessing import _processed_frame
from .stack_reader import StackReader


@dataclass
class PopupProcessRequest:
    job_id: int
    range_start: int
    range_end: int
    baseline_count: int
    baseline_end: int
    current_idx: int
    warm_radius: int = 10
    sample_stride: int = 5


@dataclass
class PopupProcessResult:
    job_id: int
    baseline_frame: np.ndarray
    p1: float
    p99: float
    warmed_frames: dict[int, np.ndarray]
    timings_ms: dict[str, float]


class PopupProcessingEngine:
    def __init__(self, smoothed_cache_max: int = 64, baseline_cache_max: int = 16, norm_cache_max: int = 32):
        self._smoothed_cache_max = max(8, int(smoothed_cache_max))
        self._baseline_cache_max = max(4, int(baseline_cache_max))
        self._norm_cache_max = max(8, int(norm_cache_max))

        self._reader: StackReader | None = None
        self._lock = Lock()
        self._active_cancel: Event | None = None

        self._smoothed_cache: OrderedDict[int, np.ndarray] = OrderedDict()
        self._baseline_cache: OrderedDict[tuple[int, int], np.ndarray] = OrderedDict()
        self._norm_cache: OrderedDict[tuple[int, int, int, int, int], tuple[float, float]] = OrderedDict()
        self._sampled_diff_cache: OrderedDict[tuple[int, int, int], np.ndarray] = OrderedDict()
        self._sampled_diff_cache_max = 256
        self._sampled_diff_cache_max_bytes = 256 * 1024 * 1024
        self._sampled_diff_cache_bytes = 0

    def set_reader(self, reader: StackReader | None) -> None:
        with self._lock:
            self._reader = reader
            self._active_cancel = None
            self._smoothed_cache.clear()
            self._baseline_cache.clear()
            self._norm_cache.clear()
            self._sampled_diff_cache.clear()
            self._sampled_diff_cache_bytes = 0

    def cancel_active(self) -> None:
        with self._lock:
            if self._active_cancel is not None:
                self._active_cancel.set()

    def submit_popup_job(
        self,
        request: PopupProcessRequest,
        callback: Callable[[PopupProcessResult | None, Exception | None], None],
    ) -> None:
        cancel_event = Event()
        with self._lock:
            prev = self._active_cancel
            self._active_cancel = cancel_event
        if prev is not None:
            prev.set()

        def worker() -> None:
            try:
                result = self.run_popup_sync(request, cancel_event)
            except Exception as exc:  # pragma: no cover - defensive path
                if str(exc) == "Canceled" or cancel_event.is_set():
                    return
                callback(None, exc)
                return
            if result is not None and not cancel_event.is_set():
                callback(result, None)

        Thread(target=worker, daemon=True).start()

    def run_popup_sync(self, request: PopupProcessRequest, cancel_event: Event | None = None) -> PopupProcessResult | None:
        t0 = perf_counter()
        baseline = self._get_baseline(request.baseline_end, request.baseline_count, cancel_event)
        if cancel_event is not None and cancel_event.is_set():
            return None
        t1 = perf_counter()

        p1, p99 = self._get_norm_stats(
            request.range_start,
            request.range_end,
            request.baseline_end,
            request.baseline_count,
            request.sample_stride,
            baseline,
            cancel_event,
        )
        if cancel_event is not None and cancel_event.is_set():
            return None
        t2 = perf_counter()

        warmed: dict[int, np.ndarray] = {}
        lo = max(request.range_start, int(request.current_idx) - int(request.warm_radius))
        hi = min(request.range_end, int(request.current_idx) + int(request.warm_radius))
        for idx in range(lo, hi + 1):
            if cancel_event is not None and cancel_event.is_set():
                return None
            warmed[idx] = self.get_processed_frame(idx, baseline, p1, p99)
        t3 = perf_counter()

        return PopupProcessResult(
            job_id=request.job_id,
            baseline_frame=baseline,
            p1=float(p1),
            p99=float(p99),
            warmed_frames=warmed,
            timings_ms={
                "baseline": (t1 - t0) * 1000.0,
                "norm": (t2 - t1) * 1000.0,
                "warm": (t3 - t2) * 1000.0,
                "total": (t3 - t0) * 1000.0,
            },
        )

    def prewarm_smoothed(self, indices: list[int]) -> None:
        for idx in indices:
            self._get_smoothed_frame(int(idx), cancel_event=None)

    def get_processed_frame(self, frame_idx: int, baseline: np.ndarray, p1: float, p99: float) -> np.ndarray:
        smoothed = self._get_smoothed_frame(int(frame_idx), cancel_event=None)
        sub = smoothed - baseline
        denom = max(1e-8, float(p99 - p1))
        norm = np.clip((sub - float(p1)) / denom, 0.0, 1.0)
        return (norm * 255.0).astype(np.uint8)

    def _require_reader(self) -> StackReader:
        with self._lock:
            reader = self._reader
        if reader is None:
            raise RuntimeError("Stack reader is not set.")
        return reader

    def _cache_put(self, cache: OrderedDict, key, value, max_len: int) -> None:
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > max_len:
            cache.popitem(last=False)

    def _cache_put_sampled_diff(self, key: tuple[int, int, int], value: np.ndarray) -> None:
        prev = self._sampled_diff_cache.pop(key, None)
        if prev is not None:
            self._sampled_diff_cache_bytes = max(0, self._sampled_diff_cache_bytes - int(prev.nbytes))
        self._sampled_diff_cache[key] = value
        self._sampled_diff_cache.move_to_end(key)
        self._sampled_diff_cache_bytes += int(value.nbytes)

        while len(self._sampled_diff_cache) > self._sampled_diff_cache_max:
            _old_key, old_value = self._sampled_diff_cache.popitem(last=False)
            self._sampled_diff_cache_bytes = max(0, self._sampled_diff_cache_bytes - int(old_value.nbytes))
        while self._sampled_diff_cache and self._sampled_diff_cache_bytes > self._sampled_diff_cache_max_bytes:
            _old_key, old_value = self._sampled_diff_cache.popitem(last=False)
            self._sampled_diff_cache_bytes = max(0, self._sampled_diff_cache_bytes - int(old_value.nbytes))

    def collect_garbage(self, aggressive: bool = False) -> None:
        with self._lock:
            self._norm_cache.clear()
            if aggressive:
                self._smoothed_cache.clear()
                self._baseline_cache.clear()
                self._sampled_diff_cache.clear()
                self._sampled_diff_cache_bytes = 0
                return
            while len(self._sampled_diff_cache) > max(8, self._sampled_diff_cache_max // 2):
                _old_key, old_value = self._sampled_diff_cache.popitem(last=False)
                self._sampled_diff_cache_bytes = max(0, self._sampled_diff_cache_bytes - int(old_value.nbytes))
            while self._sampled_diff_cache and self._sampled_diff_cache_bytes > (self._sampled_diff_cache_max_bytes // 2):
                _old_key, old_value = self._sampled_diff_cache.popitem(last=False)
                self._sampled_diff_cache_bytes = max(0, self._sampled_diff_cache_bytes - int(old_value.nbytes))
            while len(self._smoothed_cache) > max(16, self._smoothed_cache_max // 2):
                self._smoothed_cache.popitem(last=False)
            while len(self._baseline_cache) > max(4, self._baseline_cache_max // 2):
                self._baseline_cache.popitem(last=False)

    def _get_smoothed_frame(self, frame_idx: int, cancel_event: Event | None) -> np.ndarray:
        with self._lock:
            if frame_idx in self._smoothed_cache:
                out = self._smoothed_cache.pop(frame_idx)
                self._smoothed_cache[frame_idx] = out
                return out
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("Canceled")

        reader = self._require_reader()
        raw = reader.read_frame(frame_idx, use_cache=True).astype(np.float32, copy=False)
        smoothed = _processed_frame(
            raw,
            apply_horizontal_bar_denoise=False,
            apply_smoothing=True,
        )

        with self._lock:
            self._cache_put(self._smoothed_cache, frame_idx, smoothed, self._smoothed_cache_max)
        return smoothed

    def _get_baseline(self, baseline_end: int, baseline_count: int, cancel_event: Event | None) -> np.ndarray:
        key = (int(baseline_end), int(baseline_count))
        with self._lock:
            if key in self._baseline_cache:
                out = self._baseline_cache.pop(key)
                self._baseline_cache[key] = out
                return out

        baseline_start = max(0, int(baseline_end) - int(baseline_count) + 1)
        indices = list(range(baseline_start, int(baseline_end) + 1))
        if not indices:
            raise RuntimeError("No baseline frames available.")

        parts: list[np.ndarray] = []
        for idx in indices:
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("Canceled")
            parts.append(self._get_smoothed_frame(idx, cancel_event))
        baseline = np.median(np.stack(parts, axis=0), axis=0).astype(np.float32, copy=False)

        with self._lock:
            self._cache_put(self._baseline_cache, key, baseline, self._baseline_cache_max)
        return baseline

    def _get_norm_stats(
        self,
        range_start: int,
        range_end: int,
        baseline_end: int,
        baseline_count: int,
        sample_stride: int,
        baseline: np.ndarray,
        cancel_event: Event | None,
    ) -> tuple[float, float]:
        stride = max(1, int(sample_stride))
        nkey = (int(range_start), int(range_end), int(baseline_end), int(baseline_count), int(stride))
        with self._lock:
            if nkey in self._norm_cache:
                out = self._norm_cache.pop(nkey)
                self._norm_cache[nkey] = out
                return out

        sampled_indices = list(range(int(range_start), int(range_end) + 1, stride))
        if (int(range_end) - int(range_start)) % stride != 0:
            sampled_indices.append(int(range_end))

        sampled_diffs: list[np.ndarray] = []
        for idx in sampled_indices:
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("Canceled")
            skey = (int(idx), int(baseline_end), int(baseline_count))
            with self._lock:
                cached = self._sampled_diff_cache.get(skey)
                if cached is not None:
                    self._sampled_diff_cache.move_to_end(skey)
            if cached is not None:
                sampled_diffs.append(cached)
                continue
            smoothed = self._get_smoothed_frame(idx, cancel_event)
            diff = (smoothed - baseline).astype(np.float32, copy=False)
            sampled_diffs.append(diff)
            with self._lock:
                self._cache_put_sampled_diff(skey, diff)

        sampled_stack = np.stack(sampled_diffs, axis=0)
        if sampled_stack.nbytes > 400_000_000:
            rng = np.random.default_rng(0)
            sampled_values = []
            for frame in sampled_stack:
                flat = frame.ravel()
                take = min(flat.size, 100_000)
                idxs = rng.choice(flat.size, size=take, replace=False)
                sampled_values.append(flat[idxs])
            pool = np.concatenate(sampled_values, axis=0)
            p1 = float(np.percentile(pool, 1))
            p99 = float(np.percentile(pool, 99))
        else:
            p1 = float(np.percentile(sampled_stack, 1))
            p99 = float(np.percentile(sampled_stack, 99))

        if p99 <= p1:
            p99 = p1 + 1e-8

        with self._lock:
            self._cache_put(self._norm_cache, nkey, (p1, p99), self._norm_cache_max)
        return p1, p99
