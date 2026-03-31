from __future__ import annotations

from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from sdapp.host.preview_controller import HostPreviewController


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
        preview_overlay=None,
        preview_scale=None,
        dc_trace_controller=SimpleNamespace(update_for_frame=lambda _idx: None),
        _main_render_cache=OrderedDict(),
        _main_render_cache_max=24,
        _normalized_frame_u8_cache=OrderedDict(),
        _normalized_frame_u8_cache_max=64,
        _normalized_frame_u8_cache_max_bytes=8 * 1024 * 1024,
        _mark_mini_canvas=_Canvas(),
        _mark_mini_frame=SimpleNamespace(),
        _mark_popup_mini_image=None,
        _trim_numpy_cache_by_bytes=lambda _cache, _max_bytes: None,
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

    with patch("sdapp.host.preview_controller.ImageTk.PhotoImage", side_effect=lambda image: ("photo", image.size)):
        controller.update_popup_mini_raw(1)

    assert app.reader.read_calls == [1]
    assert normalize_calls == [(1, "default")]
    assert len(app._mark_mini_canvas.images) == 1
