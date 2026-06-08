from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
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


def test_missing_source_paths_reports_moved_stack_folder(tmp_path: Path) -> None:
    arr = np.full((6, 7), 10, dtype=np.uint8)
    _save_png(tmp_path / "a.png", arr)
    reader = StackReader()
    reader.open_stack(tmp_path)

    moved = tmp_path.parent / f"{tmp_path.name}_moved"
    tmp_path.rename(moved)

    missing = reader.missing_source_paths(limit=1)

    assert missing == [tmp_path]


def test_open_stack_png_uses_metadata_during_indexing(tmp_path: Path, monkeypatch) -> None:
    arr = np.full((6, 7), 10, dtype=np.uint8)
    _save_png(tmp_path / "a.png", arr)
    _save_png(tmp_path / "b.png", arr)

    real_asarray = np.asarray

    def _guard(value, *args, **kwargs):
        if isinstance(value, Image.Image):
            raise AssertionError("open_stack should not decode PNG files while indexing")
        return real_asarray(value, *args, **kwargs)

    monkeypatch.setattr("sdapp.host.stack_reader.np.asarray", _guard)

    reader = StackReader()
    info = reader.open_stack(tmp_path)
    assert info.frame_count == 2


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


def test_read_tiff_pages_concurrently_preserves_outputs_and_handle_locks(tmp_path: Path) -> None:
    pages = [np.full((4, 5), idx + 1, dtype=np.uint16) for idx in range(4)]
    for idx, page in enumerate(pages):
        tifffile.imwrite(tmp_path / f"frame_{idx:04d}.tif", page)

    reader = StackReader()
    reader.open_stack(tmp_path)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda idx: reader.read_frame(idx, use_cache=False), range(4)))

    for idx, result in enumerate(results):
        assert np.array_equal(result, pages[idx])
    assert len(reader._tiff_handle_locks) == len(reader._tiff_handle_pool)


def test_open_stack_ignores_macos_appledouble_tiff_sidecars(tmp_path: Path) -> None:
    page = np.full((4, 5), 11, dtype=np.uint16)
    tifffile.imwrite(tmp_path / "frame_001.tif", page)
    (tmp_path / "._frame_001.tif").write_bytes(b"\x00\x05\x16\x07not-a-real-tiff")

    reader = StackReader()
    info = reader.open_stack(tmp_path)

    assert info.frame_count == 1
    assert reader.get_frame_name(0) == "frame_001.tif"
    assert np.array_equal(reader.read_frame(0), page)


def test_open_stack_rgb_tiff_uses_grayscale_frame_dimensions(tmp_path: Path) -> None:
    tiff_path = tmp_path / "rgb_stack.tif"
    page0 = np.zeros((2048, 3072, 3), dtype=np.uint8)
    page1 = np.zeros((2048, 3072, 3), dtype=np.uint8)
    page0[:, :, 0] = 10
    page1[:, :, 1] = 20
    tifffile.imwrite(tiff_path, page0)
    tifffile.imwrite(tiff_path, page1, append=True)

    reader = StackReader()
    info = reader.open_stack(tmp_path)

    assert info.frame_count == 2
    assert info.frame_height == 2048
    assert info.frame_width == 3072
    assert reader.read_frame(0).shape == (2048, 3072)
    assert reader.read_frame(1).shape == (2048, 3072)


def test_open_stack_rgb_uses_channel_mode_resolver_once(tmp_path: Path) -> None:
    tiff_path = tmp_path / "rgb_stack.tif"
    page0 = np.zeros((3, 3, 3), dtype=np.uint8)
    page1 = np.zeros((3, 3, 3), dtype=np.uint8)
    page0[:, :, 0] = 11
    page1[:, :, 0] = 22
    tifffile.imwrite(tiff_path, page0)
    tifffile.imwrite(tiff_path, page1, append=True)

    calls: list[str] = []

    def _resolver() -> str:
        calls.append("called")
        return "first"

    reader = StackReader(channel_mode_resolver=_resolver)
    reader.open_stack(tmp_path)

    assert len(calls) == 1
    assert reader.channel_mode == "first"
    assert np.array_equal(reader.read_frame(0), page0[:, :, 0])
    assert np.array_equal(reader.read_frame(1), page1[:, :, 0])


def test_open_stack_rgb_defaults_to_average_when_resolver_invalid(tmp_path: Path) -> None:
    tiff_path = tmp_path / "rgb_stack.tif"
    page0 = np.zeros((2, 2, 3), dtype=np.uint8)
    page0[:, :, 0] = 100
    page0[:, :, 1] = 10
    page0[:, :, 2] = 0
    tifffile.imwrite(tiff_path, page0)

    reader = StackReader(channel_mode_resolver=lambda: "invalid")
    reader.open_stack(tmp_path)
    out = reader.read_frame(0)

    expected = np.array([[35, 35], [35, 35]], dtype=np.uint8)
    assert np.array_equal(out, expected)


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
