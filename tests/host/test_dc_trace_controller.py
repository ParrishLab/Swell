from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from swell.host.controllers.dc_trace_controller import HostDCTraceController
from swell.shared.trace import TimeAlignment, TraceAttachment, TraceRecord


class _FakeBrowserController:
    def __init__(self, defaults: dict | None = None, attachment: dict | None = None) -> None:
        self._defaults = dict(defaults or {})
        self._attachment = dict(attachment or {}) if isinstance(attachment, dict) else None
        self.attachment_updates: list[dict | None] = []

    def get_global_metrics_defaults(self) -> dict:
        return dict(self._defaults)

    def get_dc_trace_attachment(self) -> dict | None:
        return None if self._attachment is None else dict(self._attachment)

    def set_dc_trace_attachment(self, payload: dict | None) -> None:
        normalized = None if payload is None else dict(payload)
        self._attachment = normalized
        self.attachment_updates.append(normalized)


def _build_app(*, with_stack: bool, defaults: dict | None = None, attachment: dict | None = None):
    warnings: list[tuple[str, str]] = []
    info_logs: list[str] = []
    error_logs: list[str] = []
    statuses: list[str] = []
    metrics_requests: list[str] = []
    preview_targets: list[int] = []

    class _Scale:
        def set(self, value: int) -> None:
            preview_targets.append(int(value))

    return SimpleNamespace(
        reader=object() if with_stack else None,
        stack_info=SimpleNamespace(frame_count=20, input_dir="/tmp/stack") if with_stack else None,
        browser_controller=_FakeBrowserController(defaults=defaults, attachment=attachment),
        root=SimpleNamespace(after=lambda _delay, fn: fn()),
        preview_scale=_Scale(),
        current_frame_idx=0,
        _show_warning=lambda title, text: warnings.append((str(title), str(text))),
        _open_generate_metrics_popup=lambda: metrics_requests.append("open"),
        _update_preview=lambda frame_idx: preview_targets.append(int(frame_idx)),
        _set_status=lambda text: statuses.append(str(text)),
        _log_info=lambda text: info_logs.append(str(text)),
        _log_error=lambda text: error_logs.append(str(text)),
        warnings=warnings,
        info_logs=info_logs,
        error_logs=error_logs,
        statuses=statuses,
        metrics_requests=metrics_requests,
        preview_targets=preview_targets,
        events=[],
    )


def test_import_dc_trace_blocks_without_stack() -> None:
    app = _build_app(with_stack=False)
    controller = HostDCTraceController(app)

    controller.import_dc_trace()

    assert app.warnings
    assert app.warnings[-1][0] == "Import DC Trace"
    assert "Load a stack first" in app.warnings[-1][1]


def test_import_dc_trace_requires_explicit_project_fps(monkeypatch) -> None:
    app = _build_app(with_stack=True, defaults={})
    controller = HostDCTraceController(app)
    monkeypatch.setattr("swell.host.controllers.dc_trace_controller.messagebox.askyesno", lambda *args, **kwargs: True)

    controller.import_dc_trace()

    assert app.metrics_requests == ["open"]
    assert app.warnings == []


def test_trace_frame_mapping_round_trip_uses_manual_offset() -> None:
    app = _build_app(with_stack=True, defaults={"frames_per_sec": 2.0})
    controller = HostDCTraceController(app)
    controller._attachment = TraceAttachment(
        source_type="wavesurfer_h5",
        source_path="/tmp/dc.h5",
        channel_index=0,
        channel_name="LFP 1",
        sample_rate_hz=10.0,
        unit="mV",
        alignment=TimeAlignment(mode="manual_offset", offset_s=1.25),
    )
    controller._trace_record = TraceRecord(
        source_type="wavesurfer_h5",
        channel_names=["LFP 1"],
        units=["mV"],
        sample_rate_hz=10.0,
        timestamps_s=None,
        signals=np.arange(100, dtype=np.float64).reshape(-1, 1),
        segments=[(0, 100)],
        start_time_s=0.0,
        metadata={},
    )

    trace_time = controller.get_trace_time_for_frame(6)
    frame_idx = controller.get_frame_for_trace_time(4.25)
    value = controller.get_trace_value_at_frame(6)

    assert trace_time == 4.25
    assert frame_idx == 6
    assert value is not None


def test_trace_frame_mapping_rejects_non_finite_times() -> None:
    app = _build_app(with_stack=True, defaults={"frames_per_sec": 2.0})
    controller = HostDCTraceController(app)
    controller._attachment = TraceAttachment(
        source_type="wavesurfer_h5", source_path="/tmp/dc.h5", channel_index=0,
        channel_name="LFP 1", sample_rate_hz=10.0, unit="mV", alignment=TimeAlignment(),
    )

    assert controller.get_frame_for_trace_time(float("nan")) is None
    assert controller.get_frame_for_trace_time(float("inf")) is None


def test_remove_dc_trace_clears_runtime_and_project_metadata() -> None:
    app = _build_app(with_stack=True, defaults={"frames_per_sec": 2.0})
    controller = HostDCTraceController(app)
    controller._attachment = TraceAttachment(
        source_type="wavesurfer_h5",
        source_path="/tmp/dc.h5",
        channel_index=0,
        channel_name="LFP 1",
        sample_rate_hz=10.0,
        unit="mV",
        alignment=TimeAlignment(mode="manual_offset", offset_s=0.0),
    )
    controller._trace_record = TraceRecord(
        source_type="wavesurfer_h5",
        channel_names=["LFP 1"],
        units=["mV"],
        sample_rate_hz=10.0,
        timestamps_s=None,
        signals=np.arange(10, dtype=np.float64).reshape(-1, 1),
        segments=[(0, 10)],
        start_time_s=0.0,
        metadata={},
    )

    controller.remove_dc_trace()

    assert controller._attachment is None
    assert controller._trace_record is None
    assert app.browser_controller.attachment_updates[-1] is None


def test_display_trace_window_filters_spikes_and_downsamples() -> None:
    app = _build_app(with_stack=True, defaults={"frames_per_sec": 10.0})
    controller = HostDCTraceController(app)
    controller._attachment = TraceAttachment(
        source_type="wavesurfer_h5",
        source_path="/tmp/dc.h5",
        channel_index=0,
        channel_name="DC",
        sample_rate_hz=1000.0,
        unit="mV",
        alignment=TimeAlignment(mode="manual_offset", offset_s=0.0),
    )
    signal = np.zeros(2000, dtype=np.float64)
    signal[1000] = 1000.0
    controller._trace_record = TraceRecord(
        source_type="wavesurfer_h5",
        channel_names=["DC"],
        units=["mV"],
        sample_rate_hz=1000.0,
        timestamps_s=None,
        signals=signal.reshape(-1, 1),
        segments=[(0, 2000)],
        start_time_s=0.0,
        metadata={},
    )

    times, display = controller._display_trace_window((0.0, 2.0))

    assert len(times) == len(display)
    assert len(display) < len(signal)
    assert float(np.nanmax(display)) < 1000.0


def test_update_for_frame_coalesces_pending_cursor_updates() -> None:
    scheduled: dict[str, object] = {}

    class _Root:
        def after(self, delay_ms: int, callback):
            scheduled["delay_ms"] = int(delay_ms)
            scheduled["callback"] = callback
            return "after-id"

        def after_cancel(self, _after_id) -> None:
            return

    app = _build_app(with_stack=True, defaults={"frames_per_sec": 10.0})
    app.root = _Root()
    controller = HostDCTraceController(app)
    controller._attachment = TraceAttachment(
        source_type="wavesurfer_h5",
        source_path="/tmp/dc.h5",
        channel_index=0,
        channel_name="DC",
        sample_rate_hz=100.0,
        unit="mV",
        alignment=TimeAlignment(mode="manual_offset", offset_s=0.0),
    )
    controller._trace_record = TraceRecord(
        source_type="wavesurfer_h5",
        channel_names=["DC"],
        units=["mV"],
        sample_rate_hz=100.0,
        timestamps_s=None,
        signals=np.arange(100, dtype=np.float64).reshape(-1, 1),
        segments=[(0, 100)],
        start_time_s=0.0,
        metadata={},
    )
    flushed: list[int] = []
    controller._update_cursor = lambda frame_idx: flushed.append(int(frame_idx))  # type: ignore[method-assign]

    controller.update_for_frame(3)
    controller.update_for_frame(7)

    assert scheduled["delay_ms"] == 16
    assert flushed == []
    scheduled["callback"]()
    assert flushed == [7]


def test_update_cursor_uses_blit_when_background_available() -> None:
    app = _build_app(with_stack=True, defaults={"frames_per_sec": 10.0})
    controller = HostDCTraceController(app)
    controller._panel_visible = True
    controller._attachment = TraceAttachment(
        source_type="wavesurfer_h5",
        source_path="/tmp/dc.h5",
        channel_index=0,
        channel_name="DC",
        sample_rate_hz=100.0,
        unit="mV",
        alignment=TimeAlignment(mode="manual_offset", offset_s=0.0),
    )

    class _Artist:
        def __init__(self) -> None:
            self.xdata = None

        def set_xdata(self, value) -> None:
            self.xdata = list(value)

    class _Axes:
        def __init__(self) -> None:
            self.bbox = object()
            self.drawn: list[object] = []

        def draw_artist(self, artist) -> None:
            self.drawn.append(artist)

    class _Canvas:
        def __init__(self) -> None:
            self.restored: list[object] = []
            self.blitted: list[object] = []
            self.draw_idle_calls = 0

        def restore_region(self, background) -> None:
            self.restored.append(background)

        def blit(self, bbox) -> None:
            self.blitted.append(bbox)

        def draw_idle(self) -> None:
            self.draw_idle_calls += 1

    controller._cursor_artist = _Artist()
    controller._axes = _Axes()
    controller._canvas = _Canvas()
    controller._cursor_background = object()

    controller._update_cursor(5)

    assert controller._cursor_artist.xdata == [0.5, 0.5]
    assert len(controller._canvas.restored) == 1
    assert len(controller._canvas.blitted) == 1
    assert controller._canvas.draw_idle_calls == 0
