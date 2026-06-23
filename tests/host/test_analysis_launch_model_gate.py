from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from swell.host.host_models import EventMeta
from swell.host.controllers.analysis_launch_controller import AnalysisLaunchController


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

    with patch("swell.host.controllers.analysis_launch_controller.messagebox.askyesno", return_value=False):
        controller.analyze_selected_event()

    assert warnings
    assert warnings[-1][0] == "Open Analysis"
    assert "model setup" in warnings[-1][1].lower()
    assert manager_calls == []


def test_open_analysis_full_stack_fallback_cancelled_before_preview() -> None:
    ensured: list[int] = []
    prompted: list[dict[str, object]] = []
    browser = SimpleNamespace(
        ensure_full_stack_analysis_event=lambda **kwargs: ensured.append(int(kwargs["frame_count"])),
    )
    model_setup = SimpleNamespace(
        is_analysis_allowed=lambda: (True, "ready"),
    )
    app = SimpleNamespace(
        _get_model_setup_controller=lambda: model_setup,
        _get_project_controller=lambda: SimpleNamespace(ensure_active_stack_available=lambda **kwargs: True),
        _show_warning=lambda *_args: None,
        root=object(),
        reader=object(),
        stack_info=SimpleNamespace(frame_count=8),
        _active_event_id=lambda: None,
        browser_controller=browser,
        analysis_window_manager=SimpleNamespace(focus_event_window=lambda *_args: False),
    )
    controller = AnalysisLaunchController(app)
    controller.prompt_analysis_open_options = lambda **kwargs: prompted.append(dict(kwargs))  # type: ignore[method-assign]

    with patch("swell.host.controllers.analysis_launch_controller.messagebox.askyesno", return_value=False):
        controller.analyze_selected_event()

    assert ensured == []
    assert prompted == []


def test_open_analysis_full_stack_fallback_creates_event_before_preview() -> None:
    ensured: list[int] = []
    prompted: list[dict[str, object]] = []
    contexts: list[str] = []

    def _ensure_full_stack_analysis_event(*, frame_count: int):
        ensured.append(int(frame_count))
        return EventMeta(
            event_id="event_full_stack",
            label="Full Stack Analysis",
            start_idx=0,
            end_idx=7,
            flags={"host_full_stack_event": True},
        )

    def _host_context_for_event(event_id: str) -> dict:
        contexts.append(str(event_id))
        return {
            "event": {
                "event_id": str(event_id),
                "label": "Full Stack Analysis",
                "start_idx": 0,
                "end_idx": 7,
                "flags": {"host_full_stack_event": True},
            },
            "project_metadata": {},
        }

    browser = SimpleNamespace(
        ensure_full_stack_analysis_event=_ensure_full_stack_analysis_event,
        get_frame_source=lambda: object(),
        host_context_for_event=_host_context_for_event,
    )
    model_setup = SimpleNamespace(
        is_analysis_allowed=lambda: (True, "ready"),
        resolve_project_model_mismatch=lambda _metadata: {"ok": True},
        build_host_model_context=lambda: {"checkpoint": "ok"},
    )
    app = SimpleNamespace(
        _get_model_setup_controller=lambda: model_setup,
        _get_project_controller=lambda: SimpleNamespace(ensure_active_stack_available=lambda **kwargs: True),
        _show_warning=lambda *_args: None,
        _log_info=lambda *_args: None,
        root=object(),
        reader=object(),
        stack_info=SimpleNamespace(frame_count=8),
        _active_event_id=lambda: None,
        browser_controller=browser,
        analysis_window_manager=SimpleNamespace(focus_event_window=lambda *_args: False),
    )
    controller = AnalysisLaunchController(app)
    controller.prompt_analysis_open_options = lambda **kwargs: prompted.append(dict(kwargs)) or None  # type: ignore[method-assign]

    with patch("swell.host.controllers.analysis_launch_controller.messagebox.askyesno", return_value=True):
        controller.analyze_selected_event()

    assert ensured == [8]
    assert contexts == ["event_full_stack"]
    assert prompted == [{"event_id": "event_full_stack", "event_start": 0, "event_end": 7}]


def test_open_analysis_selected_event_skips_full_stack_confirmation() -> None:
    prompted: list[dict[str, object]] = []
    browser = SimpleNamespace(
        get_frame_source=lambda: object(),
        host_context_for_event=lambda event_id: {
            "event": {
                "event_id": str(event_id),
                "label": "Selected Event",
                "start_idx": 2,
                "end_idx": 5,
                "flags": {},
            },
            "project_metadata": {},
        },
        ensure_full_stack_analysis_event=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("should not create full-stack event")),
    )
    model_setup = SimpleNamespace(
        is_analysis_allowed=lambda: (True, "ready"),
        resolve_project_model_mismatch=lambda _metadata: {"ok": True},
        build_host_model_context=lambda: {"checkpoint": "ok"},
    )
    app = SimpleNamespace(
        _get_model_setup_controller=lambda: model_setup,
        _get_project_controller=lambda: SimpleNamespace(ensure_active_stack_available=lambda **kwargs: True),
        _show_warning=lambda *_args: None,
        _log_info=lambda *_args: None,
        root=object(),
        reader=object(),
        stack_info=SimpleNamespace(frame_count=8),
        _active_event_id=lambda: "event_0042",
        browser_controller=browser,
        analysis_window_manager=SimpleNamespace(focus_event_window=lambda *_args: False),
    )
    controller = AnalysisLaunchController(app)
    controller.prompt_analysis_open_options = lambda **kwargs: prompted.append(dict(kwargs)) or None  # type: ignore[method-assign]

    with patch("swell.host.controllers.analysis_launch_controller.messagebox.askyesno", side_effect=AssertionError("should not confirm")):
        controller.analyze_selected_event()

    assert prompted == [{"event_id": "event_0042", "event_start": 2, "event_end": 5}]
