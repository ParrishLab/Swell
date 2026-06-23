from __future__ import annotations

import tkinter as tk
from typing import Any

from swell.host.ui_geometry import clamp_popup_range, linear_value_to_x, linear_x_to_value


class PopupRangeController:
    """Own range-selector coordinate mapping, dragging, and bound application."""

    def __init__(self, app: Any, owner: Any) -> None:
        self.app = app
        self.owner = owner

    def range_x_to_idx(self, x: float) -> int:
        if self.app.stack_info is None or self.app._popup.mark_range_canvas is None:
            return 0
        width = max(2, self.app._popup.mark_range_canvas.winfo_width() - 12)
        frame_count = int(self.app.stack_info.frame_count)
        return linear_x_to_value(x - 6.0, width, 0, max(0, frame_count - 1))

    def range_idx_to_x(self, idx: int) -> float:
        if self.app.stack_info is None or self.app._popup.mark_range_canvas is None:
            return 6.0
        width = max(2, self.app._popup.mark_range_canvas.winfo_width() - 12)
        frame_count = int(self.app.stack_info.frame_count)
        return 6.0 + linear_value_to_x(idx, 0, max(0, frame_count - 1), width)

    def redraw_range_selector(self) -> None:
        if getattr(self.app._popup, "mark_range_canvas", None) is None or self.app.stack_info is None:
            return
        c = self.app._popup.mark_range_canvas
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 20 or h < 12:
            return

        y = h // 2
        c.create_line(6, y, w - 6, y, fill="#4c5058", width=4, capstyle=tk.ROUND)
        x0 = self.range_idx_to_x(self.app._popup.mark_range_start_idx)
        x1 = self.range_idx_to_x(self.app._popup.mark_range_end_idx)
        left = min(x0, x1)
        right = max(x0, x1)
        c.create_line(left, y, right, y, fill="#9cdb8f", width=6, capstyle=tk.ROUND)
        c.create_rectangle(left, y - 4, right, y + 4, fill="#9cdb8f", outline="")

        handle_radius = 7
        inner_radius = 4
        for x_pos, fill in ((x0, "#b7ffd9"), (x1, "#ffd1d1")):
            c.create_oval(
                x_pos - handle_radius,
                y - handle_radius,
                x_pos + handle_radius,
                y + handle_radius,
                fill="#171b20",
                outline="#e7edf2",
                width=2,
            )
            c.create_oval(
                x_pos - inner_radius,
                y - inner_radius,
                x_pos + inner_radius,
                y + inner_radius,
                fill=fill,
                outline="",
            )

    def range_press(self, event) -> None:
        if self.app.stack_info is None or self.app._popup.mark_range_canvas is None:
            return
        x_start = self.range_idx_to_x(self.app._popup.mark_range_start_idx)
        x_end = self.range_idx_to_x(self.app._popup.mark_range_end_idx)
        self.app._popup.mark_range_active_handle = "start" if abs(event.x - x_start) <= abs(event.x - x_end) else "end"
        self.range_drag(event)

    def range_drag(self, event) -> None:
        if self.app._popup.mark_range_active_handle is None:
            return
        idx = self.range_x_to_idx(event.x)
        if self.app._popup.mark_range_active_handle == "start":
            self.on_range_changed(idx, self.app._popup.mark_range_end_idx, drag_final=False)
        else:
            self.on_range_changed(self.app._popup.mark_range_start_idx, idx, drag_final=False)

    def range_release(self, _event) -> None:
        self.on_range_changed(self.app._popup.mark_range_start_idx, self.app._popup.mark_range_end_idx, drag_final=True)
        self.app._popup.mark_range_active_handle = None

    def on_range_changed(self, start_idx: int, end_idx: int, drag_final: bool = False) -> None:
        self.app._popup.mark_last_full_refresh_note = ""
        self.apply_range_bounds(start_idx, end_idx)
        if drag_final:
            self.owner.redraw_overlay()

    def apply_range_bounds(self, start_idx: int, end_idx: int) -> None:
        if self.app.stack_info is None or self.app._popup.mark_scale is None:
            return
        current_idx = int(self.app._popup.mark_popup_current_idx)
        mark_start, mark_end = self.app._popup_get_normalized_mark_bounds_for_overlay()
        if mark_start is not None:
            start_idx = min(int(start_idx), int(mark_start))
        if mark_end is not None:
            end_idx = max(int(end_idx), int(mark_end))
        start_idx = min(int(start_idx), current_idx)
        end_idx = max(int(end_idx), current_idx)
        start_idx, end_idx, clamped_current, _removed = clamp_popup_range(
            start_idx,
            end_idx,
            int(self.app.stack_info.frame_count),
            current_idx,
            self.app._popup.mark_processed_cache,
        )
        self.app._popup.mark_popup_local_start = start_idx
        self.app._popup.mark_popup_local_end = end_idx
        self.app._popup.mark_range_start_idx = start_idx
        self.app._popup.mark_range_end_idx = end_idx
        self.app._popup.mark_popup_current_idx = clamped_current
        self.app._popup.mark_scale.configure(from_=start_idx, to=end_idx)
        self.app._popup.mark_scale.set(clamped_current)
        self.owner.update_window_info()
        self.owner.redraw_overlay()
        self.redraw_range_selector()
        self.owner.update_preview(clamped_current)
