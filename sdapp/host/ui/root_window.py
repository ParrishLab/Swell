from __future__ import annotations

import tkinter as tk

from sdapp.host.sd_gui import SDAnalyzerApp


def run_host_app() -> None:
    root = tk.Tk()
    SDAnalyzerApp(root)
    root.mainloop()
