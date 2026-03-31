from __future__ import annotations

from sdapp.shared.project_naming import derive_input_folder_name, derive_sdproj_filename, derive_sdproj_name


def test_derive_sdproj_name_prefers_existing_project_path() -> None:
    assert derive_sdproj_name("/tmp/already_named.sdproj", default_base="session", input_dir="/tmp/input_folder") == "already_named"


def test_derive_sdproj_name_uses_input_folder_when_project_path_missing() -> None:
    assert derive_sdproj_name(None, default_base="session", input_dir="/tmp/input_folder") == "input_folder"


def test_derive_sdproj_name_uses_shared_parent_for_source_paths() -> None:
    assert derive_sdproj_name(
        None,
        default_base="analysis",
        source_paths=["/tmp/input_folder/frame_001.tif", "/tmp/input_folder/frame_002.tif"],
    ) == "input_folder"


def test_derive_input_folder_name_rejects_mixed_source_parents() -> None:
    assert derive_input_folder_name(source_paths=["/tmp/a/frame_001.tif", "/tmp/b/frame_002.tif"]) is None


def test_derive_sdproj_filename_falls_back_when_input_folder_missing() -> None:
    assert derive_sdproj_filename(default_base="session") == "session.sdproj"
