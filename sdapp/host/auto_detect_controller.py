"""AutoDetectController — launches the Auto-detect Workbench window."""
from __future__ import annotations

from tkinter import messagebox


class AutoDetectController:
    """Owned by SDAnalyzerApp; provides the Auto-detect button handler."""

    def __init__(self, app) -> None:
        self.app = app

    def start(self) -> None:
        """Called when the user clicks 'Auto-detect'. Runs on the UI thread."""
        app = self.app
        if app.stack_info is None or app.reader is None:
            messagebox.showerror(
                "Auto-detect",
                "Please open a recording before running auto-detection.",
                parent=app.root,
            )
            return

        from .auto_detect_window import AutoDetectWindow
        AutoDetectWindow(app).open()
