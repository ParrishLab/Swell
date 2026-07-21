from __future__ import annotations

import numpy as np
import pytest
from PIL import Image, ImageOps

from swell.shared.frame_source.image_decoding import (
    apply_orientation,
    array_frame_layout,
    array_to_gray_frames,
    oriented_pil_shape,
    pil_image_to_gray,
)


@pytest.mark.parametrize("orientation", range(1, 9))
def test_apply_orientation_matches_pillow_exif_semantics(orientation: int) -> None:
    pixels = np.arange(12, dtype=np.uint8).reshape(3, 4)
    image = Image.fromarray(pixels)
    exif = Image.Exif()
    exif[274] = orientation
    image.info["exif"] = exif.tobytes()

    expected = np.asarray(ImageOps.exif_transpose(image))

    np.testing.assert_array_equal(apply_orientation(pixels, orientation), expected)
    assert oriented_pil_shape(image) == expected.shape


@pytest.mark.parametrize(
    ("shape", "axes", "rgb", "expected_shape", "expected_count"),
    [
        ((5, 7, 3), "YXS", True, (5, 7), 1),
        ((3, 5, 7), "SYX", True, (5, 7), 1),
        ((4, 5, 7), "CYX", False, (5, 7), 1),
        ((2, 4, 5, 7), "TCYX", False, (5, 7), 2),
        ((2, 3, 5, 7), "TZYX", False, (5, 7), 6),
    ],
)
def test_array_axis_matrix(
    shape: tuple[int, ...],
    axes: str,
    rgb: bool,
    expected_shape: tuple[int, int],
    expected_count: int,
) -> None:
    image = np.arange(np.prod(shape), dtype=np.float32).reshape(shape)

    layout = array_frame_layout(shape, axes=axes, rgb=rgb)
    frames = array_to_gray_frames(image, axes=axes, rgb=rgb)

    assert layout == (expected_shape, expected_count)
    assert len(frames) == expected_count
    assert all(frame.shape == expected_shape for frame in frames)
    assert all(np.all(np.isfinite(frame)) for frame in frames)


def test_channel_first_and_channel_last_rgb_are_equivalent() -> None:
    channel_last = np.zeros((4, 6, 3), dtype=np.uint16)
    channel_last[:, :, 0] = 1000
    channel_last[:, :, 1] = 2000
    channel_last[:, :, 2] = 3000
    channel_first = np.moveaxis(channel_last, -1, 0)

    yxs = array_to_gray_frames(channel_last, axes="YXS", rgb=True)[0]
    syx = array_to_gray_frames(channel_first, axes="SYX", rgb=True)[0]

    np.testing.assert_array_equal(yxs, syx)
    assert yxs.dtype == np.uint16


@pytest.mark.parametrize("mode", ["P", "CMYK", "RGBA"])
def test_pillow_color_modes_decode_to_one_grayscale_frame(mode: str) -> None:
    rgb = np.zeros((4, 5, 3), dtype=np.uint8)
    rgb[:, :, 0] = 200
    image = Image.fromarray(rgb).convert(mode)

    result = pil_image_to_gray(image)

    assert result.shape == (4, 5)
    assert result.dtype == np.uint8


def test_pillow_uint16_grayscale_preserves_dtype_and_values() -> None:
    pixels = np.array([[0, 1024], [4096, 65535]], dtype=np.uint16)
    image = Image.fromarray(pixels)

    result = pil_image_to_gray(image)

    np.testing.assert_array_equal(result, pixels)
    assert result.dtype == np.uint16
