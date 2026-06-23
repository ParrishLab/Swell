from __future__ import annotations

from typing import Any

import numpy as np

from swell.host.processing_engine import PopupProcessRequest, PopupProcessResult
from swell.host.ui_geometry import adjust_baseline_end_for_start
from swell.shared.ui import dialogs as messagebox


class PopupProcessingController:
    """Own popup baseline parsing, async recompute jobs, and processed-frame cache."""

    def __init__(self, app: Any, owner: Any) -> None:
        self.app = app
        self.owner = owner

    def parse_baseline_controls(self) -> tuple[int, int]:
        if self.app.stack_info is None:
            raise RuntimeError("No stack loaded.")
        frame_count = int(self.app.stack_info.frame_count)
        count_raw = (
            self.app._popup.mark_baseline_count_var.get().strip()
            if self.app._popup.mark_baseline_count_var is not None
            else "30"
        )
        end_raw = (
            self.app._popup.mark_baseline_end_var.get().strip()
            if self.app._popup.mark_baseline_end_var is not None
            else "0"
        )
        try:
            baseline_count = int(float(count_raw))
        except ValueError as exc:
            raise ValueError("Baseline Count must be a frame number.") from exc
        try:
            baseline_end = int(float(end_raw))
        except ValueError as exc:
            raise ValueError("Baseline End must be a frame number.") from exc
        if baseline_count < 1:
            raise ValueError("Baseline Count must be >= 1.")
        baseline_end = max(0, min(baseline_end, frame_count - 1))
        return baseline_count, baseline_end

    def auto_adjust_baseline_from_start(self, force_match_start: bool = False) -> bool:
        if self.app.stack_info is None or self.app._popup.mark_start_var is None:
            return False
        if self.app._popup.mark_baseline_count_var is None or self.app._popup.mark_baseline_end_var is None:
            return False
        start_raw = self.app._popup.mark_start_var.get().strip()
        if not start_raw:
            return False
        try:
            start_idx = int(float(start_raw))
            baseline_end = int(float(self.app._popup.mark_baseline_end_var.get().strip()))
        except ValueError:
            return False

        frame_count = int(self.app.stack_info.frame_count)
        if frame_count <= 0:
            return False
        next_end, changed = adjust_baseline_end_for_start(
            start_idx,
            frame_count,
            baseline_end,
            force_match_start=force_match_start,
        )
        if changed:
            self.app._popup.mark_baseline_end_var.set(str(next_end))
            return True
        return False

    def set_loading(self, loading: bool, text: str = "Loading...") -> None:
        if (
            self.app._popup.mark_loading_var is None
            or self.app._popup.mark_loading_label is None
            or self.app._popup.mark_loading_bar is None
        ):
            return
        if loading:
            self.app._popup.mark_loading_var.set(text)
            if not self.app._popup.mark_loading_label.winfo_ismapped():
                self.app._popup.mark_loading_label.pack(anchor="w", pady=(0, 2))
            if not self.app._popup.mark_loading_bar.winfo_ismapped():
                self.app._popup.mark_loading_bar.pack(fill="x", pady=(0, 4))
            self.app._popup.mark_loading_bar.start(8)
            if self.app._popup.mark_popup is not None and self.app._popup.mark_popup.winfo_exists():
                self.app._popup.mark_popup.update_idletasks()
        else:
            self.app._popup.mark_loading_bar.stop()
            if self.app._popup.mark_loading_bar.winfo_ismapped():
                self.app._popup.mark_loading_bar.pack_forget()
            if self.app._popup.mark_loading_label.winfo_ismapped():
                self.app._popup.mark_loading_label.pack_forget()
            self.app._popup.mark_loading_var.set("")

    def refresh_full_sequence(self) -> None:
        if self.app.stack_info is None:
            return
        range_start, range_end = self.app._popup_overlay_bounds()
        ok = self.recompute_pipeline_for_bounds(
            range_start,
            range_end,
            show_errors=True,
            loading_text="Refreshing current sequence...",
        )
        if ok:
            self.app._popup.mark_last_full_refresh_note = " | Current sequence refreshed"
            self.owner.update_window_info()

    def recompute_pipeline_for_bounds(
        self,
        range_start: int,
        range_end: int,
        show_errors: bool = True,
        loading_text: str = "Computing popup sequence...",
        fast_mode: bool = False,
        normalization_range_start: int | None = None,
        normalization_range_end: int | None = None,
    ) -> bool:
        if self.app._popup.mark_popup is None or not self.app._popup.mark_popup.winfo_exists() or self.app.stack_info is None:
            return False
        try:
            baseline_count, baseline_end = self.parse_baseline_controls()
        except Exception as exc:
            if show_errors:
                self.app._log_warn(f"Popup recompute failed: {exc}")
                messagebox.showwarning("Mark Event", str(exc), parent=self.app.root)
            return False
        self.app._popup.popup_job_seq += 1
        job_id = int(self.app._popup.popup_job_seq)
        self.app._popup.popup_active_job_id = job_id
        self.set_loading(True, loading_text)
        req = PopupProcessRequest(
            job_id=job_id,
            range_start=int(range_start),
            range_end=int(range_end),
            baseline_count=int(baseline_count),
            baseline_end=int(baseline_end),
            current_idx=int(self.app._popup.mark_popup_current_idx),
            warm_radius=4 if fast_mode else 10,
            sample_stride=9 if fast_mode else 5,
            norm_range_start=None if normalization_range_start is None else int(normalization_range_start),
            norm_range_end=None if normalization_range_end is None else int(normalization_range_end),
        )

        def done(result: PopupProcessResult | None, error: Exception | None) -> None:
            self.app.root.after(0, lambda: self.on_process_result(job_id, result, error, show_errors))

        self.app._popup.engine.submit_popup_job(req, done)
        return True

    def on_process_result(
        self,
        job_id: int,
        result: PopupProcessResult | None,
        error: Exception | None,
        show_errors: bool,
    ) -> None:
        if self.app._popup.mark_popup is None or not self.app._popup.mark_popup.winfo_exists():
            return
        if int(job_id) != int(self.app._popup.popup_active_job_id):
            return

        self.set_loading(False)

        if error is not None:
            self.app._log_warn(f"Popup recompute failed: {error}")
            if show_errors:
                messagebox.showwarning("Mark Event", str(error), parent=self.app.root)
            return
        if result is None:
            return

        self.app._popup.mark_baseline_frame = result.baseline_frame
        self.app._popup.mark_norm_p1 = float(result.p1)
        self.app._popup.mark_norm_p99 = float(result.p99)
        self.app._popup.mark_processed_cache.clear()
        for idx in sorted(result.warmed_frames.keys()):
            self.cache_processed_frame(idx, result.warmed_frames[idx])

        t = result.timings_ms
        self.app._log_info(
            "Popup recompute timings (ms): "
            f"baseline={t.get('baseline', 0.0):.1f}, norm={t.get('norm', 0.0):.1f}, "
            f"warm={t.get('warm', 0.0):.1f}, total={t.get('total', 0.0):.1f}."
        )
        self.owner.update_window_info()
        self.owner.update_preview(self.app._popup.mark_popup_current_idx)

    def schedule_recompute(
        self,
        show_errors: bool = False,
        delay_ms: int = 1400,
        align_baseline_to_start: bool = False,
    ) -> None:
        if self.app._popup.mark_popup is None or not self.app._popup.mark_popup.winfo_exists():
            return
        adjusted = self.auto_adjust_baseline_from_start(force_match_start=align_baseline_to_start)
        if adjusted:
            self.owner.redraw_overlay()
        if show_errors:
            self.app._popup.mark_recompute_show_errors = True
        if self.app._popup.mark_recompute_after_id is not None:
            try:
                self.app._popup.mark_popup.after_cancel(self.app._popup.mark_recompute_after_id)
            except Exception:
                pass
        self.app._popup.mark_recompute_after_id = self.app._popup.mark_popup.after(
            max(1000, int(delay_ms)), self.run_scheduled_recompute
        )

    def run_scheduled_recompute(self) -> None:
        show_errors = bool(self.app._popup.mark_recompute_show_errors)
        self.app._popup.mark_recompute_show_errors = False
        self.app._popup.mark_recompute_after_id = None
        self.recompute_pipeline(show_errors=show_errors)

    def recompute_pipeline(self, show_errors: bool = True) -> bool:
        if self.app._popup.mark_popup is None or not self.app._popup.mark_popup.winfo_exists() or self.app.stack_info is None:
            return False
        adjusted = self.auto_adjust_baseline_from_start(force_match_start=False)
        if adjusted:
            self.owner.redraw_overlay()
        if self.app._popup.mark_recompute_after_id is not None:
            try:
                self.app._popup.mark_popup.after_cancel(self.app._popup.mark_recompute_after_id)
            except Exception:
                pass
            self.app._popup.mark_recompute_after_id = None
        self.app._popup.mark_recompute_show_errors = False

        range_start, range_end = self.app._popup_overlay_bounds()
        self.app._popup.mark_last_full_refresh_note = ""
        return self.recompute_pipeline_for_bounds(
            range_start,
            range_end,
            show_errors=show_errors,
            fast_mode=not show_errors,
        )

    def get_processed_frame(self, frame_idx: int) -> np.ndarray:
        if self.app.reader is None:
            raise RuntimeError("Stack not loaded.")

        if self.app._popup.mark_baseline_frame is None:
            raw = self.app.reader.read_frame(frame_idx, use_cache=True)
            return self.app._normalize_frame_percentile(raw)

        if frame_idx in self.app._popup.mark_processed_cache:
            return self.app._popup.mark_processed_cache.promote(frame_idx)

        frame_u8 = self.app._popup.engine.get_processed_frame(
            frame_idx,
            self.app._popup.mark_baseline_frame,
            self.app._popup.mark_norm_p1,
            self.app._popup.mark_norm_p99,
        )
        self.cache_processed_frame(frame_idx, frame_u8)
        return frame_u8

    def cache_processed_frame(self, frame_idx: int, frame_u8: np.ndarray) -> None:
        self.app._popup.mark_processed_cache[int(frame_idx)] = frame_u8
