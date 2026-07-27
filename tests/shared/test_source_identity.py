from __future__ import annotations

import unicodedata
from pathlib import Path

import numpy as np

from swell.shared.frame_source.source_identity import (
    decoded_source_fingerprint,
    source_identity,
)


class _FileBackedReader:
    def __init__(self, path: Path, *, frame_name: str, decoded_value: int) -> None:
        self.path = path
        self.frame_name = frame_name
        self.decoded_value = decoded_value

    def get_frame_count(self) -> int:
        return 1

    def get_frame_name(self, _idx: int) -> str:
        return self.frame_name

    def get_frame_ref(self, _idx: int):
        return type("_Ref", (), {"source_path": self.path})()

    def read_frame(self, _idx: int, use_cache: bool = True) -> np.ndarray:  # noqa: ARG002
        return np.full((3, 4), self.decoded_value, dtype=np.uint8)


def test_source_identity_is_portable_across_path_unicode_and_decoder_changes(tmp_path: Path) -> None:
    first_path = tmp_path / "mac" / "frame.tif"
    second_path = tmp_path / "windows" / "frame.tif"
    first_path.parent.mkdir()
    second_path.parent.mkdir()
    source_bytes = b"portable-image-content" * 500
    first_path.write_bytes(source_bytes)
    second_path.write_bytes(source_bytes)
    composed_name = "café.tif"
    decomposed_name = unicodedata.normalize("NFD", composed_name)

    first = source_identity(
        _FileBackedReader(first_path, frame_name=composed_name, decoded_value=10)
    )
    second = source_identity(
        _FileBackedReader(second_path, frame_name=decomposed_name, decoded_value=200)
    )

    assert first == second
    assert decoded_source_fingerprint(
        _FileBackedReader(first_path, frame_name=composed_name, decoded_value=10)
    ) != decoded_source_fingerprint(
        _FileBackedReader(second_path, frame_name=decomposed_name, decoded_value=200)
    )
    assert first["frame_names_digest"].startswith("v2:")
    assert first["source_fingerprint"].startswith("v2:")


def test_source_identity_detects_changed_source_file_bytes(tmp_path: Path) -> None:
    first_path = tmp_path / "first.tif"
    second_path = tmp_path / "second.tif"
    first_path.write_bytes(b"a" * 12_000)
    second_path.write_bytes(b"b" * 12_000)

    first = source_identity(
        _FileBackedReader(first_path, frame_name="frame.tif", decoded_value=10)
    )
    second = source_identity(
        _FileBackedReader(second_path, frame_name="frame.tif", decoded_value=10)
    )

    assert first["frame_names_digest"] == second["frame_names_digest"]
    assert first["source_fingerprint"] != second["source_fingerprint"]
