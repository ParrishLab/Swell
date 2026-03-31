from __future__ import annotations

import tkinter as tk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sdapp.shared.services import SingleInstanceBridge


def run_host_app(
    *,
    initial_project_path: str | None = None,
    instance_bridge: SingleInstanceBridge | None = None,
) -> None:
    root = tk.Tk()
    root.title("SDApp")
    root.geometry("480x220")
    splash = tk.Frame(root, padx=24, pady=24)
    splash.pack(fill="both", expand=True)
    tk.Label(splash, text="Starting SDApp...", font=("Helvetica", 18, "bold")).pack(anchor="center", pady=(24, 8))
    tk.Label(
        splash,
        text="Loading the packaged runtime and UI modules.",
        justify="center",
    ).pack(anchor="center")
    try:
        root.update_idletasks()
        root.update()
    except Exception:
        pass

    from sdapp.host.app import SDAnalyzerApp

    splash.destroy()
    SDAnalyzerApp(root, initial_project_path=initial_project_path, instance_bridge=instance_bridge)
    root.mainloop()
