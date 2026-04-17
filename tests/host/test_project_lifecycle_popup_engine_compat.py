from __future__ import annotations

from types import SimpleNamespace

from sdapp.host.controllers.project_lifecycle_controller import HostProjectLifecycleController


def test_on_stack_loaded_uses_popup_window_manager_engine_when_legacy_attr_missing() -> None:
    popup_readers: list[object] = []
    statuses: list[str] = []
    logs: list[str] = []
    on_stack_loaded_calls: list[tuple[object, object]] = []
    popup_destroyed = {"value": False}

    app = SimpleNamespace(
        _popup=SimpleNamespace(
            engine=SimpleNamespace(set_reader=lambda reader: popup_readers.append(reader)),
            mark_processed_cache=SimpleNamespace(clear=lambda: None),
            mark_popup=SimpleNamespace(
                winfo_exists=lambda: True,
                destroy=lambda: popup_destroyed.__setitem__("value", True),
            ),
        ),
        dc_trace_controller=SimpleNamespace(clear_runtime=lambda: None),
        browser_controller=SimpleNamespace(
            on_stack_loaded=lambda reader, info: on_stack_loaded_calls.append((reader, info)),
            session=SimpleNamespace(set_project_path=lambda _path: None),
        ),
        _main_render_cache=SimpleNamespace(clear=lambda: None),
        _normalized_frame_u8_cache=SimpleNamespace(clear=lambda: None),
        _sync_event_projections=lambda: None,
        preview_scale=SimpleNamespace(configure=lambda **_kwargs: None, set=lambda _value: None),
        _update_preview=lambda _idx: None,
        _redraw_main_overlay=lambda: None,
        _set_status=lambda text: statuses.append(str(text)),
        _log_info=lambda text: logs.append(str(text)),
        analysis_launch_controller=SimpleNamespace(prewarm_analysis_app_class_async=lambda: None),
        _gc_runtime_caches=lambda **_kwargs: None,
    )

    controller = HostProjectLifecycleController(app)
    controller.warmup_main_preview_async = lambda: None
    reader = object()
    info = SimpleNamespace(frame_count=42, frame_width=64, frame_height=32, dtype="uint8")

    controller.on_stack_loaded(reader, info)

    assert popup_readers == [reader]
    assert on_stack_loaded_calls == [(reader, info)]
    assert popup_destroyed["value"] is True
    assert statuses and statuses[-1].startswith("Loaded 42 frames")
    assert any("Stack load completed" in entry for entry in logs)
