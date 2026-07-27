from __future__ import annotations

from swell.shared.project_naming import derive_input_folder_name, derive_project_filename, derive_project_name


def test_derive_project_name_prefers_existing_project_path() -> None:
    assert derive_project_name("/tmp/already_named.swell", default_base="session", input_dir="/tmp/input_folder") == "already_named"


def test_derive_project_name_uses_input_folder_when_project_path_missing() -> None:
    assert derive_project_name(None, default_base="session", input_dir="/tmp/input_folder") == "input_folder"


def test_derive_project_name_uses_shared_parent_for_source_paths() -> None:
    assert derive_project_name(
        None,
        default_base="analysis",
        source_paths=["/tmp/input_folder/frame_001.tif", "/tmp/input_folder/frame_002.tif"],
    ) == "input_folder"


def test_derive_input_folder_name_rejects_mixed_source_parents() -> None:
    assert derive_input_folder_name(source_paths=["/tmp/a/frame_001.tif", "/tmp/b/frame_002.tif"]) is None


def test_derive_project_filename_falls_back_when_input_folder_missing() -> None:
    assert derive_project_filename(default_base="session") == "session.swell"


def test_derive_project_name_handles_windows_paths_on_non_windows_hosts() -> None:
    assert derive_project_name(
        r"C:\data\experiment\project.swell",
        default_base="session",
    ) == "project"
    assert derive_project_name(
        None,
        default_base="session",
        source_paths=[
            r"E:\images\stack_04\frame_001.tif",
            r"E:\images\stack_04\frame_002.tif",
        ],
    ) == "stack_04"
