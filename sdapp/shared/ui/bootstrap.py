from __future__ import annotations

import tkinter as tk
from tkinter import ttk as tk_ttk

try:
    import ttkbootstrap as ttkbootstrap_module
except Exception:  # pragma: no cover - exercised when dependency is absent locally
    ttkbootstrap_module = None


BOOTSTRAP_AVAILABLE = ttkbootstrap_module is not None

if BOOTSTRAP_AVAILABLE:
    ttk = ttkbootstrap_module
    Style = ttkbootstrap_module.Style
else:
    ttk = tk_ttk
    Style = tk_ttk.Style


def create_root_window(*, themename: str = "darkly"):
    if BOOTSTRAP_AVAILABLE:
        return ttkbootstrap_module.Window(themename=themename)
    return tk.Tk()


def center_window_on_screen(window, *, width: int | None = None, height: int | None = None) -> None:
    try:
        window.update_idletasks()
        target_width = int(width) if width is not None else int(window.winfo_width())
        target_height = int(height) if height is not None else int(window.winfo_height())
        if target_width <= 1:
            target_width = int(window.winfo_reqwidth())
        if target_height <= 1:
            target_height = int(window.winfo_reqheight())
        target_width = max(1, target_width)
        target_height = max(1, target_height)
        x = max(0, int((int(window.winfo_screenwidth()) - target_width) / 2))
        y = max(0, int((int(window.winfo_screenheight()) - target_height) / 2))
        window.geometry(f"{target_width}x{target_height}+{x}+{y}")
    except Exception:
        return


def semantic_button_options(kind: str) -> dict[str, str]:
    normalized = str(kind or "secondary").strip().lower() or "secondary"
    mapping = {
        "primary": "Accent.TButton",
        "success": "Accent.TButton",
        "secondary": "Quiet.TButton",
        "danger": "Danger.TButton",
    }
    return {"style": mapping.get(normalized, "Quiet.TButton")}
