from __future__ import annotations

import numpy as np

from sdapp.host.sd_gui import SDAnalyzerApp


def test_export_selected_routes_through_options_dialog() -> None:
    app = SDAnalyzerApp.__new__(SDAnalyzerApp)
    app._log_info = lambda *_args, **_kwargs: None
    app._log_warn = lambda *_args, **_kwargs: None
    app._selected_event_ids = lambda: ["event_0001", "event_0002"]
    app._prompt_export_options = lambda _n: {
        "include_event_images": True,
        "include_baseline_images": False,
        "include_binary_masks": True,
    }
    captured: dict[str, object] = {}
    app._run_export = lambda ids, *, options: captured.update({"ids": list(ids), "options": dict(options)})

    app._export_selected()

    assert captured["ids"] == ["event_0001", "event_0002"]
    assert captured["options"] == {
        "include_event_images": True,
        "include_baseline_images": False,
        "include_binary_masks": True,
    }


def test_export_selected_cancel_skips_export() -> None:
    app = SDAnalyzerApp.__new__(SDAnalyzerApp)
    app._log_info = lambda *_args, **_kwargs: None
    app._log_warn = lambda *_args, **_kwargs: None
    app._selected_event_ids = lambda: ["event_0001"]
    app._prompt_export_options = lambda _n: None
    called = {"run": False}
    app._run_export = lambda *_args, **_kwargs: called.update({"run": True})

    app._export_selected()

    assert called["run"] is False


def test_export_all_routes_through_options_dialog() -> None:
    app = SDAnalyzerApp.__new__(SDAnalyzerApp)
    app._log_info = lambda *_args, **_kwargs: None
    app._log_warn = lambda *_args, **_kwargs: None
    app.browser_controller = type(
        "BC",
        (),
        {
            "list_events": lambda self: [
                type("E", (), {"event_id": "event_0001"})(),
                type("E", (), {"event_id": "event_0002"})(),
            ]
        },
    )()
    app._prompt_export_options = lambda _n: {
        "include_event_images": False,
        "include_baseline_images": True,
        "include_binary_masks": False,
    }
    captured: dict[str, object] = {}
    app._run_export = lambda ids, *, options: captured.update({"ids": list(ids), "options": dict(options)})

    app._export_all()

    assert captured["ids"] == ["event_0001", "event_0002"]
    assert captured["options"] == {
        "include_event_images": False,
        "include_baseline_images": True,
        "include_binary_masks": False,
    }


def test_has_binary_masks_for_events_detects_available_masks() -> None:
    app = SDAnalyzerApp.__new__(SDAnalyzerApp)
    masks = np.zeros((6, 8, 8), dtype=np.uint8)
    masks[2, 1:3, 1:3] = 1
    state = type("S", (), {"analysis_sidecar": {"event_0001": {"masks_committed": masks}}})()
    app.browser_controller = type("BC", (), {"session": type("Session", (), {"state": lambda self: state})()})()

    assert app._has_binary_masks_for_events(["event_0001"]) is True
    assert app._has_binary_masks_for_events(["event_0002"]) is False
