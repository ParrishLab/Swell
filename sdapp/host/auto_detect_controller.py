"""AutoDetectController — launches the Auto-detect Workbench window."""
from __future__ import annotations

from sdapp.shared.ui import dialogs as messagebox


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
        project_controller = getattr(app, "_get_project_controller", lambda: None)()
        ensure_stack = getattr(project_controller, "ensure_active_stack_available", None)
        if callable(ensure_stack) and not bool(ensure_stack(title="Auto-detect")):
            return

        from .auto_detect_window import AutoDetectWindow
        AutoDetectWindow(app).open()
