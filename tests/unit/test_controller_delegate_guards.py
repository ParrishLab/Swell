from __future__ import annotations

import inspect

from swell.analysis.app import SwellAnalysisApp
from swell.host.event_gui import SwellHostApp


def test_host_popup_methods_delegate_to_popup_controller() -> None:
    assert "self.popup_controller.open_popup" in inspect.getsource(SwellHostApp._open_mark_popup)
    assert "self.popup_controller.on_destroy" in inspect.getsource(SwellHostApp._on_mark_popup_destroy)
    assert "self.popup_controller.confirm" in inspect.getsource(SwellHostApp._popup_confirm)
    assert "self.popup_controller.cancel" in inspect.getsource(SwellHostApp._popup_cancel)
    assert "self.popup_controller.delete_selected_events" in inspect.getsource(SwellHostApp._delete_selected_events)
    assert "self._get_popup_controller().step" in inspect.getsource(SwellHostApp._handle_popup_key)
    assert "self._get_window_controller().open_generate_metrics_popup" in inspect.getsource(
        SwellHostApp._open_generate_metrics_popup
    )
    assert "self._get_analysis_launch_controller().compute_analysis_preview_frame" in inspect.getsource(
        SwellHostApp._compute_analysis_preview_frame
    )


def test_analysis_host_mode_methods_delegate_to_controller() -> None:
    assert "self._get_host_mode_controller().emit_host_sync" in inspect.getsource(SwellAnalysisApp._emit_host_sync)
    assert "self._get_host_mode_controller().open_from_host_context" in inspect.getsource(SwellAnalysisApp.open_from_host_context)
    assert "self._get_host_mode_controller().prepare_host_mode_buffers" in inspect.getsource(
        SwellAnalysisApp._prepare_host_mode_buffers
    )
