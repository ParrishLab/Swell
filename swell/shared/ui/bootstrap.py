from __future__ import annotations

import re
import tkinter as tk
from tkinter import ttk as tk_ttk

BOOTSTRAP_AVAILABLE = False
ttk = tk_ttk
Style = tk_ttk.Style


def create_root_window(*, themename: str = "darkly"):
    return tk.Tk()


def center_window_on_screen(window, *, width: int | None = None, height: int | None = None) -> None:
    try:
        # Check current geometry string (e.g. "680x1+0+0" or "1x1+0+0").
        # If geometry was locked with a placeholder dimension (typically height=1),
        # we temporarily release it by setting geometry("") to let Tkinter layout propagate.
        try:
            geom = window.geometry()
            if not isinstance(geom, str):
                geom = ""
        except Exception:
            geom = ""
        match = re.match(r"^(\d+)x(\d+)", geom) if geom else None
        current_w, current_h = (int(match.group(1)), int(match.group(2))) if match else (None, None)

        if (width is None and (current_w is None or current_w <= 1)) or \
           (height is None and (current_h is None or current_h <= 1)):
            try:
                window.geometry("")
            except Exception:
                pass

        window.update_idletasks()
        target_width = int(width) if width is not None else int(window.winfo_width())
        target_height = int(height) if height is not None else int(window.winfo_height())
        if target_width <= 1:
            target_width = int(window.winfo_reqwidth())
        if target_height <= 1:
            target_height = int(window.winfo_reqheight())
        
        # Check minsize of window and clamp to it if it is configured
        try:
            min_w, min_h = window.minsize()
            if min_w > 0:
                target_width = max(target_width, min_w)
            if min_h > 0:
                target_height = max(target_height, min_h)
        except Exception:
            pass

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
        "primary": "AppAccent.TButton",
        "success": "AppAccent.TButton",
        "secondary": "AppQuiet.TButton",
        "danger": "AppDanger.TButton",
    }
    return {"style": mapping.get(normalized, "AppQuiet.TButton")}
