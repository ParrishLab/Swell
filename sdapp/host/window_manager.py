from __future__ import annotations

from sdapp.shared.services.analysis_window_manager import AnalysisWindowManager as _AnalysisWindowManager
from sdapp.shared.services.analysis_window_manager import AnalysisWindowRef


class AnalysisWindowManager(_AnalysisWindowManager):
    """Compatibility alias over shared AnalysisWindowManager."""

    def register(self, scope_id: str, event_id: str, window, app) -> AnalysisWindowRef:
        return self.open_event_window(scope_id, event_id, window, app)

    def focus_existing(self, scope_id: str, event_id: str) -> bool:
        return self.focus_event_window(scope_id, event_id)
