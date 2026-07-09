from __future__ import annotations

import contextlib
import gc
import inspect
import importlib
import io
import queue
import threading
import time
from collections import OrderedDict
from typing import Callable, Optional
from swell.shared.ui import dialogs as messagebox

import numpy as np

from swell.shared.errors import InferenceRuntimeError
from swell.shared.ui.theme import APP_COLORS

from swell.analysis.core.seg_state import SegmentationState

torch = None


def _torch_module():
    global torch
    if torch is not None:
        return torch
    try:
        torch = importlib.import_module("torch")
    except Exception:
        torch = None
    return torch


class InferenceManager:
    def __init__(
        self,
        state: SegmentationState,
        root,
        predictor_lock,
        get_sensitivity: Callable[[], float],
        get_current_frame_idx: Callable[[], int],
        get_frame_count: Callable[[], int],
        get_frame_shape: Callable[[], tuple[int, int]],
        set_slider_frame: Callable[[int], None],
        update_display: Callable[[], None],
        recompute_markers: Callable[[], None],
        set_propagated_frames: Callable[[set[int]], None],
        set_status: Callable[[str, str], None],
        prop_log_start: Callable[..., int],
        prop_log_tick: Callable[..., None],
        prop_log_finish: Callable[..., None],
        on_propagation_status: Callable[[str, int, int], None] | None,
        log: Callable[[str, str, str], None],
        is_ui_alive: Callable[[], bool],
        on_device_oom: Callable[[str], bool] | None = None,
    ):
        self.state = state
        self.root = root
        self.predictor_lock = predictor_lock

        self.get_sensitivity = get_sensitivity
        self.get_current_frame_idx = get_current_frame_idx
        self.get_frame_count = get_frame_count
        self.get_frame_shape = get_frame_shape
        self.set_slider_frame = set_slider_frame
        self.update_display = update_display
        self.recompute_markers = recompute_markers
        self.set_propagated_frames = set_propagated_frames
        self.set_status = set_status
        self.prop_log_start = prop_log_start
        self.prop_log_tick = prop_log_tick
        self.prop_log_finish = prop_log_finish
        self.on_propagation_status = on_propagation_status
        self.on_device_oom = on_device_oom
        self.log = log
        self.is_ui_alive = is_ui_alive

        self.predictor = None
        self.inference_state = None
        self.model_ready = False

        self._infer_worker_thread = None
        self._infer_worker_stop = threading.Event()
        self._infer_queue = queue.Queue()
        self._infer_state_lock = threading.Lock()
        self._infer_pending_frames = set()
        self._infer_generation = 0
        self._infer_frame_generation = {}
        self._infer_stale_skip_count = 0
        self._infer_max_queue_depth = 0
        self._sensitivity_debounce_job = None
        self._pending_marker_batch_frames = set()

        # Cache of raw mask logits per frame so a pure sensitivity (threshold)
        # change can re-threshold without re-running the network forward pass.
        self._logits_cache: "OrderedDict[int, tuple[tuple, np.ndarray]]" = OrderedDict()
        self._logits_cache_lock = threading.Lock()
        self._logits_cache_max = 32

        self.propagate_thread = None
        self._prop_stop_event = threading.Event()
        self._prop_pause_event = threading.Event()
        self._prop_thread_lock = threading.Lock()
        self._active_propagation_generation = 0
        self._prop_start_retry_job = None
        self._prop_restart_wait_count = 0
        self._preserve_generated_masks_on_stop = False

    def _log_debug(self, context: str, message: str):
        self.log("DEBUG", context, message)

    def _log_info(self, context: str, message: str):
        self.log("INFO", context, message)

    def _log_warn(self, context: str, message: str):
        self.log("WARN", context, message)

    def _log_error(self, context: str, message: str):
        self.log("ERROR", context, message)

    def _validate_point_prompt_arrays(self, points, labels):
        if points.ndim != 2:
            return False, f"points.ndim={points.ndim} (expected 2)"
        if points.shape[1] != 2:
            return False, f"points.shape[1]={points.shape[1]} (expected 2)"
        if labels.ndim != 1:
            return False, f"labels.ndim={labels.ndim} (expected 1)"
        if points.shape[0] <= 0:
            return False, "points has zero rows"
        if labels.shape[0] != points.shape[0]:
            return False, f"labels rows={labels.shape[0]} do not match points rows={points.shape[0]}"
        return True, ""

    def _normalize_box_prompt(self, frame_idx: int) -> np.ndarray | None:
        boxes = getattr(self.state, "boxes", {}) or {}
        raw_box = boxes.get(frame_idx) if isinstance(boxes, dict) else None
        box = self.state._normalize_box(raw_box) if raw_box is not None else None
        if box is None:
            return None
        return np.asarray(box, dtype=np.float32).reshape(4)

    def _predictor_accepts_box_prompt(self) -> bool:
        method = getattr(self.predictor, "add_new_points_or_box", None)
        if method is None:
            return False
        try:
            sig = inspect.signature(method)
        except (TypeError, ValueError):
            return True
        for param in sig.parameters.values():
            if param.kind == inspect.Parameter.VAR_KEYWORD or param.name == "box":
                return True
        return False

    @staticmethod
    def _is_box_kwarg_type_error(exc: TypeError) -> bool:
        message = str(exc).lower()
        return "box" in message and ("unexpected" in message or "keyword" in message)

    def _add_new_points_or_box_compatible(
        self,
        *,
        frame_idx: int,
        points,
        labels,
        box,
        clear_old_points: bool | None = None,
    ):
        kwargs = {
            "inference_state": self.inference_state,
            "frame_idx": frame_idx,
            "obj_id": 1,
            "points": points,
            "labels": labels,
        }
        if clear_old_points is not None:
            kwargs["clear_old_points"] = bool(clear_old_points)
        if box is not None or self._predictor_accepts_box_prompt():
            kwargs["box"] = box
        try:
            return self.predictor.add_new_points_or_box(**kwargs)
        except TypeError as exc:
            if "box" in kwargs and self._is_box_kwarg_type_error(exc):
                kwargs.pop("box", None)
                self._log_warn("Model", "Predictor does not accept box prompts; retrying without box.")
                return self.predictor.add_new_points_or_box(**kwargs)
            raise

    def _inference_queue_depth(self):
        try:
            return int(self._infer_queue.qsize())
        except Exception as e:
            self._log_warn("Inference", f"Failed to get inference queue depth: {e}")
            return 0

    def is_busy(self) -> bool:
        with self._infer_state_lock:
            has_pending_frames = bool(self._infer_pending_frames)
            has_pending_marker_batch = bool(self._pending_marker_batch_frames)
        has_queued_jobs = bool(self._inference_queue_depth() > 0)
        has_debounced_sensitivity = self._sensitivity_debounce_job is not None
        with self._prop_thread_lock:
            propagation_alive = self.propagate_thread is not None and self.propagate_thread.is_alive()
        has_retry_job = self._prop_start_retry_job is not None
        return bool(
            has_pending_frames
            or has_pending_marker_batch
            or has_queued_jobs
            or has_debounced_sensitivity
            or propagation_alive
            or has_retry_job
        )

    def wait_until_idle(self, timeout_s: float = 1.5, poll_s: float = 0.02) -> bool:
        deadline = time.perf_counter() + max(0.05, float(timeout_s))
        while time.perf_counter() < deadline:
            if not self.is_busy():
                return True
            time.sleep(max(0.005, float(poll_s)))
        return not self.is_busy()

    def _is_propagation_cancelled(self, generation):
        return self._prop_stop_event.is_set() or generation != self._active_propagation_generation

    def is_propagation_running(self) -> bool:
        with self._prop_thread_lock:
            return self.propagate_thread is not None and self.propagate_thread.is_alive()

    def is_segmentation_mutation_blocked(self) -> bool:
        return self.is_propagation_running()

    def is_propagation_paused(self) -> bool:
        return self.is_propagation_running() and self._prop_pause_event.is_set()

    def _wait_if_propagation_paused(self, generation) -> bool:
        while self._prop_pause_event.is_set():
            if self._is_propagation_cancelled(generation):
                return False
            time.sleep(0.05)
        return not self._is_propagation_cancelled(generation)

    def pause_propagation(self) -> bool:
        if not self.is_propagation_running():
            return False
        self._prop_pause_event.set()
        self._log_info("Propagation", "Propagation paused.")
        if self.is_ui_alive():
            self.root.after(0, lambda: self.set_status("Propagation Paused", APP_COLORS["warning"]))
        return True

    def resume_propagation(self) -> bool:
        if not self.is_propagation_running() or not self._prop_pause_event.is_set():
            return False
        self._prop_pause_event.clear()
        self._log_info("Propagation", "Propagation resumed.")
        if self.is_ui_alive():
            self.root.after(0, lambda: self.set_status("Propagating...", APP_COLORS["purple"]))
        return True

    def request_stop_propagation(self, *, preserve_generated_masks: bool = False) -> bool:
        with self._prop_thread_lock:
            thread = self.propagate_thread
            if thread is None or not thread.is_alive():
                return False
            self._preserve_generated_masks_on_stop = bool(preserve_generated_masks)
            self._prop_stop_event.set()
            self._prop_pause_event.clear()
        self._log_info(
            "Propagation",
            "Stopping propagation and preserving generated masks."
            if preserve_generated_masks
            else "Stopping propagation and restoring previous masks.",
        )
        if self.is_ui_alive():
            self.root.after(0, lambda: self.set_status("Stopping Propagation...", APP_COLORS["warning"]))
        return True

    def _frame_shape_hw(self) -> tuple[int, int] | None:
        try:
            frame_shape = tuple(int(v) for v in self.get_frame_shape()[:2])
        except Exception as e:
            self._log_warn("Inference", f"Failed to get frame shape: {e}")
            return None
        if len(frame_shape) != 2 or frame_shape[0] <= 0 or frame_shape[1] <= 0:
            return None
        return frame_shape

    def _clear_accelerator_cache(self):
        gc.collect()
        torch = _torch_module()
        if torch is not None:
            if torch.backends.mps.is_available():
                torch.mps.empty_cache()
            elif torch.cuda.is_available():
                torch.cuda.empty_cache()

    def _is_accelerator_oom(self, exc: Exception) -> bool:
        message = str(exc or "").lower()
        if "out of memory" not in message:
            return False
        return any(token in message for token in ("mps", "cuda", "private pool"))

    def _recover_from_accelerator_oom(self, context: str, exc: Exception) -> bool:
        if not self._is_accelerator_oom(exc):
            return False
        message = str(exc).strip()
        self._log_warn(context, f"Accelerator OOM detected: {message}")
        try:
            self._clear_accelerator_cache()
        except Exception as cache_exc:
            self._log_debug(context, f"Accelerator cache clear skipped after OOM: {cache_exc}")
        if callable(self.on_device_oom):
            try:
                return bool(self.on_device_oom(message))
            except Exception as callback_exc:
                self._log_error(context, f"OOM recovery callback failed: {callback_exc}")
        return False

    def _has_nonempty_cached_mask(self, frame_idx: int) -> bool:
        # Raw committed masks are allowed here because propagation can fall back
        # to an existing mask seed when no prompt anchors exist. Persistent
        # regions intentionally do not create propagation anchors.
        try:
            cached = self.state.masks_cache.get(int(frame_idx))
        except Exception:
            return False
        if cached is None:
            return False
        try:
            return bool(np.any(cached))
        except Exception:
            return False

    def _nearest_frame(self, candidates: set[int], target_idx: int) -> int | None:
        cleaned = sorted(int(idx) for idx in candidates)
        if not cleaned:
            return None
        return min(cleaned, key=lambda idx: (abs(idx - int(target_idx)), idx))

    def _notify_mask_updated(self, *, recompute_markers: bool = True):
        if self.is_ui_alive():
            if recompute_markers:
                self.root.after(0, self.recompute_markers)
            self.root.after(0, self.update_display)

    def _finish_pending_marker_batch_frame(self, frame_idx: int) -> bool:
        with self._infer_state_lock:
            if int(frame_idx) not in self._pending_marker_batch_frames:
                return False
            self._pending_marker_batch_frames.discard(int(frame_idx))
            batch_drained = not self._pending_marker_batch_frames
        if batch_drained:
            self._log_debug("Model", "Pending-point marker batch completed; recomputing markers once.")
        return batch_drained

    def start(self):
        self._start_inference_worker()

    def stop(self, join_timeout: float = 1.0):
        self._stop_propagation_thread(clear_event=False, timeout=join_timeout)
        self._stop_inference_worker(timeout=join_timeout)

    def on_model_ready(self, predictor, inference_state):
        self.predictor = predictor
        self.inference_state = inference_state
        self.model_ready = predictor is not None and inference_state is not None

    def on_model_unloaded(self):
        self.model_ready = False
        self.predictor = None
        self.inference_state = None
        self._stop_propagation_thread(clear_event=True, timeout=0.2)
        self._stop_inference_worker(timeout=0.2)
        self._start_inference_worker()

    def _start_inference_worker(self):
        if self._infer_worker_thread is not None and self._infer_worker_thread.is_alive():
            return
        self._infer_worker_stop.clear()
        self._infer_queue = queue.Queue()
        with self._infer_state_lock:
            self._infer_pending_frames.clear()
            self._infer_frame_generation.clear()
            self._infer_generation = 0
            self._infer_stale_skip_count = 0
            self._infer_max_queue_depth = 0
            self._pending_marker_batch_frames.clear()
        self._clear_logits_cache()
        self._infer_worker_thread = threading.Thread(target=self._inference_worker_loop, daemon=True)
        self._infer_worker_thread.start()
        self._log_debug("Model", "Started inference worker thread.")

    def _stop_inference_worker(self, timeout=1.0):
        self._infer_worker_stop.set()
        if self._sensitivity_debounce_job is not None and self.is_ui_alive():
            try:
                self.root.after_cancel(self._sensitivity_debounce_job)
            except Exception as exc:
                self._log_debug("Model", f"Debounce cancel skipped: {exc}")
            self._sensitivity_debounce_job = None

        try:
            self._infer_queue.put_nowait(None)
        except Exception as exc:
            self._log_debug("Model", f"Queue sentinel enqueue skipped: {exc}")

        thread = self._infer_worker_thread
        if thread is not None and thread.is_alive():
            try:
                thread.join(timeout=timeout)
            except Exception as exc:
                self._log_debug("Model", f"Inference worker join skipped: {exc}")
            if thread.is_alive():
                self._log_warn("Model", "Inference worker did not stop before timeout.")

        self._infer_worker_thread = None
        self._infer_queue = queue.Queue()
        with self._infer_state_lock:
            self._infer_pending_frames.clear()
            self._infer_frame_generation.clear()
            self._pending_marker_batch_frames.clear()

    def _stop_propagation_thread(self, clear_event=False, timeout=1.0):
        with self._prop_thread_lock:
            self._prop_stop_event.set()
            self._prop_pause_event.clear()
            if self._prop_start_retry_job is not None and self.is_ui_alive():
                try:
                    self.root.after_cancel(self._prop_start_retry_job)
                except Exception as exc:
                    self._log_debug("Propagation", f"Retry cancel skipped: {exc}")
                self._prop_start_retry_job = None
            thread = self.propagate_thread

        if thread is not None and thread.is_alive():
            try:
                thread.join(timeout=timeout)
            except Exception as exc:
                self._log_debug("Propagation", f"Propagation join skipped: {exc}")
            if thread.is_alive():
                self._log_warn("Propagation", "Propagation thread did not stop before timeout.")

        with self._prop_thread_lock:
            if self.propagate_thread is thread and (thread is None or not thread.is_alive()):
                self.propagate_thread = None
            if clear_event and (self.propagate_thread is None or not self.propagate_thread.is_alive()):
                self._prop_stop_event.clear()
                self._preserve_generated_masks_on_stop = False

    def enqueue_pending_point_frames(self, frame_indices):
        if not self.model_ready:
            return
        frames = sorted(list(frame_indices))
        if not frames:
            return
        with self._infer_state_lock:
            self._pending_marker_batch_frames.update(int(frame_idx) for frame_idx in frames)
        self._log_info("Model", f"Processing {len(frames)} frame(s) with pending points.")
        for frame_idx in frames:
            self.enqueue_frame_inference(frame_idx, reason="pending_points")

    def enqueue_frame_inference(self, frame_idx, reason="update"):
        self.state.prune_invalid_points()

        if not self.model_ready or self.predictor is None or self.inference_state is None:
            return
        if self.is_propagation_running():
            self._log_debug("Model", f"Skipping frame inference for frame {int(frame_idx) + 1} during propagation.")
            self._finish_pending_marker_batch_frame(frame_idx)
            return

        valid_frames = self.state.get_valid_point_frames() | self.state.get_valid_box_frames()
        if frame_idx not in valid_frames:
            self.state.clear_mask(frame_idx)
            should_recompute = self._finish_pending_marker_batch_frame(frame_idx)
            self._notify_mask_updated(recompute_markers=should_recompute)
            return

        with self._infer_state_lock:
            self._infer_generation += 1
            generation = self._infer_generation
            self._infer_frame_generation[frame_idx] = generation
            already_pending = frame_idx in self._infer_pending_frames
            if not already_pending:
                self._infer_pending_frames.add(frame_idx)
                self._infer_queue.put((frame_idx, generation))
                depth = self._inference_queue_depth()
                self._infer_max_queue_depth = max(self._infer_max_queue_depth, depth)
                self._log_debug("Model", f"Queued inference frame {frame_idx + 1} ({reason}). queue_depth={depth}")

    def schedule_sensitivity_inference(self, frame_idx, debounce_ms=80):
        if self._sensitivity_debounce_job is not None and self.is_ui_alive():
            try:
                self.root.after_cancel(self._sensitivity_debounce_job)
            except Exception as exc:
                self._log_debug("Model", f"Debounce cancel skipped: {exc}")

        if self.is_ui_alive():
            self._sensitivity_debounce_job = self.root.after(
                int(debounce_ms),
                lambda f=frame_idx: self._fire_sensitivity_inference(f),
            )

    def _fire_sensitivity_inference(self, frame_idx):
        self._sensitivity_debounce_job = None
        # A sensitivity change only moves the threshold applied to the mask
        # logits; if we still hold the logits from the last forward pass for
        # the same point prompts, re-threshold instead of re-running the model.
        if self._try_rethreshold_from_cache(frame_idx):
            return
        self.enqueue_frame_inference(frame_idx, reason="sensitivity")

    def _prompt_signature(self, frame_idx):
        pt_list = self.state.points.get(frame_idx)
        boxes = getattr(self.state, "boxes", {}) or {}
        raw_box = boxes.get(frame_idx) if isinstance(boxes, dict) else None
        box = self.state._normalize_box(raw_box) if raw_box is not None else None
        try:
            points_sig = tuple(
                (float(p["x"]), float(p["y"]), int(p["label"])) for p in list(pt_list or [])
            )
        except Exception:
            return None
        if not points_sig and box is None:
            return None
        return points_sig, tuple(box) if box is not None else None

    def _store_frame_logits(self, frame_idx, signature, logits_np):
        if signature is None or logits_np is None:
            return
        with self._logits_cache_lock:
            self._logits_cache[frame_idx] = (signature, logits_np)
            self._logits_cache.move_to_end(frame_idx)
            while len(self._logits_cache) > self._logits_cache_max:
                self._logits_cache.popitem(last=False)

    def _clear_logits_cache(self):
        with self._logits_cache_lock:
            self._logits_cache.clear()

    def _prompted_frames(self) -> set[int]:
        """Frames with valid point or box prompts."""
        frames = set(self.state.get_valid_point_frames() or [])
        get_box_frames = getattr(self.state, "get_valid_box_frames", None)
        if callable(get_box_frames):
            try:
                frames.update(get_box_frames() or [])
            except Exception:
                pass
        return frames

    def _try_rethreshold_from_cache(self, frame_idx) -> bool:
        if not self.model_ready:
            return False
        if self.is_propagation_running():
            return False
        self.state.prune_invalid_points()
        if frame_idx not in self._prompted_frames():
            return False
        signature = self._prompt_signature(frame_idx)
        if signature is None:
            return False
        with self._logits_cache_lock:
            cached = self._logits_cache.get(frame_idx)
            if cached is not None:
                self._logits_cache.move_to_end(frame_idx)
        if cached is None:
            return False
        cached_signature, logits_np = cached
        if cached_signature != signature:
            return False
        thresh = float(self.get_sensitivity())
        self.state.set_mask(frame_idx, (logits_np > thresh).squeeze())
        with self._infer_state_lock:
            defer_markers = int(frame_idx) in self._pending_marker_batch_frames
        self._notify_mask_updated(recompute_markers=not defer_markers)
        self._log_debug("Model", f"Re-thresholded frame {frame_idx + 1} from cached logits (sensitivity).")
        return True

    def _inference_worker_loop(self):
        while not self._infer_worker_stop.is_set():
            item = self._infer_queue.get(block=True)

            if item is None:
                try:
                    self._infer_queue.task_done()
                except Exception as exc:
                    self._log_debug("Model", f"Queue task_done skipped: {exc}")
                continue

            frame_idx, requested_generation = item
            try:
                current_generation = requested_generation
                while not self._infer_worker_stop.is_set():
                    with self._infer_state_lock:
                        latest_generation = self._infer_frame_generation.get(frame_idx)
                    if latest_generation is None:
                        break

                    if latest_generation != current_generation:
                        with self._infer_state_lock:
                            self._infer_stale_skip_count += 1
                        self._log_debug("Model", f"Skipping stale inference for frame {frame_idx + 1}.")
                        current_generation = latest_generation

                    self._run_single_frame_inference_core(frame_idx, current_generation)

                    with self._infer_state_lock:
                        newest_generation = self._infer_frame_generation.get(frame_idx)
                    if newest_generation == current_generation:
                        break
            finally:
                should_recompute = self._finish_pending_marker_batch_frame(frame_idx)
                with self._infer_state_lock:
                    self._infer_pending_frames.discard(frame_idx)
                try:
                    self._infer_queue.task_done()
                except Exception as exc:
                    self._log_debug("Model", f"Queue task_done skipped: {exc}")
                if should_recompute and self.is_ui_alive():
                    self.root.after(0, self.recompute_markers)

    def _run_single_frame_inference_core(self, frame_idx, generation):
        if self.is_propagation_running():
            return
        self.state.prune_invalid_points()
        if frame_idx not in self._prompted_frames():
            return
        if not self.model_ready or self.predictor is None or self.inference_state is None:
            return

        try:
            with self.predictor_lock:
                if self._infer_worker_stop.is_set() or self._prop_stop_event.is_set() or self.is_propagation_running():
                    return
                self.predictor.reset_state(self.inference_state)
                pt_list = list(self.state.points.get(frame_idx) or [])
                points = None
                labels = None
                if pt_list:
                    points = np.array([[p["x"], p["y"]] for p in pt_list], dtype=np.float32)
                    labels = np.array([p["label"] for p in pt_list], dtype=np.int32)
                    valid_arrays, reason = self._validate_point_prompt_arrays(points, labels)
                    if not valid_arrays:
                        self._log_warn("Model", f"Skipping inference prompt on frame {frame_idx + 1}: {reason}.")
                        return
                box_arr = self._normalize_box_prompt(frame_idx)
                if points is None and box_arr is None:
                    return

                _, _, out_mask_logits = self._add_new_points_or_box_compatible(
                    frame_idx=frame_idx,
                    points=points,
                    labels=labels,
                    box=box_arr,
                    clear_old_points=True,
                )

            with self._infer_state_lock:
                latest_generation = self._infer_frame_generation.get(frame_idx)
            if latest_generation != generation:
                with self._infer_state_lock:
                    self._infer_stale_skip_count += 1
                return
            if self.is_propagation_running():
                return

            thresh = float(self.get_sensitivity())
            raw_logit = out_mask_logits[0]
            logits_np = (raw_logit.detach() if hasattr(raw_logit, "detach") else raw_logit).cpu().numpy()
            self.state.set_mask(frame_idx, (logits_np > thresh).squeeze())
            self._store_frame_logits(frame_idx, self._prompt_signature(frame_idx), logits_np)
            with self._infer_state_lock:
                defer_markers = int(frame_idx) in self._pending_marker_batch_frames
            self._notify_mask_updated(recompute_markers=not defer_markers)
        except Exception as e:
            if self._recover_from_accelerator_oom("Model", e):
                self._log_warn("Model", f"Inference stopped on frame {frame_idx + 1}; CPU fallback is now active.")
                if self.is_ui_alive():
                    self.root.after(0, lambda: messagebox.showwarning("Inference Fallback", f"GPU Out of Memory on frame {frame_idx + 1}. Switching to CPU fallback."))
                return
            err = InferenceRuntimeError(str(e))
            self._log_error("Model", f"Inference failed on frame {frame_idx + 1}: {err}")
            if self.is_ui_alive():
                self.root.after(0, lambda: messagebox.showerror("Inference Error", f"Inference failed on frame {frame_idx + 1}:\n\n{err}"))

    def trigger_propagation(self, prop_start, prop_end, anchor_frame):
        self._last_propagation_params = (prop_start, prop_end, anchor_frame)
        if self._prop_start_retry_job is not None and self.is_ui_alive():
            try:
                self.root.after_cancel(self._prop_start_retry_job)
            except Exception as exc:
                self._log_debug("Propagation", f"Retry cancel skipped: {exc}")
            self._prop_start_retry_job = None

        with self._prop_thread_lock:
            if self.propagate_thread is not None and self.propagate_thread.is_alive():
                self._preserve_generated_masks_on_stop = False
                self._prop_stop_event.set()
                self._prop_pause_event.clear()
                self._prop_restart_wait_count += 1
                self._log_debug("Propagation", "Waiting for existing propagation thread to stop before restart.")
                if self._prop_start_retry_job is None and self.is_ui_alive():
                    self._prop_start_retry_job = self.root.after(
                        75,
                        lambda s=prop_start, e=prop_end, a=anchor_frame: self.trigger_propagation(s, e, a),
                    )
                return

            self._prop_stop_event.clear()
            self._prop_pause_event.clear()
            self._preserve_generated_masks_on_stop = False
            self._active_propagation_generation += 1
            with self._infer_state_lock:
                self._infer_generation += 1
                self._infer_frame_generation.clear()
                self._infer_pending_frames.clear()
                self._pending_marker_batch_frames.clear()
            generation = self._active_propagation_generation
            self.propagate_thread = threading.Thread(
                target=self._run_background_propagation,
                args=(generation, prop_start, prop_end, anchor_frame),
                daemon=True,
            )
            self.propagate_thread.start()
            self._log_debug("Propagation", f"Started propagation generation {generation}.")

    def _run_background_propagation(self, propagation_generation, prop_start, prop_end, anchor_frame):
        start_ts = time.perf_counter()
        prop_log_run_id = None
        inject_ms = 0.0
        forward_ms = 0.0
        backward_ms = 0.0
        forward_durations: list[float] = []
        backward_durations: list[float] = []
        try:
            if self._is_propagation_cancelled(propagation_generation):
                return
            self.state.prune_invalid_points()

            total_frames = int(self.get_frame_count())
            if total_frames <= 0:
                return
            prop_start = max(0, min(int(prop_start), total_frames - 1))
            prop_end = max(0, min(int(prop_end), total_frames - 1))
            anchor_frame = max(prop_start, min(int(anchor_frame), prop_end))
            in_range = range(prop_start, prop_end + 1)
            valid_prompt_frames = self.state.get_valid_point_frames() | self.state.get_valid_box_frames()
            prompt_frames = {idx for idx in in_range if idx in valid_prompt_frames}
            paint_frames = {idx for idx in in_range if self.state.has_nonempty_paint(idx)}
            frame_shape = self._frame_shape_hw()
            mask_only_frames = {
                idx for idx in in_range if self._has_nonempty_cached_mask(idx)
            }
            anchor_frames = self.state.get_prompt_anchor_frames(total_frames)
            user_seed_frames = {idx for idx in in_range if idx in anchor_frames}
            mask_seed_frames: set[int] = set()
            frames_with_input = set(user_seed_frames)

            if user_seed_frames:
                nearest_seed = self._nearest_frame(user_seed_frames, anchor_frame)
                if nearest_seed is not None:
                    anchor_frame = nearest_seed
            elif mask_only_frames:
                nearest_mask = self._nearest_frame(mask_only_frames, anchor_frame)
                if nearest_mask is None:
                    nearest_mask = self._nearest_frame(mask_only_frames, self.get_current_frame_idx())
                if nearest_mask is not None:
                    anchor_frame = nearest_mask
                    mask_seed_frames = {nearest_mask}
                    frames_with_input = {nearest_mask}
                    self._log_info(
                        "Propagation",
                        f"No point/paint prompts found; using committed mask on frame {nearest_mask + 1} as the seed.",
                    )

            # Ground-truth frames are explicit, first-class mask seeds: they are
            # already anchors (get_prompt_anchor_frames), so they sit in
            # frames_with_input and are protected from overwrite; routing them
            # through mask_seed_frames re-injects their mask as a SAM prompt.
            gt_seed_frames = {idx for idx in in_range if self.state.is_ground_truth_frame(idx)}
            if gt_seed_frames:
                mask_seed_frames = set(mask_seed_frames) | gt_seed_frames
                frames_with_input = set(frames_with_input) | gt_seed_frames

            if not frames_with_input:
                self._log_warn("Propagation", "No valid point prompts, paint edits, or committed masks found in selected range; stopping.")
                return

            if self.is_ui_alive():
                self.root.after(0, lambda f=anchor_frame: self.set_slider_frame(f))
            thresh = float(self.get_sensitivity())

            self._log_info(
                "Propagation",
                f"Started propagation (anchor={anchor_frame + 1}, range={prop_start + 1}-{prop_end + 1}).",
            )
            if self.on_propagation_status is not None:
                self.on_propagation_status("started", int(prop_start), int(prop_end))
            forward_expected = max(0, prop_end - anchor_frame + 1)
            backward_expected = max(0, anchor_frame - prop_start + 1)
            total_expected = forward_expected + backward_expected
            prop_log_run_id = self.prop_log_start(
                total_expected,
                "Propagation",
                prop_start=prop_start,
                prop_end=prop_end,
                anchor=anchor_frame,
            )
            if self.is_ui_alive():
                self.root.after(0, lambda: self.set_status("Propagating...", APP_COLORS["purple"]))

            def cleanup():
                gc.collect()
                torch = _torch_module()
                if torch is not None:
                    if torch.backends.mps.is_available():
                        torch.mps.empty_cache()
                    elif torch.cuda.is_available():
                        torch.cuda.empty_cache()

            cleanup()
            was_stopped = False
            propagated_result_frames = set()

            with self.predictor_lock:
                with io.StringIO() as silent_out, io.StringIO() as silent_err:
                    with contextlib.redirect_stdout(silent_out), contextlib.redirect_stderr(silent_err):
                        if self._is_propagation_cancelled(propagation_generation):
                            was_stopped = True
                        else:
                            self.predictor.reset_state(self.inference_state)
                            sorted_frames = sorted(list(frames_with_input))
                            self._log_info("Propagation", f"Injecting prompts for {len(sorted_frames)} frame(s).")

                            inject_t0 = time.perf_counter()
                            for f_idx in sorted_frames:
                                if not self._wait_if_propagation_paused(propagation_generation):
                                    was_stopped = True
                                    break
                                if self._is_propagation_cancelled(propagation_generation):
                                    was_stopped = True
                                    break
                                has_paint = f_idx in paint_frames
                                has_mask_seed = f_idx in mask_seed_frames

                                if has_paint:
                                    if frame_shape is None:
                                        self._log_warn("Propagation", "Skipping paint prompt injection: invalid frame shape.")
                                        continue
                                    base_mask = np.zeros(frame_shape, dtype=bool)
                                    if f_idx in self.state.masks_cache and self.state.masks_cache[f_idx] is not None:
                                        base_mask = self.state.masks_cache[f_idx].astype(bool)

                                    plus = self.state.paint_layers[f_idx]["plus"]
                                    minus = self.state.paint_layers[f_idx]["minus"]
                                    final_mask = (base_mask | plus) & ~minus

                                    self.predictor.add_new_mask(
                                        inference_state=self.inference_state,
                                        frame_idx=f_idx,
                                        obj_id=1,
                                        mask=final_mask.astype(np.float32),
                                    )
                                    self.state.set_mask(f_idx, final_mask)

                                elif has_mask_seed:
                                    if frame_shape is None:
                                        self._log_warn("Propagation", "Skipping mask prompt injection: invalid frame shape.")
                                        continue
                                    final_mask = self.state.compose_final_mask(
                                        f_idx, frame_shape, apply_persistent_regions=False
                                    )
                                    if final_mask is None or not np.any(final_mask):
                                        self._log_warn("Propagation", f"Skipping frame {f_idx + 1}: empty mask prompt.")
                                        continue
                                    self.predictor.add_new_mask(
                                        inference_state=self.inference_state,
                                        frame_idx=f_idx,
                                        obj_id=1,
                                        mask=np.asarray(final_mask, dtype=np.float32),
                                    )
                                    self.state.set_mask(f_idx, np.asarray(final_mask, dtype=bool))

                                else:
                                    if f_idx not in valid_prompt_frames:
                                        self._log_warn("Propagation", f"Skipping frame {f_idx + 1}: no valid point or box prompts.")
                                        continue
                                    pt_list = list(self.state.points.get(f_idx) or [])
                                    points = None
                                    labels = None
                                    if pt_list:
                                        points = np.array([[p["x"], p["y"]] for p in pt_list], dtype=np.float32)
                                        labels = np.array([p["label"] for p in pt_list], dtype=np.int32)
                                        valid_arrays, reason = self._validate_point_prompt_arrays(points, labels)
                                        if not valid_arrays:
                                            self._log_warn(
                                                "Propagation", f"Skipping frame {f_idx + 1}: invalid point prompt ({reason})."
                                            )
                                            continue
                                    box_arr = self._normalize_box_prompt(f_idx)
                                    if points is None and box_arr is None:
                                        self._log_warn("Propagation", f"Skipping frame {f_idx + 1}: no valid point or box prompts.")
                                        continue
                                    self._add_new_points_or_box_compatible(
                                        frame_idx=f_idx,
                                        points=points,
                                        labels=labels,
                                        box=box_arr,
                                    )

                            inject_ms = (time.perf_counter() - inject_t0) * 1000.0

                            if not was_stopped:
                                forward_generator = self.predictor.propagate_in_video(
                                    self.inference_state, start_frame_idx=anchor_frame, reverse=False
                                )

                                fwd_t0 = time.perf_counter()
                                fwd_tick = fwd_t0
                                forward_done = 0
                                for out_frame_idx, out_obj_ids, out_mask_logits in forward_generator:
                                    now = time.perf_counter()
                                    forward_durations.append((now - fwd_tick) * 1000.0)
                                    fwd_tick = now
                                    if not self._wait_if_propagation_paused(propagation_generation):
                                        was_stopped = True
                                        break
                                    if self._is_propagation_cancelled(propagation_generation):
                                        was_stopped = True
                                        break
                                    if out_frame_idx > prop_end:
                                        break

                                    forward_done += 1
                                    self.prop_log_tick(
                                        run_id=prop_log_run_id,
                                        phase="forward",
                                        direction="forward",
                                        phase_done=forward_done,
                                        phase_total=forward_expected,
                                    )
                                    if len(out_obj_ids) > 0:
                                        if out_frame_idx in frames_with_input:
                                            continue
                                        res_mask = (out_mask_logits[0] > thresh).cpu().numpy().squeeze()
                                        self.state.set_mask(out_frame_idx, res_mask)
                                        propagated_result_frames.add(out_frame_idx)
                                        if out_frame_idx == self.get_current_frame_idx() and self.is_ui_alive():
                                            self.root.after(0, self.update_display)

                                forward_ms = (time.perf_counter() - fwd_t0) * 1000.0

                            if not was_stopped:
                                backward_generator = self.predictor.propagate_in_video(
                                    self.inference_state, start_frame_idx=anchor_frame, reverse=True
                                )

                                bwd_t0 = time.perf_counter()
                                bwd_tick = bwd_t0
                                backward_done = 0
                                for out_frame_idx, out_obj_ids, out_mask_logits in backward_generator:
                                    now = time.perf_counter()
                                    backward_durations.append((now - bwd_tick) * 1000.0)
                                    bwd_tick = now
                                    if not self._wait_if_propagation_paused(propagation_generation):
                                        was_stopped = True
                                        break
                                    if self._is_propagation_cancelled(propagation_generation):
                                        was_stopped = True
                                        break
                                    if out_frame_idx < prop_start:
                                        break

                                    backward_done += 1
                                    self.prop_log_tick(
                                        run_id=prop_log_run_id,
                                        phase="backward",
                                        direction="backward",
                                        phase_done=backward_done,
                                        phase_total=backward_expected,
                                    )
                                    if len(out_obj_ids) > 0:
                                        if out_frame_idx in frames_with_input:
                                            continue
                                        res_mask = (out_mask_logits[0] > thresh).cpu().numpy().squeeze()
                                        self.state.set_mask(out_frame_idx, res_mask)
                                        propagated_result_frames.add(out_frame_idx)
                                        if out_frame_idx == self.get_current_frame_idx() and self.is_ui_alive():
                                            self.root.after(0, self.update_display)

                                backward_ms = (time.perf_counter() - bwd_t0) * 1000.0

            cleanup()
            if was_stopped or self._is_propagation_cancelled(propagation_generation):
                preserve_on_stop = bool(self._preserve_generated_masks_on_stop)
                stop_status = "stopped_preserve" if preserve_on_stop else "stopped"
                self.prop_log_finish("stopped", run_id=prop_log_run_id)
                if self.on_propagation_status is not None:
                    self.on_propagation_status(stop_status, int(prop_start), int(prop_end))
                if self.is_ui_alive():
                    self.root.after(0, self.recompute_markers)
                    self.root.after(0, lambda: self.set_status("Propagation Stopped", APP_COLORS["warning"]))
            else:
                self.prop_log_finish("complete", run_id=prop_log_run_id)
                if self.on_propagation_status is not None:
                    self.on_propagation_status("complete", int(prop_start), int(prop_end))
                if self.is_ui_alive():
                    completed_run_indices = set(range(int(prop_start), int(prop_end) + 1))
                    self.root.after(0, lambda f=completed_run_indices: self.set_propagated_frames(f))
                    self.root.after(0, lambda: self.set_status("Propagation Complete", APP_COLORS["success"]))

        except Exception as e:
            handled_oom = self._recover_from_accelerator_oom("Propagation", e)
            self.prop_log_finish("failed", run_id=prop_log_run_id)
            if self.on_propagation_status is not None:
                self.on_propagation_status("failed", int(prop_start), int(prop_end))
            if self.is_ui_alive():
                self.root.after(0, self.recompute_markers)
                if handled_oom:
                    self.root.after(0, lambda: self.set_status("Switched to CPU Fallback", APP_COLORS["warning"]))
                else:
                    self.root.after(0, lambda: self.set_status("Propagation Error", APP_COLORS["danger"]))
            if handled_oom:
                self._log_warn("Propagation", "Propagation stopped after accelerator OOM; CPU fallback is now active.")
                if self.is_ui_alive():
                    self.root.after(0, lambda: messagebox.showwarning("Inference Fallback", "GPU Out of Memory during propagation. Switching to CPU fallback."))
            else:
                err = InferenceRuntimeError(str(e))
                self._log_error("Propagation", f"Propagation failed: {err}")
                if self.is_ui_alive():
                    self.root.after(0, lambda: messagebox.showerror("Inference Error", f"Propagation failed:\n\n{err}"))
                import traceback

                traceback.print_exc()
        finally:
            elapsed_ms = (time.perf_counter() - start_ts) * 1000.0

            def _per_frame(total_ms: float, durations: list[float]) -> str:
                # Drop the first sample: it includes generator setup, not frame work.
                samples = durations[1:] if len(durations) > 1 else durations
                count = len(samples)
                if count == 0:
                    return "0 frames"
                avg = sum(samples) / count
                growth = ""
                if count >= 6:
                    third = count // 3
                    head = sum(samples[:third]) / third
                    tail = sum(samples[-third:]) / third
                    if head > 0:
                        growth = f" growth={tail / head:.2f}x"
                return f"{count} frames {total_ms:.0f}ms ({avg:.1f}ms/frame{growth})"

            self._log_debug(
                "Perf",
                (
                    f"Propagation run elapsed={elapsed_ms:.1f}ms "
                    f"inject={inject_ms:.0f}ms "
                    f"forward=[{_per_frame(forward_ms, forward_durations)}] "
                    f"backward=[{_per_frame(backward_ms, backward_durations)}] "
                    f"restart_waits={self._prop_restart_wait_count} "
                    f"stale_skips={self._infer_stale_skip_count} "
                    f"max_queue_depth={self._infer_max_queue_depth}"
                ),
            )
            with self._prop_thread_lock:
                if self.propagate_thread is threading.current_thread():
                    self.propagate_thread = None
                if self.propagate_thread is None:
                    self._prop_pause_event.clear()
                    self._preserve_generated_masks_on_stop = False
                if self._prop_start_retry_job is not None and self.is_ui_alive():
                    try:
                        self.root.after_cancel(self._prop_start_retry_job)
                    except Exception as exc:
                        self._log_debug("Propagation", f"Retry cancel skipped: {exc}")
                    self._prop_start_retry_job = None
