from __future__ import annotations

"""Preview panel resize interaction helpers."""

from typing import Any


def start_resize_preview(app, event: Any) -> None:
    app._resize_start_x = event.x_root
    app._resize_start_y = event.y_root
    app._resize_start_w = app.preview_frame.winfo_width()
    app._resize_start_h = app.preview_frame.winfo_height()


def do_resize_preview(app, event: Any) -> None:
    if not hasattr(app, "_resize_start_x"):
        return
    dx = app._resize_start_x - event.x_root
    dy = event.y_root - app._resize_start_y
    delta = max(dx, dy)
    new_size = max(50, app._resize_start_w + delta)
    app.preview_frame.configure(width=new_size, height=new_size)
    app.preview_frame.update_idletasks()
    app.update_display(update_preview=True)


def stop_resize_preview(app, _event: Any) -> None:
    if not hasattr(app, "_resize_start_x"):
        return
    del app._resize_start_x
    app.preview_frame.update_idletasks()
    app.update_display(update_preview=True)
