from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from swell.shared.persistence.schema import PROJECT_EXTENSION, SUPPORTED_PROJECT_EXTENSIONS


def _coerce_path_name(value: str | Path | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    return str(Path(raw).expanduser().name).strip() or None


def derive_input_folder_name(
    *,
    input_dir: str | Path | None = None,
    source_paths: Iterable[str | Path] | None = None,
) -> str | None:
    folder_name = _coerce_path_name(input_dir)
    if folder_name:
        return folder_name

    parent_names: set[str] = set()
    for raw_path in source_paths or ():
        raw = str(raw_path or "").strip()
        if not raw:
            continue
        parent_name = str(Path(raw).expanduser().parent.name).strip()
        if not parent_name:
            continue
        parent_names.add(parent_name)
        if len(parent_names) > 1:
            return None

    if len(parent_names) == 1:
        return next(iter(parent_names))
    return None


def derive_project_name(
    current_project_path: str | Path | None,
    *,
    default_base: str,
    input_dir: str | Path | None = None,
    source_paths: Iterable[str | Path] | None = None,
) -> str:
    current_name = _coerce_path_name(current_project_path)
    if current_name:
        if Path(current_name).suffix.lower() in SUPPORTED_PROJECT_EXTENSIONS:
            stem = Path(current_name).stem
            if stem:
                return stem
        return current_name

    return derive_input_folder_name(input_dir=input_dir, source_paths=source_paths) or str(default_base)


def derive_project_filename(
    *,
    default_base: str,
    input_dir: str | Path | None = None,
    source_paths: Iterable[str | Path] | None = None,
) -> str:
    return f"{derive_input_folder_name(input_dir=input_dir, source_paths=source_paths) or str(default_base)}{PROJECT_EXTENSION}"
