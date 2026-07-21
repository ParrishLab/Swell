from __future__ import annotations

from typing import Any


class PopupPreviewController:
    """Own popup frame navigation, preview debounce, contrast, and mini-preview resize."""

    def __init__(self, app: Any, processing_controller: Any | None = None) -> None:
        self.app = app
        self.processing_controller = processing_controller

    def step(self, delta: int) -> None:
        if self.app.stack_info is None or self.app._popup.mark_scale is None:
            return
        low, high = self.app._popup_overlay_bounds()
        idx = max(low, min(self.app._popup.mark_popup_current_idx + int(delta), high))
        self.app._popup.mark_scale.set(idx)
        self.update_preview(idx)

    def on_slide(self, value: str) -> None:
        idx = int(float(value))
        self.schedule_preview_update(idx)

    def schedule_preview_update(self, idx: int) -> None:
        if self.app._popup.mark_popup is None or not self.app._popup.mark_popup.winfo_exists():
            return
        self.app._popup.pending_popup_frame_idx = int(idx)
        if self.app._popup.pending_popup_after_id is not None:
            try:
                self.app._popup.mark_popup.after_cancel(self.app._popup.pending_popup_after_id)
            except Exception:
                pass
        self.app._popup.pending_popup_after_id = self.app._popup.mark_popup.after(16, self.flush_preview_update)

    def flush_preview_update(self) -> None:
        self.app._popup.pending_popup_after_id = None
        if self.app._popup.pending_popup_frame_idx is None:
            return
        idx = int(self.app._popup.pending_popup_frame_idx)
        self.app._popup.pending_popup_frame_idx = None
        self.update_preview(idx)
        self.redraw_overlay()

    def set_start_current(self) -> None:
        if self.app._popup.mark_start_var is None:
            return
        idx = int(self.app._popup.mark_popup_current_idx)
        self.app._popup.mark_start_var.set(str(idx + 1))
        if self.app._popup.mark_end_var is not None:
            try:
                end_val = int(float(self.app._popup.mark_end_var.get().strip())) - 1
                if idx > end_val:
                    self.app._popup.mark_end_var.set(str(idx + 1))
            except ValueError:
                pass
        self.redraw_overlay()
        if self.processing_controller is not None:
            self.processing_controller.schedule_recompute(align_baseline_to_start=True)

    def set_end_current(self) -> None:
        if self.app._popup.mark_end_var is None:
            return
        idx = int(self.app._popup.mark_popup_current_idx)
        self.app._popup.mark_end_var.set(str(idx + 1))
        if self.app._popup.mark_start_var is not None:
            try:
                start_val = int(float(self.app._popup.mark_start_var.get().strip())) - 1
                if idx < start_val:
                    self.app._popup.mark_start_var.set(str(idx + 1))
            except ValueError:
                pass
        self.redraw_overlay()

    def on_contrast_change(self, value: str) -> None:
        try:
            factor = float(value)
        except ValueError:
            factor = float(self.app._popup.mark_contrast_var.get()) if self.app._popup.mark_contrast_var is not None else 1.0
        factor = max(0.5, min(3.0, factor))
        if abs(factor - 1.0) <= 0.05:
            factor = 1.0
        if self.app._popup.mark_contrast_var is not None:
            self.app._popup.mark_contrast_var.set(factor)
        if self.app._popup.mark_contrast_label_var is not None:
            self.app._popup.mark_contrast_label_var.set(f"Contrast: {factor:.2f}x")
        self.update_preview(self.app._popup.mark_popup_current_idx)

    def start_resize_mini(self, event) -> None:
        if self.app._popup.mark_mini_frame is None:
            return
        self.app._popup.mark_resize_start_x = event.x_root
        self.app._popup.mark_resize_start_y = event.y_root
        self.app._popup.mark_resize_start_w = self.app._popup.mark_mini_frame.winfo_width()
        self.app._popup.mark_resize_start_h = self.app._popup.mark_mini_frame.winfo_height()

    def do_resize_mini(self, event) -> None:
        if self.app._popup.mark_mini_frame is None or self.app._popup.mark_resize_start_x is None:
            return
        dx = self.app._popup.mark_resize_start_x - event.x_root
        dy = event.y_root - self.app._popup.mark_resize_start_y
        delta = max(dx, dy)
        base_w = (
            self.app._popup.mark_resize_start_w
            if self.app._popup.mark_resize_start_w is not None
            else self.app._popup.mark_mini_frame.winfo_width()
        )
        base_h = (
            self.app._popup.mark_resize_start_h
            if self.app._popup.mark_resize_start_h is not None
            else self.app._popup.mark_mini_frame.winfo_height()
        )
        new_size = max(70, min(450, max(base_w, base_h) + delta))
        self.app._popup.mark_mini_frame.configure(width=new_size, height=new_size)
        self.app._popup.mark_mini_frame.update_idletasks()
        self.update_mini_raw(self.app._popup.mark_popup_current_idx)

    def stop_resize_mini(self, _event) -> None:
        self.app._popup.mark_resize_start_x = None
        self.app._popup.mark_resize_start_y = None
        self.app._popup.mark_resize_start_w = None
        self.app._popup.mark_resize_start_h = None
        self.update_mini_raw(self.app._popup.mark_popup_current_idx)

    def update_mini_raw(self, frame_idx: int) -> None:
        self.app._get_preview_controller().update_popup_mini_raw(frame_idx)

    def update_window_info(self) -> None:
        self.app._get_preview_controller().popup_update_window_info()

    def update_preview(self, frame_idx: int) -> None:
        self.app._get_preview_controller().popup_update_preview(frame_idx)

    def redraw_overlay(self) -> None:
        self.app._get_preview_controller().redraw_popup_overlay()
