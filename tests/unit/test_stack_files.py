from __future__ import annotations

from pathlib import Path

from sdapp.shared.frame_source.stack_files import list_stack_files


def test_list_stack_files_skips_hidden_and_sorts_naturally(tmp_path: Path) -> None:
    for name in ("frame_10.png", "frame_2.png", "frame_1.tif", ".hidden.png", "._frame_3.png", "notes.txt"):
        (tmp_path / name).write_bytes(b"x")

    files = list_stack_files(tmp_path)

    assert [path.name for path in files] == ["frame_1.tif", "frame_2.png", "frame_10.png"]


def test_list_stack_files_returns_empty_for_missing_directory(tmp_path: Path) -> None:
    assert list_stack_files(tmp_path / "missing") == []
