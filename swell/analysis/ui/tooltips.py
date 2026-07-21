from __future__ import annotations

from math import ceil
import time
import tkinter as tk

from swell.shared.ui.bootstrap import ttk


class TooltipManager:
    """Delayed, single-window tooltip controller for analysis UI help."""

    def __init__(
        self,
        root,
        *,
        hover_delay_ms: int = 600,
        focus_delay_ms: int = 300,
        cooldown_ms: int = 250,
        movement_threshold_px: int = 6,
        offset_px: int = 8,
        wraplength: int = 280,
        clock=time.monotonic,
        toplevel_factory=None,
    ) -> None:
        self.root = root
        self.hover_delay_ms = int(hover_delay_ms)
        self.focus_delay_ms = int(focus_delay_ms)
        self.cooldown_ms = int(cooldown_ms)
        self.movement_threshold_px = int(movement_threshold_px)
        self.offset_px = int(offset_px)
        self.wraplength = int(wraplength)
        self._clock = clock
        self._toplevel_factory = toplevel_factory or tk.Toplevel
        self._window = None
        self._label = None
        self._pending_job = None
        self._pending_widget = None
        self._pending_text = ""
        self._pending_origin = None
        self._pending_delay_ms = self.hover_delay_ms
        self._active_widget = None
        self._cooldown_until = 0.0
        self._create_count = 0

    @property
    def create_count(self) -> int:
        return int(self._create_count)

    def attach(self, widget, text: str, *, hover_delay_ms: int | None = None, focus_delay_ms: int | None = None) -> None:
        text = str(text or "").strip()
        if not text:
            return
        try:
            setattr(widget, "_analysis_tooltip_text", text)
        except Exception:
            pass

        def on_enter(event, *, target=widget, copy=text):
            self.schedule(target, copy, event, delay_ms=self.hover_delay_ms if hover_delay_ms is None else hover_delay_ms)

        def on_focus(event, *, target=widget, copy=text):
            self.schedule(target, copy, event, delay_ms=self.focus_delay_ms if focus_delay_ms is None else focus_delay_ms)

        widget.bind("<Enter>", on_enter, add="+")
        widget.bind("<FocusIn>", on_focus, add="+")
        widget.bind("<Motion>", self._on_motion, add="+")
        for sequence in ("<Leave>", "<FocusOut>", "<ButtonPress>", "<MouseWheel>", "<Button-4>", "<Button-5>", "<Escape>", "<Destroy>"):
            widget.bind(sequence, self.hide, add="+")

    def schedule(self, widget, text: str, event=None, *, delay_ms: int | None = None) -> None:
        self._cancel_pending()
        text = str(text or "").strip()
        if not text:
            self.hide()
            return
        self._pending_widget = widget
        self._pending_text = text
        self._pending_origin = self._event_root_xy(event, widget)
        delay = self.hover_delay_ms if delay_ms is None else int(delay_ms)
        cooldown_remaining_ms = ceil(max(0.0, self._cooldown_until - self._clock()) * 1000.0)
        delay = max(delay, cooldown_remaining_ms)
        self._pending_delay_ms = delay
        self._pending_job = self.root.after(max(0, delay), self._show_pending)

    def show_at_event(self, event, text: str) -> None:
        text = str(text or "").strip()
        if not text:
            self.hide()
            return
        self._cancel_pending()
        widget = getattr(event, "widget", self.root)
        x, y = self._event_root_xy(event, widget)
        self._show(widget, text, x, y)

    def hide(self, _event=None) -> None:
        was_visible = self._active_widget is not None
        self._cancel_pending()
        self._pending_widget = None
        self._pending_text = ""
        self._pending_origin = None
        self._active_widget = None
        if was_visible:
            self._cooldown_until = self._clock() + (self.cooldown_ms / 1000.0)
        window = self._window
        if window is None:
            return
        try:
            window.withdraw()
        except Exception:
            pass

    def _cancel_pending(self) -> None:
        job = self._pending_job
        self._pending_job = None
        if job is None:
            return
        try:
            self.root.after_cancel(job)
        except Exception:
            pass

    def _show_pending(self) -> None:
        self._pending_job = None
        widget = self._pending_widget
        text = self._pending_text
        x, y = self._pending_origin or self._widget_root_xy(widget)
        self._pending_widget = None
        self._pending_text = ""
        self._pending_origin = None
        self._show(widget, text, x, y)

    def _show(self, widget, text: str, x_root: int, y_root: int) -> None:
        text = str(text or "").strip()
        if not text:
            self.hide()
            return
        window, label = self._ensure_window()
        try:
            label.configure(text=text, wraplength=self.wraplength)
            window.update_idletasks()
        except Exception:
            pass
        x, y = self._clamp_geometry(x_root + self.offset_px, y_root + self.offset_px, window)
        try:
            window.geometry(f"+{x}+{y}")
            window.deiconify()
            window.lift()
        except Exception:
            pass
        self._active_widget = widget

    def _ensure_window(self):
        if self._window is not None:
            return self._window, self._label
        window = self._toplevel_factory(self.root)
        self._create_count += 1
        try:
            window.withdraw()
            window.overrideredirect(True)
        except Exception:
            pass
        frame = ttk.Frame(window, padding=(8, 5), style="AppOverlay.TFrame")
        frame.grid(row=0, column=0, sticky="nsew")
        label = ttk.Label(frame, text="", style="AppOverlayMeta.TLabel", justify="left", wraplength=self.wraplength)
        label.grid(row=0, column=0, sticky="w")
        self._window = window
        self._label = label
        return window, label

    def _on_motion(self, event) -> None:
        origin = self._pending_origin
        if origin is None:
            return
        x, y = self._event_root_xy(event, getattr(event, "widget", self.root))
        if abs(int(x) - int(origin[0])) > self.movement_threshold_px or abs(int(y) - int(origin[1])) > self.movement_threshold_px:
            widget = self._pending_widget
            text = self._pending_text
            delay = self._pending_delay_ms
            if widget is not None and text:
                self.schedule(widget, text, event, delay_ms=delay)

    def _event_root_xy(self, event, widget) -> tuple[int, int]:
        if event is not None and hasattr(event, "x_root") and hasattr(event, "y_root"):
            try:
                return int(event.x_root), int(event.y_root)
            except Exception:
                pass
        return self._widget_root_xy(widget)

    def _widget_root_xy(self, widget) -> tuple[int, int]:
        try:
            return int(widget.winfo_rootx()), int(widget.winfo_rooty())
        except Exception:
            return 0, 0

    def _clamp_geometry(self, x: int, y: int, window) -> tuple[int, int]:
        try:
            screen_w = int(self.root.winfo_screenwidth())
            screen_h = int(self.root.winfo_screenheight())
        except Exception:
            screen_w, screen_h = 1920, 1080
        try:
            req_w = int(window.winfo_reqwidth())
            req_h = int(window.winfo_reqheight())
        except Exception:
            req_w, req_h = 1, 1
        x = max(0, min(int(x), max(0, screen_w - req_w - self.offset_px)))
        y = max(0, min(int(y), max(0, screen_h - req_h - self.offset_px)))
        return x, y
