from __future__ import annotations

import tkinter as tk

from sdapp.shared.ui.bootstrap import ttk


def build_preview_overlay(parent, on_start, on_drag, on_stop, *, dark_theme: bool = True):
    del dark_theme

    preview_frame = ttk.Frame(parent, width=148, height=148, style="AppPreview.TFrame")
    preview_frame.grid_propagate(False)
    preview_frame.place(relx=1.0, rely=0.0, anchor="ne", x=-8, y=8)
    preview_frame.columnconfigure(0, weight=1)
    preview_frame.rowconfigure(0, weight=1)

    canvas_preview = tk.Canvas(
        preview_frame,
        bg="black",
        width=136,
        height=136,
        highlightthickness=0,
        bd=0,
    )
    canvas_preview.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)

    lbl_grip = ttk.Label(
        preview_frame,
        text="\u2199",
        style="AppPreviewGrip.TLabel",
        cursor="fleur",
        width=2,
    )
    lbl_grip.place(relx=0.0, rely=1.0, anchor="sw", x=6, y=-6)

    lbl_grip.bind("<Button-1>", on_start)
    lbl_grip.bind("<B1-Motion>", on_drag)
    lbl_grip.bind("<ButtonRelease-1>", on_stop)

    return preview_frame, canvas_preview, lbl_grip
