from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from sdapp.host.stack_reader import StackReader
from sdapp.shared.frame_source import SDStackFrameSource


def _save_png(path: Path, arr: np.ndarray) -> None:
    Image.fromarray(arr).save(path)


def test_sd_stack_frame_source_metadata_and_frames(tmp_path: Path) -> None:
    a = np.full((6, 7), 10, dtype=np.uint8)
    b = np.full((6, 7), 20, dtype=np.uint8)
    _save_png(tmp_path / "a.png", a)
    _save_png(tmp_path / "b.png", b)

    reader = StackReader()
    reader.open_stack(tmp_path)
    src = SDStackFrameSource(reader=reader)

    assert src.frame_count == 2
    assert src.frame_shape == (6, 7)
    assert list(src.frame_names) == ["a.png", "b.png"]
    assert len(list(src.source_paths)) == 2
    assert np.array_equal(src.get_raw_frame(1), b)
    assert src.capabilities == {"raw": True, "subtracted": False, "visual": False}


def test_sd_stack_frame_source_optional_methods_not_implemented(tmp_path: Path) -> None:
    arr = np.full((4, 4), 10, dtype=np.uint8)
    _save_png(tmp_path / "a.png", arr)
    reader = StackReader()
    reader.open_stack(tmp_path)
    src = SDStackFrameSource(reader=reader)

    with pytest.raises(NotImplementedError):
        src.get_subtracted_frame(0)
    with pytest.raises(NotImplementedError):
        src.get_visual_frame(0)
