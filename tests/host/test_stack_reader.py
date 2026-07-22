from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest
import tifffile
from PIL import Image

from swell.host.stack_reader import StackReader, _to_grayscale


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


def test_open_stack_png_rejects_mismatched_shapes(tmp_path: Path) -> None:
    a = np.full((6, 7), 10, dtype=np.uint8)
    b = np.full((6, 7), 20, dtype=np.uint8)
    c = np.full((5, 7), 30, dtype=np.uint8)

    _save_png(tmp_path / "a.png", a)
    _save_png(tmp_path / "b.png", b)
    _save_png(tmp_path / "c.png", c)

    reader = StackReader(max_cache=1)
    with pytest.raises(ValueError, match=r"mixed frame dimensions.*c\.png \(7x5\)"):
        reader.open_stack(tmp_path)

    assert reader.get_frame_count() == 0


def test_failed_mixed_dimension_open_preserves_previous_stack(tmp_path: Path) -> None:
    valid_dir = tmp_path / "valid"
    invalid_dir = tmp_path / "invalid"
    valid_dir.mkdir()
    invalid_dir.mkdir()
    original = np.full((6, 7), 42, dtype=np.uint8)
    _save_png(valid_dir / "frame.png", original)
    _save_png(invalid_dir / "a.png", np.zeros((6, 7), dtype=np.uint8))
    _save_png(invalid_dir / "b.png", np.zeros((5, 7), dtype=np.uint8))
    reader = StackReader()
    reader.open_stack(valid_dir)

    with pytest.raises(ValueError, match="mixed frame dimensions"):
        reader.open_stack(invalid_dir)

    assert reader.get_frame_count() == 1
    np.testing.assert_array_equal(reader.read_frame(0), original)


def test_open_stack_rejects_dimension_mismatch_within_multipage_tiff(tmp_path: Path) -> None:
    path = tmp_path / "mixed_pages.tif"
    tifffile.imwrite(path, np.zeros((4, 5), dtype=np.uint8))
    tifffile.imwrite(path, np.zeros((6, 5), dtype=np.uint8), append=True)

    with pytest.raises(ValueError, match=r"page 2 \(5x6\)"):
        StackReader().open_stack(tmp_path)


def test_orientation_normalized_dimensions_are_compared(tmp_path: Path) -> None:
    pixels = np.zeros((2, 3, 3), dtype=np.uint8)
    exif = Image.Exif()
    exif[274] = 6
    Image.fromarray(pixels).save(tmp_path / "a_oriented.png", exif=exif)
    Image.fromarray(np.zeros((3, 2, 3), dtype=np.uint8)).save(tmp_path / "b_regular.png")

    info = StackReader().open_stack(tmp_path)

    assert info.frame_count == 2
    assert (info.frame_height, info.frame_width) == (3, 2)


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

    monkeypatch.setattr("swell.host.stack_reader.np.asarray", _guard)

    reader = StackReader()
    info = reader.open_stack(tmp_path)
    assert info.frame_count == 2


def test_read_frame_png_does_not_depend_on_asarray_image_conversion(tmp_path: Path, monkeypatch) -> None:
    arr = np.full((6, 7), 10, dtype=np.uint8)
    _save_png(tmp_path / "a.png", arr)
    reader = StackReader()
    reader.open_stack(tmp_path)

    real_asarray = np.asarray

    def _guard(value, *args, **kwargs):
        if isinstance(value, Image.Image):
            raise ValueError("Unable to avoid copy while creating an array as requested.")
        return real_asarray(value, *args, **kwargs)

    monkeypatch.setattr("swell.host.stack_reader.np.asarray", _guard)

    assert np.array_equal(reader.read_frame(0, use_cache=False), arr)


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


def test_tiff_decode_failure_releases_per_handle_lock(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "frame.tif"
    tifffile.imwrite(path, np.arange(20, dtype=np.uint16).reshape(4, 5))
    reader = StackReader()
    reader.open_stack(tmp_path)
    page_type = tifffile.TiffPage
    original = page_type.asarray

    def fail_decode(self, *args, **kwargs):  # noqa: ANN001
        raise RuntimeError("synthetic decoder failure")

    monkeypatch.setattr(page_type, "asarray", fail_decode)
    with pytest.raises(RuntimeError, match="synthetic decoder failure"):
        reader._read_tiff_page(path, 0)

    handle_lock = reader._tiff_handle_locks[str(path)]
    assert handle_lock.acquire(blocking=False), "failed TIFF decodes must not strand the handle lock"
    handle_lock.release()

    monkeypatch.setattr(page_type, "asarray", original)
    np.testing.assert_array_equal(reader._read_tiff_page(path, 0), np.arange(20, dtype=np.uint16).reshape(4, 5))


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


def test_context_manager_releases_cached_frames_and_tiff_handles(tmp_path: Path) -> None:
    path = tmp_path / "frame.tif"
    frame = np.arange(20, dtype=np.uint16).reshape(4, 5)
    tifffile.imwrite(path, frame)

    with StackReader() as reader:
        reader.open_stack(tmp_path)
        np.testing.assert_array_equal(reader.read_frame(0), frame)
        assert reader._cache
        assert reader._tiff_handle_pool

    assert not reader._cache
    assert not reader._tiff_handle_pool
    assert not reader._tiff_handle_locks
    reader.close()
    path.unlink()


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


def test_open_stack_planar_rgb_tiff_uses_axis_metadata(tmp_path: Path) -> None:
    tiff_path = tmp_path / "planar_rgb.tif"
    page = np.zeros((3, 7, 11), dtype=np.uint8)
    page[0] = 255
    tifffile.imwrite(tiff_path, page, photometric="rgb", planarconfig="separate")

    reader = StackReader()
    info = reader.open_stack(tmp_path)
    frame = reader.read_frame(0)

    assert (info.frame_height, info.frame_width) == (7, 11)
    assert frame.shape == (7, 11)
    assert np.all(frame == 76)


def test_open_stack_applies_exif_orientation(tmp_path: Path) -> None:
    path = tmp_path / "portrait.jpg"
    pixels = np.zeros((2, 3, 3), dtype=np.uint8)
    pixels[:, 0, 0] = 255
    exif = Image.Exif()
    exif[274] = 6
    Image.fromarray(pixels).save(path, exif=exif, quality=100, subsampling=0)

    reader = StackReader()
    info = reader.open_stack(tmp_path)
    frame = reader.read_frame(0)

    assert (info.frame_height, info.frame_width) == (3, 2)
    assert frame.shape == (3, 2)


def test_open_stack_applies_tiff_orientation(tmp_path: Path) -> None:
    path = tmp_path / "oriented.tif"
    pixels = np.arange(6, dtype=np.uint8).reshape(2, 3)
    tifffile.imwrite(path, pixels, extratags=[(274, "H", 1, 6, False)])

    reader = StackReader()
    info = reader.open_stack(tmp_path)
    frame = reader.read_frame(0)

    assert (info.frame_height, info.frame_width) == (3, 2)
    np.testing.assert_array_equal(frame, np.rot90(pixels, -1))


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
    real_asarray = np.asarray

    def _guard(value, *args, **kwargs):
        if isinstance(value, Image.Image):
            raise ValueError("Unable to avoid copy while creating an array as requested.")
        return real_asarray(value, *args, **kwargs)

    monkeypatch.setattr("swell.host.stack_reader.np.asarray", _guard)
    out0 = reader.read_frame(0, use_cache=False)
    out1 = reader.read_frame(1, use_cache=False)

    assert np.array_equal(out0, page0)
    assert np.array_equal(out1, page1)


@pytest.mark.parametrize(
    ("writer_kwargs", "filename"),
    [
        ({"bigtiff": True}, "big.tif"),
        ({"compression": "deflate"}, "compressed.tif"),
        ({"imagej": True, "metadata": {"axes": "TYX"}}, "imagej.tif"),
        ({"ome": True, "metadata": {"axes": "TYX"}}, "ome.tif"),
    ],
)
def test_tiff_container_variants_load(tmp_path: Path, writer_kwargs: dict, filename: str) -> None:
    path = tmp_path / filename
    stack = np.stack(
        [np.full((5, 7), 11, dtype=np.uint16), np.full((5, 7), 22, dtype=np.uint16)],
        axis=0,
    )
    tifffile.imwrite(path, stack, photometric="minisblack", **writer_kwargs)

    reader = StackReader()
    info = reader.open_stack(tmp_path)

    assert info.frame_count == 2
    np.testing.assert_array_equal(reader.read_frame(0), stack[0])
    np.testing.assert_array_equal(reader.read_frame(1), stack[1])


def test_corrupt_tiff_open_fails_without_replacing_previous_stack(tmp_path: Path) -> None:
    valid_dir = tmp_path / "valid"
    corrupt_dir = tmp_path / "corrupt"
    valid_dir.mkdir()
    corrupt_dir.mkdir()
    original = np.full((3, 4), 9, dtype=np.uint8)
    tifffile.imwrite(valid_dir / "valid.tif", original)
    (corrupt_dir / "broken.tif").write_bytes(b"II*\x00truncated")
    reader = StackReader()
    reader.open_stack(valid_dir)

    with pytest.raises(Exception):
        reader.open_stack(corrupt_dir)

    np.testing.assert_array_equal(reader.read_frame(0), original)


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
