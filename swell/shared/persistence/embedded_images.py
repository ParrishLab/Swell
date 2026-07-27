from __future__ import annotations

from pathlib import Path

from swell.shared.persistence.schema import EMBEDDED_IMAGES_DIR
from swell.shared.persistence.event_path import (
    portable_path_collision_key,
    sanitize_filesystem_filename,
)


def reserve_embedded_image_arcname(filename: str | Path, used_arcnames: set[str]) -> str:
    name = sanitize_filesystem_filename(Path(filename).name, default="image")
    candidate = f"{EMBEDDED_IMAGES_DIR}/{name}"
    used_keys = {portable_path_collision_key(value) for value in used_arcnames}
    if portable_path_collision_key(candidate) not in used_keys:
        used_arcnames.add(candidate)
        return candidate

    stem = Path(name).stem
    suffix = Path(name).suffix
    idx = 2
    while True:
        candidate_name = sanitize_filesystem_filename(
            f"{stem}_{idx}{suffix}",
            default=f"image_{idx}",
        )
        candidate = f"{EMBEDDED_IMAGES_DIR}/{candidate_name}"
        if portable_path_collision_key(candidate) not in used_keys:
            used_arcnames.add(candidate)
            return candidate
        idx += 1
