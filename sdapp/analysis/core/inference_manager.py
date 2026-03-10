from __future__ import annotations

import contextlib
import gc
import io
import queue
import threading
import time
from typing import Callable, Optional

import numpy as np
import torch

from sdapp.analysis.core.seg_state import SegmentationState


class InferenceManager:
    def __init__(
        self,
        state: SegmentationState,
        root,
        predictor_lock,
        get_sensitivity: Callable[[], float],
        get_current_frame_idx: Callable[[], int],
        get_frames_raw: Callable[[], Optional[np.ndarray]],
        set_slider_frame: Callable[[int], None],
        update_display: Callable[[], None],
        recompute_markers: Callable[[], None],
        set_propagated_frames: Callable[[set[int]], None],
        set_status: Callable[[str, str], None],
        prop_log_start: Callable[[int, str], int],
        prop_log_tick: Callable[..., None],
        prop_log_finish: Callable[..., None],
        on_propagation_status: Callable[[str, int, int], None] | None,
        log: Callable[[str, str, str], None],
        is_ui_alive: Callable[[], bool],
    ):
        self.state = state
        self.root = root
        self.predictor_lock = predictor_lock

        self.get_sensitivity = get_sensitivity
        self.get_current_frame_idx = get_current_frame_idx
        self.get_frames_raw = get_frames_raw
        self.set_slider_frame = set_slider_frame
        self.update_display = update_display
        self.recompute_markers = recompute_markers
        self.set_propagated_frames = set_propagated_frames
        self.set_status = set_status
        self.prop_log_start = prop_log_start
        self.prop_log_tick = prop_log_tick
        self.prop_log_finish = prop_log_finish
        self.on_propagation_status = on_propagation_status
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

        self.propagate_thread = None
        self._prop_stop_event = threading.Event()
        self._prop_thread_lock = threading.Lock()
        self._active_propagation_generation = 0
        self._prop_start_retry_job = None
        self._prop_restart_wait_count = 0

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

    def _inference_queue_depth(self):
        try:
            return int(self._infer_queue.qsize())
        except Exception:
            return 0

    def _is_propagation_cancelled(self, generation):
        return self._prop_stop_event.is_set() or generation != self._active_propagation_generation

    def _notify_mask_updated(self):
        if self.is_ui_alive():
            self.root.after(0, self.recompute_markers)
            self.root.after(0, self.update_display)

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

    def _stop_propagation_thread(self, clear_event=False, timeout=1.0):
        with self._prop_thread_lock:
            self._prop_stop_event.set()
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

    def enqueue_pending_point_frames(self, frame_indices):
        if not self.model_ready:
            return
        frames = sorted(list(frame_indices))
        if not frames:
            return
        self._log_info("Model", f"Processing {len(frames)} frame(s) with pending points.")
        for frame_idx in frames:
            self.enqueue_frame_inference(frame_idx, reason="pending_points")

    def enqueue_frame_inference(self, frame_idx, reason="update"):
        self.state.prune_invalid_points()

        if not self.model_ready or self.predictor is None or self.inference_state is None:
            return

        valid_frames = self.state.get_valid_point_frames()
        if frame_idx not in valid_frames:
            self.state.clear_mask(frame_idx)
            self._notify_mask_updated()
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
        self.enqueue_frame_inference(frame_idx, reason="sensitivity")

    def _inference_worker_loop(self):
        while not self._infer_worker_stop.is_set():
            try:
                item = self._infer_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if item is None:
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
                with self._infer_state_lock:
                    self._infer_pending_frames.discard(frame_idx)
                try:
                    self._infer_queue.task_done()
                except Exception as exc:
                    self._log_debug("Model", f"Queue task_done skipped: {exc}")

    def _run_single_frame_inference_core(self, frame_idx, generation):
        self.state.prune_invalid_points()
        valid_frames = self.state.get_valid_point_frames()
        if frame_idx not in valid_frames:
            return
        if not self.model_ready or self.predictor is None or self.inference_state is None:
            return

        try:
            with self.predictor_lock:
                if self._infer_worker_stop.is_set() or self._prop_stop_event.is_set():
                    return
                self.predictor.reset_state(self.inference_state)
                pt_list = self.state.points[frame_idx]
                points = np.array([[p["x"], p["y"]] for p in pt_list], dtype=np.float32)
                labels = np.array([p["label"] for p in pt_list], dtype=np.int32)
                valid_arrays, reason = self._validate_point_prompt_arrays(points, labels)
                if not valid_arrays:
                    self._log_warn("Model", f"Skipping inference prompt on frame {frame_idx + 1}: {reason}.")
                    return

                _, _, out_mask_logits = self.predictor.add_new_points_or_box(
                    inference_state=self.inference_state,
                    frame_idx=frame_idx,
                    obj_id=1,
                    points=points,
                    labels=labels,
                    clear_old_points=True,
                )

            with self._infer_state_lock:
                latest_generation = self._infer_frame_generation.get(frame_idx)
            if latest_generation != generation:
                with self._infer_state_lock:
                    self._infer_stale_skip_count += 1
                return

            thresh = float(self.get_sensitivity())
            self.state.set_mask(frame_idx, (out_mask_logits[0] > thresh).cpu().numpy().squeeze())
            self._notify_mask_updated()
        except Exception as e:
            self._log_error("Model", f"Inference failed on frame {frame_idx + 1}: {e}")

    def trigger_propagation(self, prop_start, prop_end, anchor_frame):
        if self._prop_start_retry_job is not None and self.is_ui_alive():
            try:
                self.root.after_cancel(self._prop_start_retry_job)
            except Exception as exc:
                self._log_debug("Propagation", f"Retry cancel skipped: {exc}")
            self._prop_start_retry_job = None

        with self._prop_thread_lock:
            if self.propagate_thread is not None and self.propagate_thread.is_alive():
                self._prop_stop_event.set()
                self._prop_restart_wait_count += 1
                self._log_debug("Propagation", "Waiting for existing propagation thread to stop before restart.")
                if self._prop_start_retry_job is None and self.is_ui_alive():
                    self._prop_start_retry_job = self.root.after(
                        75,
                        lambda s=prop_start, e=prop_end, a=anchor_frame: self.trigger_propagation(s, e, a),
                    )
                return

            self._prop_stop_event.clear()
            self._active_propagation_generation += 1
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
        try:
            if self._is_propagation_cancelled(propagation_generation):
                return
            self.state.prune_invalid_points()
            if self.is_ui_alive():
                self.root.after(0, lambda: self.set_status("Propagating...", "purple"))

            frames_raw = self.get_frames_raw()
            if frames_raw is None or len(frames_raw) == 0:
                return
            total_frames = len(frames_raw)
            prop_start = max(0, min(int(prop_start), total_frames - 1))
            prop_end = max(0, min(int(prop_end), total_frames - 1))
            anchor_frame = max(prop_start, min(int(anchor_frame), prop_end))
            in_range = range(prop_start, prop_end + 1)

            def frame_has_mask_or_paint(idx):
                if idx in self.state.masks_cache and self.state.masks_cache[idx] is not None and np.any(self.state.masks_cache[idx]):
                    return True
                return self.state.has_nonempty_paint(idx)

            if not frame_has_mask_or_paint(anchor_frame):
                candidates = [i for i in in_range if frame_has_mask_or_paint(i)]
                if candidates:
                    anchor_frame = min(candidates, key=lambda i: abs(i - self.get_current_frame_idx()))
                    if self.is_ui_alive():
                        self.root.after(0, lambda f=anchor_frame: self.set_slider_frame(f))

            point_frames = {idx for idx in in_range if idx in self.state.get_valid_point_frames()}
            paint_frames = {idx for idx in in_range if self.state.has_nonempty_paint(idx)}
            frames_with_input = point_frames | paint_frames
            if not frames_with_input:
                self._log_warn("Propagation", "No valid point/paint prompts found in selected range; stopping.")
                return
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
            prop_log_run_id = self.prop_log_start(total_expected, "Propagation")

            def cleanup():
                gc.collect()
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
                            return
                        self.predictor.reset_state(self.inference_state)
                        sorted_frames = sorted(list(frames_with_input))
                        self._log_info("Propagation", f"Injecting prompts for {len(sorted_frames)} frame(s).")

                        for f_idx in sorted_frames:
                            if self._is_propagation_cancelled(propagation_generation):
                                break
                            has_paint = f_idx in paint_frames

                            if has_paint:
                                base_mask = np.zeros_like(frames_raw[0], dtype=bool)
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

                            else:
                                if f_idx not in self.state.get_valid_point_frames():
                                    self._log_warn("Propagation", f"Skipping frame {f_idx + 1}: no valid point prompts.")
                                    continue
                                pt_list = self.state.points[f_idx]
                                points = np.array([[p["x"], p["y"]] for p in pt_list], dtype=np.float32)
                                labels = np.array([p["label"] for p in pt_list], dtype=np.int32)
                                valid_arrays, reason = self._validate_point_prompt_arrays(points, labels)
                                if not valid_arrays:
                                    self._log_warn(
                                        "Propagation", f"Skipping frame {f_idx + 1}: invalid point prompt ({reason})."
                                    )
                                    continue
                                self.predictor.add_new_points_or_box(
                                    inference_state=self.inference_state,
                                    frame_idx=f_idx,
                                    obj_id=1,
                                    points=points,
                                    labels=labels,
                                )

                        forward_generator = self.predictor.propagate_in_video(
                            self.inference_state, start_frame_idx=anchor_frame, reverse=False
                        )

                        for out_frame_idx, out_obj_ids, out_mask_logits in forward_generator:
                            if self._is_propagation_cancelled(propagation_generation):
                                was_stopped = True
                                break
                            if out_frame_idx > prop_end:
                                break

                            self.prop_log_tick(run_id=prop_log_run_id)
                            if len(out_obj_ids) > 0:
                                if out_frame_idx in frames_with_input:
                                    continue
                                res_mask = (out_mask_logits[0] > thresh).cpu().numpy().squeeze()
                                self.state.set_mask(out_frame_idx, res_mask)
                                propagated_result_frames.add(out_frame_idx)
                                if out_frame_idx == self.get_current_frame_idx() and self.is_ui_alive():
                                    self.root.after(0, self.update_display)

                        if not was_stopped:
                            backward_generator = self.predictor.propagate_in_video(
                                self.inference_state, start_frame_idx=anchor_frame, reverse=True
                            )

                            for out_frame_idx, out_obj_ids, out_mask_logits in backward_generator:
                                if self._is_propagation_cancelled(propagation_generation):
                                    was_stopped = True
                                    break
                                if out_frame_idx < prop_start:
                                    break

                                self.prop_log_tick(run_id=prop_log_run_id)
                                if len(out_obj_ids) > 0:
                                    if out_frame_idx in frames_with_input:
                                        continue
                                    res_mask = (out_mask_logits[0] > thresh).cpu().numpy().squeeze()
                                    self.state.set_mask(out_frame_idx, res_mask)
                                    propagated_result_frames.add(out_frame_idx)
                                    if out_frame_idx == self.get_current_frame_idx() and self.is_ui_alive():
                                        self.root.after(0, self.update_display)

            cleanup()
            if was_stopped or self._is_propagation_cancelled(propagation_generation):
                self.prop_log_finish("stopped", run_id=prop_log_run_id)
                if self.on_propagation_status is not None:
                    self.on_propagation_status("stopped", int(prop_start), int(prop_end))
                if self.is_ui_alive():
                    self.root.after(0, self.recompute_markers)
                    self.root.after(0, lambda: self.set_status("Propagation Stopped", "orange"))
            else:
                self.prop_log_finish("complete", run_id=prop_log_run_id)
                if self.on_propagation_status is not None:
                    self.on_propagation_status("complete", int(prop_start), int(prop_end))
                if self.is_ui_alive():
                    completed_run_indices = set(range(int(prop_start), int(prop_end) + 1))
                    self.root.after(0, lambda f=completed_run_indices: self.set_propagated_frames(f))
                    self.root.after(0, lambda: self.set_status("Propagation Complete", "green"))

        except Exception as e:
            self.prop_log_finish("failed", run_id=prop_log_run_id)
            if self.on_propagation_status is not None:
                self.on_propagation_status("failed", int(prop_start), int(prop_end))
            if self.is_ui_alive():
                self.root.after(0, self.recompute_markers)
                self.root.after(0, lambda: self.set_status("Propagation Error", "red"))
            self._log_error("Propagation", f"Propagation failed: {e}")
            import traceback

            traceback.print_exc()
        finally:
            elapsed_ms = (time.perf_counter() - start_ts) * 1000.0
            self._log_debug(
                "Perf",
                (
                    f"Propagation run elapsed={elapsed_ms:.1f}ms "
                    f"restart_waits={self._prop_restart_wait_count} "
                    f"stale_skips={self._infer_stale_skip_count} "
                    f"max_queue_depth={self._infer_max_queue_depth}"
                ),
            )
            with self._prop_thread_lock:
                if self.propagate_thread is threading.current_thread():
                    self.propagate_thread = None
                if self._prop_start_retry_job is not None and self.is_ui_alive():
                    try:
                        self.root.after_cancel(self._prop_start_retry_job)
                    except Exception as exc:
                        self._log_debug("Propagation", f"Retry cancel skipped: {exc}")
                    self._prop_start_retry_job = None
