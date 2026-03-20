from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
import re
from threading import Lock
from typing import Callable, Optional

import numpy as np
from PIL import Image
import tifffile

from .config import FrameRef, MAX_PREVIEW_CACHE, SUPPORTED_EXTENSIONS, StackInfo


class StackReader:
    def __init__(self, max_cache: int = MAX_PREVIEW_CACHE):
        self.max_cache = max(1, int(max_cache))
        self._frame_refs: list[FrameRef] = []
        self._stack_info: Optional[StackInfo] = None
        self._cache: OrderedDict[int, np.ndarray] = OrderedDict()
        self._cache_lock = Lock()
        self._tiff_handle_pool: OrderedDict[str, tifffile.TiffFile] = OrderedDict()
        self._tiff_pool_max = 4
        self._tiff_lock = Lock()

    def open_stack(self, input_dir: str | Path, progress_callback: Optional[Callable[[int, int], None]] = None) -> StackInfo:
        input_path = Path(input_dir).expanduser().resolve()
        if not input_path.exists() or not input_path.is_dir():
            raise FileNotFoundError(f"Input directory not found: {input_path}")

        files = sorted(
            [p for p in input_path.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS],
            key=_natural_sort_key,
        )
        if not files:
            raise ValueError("No supported image files found in selected folder.")

        frame_refs: list[FrameRef] = []
        expected_shape: Optional[tuple[int, int]] = None
        dtype_str: Optional[str] = None
        counter = 0

        for file_idx, file_path in enumerate(files):
            ext = file_path.suffix.lower()
            if ext in {".tif", ".tiff"}:
                with tifffile.TiffFile(str(file_path)) as tif:
                    pages = list(tif.pages)
                    if not pages:
                        continue
                    for page_idx, page in enumerate(pages):
                        if len(page.shape) < 2:
                            continue
                        shape = _normalized_frame_shape_from_shape(page.shape)
                        if shape is None:
                            continue
                        if expected_shape is None:
                            expected_shape = shape
                            dtype_str = str(page.dtype)
                        if shape != expected_shape:
                            continue
                        name = file_path.name if len(pages) == 1 else f"{file_path.name}_p{page_idx:04d}"
                        frame_refs.append(
                            FrameRef(
                                frame_idx=counter,
                                source_path=file_path,
                                page_index=page_idx,
                                source_ext=ext,
                                frame_name=name,
                            )
                        )
                        counter += 1
            else:
                with Image.open(file_path) as img:
                    arr = np.asarray(img)
                arr = _to_grayscale(arr)
                shape = arr.shape
                if expected_shape is None:
                    expected_shape = shape
                    dtype_str = str(arr.dtype)
                if shape != expected_shape:
                    continue
                frame_refs.append(
                    FrameRef(
                        frame_idx=counter,
                        source_path=file_path,
                        page_index=None,
                        source_ext=ext,
                        frame_name=file_path.name,
                    )
                )
                counter += 1

            if progress_callback is not None and (file_idx % 50 == 0 or file_idx == len(files) - 1):
                progress_callback(file_idx + 1, len(files))

        if not frame_refs:
            raise ValueError("No valid frames found after shape filtering.")

        self._close_tiff_handles()
        self._frame_refs = frame_refs
        with self._cache_lock:
            self._cache.clear()
        assert expected_shape is not None
        assert dtype_str is not None
        self._stack_info = StackInfo(
            input_dir=input_path,
            frame_count=len(frame_refs),
            frame_height=expected_shape[0],
            frame_width=expected_shape[1],
            dtype=dtype_str,
        )
        return self._stack_info

    def get_stack_info(self) -> StackInfo:
        if self._stack_info is None:
            raise RuntimeError("Stack not opened.")
        return self._stack_info

    def get_frame_count(self) -> int:
        return len(self._frame_refs)

    def get_frame_name(self, frame_idx: int) -> str:
        return self._frame_refs[frame_idx].frame_name

    def get_frame_ref(self, frame_idx: int) -> FrameRef:
        return self._frame_refs[frame_idx]

    def read_frame(self, frame_idx: int, use_cache: bool = True) -> np.ndarray:
        if frame_idx < 0 or frame_idx >= len(self._frame_refs):
            raise IndexError(f"Frame index out of range: {frame_idx}")

        if use_cache:
            with self._cache_lock:
                if frame_idx in self._cache:
                    frame = self._cache.pop(frame_idx)
                    self._cache[frame_idx] = frame
                    return frame

        ref = self._frame_refs[frame_idx]
        if ref.source_ext in {".tif", ".tiff"}:
            key = 0 if ref.page_index is None else ref.page_index
            try:
                arr = self._read_tiff_page(ref.source_path, key)
            except Exception:
                # Fallback path for frozen/runtime environments where optional TIFF
                # codecs (for example imagecodecs variants) are unavailable.
                arr = self._read_tiff_page_with_pillow(ref.source_path, key)
        else:
            with Image.open(ref.source_path) as img:
                arr = np.asarray(img)

        frame = _to_grayscale(arr)

        if use_cache:
            with self._cache_lock:
                self._cache[frame_idx] = frame
                while len(self._cache) > self.max_cache:
                    self._cache.popitem(last=False)

        return frame

    def _read_tiff_page(self, path: Path, key: int) -> np.ndarray:
        path_str = str(path)
        with self._tiff_lock:
            tif = self._tiff_handle_pool.get(path_str)
            if tif is None:
                tif = tifffile.TiffFile(path_str)
                self._tiff_handle_pool[path_str] = tif
                while len(self._tiff_handle_pool) > self._tiff_pool_max:
                    _old_path, old_tif = self._tiff_handle_pool.popitem(last=False)
                    try:
                        old_tif.close()
                    except Exception:
                        pass
            else:
                self._tiff_handle_pool.move_to_end(path_str)
            arr = tif.pages[key].asarray()
        return arr

    def _read_tiff_page_with_pillow(self, path: Path, key: int) -> np.ndarray:
        with Image.open(path) as img:
            page_count = int(getattr(img, "n_frames", 1) or 1)
            page_idx = max(0, min(int(key), max(0, page_count - 1)))
            if page_idx:
                img.seek(page_idx)
            arr = np.asarray(img)
        return arr

    def _close_tiff_handles(self) -> None:
        with self._tiff_lock:
            for _p, tif in list(self._tiff_handle_pool.items()):
                try:
                    tif.close()
                except Exception:
                    pass
            self._tiff_handle_pool.clear()

    def collect_garbage(self, aggressive: bool = False) -> None:
        with self._cache_lock:
            if aggressive:
                self._cache.clear()
            else:
                keep = max(4, self.max_cache // 2)
                while len(self._cache) > keep:
                    self._cache.popitem(last=False)
        if aggressive:
            self._close_tiff_handles()
            return
        with self._tiff_lock:
            keep_handles = max(2, self._tiff_pool_max // 2)
            while len(self._tiff_handle_pool) > keep_handles:
                _old_path, old_tif = self._tiff_handle_pool.popitem(last=False)
                try:
                    old_tif.close()
                except Exception:
                    pass

    def __del__(self):
        try:
            self._close_tiff_handles()
        except Exception:
            pass


def _to_grayscale(arr: np.ndarray) -> np.ndarray:
    if arr.ndim == 2:
        return arr
    if arr.ndim == 3:
        # RGB/RGBA -> luma approximation. Keeps source dtype.
        if arr.shape[2] >= 3:
            rgb = arr[:, :, :3].astype(np.float32)
            gray = 0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2]
            if np.issubdtype(arr.dtype, np.integer):
                info = np.iinfo(arr.dtype)
                gray = np.clip(gray, info.min, info.max)
                return gray.astype(arr.dtype)
            return gray.astype(arr.dtype)
        return arr[:, :, 0]
    if arr.ndim > 3:
        squeezed = np.asarray(arr).squeeze()
        if squeezed.ndim == 2:
            return squeezed
        if squeezed.ndim == 3:
            return _to_grayscale(squeezed)
    raise ValueError(f"Unsupported frame shape: {arr.shape}")


def _normalized_frame_shape_from_shape(raw_shape) -> tuple[int, int] | None:
    try:
        shape = tuple(int(v) for v in tuple(raw_shape))
    except Exception:
        return None
    if len(shape) == 2:
        return shape
    if len(shape) == 3:
        if int(shape[2]) in (3, 4):
            return int(shape[0]), int(shape[1])
        return int(shape[0]), int(shape[1])
    squeezed = tuple(int(v) for v in shape if int(v) != 1)
    if len(squeezed) == 2:
        return squeezed
    if len(squeezed) == 3 and int(squeezed[2]) in (3, 4):
        return int(squeezed[0]), int(squeezed[1])
    return None


def _natural_sort_key(path: Path) -> tuple:
    parts = re.split(r"(\d+)", path.name.lower())
    key: list[int | str] = []
    for part in parts:
        if part.isdigit():
            key.append(int(part))
        else:
            key.append(part)
    return tuple(key)
