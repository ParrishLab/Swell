from __future__ import annotations

from pathlib import Path
from typing import Iterable


def derive_autosave_tag(source_paths: Iterable[str] | None, entry_input_value: str | None) -> str:
    paths = list(source_paths or [])
    if paths:
        parent_names = {
            str(Path(p).resolve().parent.name).strip() or "images"
            for p in paths
        }
        if len(parent_names) == 1:
            return next(iter(parent_names))
        return "mixed_images"

    entry = str(entry_input_value or "").strip()
    if entry:
        p = Path(entry)
        if p.exists() and p.is_dir():
            return str(p.name).strip() or "images"

    return "autosave"
