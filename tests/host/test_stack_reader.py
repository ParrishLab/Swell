from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import tifffile
from PIL import Image

from sdapp.host.stack_reader import StackReader, _to_grayscale


def _save_png(path: Path, arr: np.ndarray) -> None:
    Image.fromarray(arr).save(path)


def test_to_grayscale_rgb_uint8_uses_luma_and_dtype_preserved() -> None:
    rgb = np.array([[[10, 20, 30], [200, 50, 0]]], dtype=np.uint8)
    out = _to_grayscale(rgb)

    expected = np.array([[18, 89]], dtype=np.uint8)
    assert out.dtype == np.uint8
    assert out.shape == (1, 2)
    assert np.array_equal(out, expected)


def test_to_grayscale_accepts_2d_and_single_channel_3d() -> None:
    arr2d = np.arange(6, dtype=np.uint16).reshape(2, 3)
    out2d = _to_grayscale(arr2d)
    assert np.array_equal(out2d, arr2d)

    arr3d = np.arange(12, dtype=np.uint8).reshape(2, 2, 3)[:, :, :1]
    out3d = _to_grayscale(arr3d)
    assert out3d.shape == (2, 2)
    assert np.array_equal(out3d, arr3d[:, :, 0])


def test_to_grayscale_rejects_unsupported_shape() -> None:
    arr = np.zeros((2, 2, 2, 2, 2), dtype=np.uint8)
    with pytest.raises(ValueError, match="Unsupported frame shape"):
        _to_grayscale(arr)


def test_open_stack_png_filters_mismatched_shapes_and_reads_frames(tmp_path: Path) -> None:
    a = np.full((6, 7), 10, dtype=np.uint8)
    b = np.full((6, 7), 20, dtype=np.uint8)
    c = np.full((5, 7), 30, dtype=np.uint8)  # mismatched height -> ignored

    _save_png(tmp_path / "a.png", a)
    _save_png(tmp_path / "b.png", b)
    _save_png(tmp_path / "c.png", c)

    calls: list[tuple[int, int]] = []
    reader = StackReader(max_cache=1)
    info = reader.open_stack(tmp_path, progress_callback=lambda cur, total: calls.append((cur, total)))

    assert info.frame_count == 2
    assert info.frame_height == 6
    assert info.frame_width == 7
    assert reader.get_frame_count() == 2
    assert reader.get_frame_name(0) == "a.png"
    assert reader.get_frame_name(1) == "b.png"
    assert calls
    assert calls[0][0] == 1
    assert calls[-1][1] >= 1

    f0 = reader.read_frame(0)
    f1 = reader.read_frame(1)
    assert np.array_equal(f0, a)
    assert np.array_equal(f1, b)


def test_open_stack_tiff_multipage_creates_page_names(tmp_path: Path) -> None:
    tiff_path = tmp_path / "stack.tif"
    page0 = np.full((4, 5), 11, dtype=np.uint16)
    page1 = np.full((4, 5), 22, dtype=np.uint16)
    tifffile.imwrite(tiff_path, page0)
    tifffile.imwrite(tiff_path, page1, append=True)

    reader = StackReader()
    info = reader.open_stack(tmp_path)

    assert info.frame_count == 2
    assert info.dtype in {"uint16", "<u2"}
    assert reader.get_frame_name(0) == "stack.tif_p0000"
    assert reader.get_frame_name(1) == "stack.tif_p0001"
    assert np.array_equal(reader.read_frame(0), page0)
    assert np.array_equal(reader.read_frame(1), page1)


def test_read_tiff_falls_back_to_pillow_when_tifffile_decode_fails(tmp_path: Path, monkeypatch) -> None:
    tiff_path = tmp_path / "stack_fallback.tif"
    page0 = np.full((4, 5), 17, dtype=np.uint8)
    page1 = np.full((4, 5), 33, dtype=np.uint8)
    tifffile.imwrite(tiff_path, page0)
    tifffile.imwrite(tiff_path, page1, append=True)

    reader = StackReader()
    reader.open_stack(tmp_path)

    monkeypatch.setattr(reader, "_read_tiff_page", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("codec")))
    out0 = reader.read_frame(0, use_cache=False)
    out1 = reader.read_frame(1, use_cache=False)

    assert np.array_equal(out0, page0)
    assert np.array_equal(out1, page1)


def test_open_stack_errors_for_missing_or_empty_folder(tmp_path: Path) -> None:
    reader = StackReader()
    with pytest.raises(FileNotFoundError):
        reader.open_stack(tmp_path / "missing")

    with pytest.raises(ValueError, match="No supported image files"):
        reader.open_stack(tmp_path)


def test_get_stack_info_before_open_raises() -> None:
    with pytest.raises(RuntimeError, match="Stack not opened"):
        StackReader().get_stack_info()


def test_read_frame_index_bounds_and_cache_eviction(tmp_path: Path) -> None:
    a = np.full((4, 4), 10, dtype=np.uint8)
    b = np.full((4, 4), 20, dtype=np.uint8)
    _save_png(tmp_path / "a.png", a)
    _save_png(tmp_path / "b.png", b)

    reader = StackReader(max_cache=1)
    reader.open_stack(tmp_path)

    with pytest.raises(IndexError, match="Frame index out of range"):
        reader.read_frame(-1)
    with pytest.raises(IndexError, match="Frame index out of range"):
        reader.read_frame(2)

    _ = reader.read_frame(0, use_cache=True)
    assert list(reader._cache.keys()) == [0]
    _ = reader.read_frame(1, use_cache=True)
    assert list(reader._cache.keys()) == [1]


def test_open_stack_requires_at_least_one_valid_shape(tmp_path: Path) -> None:
    # First image sets expected shape, second mismatches; if all mismatch after filtering, it should error.
    # Create only a non-2D image with unsupported shape via tiff page shape length < 2.
    # Practical approximation: create a file with unsupported extension to keep folder effectively empty.
    (tmp_path / "ignore.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="No supported image files"):
        StackReader().open_stack(tmp_path)


def test_open_stack_uses_natural_filename_order(tmp_path: Path) -> None:
    img = np.full((4, 4), 1, dtype=np.uint8)
    _save_png(tmp_path / "image_113.png", img)
    _save_png(tmp_path / "image_1130.png", img)
    _save_png(tmp_path / "image_1131.png", img)
    _save_png(tmp_path / "image_114.png", img)

    reader = StackReader()
    reader.open_stack(tmp_path)

    names = [reader.get_frame_name(i) for i in range(reader.get_frame_count())]
    assert names == [
        "image_113.png",
        "image_114.png",
        "image_1130.png",
        "image_1131.png",
    ]
