from __future__ import annotations

from pathlib import Path

from swell.shared.persistence.schema import EMBEDDED_IMAGES_DIR


def reserve_embedded_image_arcname(filename: str | Path, used_arcnames: set[str]) -> str:
    name = Path(filename).name
    candidate = f"{EMBEDDED_IMAGES_DIR}/{name}"
    if candidate not in used_arcnames:
        used_arcnames.add(candidate)
        return candidate

    stem = Path(name).stem
    suffix = Path(name).suffix
    idx = 2
    while True:
        candidate = f"{EMBEDDED_IMAGES_DIR}/{stem}_{idx}{suffix}"
        if candidate not in used_arcnames:
            used_arcnames.add(candidate)
            return candidate
        idx += 1
