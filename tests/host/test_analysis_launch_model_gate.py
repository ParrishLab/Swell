from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from sdapp.host.controllers.analysis_launch_controller import AnalysisLaunchController


def test_analyze_selected_event_blocked_when_model_gate_not_ready() -> None:
    warnings: list[tuple[str, str]] = []
    manager_calls: list[bool] = []
    model_setup = SimpleNamespace(
        is_analysis_allowed=lambda: (False, "Model File Missing"),
        open_model_manager=lambda required=False: manager_calls.append(bool(required)),
    )
    app = SimpleNamespace(
        _get_model_setup_controller=lambda: model_setup,
        _show_warning=lambda title, text: warnings.append((str(title), str(text))),
        root=object(),
    )
    controller = AnalysisLaunchController(app)

    with patch("sdapp.host.controllers.analysis_launch_controller.messagebox.askyesno", return_value=False):
        controller.analyze_selected_event()

    assert warnings
    assert warnings[-1][0] == "Open Analysis"
    assert "model setup" in warnings[-1][1].lower()
    assert manager_calls == []

