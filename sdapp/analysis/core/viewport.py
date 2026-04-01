from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass
class ViewportState:
    center_x: float = 0.0
    center_y: float = 0.0
    zoom_factor: float = 1.0
    min_zoom: float = 1.0
    max_zoom: float = 12.0


@dataclass
class ViewportTransform:
    canvas_width: int
    canvas_height: int
    image_width: int
    image_height: int
    fit_scale: float
    scale: float
    offset_x: float
    offset_y: float
    zoom_factor: float
    center_x: float
    center_y: float

    def image_to_canvas(self, x: float, y: float) -> tuple[float, float]:
        return (float(x) * self.scale + self.offset_x, float(y) * self.scale + self.offset_y)

    def canvas_to_image(self, x: float, y: float) -> tuple[float, float]:
        if self.scale <= 1e-9:
            return float(self.center_x), float(self.center_y)
        return ((float(x) - self.offset_x) / self.scale, (float(y) - self.offset_y) / self.scale)

    @property
    def visible_width_image(self) -> float:
        if self.scale <= 1e-9:
            return float(self.image_width)
        return float(self.canvas_width) / float(self.scale)

    @property
    def visible_height_image(self) -> float:
        if self.scale <= 1e-9:
            return float(self.image_height)
        return float(self.canvas_height) / float(self.scale)


def clamp_zoom(zoom_factor: float, *, min_zoom: float, max_zoom: float) -> float:
    value = float(zoom_factor)
    return max(float(min_zoom), min(float(max_zoom), value))


def compute_fit_scale(canvas_width: int, canvas_height: int, image_width: int, image_height: int) -> float:
    cw = max(1, int(canvas_width))
    ch = max(1, int(canvas_height))
    iw = max(1, int(image_width))
    ih = max(1, int(image_height))
    return min(float(cw) / float(iw), float(ch) / float(ih), 1.0)


def compute_transform(
    state: ViewportState,
    *,
    canvas_width: int,
    canvas_height: int,
    image_width: int,
    image_height: int,
) -> ViewportTransform:
    fit_scale = compute_fit_scale(canvas_width, canvas_height, image_width, image_height)
    scale = max(1e-6, float(fit_scale) * float(state.zoom_factor))
    offset_x = (float(canvas_width) / 2.0) - float(state.center_x) * scale
    offset_y = (float(canvas_height) / 2.0) - float(state.center_y) * scale
    return ViewportTransform(
        canvas_width=max(1, int(canvas_width)),
        canvas_height=max(1, int(canvas_height)),
        image_width=max(1, int(image_width)),
        image_height=max(1, int(image_height)),
        fit_scale=float(fit_scale),
        scale=float(scale),
        offset_x=float(offset_x),
        offset_y=float(offset_y),
        zoom_factor=float(state.zoom_factor),
        center_x=float(state.center_x),
        center_y=float(state.center_y),
    )


def fit_viewport(image_width: int, image_height: int, *, min_zoom: float = 1.0, max_zoom: float = 12.0) -> ViewportState:
    iw = max(1, int(image_width))
    ih = max(1, int(image_height))
    return ViewportState(
        center_x=float(iw) / 2.0,
        center_y=float(ih) / 2.0,
        zoom_factor=clamp_zoom(1.0, min_zoom=min_zoom, max_zoom=max_zoom),
        min_zoom=float(min_zoom),
        max_zoom=float(max_zoom),
    )


def clamp_viewport_center(
    state: ViewportState,
    *,
    image_width: int,
    image_height: int,
    canvas_sizes: Iterable[tuple[int, int]],
) -> ViewportState:
    iw = max(1, int(image_width))
    ih = max(1, int(image_height))
    zoom = clamp_zoom(state.zoom_factor, min_zoom=state.min_zoom, max_zoom=state.max_zoom)

    lower_x = 0.0
    upper_x = float(iw)
    lower_y = 0.0
    upper_y = float(ih)
    has_sizes = False
    for canvas_width, canvas_height in canvas_sizes:
        cw = max(1, int(canvas_width))
        ch = max(1, int(canvas_height))
        fit_scale = compute_fit_scale(cw, ch, iw, ih)
        scale = max(1e-6, float(fit_scale) * float(zoom))
        visible_w = float(cw) / scale
        visible_h = float(ch) / scale

        half_w = min(float(iw) / 2.0, visible_w / 2.0)
        half_h = min(float(ih) / 2.0, visible_h / 2.0)
        lower_x = max(lower_x, half_w)
        upper_x = min(upper_x, float(iw) - half_w)
        lower_y = max(lower_y, half_h)
        upper_y = min(upper_y, float(ih) - half_h)
        has_sizes = True

    if not has_sizes:
        lower_x = upper_x = float(iw) / 2.0
        lower_y = upper_y = float(ih) / 2.0

    if lower_x > upper_x:
        lower_x = upper_x = float(iw) / 2.0
    if lower_y > upper_y:
        lower_y = upper_y = float(ih) / 2.0

    center_x = min(max(float(state.center_x), lower_x), upper_x)
    center_y = min(max(float(state.center_y), lower_y), upper_y)
    return ViewportState(
        center_x=float(center_x),
        center_y=float(center_y),
        zoom_factor=float(zoom),
        min_zoom=float(state.min_zoom),
        max_zoom=float(state.max_zoom),
    )


def zoom_viewport_at(
    state: ViewportState,
    *,
    image_width: int,
    image_height: int,
    canvas_width: int,
    canvas_height: int,
    anchor_canvas_x: float,
    anchor_canvas_y: float,
    new_zoom_factor: float,
    shared_canvas_sizes: Iterable[tuple[int, int]],
) -> ViewportState:
    current = compute_transform(
        state,
        canvas_width=canvas_width,
        canvas_height=canvas_height,
        image_width=image_width,
        image_height=image_height,
    )
    anchor_img_x, anchor_img_y = current.canvas_to_image(anchor_canvas_x, anchor_canvas_y)
    next_state = ViewportState(
        center_x=float(state.center_x),
        center_y=float(state.center_y),
        zoom_factor=clamp_zoom(new_zoom_factor, min_zoom=state.min_zoom, max_zoom=state.max_zoom),
        min_zoom=float(state.min_zoom),
        max_zoom=float(state.max_zoom),
    )
    next_transform = compute_transform(
        next_state,
        canvas_width=canvas_width,
        canvas_height=canvas_height,
        image_width=image_width,
        image_height=image_height,
    )
    next_state.center_x = float(anchor_img_x) - ((float(anchor_canvas_x) - (float(canvas_width) / 2.0)) / next_transform.scale)
    next_state.center_y = float(anchor_img_y) - ((float(anchor_canvas_y) - (float(canvas_height) / 2.0)) / next_transform.scale)
    return clamp_viewport_center(
        next_state,
        image_width=image_width,
        image_height=image_height,
        canvas_sizes=shared_canvas_sizes,
    )


def pan_viewport(
    state: ViewportState,
    *,
    image_width: int,
    image_height: int,
    canvas_width: int,
    canvas_height: int,
    delta_canvas_x: float,
    delta_canvas_y: float,
    shared_canvas_sizes: Iterable[tuple[int, int]],
) -> ViewportState:
    transform = compute_transform(
        state,
        canvas_width=canvas_width,
        canvas_height=canvas_height,
        image_width=image_width,
        image_height=image_height,
    )
    next_state = ViewportState(
        center_x=float(state.center_x) - (float(delta_canvas_x) / transform.scale),
        center_y=float(state.center_y) - (float(delta_canvas_y) / transform.scale),
        zoom_factor=float(state.zoom_factor),
        min_zoom=float(state.min_zoom),
        max_zoom=float(state.max_zoom),
    )
    return clamp_viewport_center(
        next_state,
        image_width=image_width,
        image_height=image_height,
        canvas_sizes=shared_canvas_sizes,
    )
