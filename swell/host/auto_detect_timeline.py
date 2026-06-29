from __future__ import annotations

from typing import Any

from swell.host.auto_detect_helpers import (
    detail_window_bounds,
    detail_x_from_frame,
    frame_from_detail_x,
    frame_from_overview_x,
    overview_x_from_frame,
)
from swell.shared.ui.theme import APP_COLORS

_C_ACCENT = APP_COLORS["accent"]
_C_BORDER = APP_COLORS["border"]
_C_TEXT = APP_COLORS["text"]
_C_MUTED = APP_COLORS["muted"]
_C_MUTED_SOFT = APP_COLORS["muted_soft"]


class AutoDetectTimelineController:
    """Own overview/detail timeline drawing and direct timeline input handling."""

    def __init__(self, window: Any) -> None:
        self.window = window

    def render_trace(self) -> None:
        self.render_overview()
        self.render_detail()

    def render_overview(self) -> None:
        w = self.window
        canvas = getattr(w, "_overview_canvas", None)
        if canvas is None:
            return
        cw = max(1, canvas.winfo_width())
        ch = max(1, canvas.winfo_height())
        fc = int(w.app.stack_info.frame_count)

        canvas.delete("all")
        w._overview_items.clear()
        w._candidate_bar_overview.clear()
        if cw <= 1 or fc <= 1:
            return

        for idx, cand in enumerate(w._review_candidates):
            s = int(cand["start_frame"])
            e = int(cand["end_frame"])
            x0 = (s / (fc - 1)) * cw
            x1 = (e / (fc - 1)) * cw
            color = _C_ACCENT if idx == w._current_idx else _C_BORDER
            bar = canvas.create_rectangle(x0, ch - 4, max(x1, x0 + 1), ch, fill=color, outline="")
            w._candidate_bar_overview.append(bar)

        win_start, win_end = self.detail_window_bounds()
        vx0 = (win_start / (fc - 1)) * cw
        vx1 = (win_end / (fc - 1)) * cw
        w._overview_items["viewport"] = canvas.create_rectangle(
            vx0, 0, max(vx1, vx0 + 1), ch, outline=_C_BORDER, fill=_C_BORDER, stipple="gray25", width=1
        )

        cx = (w._current_frame / (fc - 1)) * cw
        w._overview_items["scrubber"] = canvas.create_line(cx, 0, cx, ch, fill=_C_TEXT, width=1, tags="scrubber")

    def update_overview_dynamic(self) -> None:
        w = self.window
        canvas = getattr(w, "_overview_canvas", None)
        if canvas is None:
            return
        cw = max(1, canvas.winfo_width())
        ch = max(1, canvas.winfo_height())
        fc = int(w.app.stack_info.frame_count)
        if cw <= 1 or fc <= 1:
            return
        cx = (w._current_frame / (fc - 1)) * cw
        if "scrubber" in w._overview_items:
            canvas.coords(w._overview_items["scrubber"], cx, 0, cx, ch)
        win_start, win_end = self.detail_window_bounds()
        vx0 = (win_start / (fc - 1)) * cw
        vx1 = (win_end / (fc - 1)) * cw
        if "viewport" in w._overview_items:
            canvas.coords(w._overview_items["viewport"], vx0, 0, max(vx1, vx0 + 1), ch)

    def detail_window_bounds(self) -> tuple[int, int]:
        w = self.window
        return detail_window_bounds(
            int(w.app.stack_info.frame_count),
            int(w._detail_center_frame),
            int(w._detail_half_width),
        )

    def render_detail(self) -> None:
        w = self.window
        canvas = getattr(w, "_detail_canvas", None)
        if canvas is None:
            return
        cw = max(1, canvas.winfo_width())
        ch = max(1, canvas.winfo_height())
        fc = int(w.app.stack_info.frame_count)

        canvas.delete("all")
        w._detail_items.clear()
        w._candidate_bar_detail.clear()
        if cw <= 1 or fc <= 1:
            return

        win_start, win_end = self.detail_window_bounds()
        win_span = max(1, win_end - win_start)

        def _x(frame: float) -> float:
            return (float(frame) - win_start) / win_span * cw

        for idx, cand in enumerate(w._review_candidates):
            s = int(cand["start_frame"])
            e = int(cand["end_frame"])
            if e < win_start or s > win_end:
                continue
            cs = max(s, win_start)
            ce = min(e, win_end)
            x0 = _x(cs)
            x1 = _x(ce)
            color = _C_ACCENT if idx == w._current_idx else _C_BORDER
            bar = canvas.create_rectangle(x0, ch - 10, max(x1, x0 + 1), ch - 2, fill=color, outline="")
            w._candidate_bar_detail.append(bar)

        sel_idx = w._selected_candidate_idx()
        if sel_idx is not None:
            cand = w._review_candidates[sel_idx]
            s, e = int(cand["start_frame"]), int(cand["end_frame"])
            if e >= win_start and s <= win_end:
                cs = max(s, win_start)
                ce = min(e, win_end)
                ox0 = _x(cs)
                ox1 = _x(ce)
                w._detail_items["overlay"] = canvas.create_rectangle(
                    ox0, 0, max(ox1, ox0 + 1), ch, fill=_C_ACCENT, stipple="gray25", outline=""
                )
            if win_start <= s <= win_end:
                hx = _x(s)
                h_color = _C_TEXT if w._trace_hover == "start" else _C_MUTED_SOFT
                w._detail_items["handle_start"] = canvas.create_rectangle(
                    hx - 3, 0, hx + 3, ch, fill=h_color, outline="", tags="handle_start"
                )
            if win_start <= e <= win_end:
                hx = _x(e)
                h_color = _C_TEXT if w._trace_hover == "end" else _C_MUTED_SOFT
                w._detail_items["handle_end"] = canvas.create_rectangle(
                    hx - 3, 0, hx + 3, ch, fill=h_color, outline="", tags="handle_end"
                )

        if win_start <= w._current_frame <= win_end:
            cx = _x(w._current_frame)
            w._detail_items["scrubber"] = canvas.create_line(cx, 0, cx, ch, fill=_C_TEXT, width=1, tags="scrubber")

        canvas.create_text(4, 2, anchor="nw", text=str(win_start), fill=_C_MUTED, font=("TkSmallCaptionFont",))
        canvas.create_text(cw - 4, 2, anchor="ne", text=str(win_end), fill=_C_MUTED, font=("TkSmallCaptionFont",))

    def frame_from_overview_x(self, x: float) -> int:
        w = self.window
        return frame_from_overview_x(x, canvas_width=max(1, w._overview_canvas.winfo_width()), frame_count=int(w.app.stack_info.frame_count))

    def frame_from_detail_x(self, x: float) -> int:
        w = self.window
        return frame_from_detail_x(
            x,
            canvas_width=max(1, w._detail_canvas.winfo_width()),
            window_bounds=self.detail_window_bounds(),
            frame_count=int(w.app.stack_info.frame_count),
        )

    def detail_x_from_frame(self, frame: int) -> float | None:
        w = self.window
        return detail_x_from_frame(frame, canvas_width=max(1, w._detail_canvas.winfo_width()), window_bounds=self.detail_window_bounds())

    def frame_from_x(self, x: float) -> int:
        return self.frame_from_overview_x(x)

    def x_from_frame(self, frame: int) -> float:
        w = self.window
        return overview_x_from_frame(frame, canvas_width=max(1, w._overview_canvas.winfo_width()), frame_count=int(w.app.stack_info.frame_count))

    def on_overview_click(self, event) -> None:
        w = self.window
        frame = self.frame_from_overview_x(event.x)
        w._current_frame = frame
        w._detail_center_frame = frame
        w._schedule_viewer_render(frame)
        self.render_overview()
        self.render_detail()

    def on_overview_drag(self, event) -> None:
        w = self.window
        frame = self.frame_from_overview_x(event.x)
        w._current_frame = frame
        w._detail_center_frame = frame
        w._schedule_viewer_render(frame)
        self.update_overview_dynamic()
        self.render_detail()

    def on_overview_release(self, _event) -> None:
        self.render_overview()

    def on_detail_motion(self, event) -> None:
        w = self.window
        idx = w._selected_candidate_idx()
        hover = None
        if idx is not None:
            cand = w._review_candidates[idx]
            xs = self.detail_x_from_frame(int(cand["start_frame"]))
            xe = self.detail_x_from_frame(int(cand["end_frame"]))
            if xs is not None and abs(event.x - xs) < 6:
                hover = "start"
            elif xe is not None and abs(event.x - xe) < 6:
                hover = "end"

        if hover != w._trace_hover:
            w._trace_hover = hover
            self.render_detail()
            w._detail_canvas.config(cursor="sb_h_double_arrow" if hover else "")

    def on_detail_click(self, event) -> None:
        w = self.window
        if w._trace_hover:
            w._trace_dragging = w._trace_hover
            return
        frame = self.frame_from_detail_x(event.x)
        w._current_frame = frame
        w._schedule_viewer_render(frame)
        self.render_detail()
        self.update_overview_dynamic()

    def on_detail_drag(self, event) -> None:
        w = self.window
        if w._trace_dragging:
            idx = w._selected_candidate_idx()
            if idx is not None:
                cand = w._review_candidates[idx]
                f = self.frame_from_detail_x(event.x)
                if w._trace_dragging == "start":
                    cand["start_frame"] = min(f, int(cand["end_frame"]))
                else:
                    cand["end_frame"] = max(f, int(cand["start_frame"]))
                w._refresh_tree_row(idx)
                self.render_detail()
                self.render_overview()
            return
        frame = self.frame_from_detail_x(event.x)
        w._current_frame = frame
        w._schedule_viewer_render(frame)
        self.render_detail()
        self.update_overview_dynamic()

    def on_detail_release(self, _event) -> None:
        w = self.window
        if w._trace_dragging:
            idx = w._selected_candidate_idx()
            if idx is not None:
                cand = w._review_candidates[idx]
                w._start_entry.delete(0, "end")
                w._start_entry.insert(0, str(cand["start_frame"]))
                w._end_entry.delete(0, "end")
                w._end_entry.insert(0, str(cand["end_frame"]))
            w._trace_dragging = None
            self.render_detail()

    def on_detail_wheel(self, event) -> None:
        steps = int(event.delta / 120) if abs(event.delta) >= 120 else (1 if event.delta > 0 else -1)
        self.apply_detail_wheel(steps, shift=bool(event.state & 0x0001))

    def on_detail_wheel_linux(self, _event, direction: int) -> None:
        self.apply_detail_wheel(direction, shift=False)

    def apply_detail_wheel(self, steps: int, *, shift: bool) -> None:
        w = self.window
        if steps == 0:
            return
        fc = int(w.app.stack_info.frame_count)
        if fc <= 1:
            return
        if shift:
            half = max(1, w._detail_half_width)
            w._detail_center_frame = int(max(0, min(fc - 1, w._detail_center_frame - steps * max(1, half // 4))))
        else:
            factor = 0.8 if steps > 0 else 1.25
            new_half = int(round(w._detail_half_width * factor))
            w._detail_half_width = max(w._detail_min_half_width, min(w._detail_max_half_width, new_half))
        self.render_detail()
        self.update_overview_dynamic()
