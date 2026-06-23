from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

import swell.host.preview_controller as preview_controller_module
from swell.host.preview_controller import HostPreviewController
from swell.shared.lru_cache import LRUCache


class _Label:
    def __init__(self, width: int = 240, height: int = 180) -> None:
        self.width = width
        self.height = height
        self.configured: list[dict[str, object]] = []

    def winfo_width(self) -> int:
        return self.width

    def winfo_height(self) -> int:
        return self.height

    def configure(self, **kwargs) -> None:
        self.configured.append(dict(kwargs))


class _Canvas:
    def __init__(self, width: int = 120, height: int = 120) -> None:
        self.width = width
        self.height = height
        self.images: list[tuple[int, int, object, str]] = []

    def winfo_width(self) -> int:
        return self.width

    def winfo_height(self) -> int:
        return self.height

    def delete(self, _tag: str) -> None:
        self.images.clear()

    def create_image(self, x: int, y: int, image, anchor: str) -> None:
        self.images.append((int(x), int(y), image, str(anchor)))


class _InfoVar:
    def __init__(self) -> None:
        self.value = ""

    def set(self, value: str) -> None:
        self.value = str(value)


class _Reader:
    def __init__(self, frames: list[np.ndarray]) -> None:
        self.frames = [np.asarray(frame, dtype=np.float32) for frame in frames]
        self.read_calls: list[int] = []

    def read_frame(self, frame_idx: int, use_cache: bool = True) -> np.ndarray:
        del use_cache
        self.read_calls.append(int(frame_idx))
        return self.frames[int(frame_idx)]

    def get_frame_name(self, frame_idx: int) -> str:
        return f"f{int(frame_idx)}.tif"


def _build_app(frames: list[np.ndarray]) -> SimpleNamespace:
    return SimpleNamespace(
        reader=_Reader(frames),
        stack_info=SimpleNamespace(frame_count=len(frames)),
        current_frame_idx=0,
        preview_label=_Label(),
        preview_label_info=_InfoVar(),
        preview_label_meta=_InfoVar(),
        preview_overlay=None,
        preview_scale=None,
        dc_trace_controller=SimpleNamespace(update_for_frame=lambda _idx: None),
        _main_render_cache=LRUCache(max_items=24, gc_min_keep=8),
        _normalized_frame_u8_cache=LRUCache(max_items=64, max_bytes=8 * 1024 * 1024, gc_min_keep=16),
        _popup=SimpleNamespace(
            mark_mini_canvas=_Canvas(),
            mark_mini_frame=SimpleNamespace(),
            mark_popup_mini_image=None,
        ),
        _set_status=lambda *_args: None,
        _log_error=lambda *_args: None,
        _show_warning=lambda *_args: None,
    )


def test_update_preview_reuses_normalized_frame_when_resized() -> None:
    frames = [np.arange(64, dtype=np.float32).reshape(8, 8) for _ in range(3)]
    app = _build_app(frames)
    controller = HostPreviewController(app)
    render_calls: list[tuple[tuple[int, int], bool]] = []
    normalize_calls: list[tuple[int, str]] = []
    controller.redraw_main_overlay = lambda: None  # type: ignore[method-assign]
    controller.render_preview_image = (  # type: ignore[method-assign]
        lambda frame, label, fallback_size, pre_normalized=False, contrast_factor=1.0: (
            render_calls.append((tuple(np.asarray(frame).shape), bool(pre_normalized))),
            ("image", label.winfo_width(), label.winfo_height(), contrast_factor),
        )[1]
    )
    original_normalize = controller.normalize_frame_percentile

    def _counting_normalize(frame, cache_key=None):
        if cache_key is not None:
            normalize_calls.append(cache_key)
        return original_normalize(frame, cache_key=cache_key)

    controller.normalize_frame_percentile = _counting_normalize  # type: ignore[method-assign]

    controller.update_preview(1)
    app.preview_label.width = 320
    app.preview_label.height = 240
    controller.update_preview(1)

    assert app.reader.read_calls == [1]
    assert normalize_calls == [(1, "default")]
    assert len(render_calls) == 2
    assert all(pre_normalized for _shape, pre_normalized in render_calls)


def test_normalized_frame_cache_preserves_lru_cache_policy() -> None:
    frames = [np.full((4, 4), idx, dtype=np.float32) for idx in range(4)]
    app = _build_app(frames)
    app._normalized_frame_u8_cache = LRUCache(max_items=2, gc_min_keep=1)
    controller = HostPreviewController(app)

    out0 = controller.get_normalized_reader_frame(0)
    out1 = controller.get_normalized_reader_frame(1)
    out0_again = controller.get_normalized_reader_frame(0)
    out2 = controller.get_normalized_reader_frame(2)

    assert isinstance(app._normalized_frame_u8_cache, LRUCache)
    assert np.array_equal(out0, out0_again)
    assert len(app._normalized_frame_u8_cache) == 2
    assert (1, "default") not in app._normalized_frame_u8_cache
    assert (0, "default") in app._normalized_frame_u8_cache
    assert (2, "default") in app._normalized_frame_u8_cache
    assert app.reader.read_calls == [0, 1, 2]
    assert out2.shape == out0.shape


def test_main_render_cache_hit_promotes_lru_entry() -> None:
    frames = [np.full((4, 4), idx, dtype=np.float32) for idx in range(4)]
    app = _build_app(frames)
    app._main_render_cache = LRUCache(max_items=2, gc_min_keep=1)
    controller = HostPreviewController(app)
    controller.redraw_main_overlay = lambda: None  # type: ignore[method-assign]
    controller.render_preview_image = lambda *_args, **_kwargs: object()  # type: ignore[method-assign]

    controller.update_preview(0)
    controller.update_preview(1)
    controller.update_preview(0)
    controller.update_preview(2)

    cache_keys = set(app._main_render_cache.keys())
    assert (0, 228, 168) in cache_keys
    assert (1, 228, 168) not in cache_keys
    assert (2, 228, 168) in cache_keys


def test_preview_percentiles_use_sampled_pixels(monkeypatch) -> None:
    frame = np.arange(10_000, dtype=np.float32).reshape(100, 100)
    app = _build_app([frame])
    controller = HostPreviewController(app)
    sampled = np.asarray([0.0, 100.0, 200.0, 300.0], dtype=np.float32)
    calls: list[tuple[int, int]] = []

    def _sample(frame_arg):
        arr = np.asarray(frame_arg)
        calls.append(tuple(arr.shape))
        return sampled

    monkeypatch.setattr(preview_controller_module, "_sample_percentile_pixels", _sample)

    result = controller.normalize_frame_percentile(frame)

    assert calls == [(100, 100)]
    assert result.shape == frame.shape
    assert result.dtype == np.uint8


def test_popup_mini_reuses_main_preview_normalization_cache() -> None:
    frames = [np.arange(64, dtype=np.float32).reshape(8, 8) for _ in range(3)]
    app = _build_app(frames)
    controller = HostPreviewController(app)
    controller.redraw_main_overlay = lambda: None  # type: ignore[method-assign]
    controller.render_preview_image = lambda *_args, **_kwargs: ("image", 240, 180)  # type: ignore[method-assign]
    original_normalize = controller.normalize_frame_percentile
    normalize_calls: list[tuple[int, str]] = []

    def _counting_normalize(frame, cache_key=None):
        if cache_key is not None:
            normalize_calls.append(cache_key)
        return original_normalize(frame, cache_key=cache_key)

    controller.normalize_frame_percentile = _counting_normalize  # type: ignore[method-assign]

    controller.update_preview(1)

    with patch("swell.host.preview_controller.ImageTk.PhotoImage", side_effect=lambda image: ("photo", image.size)):
        controller.update_popup_mini_raw(1)

    assert app.reader.read_calls == [1]
    assert normalize_calls == [(1, "default")]
    assert len(app._popup.mark_mini_canvas.images) == 1


def test_schedule_main_preview_update_moves_live_cursor_before_render() -> None:
    frames = [np.arange(64, dtype=np.float32).reshape(8, 8) for _ in range(3)]
    redraw_calls: list[int] = []
    trace_calls: list[int] = []
    after_calls: list[tuple[int, object]] = []

    class _Root:
        def after(self, delay_ms: int, callback):
            after_calls.append((int(delay_ms), callback))
            return "after-id"

        def after_cancel(self, _after_id) -> None:
            return

    app = _build_app(frames)
    app.root = _Root()
    app.dc_trace_controller = SimpleNamespace(update_for_frame=lambda idx: trace_calls.append(int(idx)))
    controller = HostPreviewController(app)
    controller.redraw_main_overlay = lambda: redraw_calls.append(int(app.current_frame_idx))  # type: ignore[method-assign]

    controller.schedule_main_preview_update(2)

    assert app.current_frame_idx == 2
    assert redraw_calls == [2]
    assert trace_calls == [2]
    assert app._pending_main_frame_idx == 2
    assert after_calls and after_calls[0][0] == 16


def test_overlay_click_log_uses_visible_event_label() -> None:
    frames = [np.arange(64, dtype=np.float32).reshape(8, 8) for _ in range(5)]
    app = _build_app(frames)
    logs: list[str] = []
    active: list[str] = []
    selections: list[str] = []
    app.events = [SimpleNamespace(event_id="event_0001", label="Visible Event", start_idx=1, end_idx=3)]
    app.preview_overlay = _Canvas(width=100, height=20)
    app.preview_scale = SimpleNamespace(set=lambda _value: None)
    app.tree = SimpleNamespace(
        exists=lambda _event_id: True,
        selection_set=lambda event_id: selections.append(str(event_id)),
        see=lambda _event_id: None,
    )
    app._set_active_event_id = lambda event_id: active.append(str(event_id))
    app._log_info = lambda message: logs.append(str(message))
    controller = HostPreviewController(app)
    controller.update_preview = lambda _idx: None  # type: ignore[method-assign]

    controller.on_main_overlay_click(SimpleNamespace(x=50))

    assert active == ["event_0001"]
    assert selections == ["event_0001"]
    assert logs[-1] == "Overlay click: selected Visible Event and jumped to frame 1."
