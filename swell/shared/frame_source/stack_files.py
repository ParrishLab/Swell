from __future__ import annotations

from pathlib import Path
import re


SUPPORTED_STACK_EXTENSIONS = (".tif", ".tiff", ".png", ".jpg", ".jpeg", ".bmp")


def is_supported_stack_file(path: str | Path) -> bool:
    p = Path(path)
    try:
        if not p.is_file():
            return False
    except OSError:
        return False
    name = p.name
    if name.startswith(".") or name.startswith("._"):
        return False
    return p.suffix.lower() in SUPPORTED_STACK_EXTENSIONS


def natural_stack_sort_key(path: str | Path) -> tuple:
    parts = re.split(r"(\d+)", Path(path).name.lower())
    key: list[int | str] = []
    for part in parts:
        if part.isdigit():
            key.append(int(part))
        else:
            key.append(part)
    return tuple(key)


def list_stack_files(input_dir: str | Path) -> list[Path]:
    try:
        input_path = Path(input_dir).expanduser().resolve()
        if not input_path.exists() or not input_path.is_dir():
            return []
        entries = list(input_path.iterdir())
    except OSError:
        return []
    return sorted(
        [p for p in entries if is_supported_stack_file(p)],
        key=natural_stack_sort_key,
    )
