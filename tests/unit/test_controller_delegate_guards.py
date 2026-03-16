from __future__ import annotations

import inspect

from sdapp.analysis.app import SDSegmentationApp
from sdapp.host.sd_gui import SDAnalyzerApp


def test_host_popup_methods_delegate_to_popup_controller() -> None:
    assert "self.popup_controller.open_popup" in inspect.getsource(SDAnalyzerApp._open_mark_popup)
    assert "self.popup_controller.on_destroy" in inspect.getsource(SDAnalyzerApp._on_mark_popup_destroy)
    assert "self.popup_controller.confirm" in inspect.getsource(SDAnalyzerApp._popup_confirm)
    assert "self.popup_controller.cancel" in inspect.getsource(SDAnalyzerApp._popup_cancel)
    assert "self.popup_controller.delete_selected_events" in inspect.getsource(SDAnalyzerApp._delete_selected_events)
    assert "self._get_window_controller().open_generate_metrics_popup" in inspect.getsource(
        SDAnalyzerApp._open_generate_metrics_popup
    )
    assert "self._get_analysis_launch_controller().compute_analysis_preview_frame" in inspect.getsource(
        SDAnalyzerApp._compute_analysis_preview_frame
    )


def test_analysis_host_mode_methods_delegate_to_controller() -> None:
    assert "self._get_host_mode_controller().emit_host_sync" in inspect.getsource(SDSegmentationApp._emit_host_sync)
    assert "self._get_host_mode_controller().open_from_host_context" in inspect.getsource(SDSegmentationApp.open_from_host_context)
    assert "self._get_host_mode_controller().prepare_host_mode_buffers" in inspect.getsource(
        SDSegmentationApp._prepare_host_mode_buffers
    )
