from __future__ import annotations

from math import prod
from typing import Iterable

import numpy as np
from PIL import Image, ImageOps


_SWAPPED_ORIENTATIONS = {5, 6, 7, 8}


def _orientation_value(value) -> int:
    try:
        orientation = int(value)
    except (TypeError, ValueError):
        return 1
    return orientation if 1 <= orientation <= 8 else 1


def pil_orientation(image: Image.Image) -> int:
    try:
        return _orientation_value(image.getexif().get(274, 1))
    except Exception:
        return 1


def oriented_pil_shape(image: Image.Image) -> tuple[int, int] | None:
    try:
        width, height = (int(v) for v in image.size)
    except Exception:
        return None
    if width <= 0 or height <= 0:
        return None
    if pil_orientation(image) in _SWAPPED_ORIENTATIONS:
        width, height = height, width
    return height, width


def tiff_page_orientation(page) -> int:
    try:
        tag = page.tags.get("Orientation")
        return _orientation_value(tag.value if tag is not None else 1)
    except Exception:
        return 1


def tiff_page_is_rgb(page) -> bool:
    try:
        photometric = getattr(page, "photometric", None)
        name = str(getattr(photometric, "name", photometric) or "").upper()
        return name == "RGB" or int(photometric) == 2
    except Exception:
        return False


def _normalized_axes(axes, ndim: int) -> str | None:
    text = str(axes or "").upper()
    if len(text) != int(ndim):
        return None
    return text


def _layout(
    shape: Iterable[int],
    *,
    axes: str | None,
    rgb: bool,
) -> tuple[int, int, int, int | None] | None:
    dims = tuple(int(v) for v in shape)
    if any(v <= 0 for v in dims) or len(dims) < 2:
        return None
    normalized_axes = _normalized_axes(axes, len(dims))
    if normalized_axes is not None and "Y" in normalized_axes and "X" in normalized_axes:
        y_axis = normalized_axes.index("Y")
        x_axis = normalized_axes.index("X")
        channel_axis = None
        for label in ("S", "C"):
            if label in normalized_axes:
                candidate = normalized_axes.index(label)
                if candidate not in {y_axis, x_axis}:
                    channel_axis = candidate
                    break
        frame_axes = [idx for idx in range(len(dims)) if idx not in {y_axis, x_axis, channel_axis}]
        frame_count = int(prod(dims[idx] for idx in frame_axes)) if frame_axes else 1
        return int(dims[y_axis]), int(dims[x_axis]), frame_count, channel_axis

    if len(dims) == 2:
        return int(dims[0]), int(dims[1]), 1, None
    if len(dims) == 3 and (bool(rgb) or int(dims[-1]) in (3, 4)):
        return int(dims[0]), int(dims[1]), 1, 2
    if len(dims) == 3:
        return int(dims[1]), int(dims[2]), int(dims[0]), None
    return None


def array_frame_layout(
    shape: Iterable[int],
    *,
    axes: str | None = None,
    rgb: bool = False,
    orientation: int = 1,
) -> tuple[tuple[int, int], int] | None:
    layout = _layout(shape, axes=axes, rgb=bool(rgb))
    if layout is None:
        return None
    height, width, frame_count, _channel_axis = layout
    if _orientation_value(orientation) in _SWAPPED_ORIENTATIONS:
        height, width = width, height
    return (int(height), int(width)), int(frame_count)


def apply_orientation(frame: np.ndarray, orientation: int) -> np.ndarray:
    arr = np.asarray(frame)
    value = _orientation_value(orientation)
    if value == 2:
        return np.fliplr(arr)
    if value == 3:
        return np.rot90(arr, 2)
    if value == 4:
        return np.flipud(arr)
    if value == 5:
        return np.transpose(arr)
    if value == 6:
        return np.rot90(arr, -1)
    if value == 7:
        return np.flip(np.transpose(arr), axis=(0, 1))
    if value == 8:
        return np.rot90(arr, 1)
    return arr


def _channels_to_gray(frame: np.ndarray, *, channel_mode: str, rgb: bool) -> np.ndarray:
    arr = np.asarray(frame)
    if arr.ndim != 3:
        raise ValueError(f"Expected a channel image, got shape {arr.shape}.")
    channel_count = int(arr.shape[2])
    if channel_count <= 0:
        raise ValueError("Image has no channels.")
    if str(channel_mode).lower() == "first" or channel_count == 1:
        return arr[:, :, 0]
    work = arr.astype(np.float32, copy=False)
    if bool(rgb) and channel_count >= 3:
        weights = np.array([0.299, 0.587, 0.114], dtype=np.float32)
        gray = np.tensordot(work[:, :, :3], weights, axes=([-1], [0]))
    else:
        gray = np.mean(work, axis=2)
    if np.issubdtype(arr.dtype, np.integer):
        info = np.iinfo(arr.dtype)
        gray = np.clip(gray, info.min, info.max)
    return gray.astype(arr.dtype)


def array_to_gray_frames(
    image: np.ndarray,
    *,
    axes: str | None = None,
    rgb: bool = False,
    channel_mode: str = "average",
    orientation: int = 1,
) -> list[np.ndarray]:
    arr = np.asarray(image)
    layout = _layout(arr.shape, axes=axes, rgb=bool(rgb))
    if layout is None:
        return []
    _height, _width, _frame_count, channel_axis = layout
    normalized_axes = _normalized_axes(axes, arr.ndim)

    if normalized_axes is not None and "Y" in normalized_axes and "X" in normalized_axes:
        y_axis = normalized_axes.index("Y")
        x_axis = normalized_axes.index("X")
        frame_axes = [idx for idx in range(arr.ndim) if idx not in {y_axis, x_axis, channel_axis}]
        order = frame_axes + [y_axis, x_axis]
        if channel_axis is not None:
            order.append(channel_axis)
        arranged = np.transpose(arr, order)
        if channel_axis is None:
            arranged = arranged.reshape((-1, arranged.shape[-2], arranged.shape[-1]))
            frames = [arranged[idx] for idx in range(arranged.shape[0])]
        else:
            arranged = arranged.reshape((-1, arranged.shape[-3], arranged.shape[-2], arranged.shape[-1]))
            frames = [
                _channels_to_gray(arranged[idx], channel_mode=channel_mode, rgb=bool(rgb))
                for idx in range(arranged.shape[0])
            ]
    elif arr.ndim == 2:
        frames = [arr]
    elif arr.ndim == 3 and channel_axis == 2:
        frames = [_channels_to_gray(arr, channel_mode=channel_mode, rgb=bool(rgb) or arr.shape[2] in (3, 4))]
    elif arr.ndim == 3:
        frames = [arr[idx] for idx in range(arr.shape[0])]
    else:
        return []

    return [np.ascontiguousarray(apply_orientation(frame, orientation)) for frame in frames]


def pil_image_to_gray(image: Image.Image, *, channel_mode: str = "average") -> np.ndarray:
    oriented = ImageOps.exif_transpose(image)
    mode = str(oriented.mode or "").upper()
    if mode in {"RGB", "RGBA"}:
        arr = np.array(oriented, copy=True)
        return array_to_gray_frames(arr, rgb=True, channel_mode=channel_mode)[0]
    if mode in {"1", "L", "I", "F", "I;16", "I;16B", "I;16L", "I;16N"}:
        arr = np.array(oriented, copy=True)
        if arr.ndim == 2:
            return arr
    converted = oriented.convert("RGB")
    arr = np.array(converted, copy=True)
    return array_to_gray_frames(arr, rgb=True, channel_mode=channel_mode)[0]
