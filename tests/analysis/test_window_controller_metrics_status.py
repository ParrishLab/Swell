from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from sdapp.analysis.controllers.window_controller import AnalysisWindowController


class _Var:
    def __init__(self, value=None) -> None:
        self._value = value

    def get(self):
        return self._value

    def set(self, value) -> None:
        self._value = value


def _make_app() -> SimpleNamespace:
    return SimpleNamespace(
        _host_mode=True,
        _frames_per_sec_is_local_override=False,
        _scale_is_local_override=False,
        _roi_is_local_override=False,
        _suppress_metrics_emit=False,
        frames_per_sec_var=_Var(2.5),
        scale_px_per_mm=4.0,
        roi_points=[[1.0, 1.0], [3.0, 1.0], [3.0, 3.0]],
        roi_mask=np.ones((2, 2), dtype=bool),
        metrics_fps_status_var=_Var(""),
        metrics_scale_status_var=_Var(""),
        metrics_roi_status_var=_Var(""),
        _ui_alive=lambda: False,
        update_display=lambda: None,
    )


def test_refresh_metrics_status_labels_reports_inherited_global_sources() -> None:
    app = _make_app()
    controller = AnalysisWindowController(app)

    controller.refresh_metrics_status_labels()

    assert app.metrics_fps_status_var.get() == "Frames/sec: 2.5 (Inherited Global)"
    assert app.metrics_scale_status_var.get() == "Scale: 4 px/mm (Inherited Global)"
    assert app.metrics_roi_status_var.get() == "ROI: 3 points (4 px) (Inherited Global)"


def test_apply_host_metrics_settings_marks_local_override_sources() -> None:
    app = _make_app()
    controller = AnalysisWindowController(app)

    controller.apply_host_metrics_settings(
        {"frames_per_sec": 2.5, "scale_px_per_mm": 4.0, "roi_points": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]]},
        {"frames_per_sec": 3.0, "scale_px_per_mm": 8.0, "roi_points": [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0]]},
    )

    assert app._frames_per_sec_is_local_override is True
    assert app._scale_is_local_override is True
    assert app._roi_is_local_override is True
    assert "Local Override" in str(app.metrics_fps_status_var.get())
    assert "Local Override" in str(app.metrics_scale_status_var.get())
    assert "Local Override" in str(app.metrics_roi_status_var.get())
