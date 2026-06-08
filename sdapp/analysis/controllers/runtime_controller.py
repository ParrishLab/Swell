from __future__ import annotations

import time

from sdapp.shared.ui import BackgroundTaskRunner


class AnalysisRuntimeController:
    def __init__(self, app) -> None:
        self.app = app

    def _set_propagation_button_state(self, running: bool, paused: bool = False) -> None:
        run_button = getattr(self.app, "btn_run_propagation", None)
        pause_button = getattr(self.app, "btn_pause_propagation", None)
        resume_button = getattr(self.app, "btn_resume_propagation", None)
        stop_button = getattr(self.app, "btn_stop_propagation", None)
        can_run = bool(not running and self.app._has_loaded_stack())
        try:
            if run_button is not None:
                run_button.configure(
                    text="Running…" if running else "Run Propagation",
                    state="disabled" if running else ("normal" if can_run else "disabled"),
                )
            if pause_button is not None:
                pause_button.configure(state="normal" if running and not paused else "disabled")
            if resume_button is not None:
                resume_button.configure(state="normal" if running and paused else "disabled")
            if stop_button is not None:
                stop_button.configure(state="normal" if running else "disabled")
        except Exception:
            return

    def sync_propagation_button_state(self) -> None:
        manager = getattr(self.app, "inference_manager", None)
        running = bool(manager is not None and manager.is_propagation_running())
        paused = bool(manager is not None and manager.is_propagation_paused())
        self._set_propagation_button_state(running, paused)

    def set_runtime_status(self, text: str, color: str) -> None:
        del color
        status = str(text or "")
        if "Propagating" in status:
            self.app._set_activity_message(status)
            self._set_propagation_button_state(True, False)
            return
        if status == "Propagation Paused":
            self.app._set_activity_message(status)
            self._set_propagation_button_state(True, True)
            return
        if status == "Stopping Propagation...":
            self.app._set_activity_message(status)
            self._set_propagation_button_state(True, False)
            return
        if status in {"Propagation Complete", "Propagation Stopped", "Propagation Error"}:
            self.app._propagation_progress_active = False
            self.app._set_activity_message(status)
            self._set_propagation_button_state(False)
            if self.app._loading_task_count <= 0 and hasattr(self.app, "loading_bar"):
                self.app.loading_bar.stop()
                if self.app.loading_bar.winfo_ismapped():
                    self.app.loading_bar.grid_remove()
            return
        self.app._set_activity_message(status)

    def set_busy(self, is_busy, status_text, color) -> None:
        self.app.lbl_status.configure(text=status_text, foreground=color)
        self.app._set_loading_indicator(bool(is_busy), str(status_text).replace("Status:", "").strip() or "Working...")
        if not is_busy:
            self.sync_propagation_button_state()
        if hasattr(self.app, "btn_save_masks"):
            if is_busy:
                self.app.btn_save_masks.configure(state="disabled")
            else:
                self.app.btn_save_masks.configure(state="normal" if self.app._has_loaded_stack() else "disabled")

    def run_thread(self, target, *, loading_text: str = "Working..."):
        self.app._begin_loading_task(loading_text)

        def _run():
            target()
            return None

        def _finish(_result) -> None:
            if self.app._ui_alive():
                self.app._end_loading_task()

        self._task_runner().start(
            _run,
            on_success=_finish,
            on_error=lambda _exc: _finish(None),
        )

    def queue_display_update(self, update_preview: bool = True) -> None:
        self.app._pending_display_preview = bool(self.app._pending_display_preview or update_preview)
        if self.app._pending_display_update:
            return
        self.app._pending_display_update = True

        def _flush() -> None:
            preview = bool(self.app._pending_display_preview)
            self.app._pending_display_update = False
            self.app._pending_display_preview = True
            self.app.update_display(update_preview=preview)

        if self.app._ui_alive():
            self.app.root.after(0, _flush)

    def schedule_analysis_prewarm(self, current_idx: int | None = None) -> None:
        frame_source = getattr(self.app, "frame_source", None)
        if frame_source is None or not callable(getattr(frame_source, "prewarm", None)):
            return
        frame_count = int(self.app._get_frame_count())
        if frame_count <= 0:
            return
        idx = int(self.app.current_frame_idx if current_idx is None else current_idx)
        idx = max(0, min(idx, frame_count - 1))
        radius = max(1, int(getattr(self.app, "_analysis_prewarm_window", 4) or 4))
        prev_idx = getattr(self.app, "_last_prewarm_frame_idx", None)
        self.app._last_prewarm_frame_idx = idx
        if prev_idx is None:
            lo = max(0, idx - radius)
            hi = min(frame_count - 1, idx + radius)
        elif idx >= int(prev_idx):
            lo = max(0, idx - radius // 2)
            hi = min(frame_count - 1, idx + radius)
        else:
            lo = max(0, idx - radius)
            hi = min(frame_count - 1, idx + radius // 2)
        indices = list(range(lo, hi + 1))
        generation = int(getattr(self.app, "_analysis_prewarm_generation", 0) or 0) + 1
        self.app._analysis_prewarm_generation = generation

        def _run():
            started = time.perf_counter()
            if int(getattr(self.app, "_analysis_prewarm_generation", 0) or 0) != generation:
                return None
            frame_source.prewarm(
                indices,
                generation=generation,
                should_continue=lambda: int(getattr(self.app, "_analysis_prewarm_generation", 0) or 0) == generation,
            )
            if int(getattr(self.app, "_analysis_prewarm_generation", 0) or 0) != generation:
                return None
            return {
                "elapsed_ms": (time.perf_counter() - started) * 1000.0,
                "center": idx + 1,
                "count": len(indices),
                "generation": generation,
            }

        def _on_success(result) -> None:
            if not isinstance(result, dict):
                return
            self.app.log_debug(
                "Perf",
                f"Analysis prewarm elapsed={result['elapsed_ms']:.1f}ms "
                f"center={result['center']} frames={result['count']} generation={result['generation']}",
            )

        def _on_error(exc: Exception) -> None:
            self.app.log_debug("Perf", f"Analysis prewarm skipped: {exc}")

        self.app._analysis_prewarm_thread = self._task_runner().start(_run, on_success=_on_success, on_error=_on_error)

    def _task_runner(self) -> BackgroundTaskRunner:
        runner = getattr(self.app, "_background_task_runner", None)
        if isinstance(runner, BackgroundTaskRunner):
            return runner
        runner = BackgroundTaskRunner(getattr(self.app, "root", None))
        self.app._background_task_runner = runner
        return runner
