import tkinter as tk
from tkinter import ttk


def build_preview_overlay(parent, on_start, on_drag, on_stop, *, dark_theme: bool = True):
    preview_frame = ttk.Frame(parent, width=150, height=150, style="Preview.TFrame")
    preview_frame.pack_propagate(False)
    preview_frame.place(relx=1.0, rely=0.0, anchor="ne", x=-10, y=10)

    canvas_preview = tk.Canvas(
        preview_frame,
        bg="black",
        width=140,
        height=140,
        highlightthickness=1,
        highlightbackground="gray",
    )
    canvas_preview.pack(fill="both", expand=True)

    lbl_grip = tk.Label(
        preview_frame,
        text="\u2199",
        font=("Arial", 16),
        cursor="fleur",
        bg="#444" if dark_theme else "#e6e9ee",
        fg="white" if dark_theme else "#1f1f1f",
    )
    lbl_grip.place(relx=0.0, rely=1.0, anchor="sw", width=25, height=25)

    lbl_grip.bind("<Button-1>", on_start)
    lbl_grip.bind("<B1-Motion>", on_drag)
    lbl_grip.bind("<ButtonRelease-1>", on_stop)

    return preview_frame, canvas_preview, lbl_grip
