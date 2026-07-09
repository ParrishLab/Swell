from __future__ import annotations

from pathlib import Path

from swell.shared.frame_source.stack_files import list_stack_files


def test_list_stack_files_skips_hidden_and_sorts_naturally(tmp_path: Path) -> None:
    for name in ("frame_10.png", "frame_2.png", "frame_1.tif", ".hidden.png", "._frame_3.png", "notes.txt"):
        (tmp_path / name).write_bytes(b"x")

    files = list_stack_files(tmp_path)

    assert [path.name for path in files] == ["frame_1.tif", "frame_2.png", "frame_10.png"]


def test_list_stack_files_returns_empty_for_missing_directory(tmp_path: Path) -> None:
    assert list_stack_files(tmp_path / "missing") == []


def test_list_stack_files_returns_empty_when_directory_iteration_fails(tmp_path: Path, monkeypatch) -> None:
    def fail_iterdir(self):
        if self == tmp_path:
            raise PermissionError("locked")
        return original_iterdir(self)

    original_iterdir = Path.iterdir
    monkeypatch.setattr(Path, "iterdir", fail_iterdir)

    assert list_stack_files(tmp_path) == []


def test_list_stack_files_skips_entries_that_fail_file_check(tmp_path: Path, monkeypatch) -> None:
    good = tmp_path / "frame_1.png"
    bad = tmp_path / "frame_2.png"
    good.write_bytes(b"x")
    bad.write_bytes(b"x")
    original_is_file = Path.is_file

    def maybe_fail_is_file(self):
        if self == bad:
            raise OSError("locked")
        return original_is_file(self)

    monkeypatch.setattr(Path, "is_file", maybe_fail_is_file)

    files = list_stack_files(tmp_path)

    assert [path.name for path in files] == ["frame_1.png"]
