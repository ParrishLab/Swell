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


def test_resolve_export_metric_prerequisites_disables_when_scale_or_roi_missing() -> None:
    app = SDAnalyzerApp.__new__(SDAnalyzerApp)
    by_event = {
        "event_0001": {"frames_per_sec": 1.0, "scale_px_per_mm": 2.0},
        "event_0002": {"frames_per_sec": 1.0},
    }
    app.browser_controller = type(
        "BC",
        (),
        {"resolve_event_metrics_settings": lambda self, event_id: dict(by_event.get(str(event_id), {}))},
    )()

    ready = app._resolve_export_metric_prerequisites(["event_0001", "event_0002"])

    assert ready["propagation_speed"]["enabled"] is False
    assert "missing scale" in str(ready["propagation_speed"]["reason"]).lower()
    assert ready["area_recruited"]["enabled"] is False
    assert ready["relative_area_recruited"]["enabled"] is False


def test_resolve_export_metric_prerequisites_enables_when_all_have_scale_and_roi() -> None:
    app = SDAnalyzerApp.__new__(SDAnalyzerApp)
    by_event = {
        "event_0001": {
            "frames_per_sec": 1.0,
            "scale_px_per_mm": 2.0,
            "roi_points": [[1.0, 1.0], [3.0, 1.0], [2.0, 3.0]],
        },
        "event_0002": {
            "frames_per_sec": 1.0,
            "scale_px_per_mm": 3.0,
            "roi_mask": np.ones((4, 4), dtype=bool),
        },
    }
    app.browser_controller = type(
        "BC",
        (),
        {"resolve_event_metrics_settings": lambda self, event_id: dict(by_event.get(str(event_id), {}))},
    )()

    ready = app._resolve_export_metric_prerequisites(["event_0001", "event_0002"])

    assert ready["propagation_speed"]["enabled"] is True
    assert ready["area_recruited"]["enabled"] is True
    assert ready["relative_area_recruited"]["enabled"] is True


def test_on_export_progress_updates_status_for_analysis_prepare() -> None:
    app = SDAnalyzerApp.__new__(SDAnalyzerApp)
    status: list[str] = []
    logs: list[str] = []
    app._set_status = lambda text: status.append(str(text))
    app._log_info = lambda text, *_args, **_kwargs: logs.append(str(text))
    app._export_progress_bucket = -1
    app._last_export_analysis_prepare_key = None

    app._on_export_progress(
        {
            "phase": "analysis_prepare",
            "event_id": "event_0001",
            "current": 6,
            "total": 15,
            "stage": "preprocess",
        }
    )

    assert status
    assert "Preparing analysis images for event_0001" in status[-1]
    assert "(40%)" in status[-1]
    assert logs
