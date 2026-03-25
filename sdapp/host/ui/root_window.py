from __future__ import annotations

import tkinter as tk

from sdapp.host.app import SDAnalyzerApp
from sdapp.shared.services import SingleInstanceBridge


def run_host_app(
    *,
    initial_project_path: str | None = None,
    instance_bridge: SingleInstanceBridge | None = None,
) -> None:
    root = tk.Tk()
    SDAnalyzerApp(root, initial_project_path=initial_project_path, instance_bridge=instance_bridge)
    root.mainloop()
