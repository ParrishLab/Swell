from __future__ import annotations

import os
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import numpy as np
from sdapp.shared.persistence.zip_io import (
    cleanup_stale_temp_files,
    fsync_parent_directory,
    read_json,
    read_npz_bytes,
    write_json,
    write_npz_bytes,
)


@dataclass
class LoadedProject:
    project_state: Dict[str, Any]
    images_manifest: Dict[str, Any]
    roi_data: Dict[str, Any]
    event_payloads: Dict[str, Dict[str, Any]]
    embedded_image_paths: Dict[str, str]


def _fsync_parent_directory(target: Path) -> None:
    fsync_parent_directory(target)


class ProjectStore:
    def save(
        self,
        target_path: str | Path,
        project_state: Dict[str, Any],
        images_manifest: Dict[str, Any],
        roi_data: Dict[str, Any],
        event_payloads: Dict[str, Dict[str, Any]],
        embed_images: bool = False,
    ) -> None:
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        fd, tmp_name = tempfile.mkstemp(suffix=".sdproj.tmp", dir=str(target.parent))
        os.close(fd)
        tmp_path = Path(tmp_name)

        try:
            with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                write_json(zf, "project_state.json", project_state)
                write_json(zf, "images.json", images_manifest)
                write_json(zf, "roi.json", roi_data)

                embedded_map = {}
                if embed_images:
                    for entry in images_manifest.get("images", []):
                        src = entry.get("absolute_path") or entry.get("relative_path")
                        if not src:
                            continue
                        src_path = Path(src)
                        if not src_path.exists() or not src_path.is_file():
                            continue
                        arcname = f"images/{src_path.name}"
                        zf.write(src_path, arcname=arcname)
                        embedded_map[entry.get("id", src_path.name)] = arcname
                    if embedded_map:
                        write_json(zf, "images_embedded.json", {"embedded": embedded_map})

                for event_id, payload in event_payloads.items():
                    masks = np.array(payload.get("masks", np.zeros((0, 0, 0), dtype=np.uint8)), dtype=np.uint8)
                    masks_draft = payload.get("masks_draft")
                    prompts = payload.get("prompts", {})
                    zf.writestr(f"events/{event_id}/masks.npz", write_npz_bytes(masks))
                    if masks_draft is not None:
                        zf.writestr(
                            f"events/{event_id}/masks_draft.npz",
                            write_npz_bytes(np.array(masks_draft, dtype=np.uint8)),
                        )
                    write_json(zf, f"events/{event_id}/prompts.json", prompts)

            with tmp_path.open("rb") as f:
                os.fsync(f.fileno())
            os.replace(tmp_path, target)
            _fsync_parent_directory(target)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    def load(self, source_path: str | Path, extract_embedded_to: str | Path | None = None) -> LoadedProject:
        src = Path(source_path)
        if not src.exists():
            raise FileNotFoundError(f"Project not found: {src}")

        with zipfile.ZipFile(src, "r") as zf:
            project_state = read_json(zf, "project_state.json", default={})
            images_manifest = read_json(zf, "images.json", default={"images": []})
            roi_data = read_json(zf, "roi.json", default={})
            embed_index = read_json(zf, "images_embedded.json", default={"embedded": {}})

            event_payloads: Dict[str, Dict[str, Any]] = {}
            for ev in project_state.get("events", []):
                event_id = str(ev.get("id", "sd_event_001"))
                masks_ref = str(ev.get("masks_ref", f"events/{event_id}/masks.npz"))
                prompts_ref = str(ev.get("prompts_ref", f"events/{event_id}/prompts.json"))
                masks_draft_ref = ev.get("masks_draft_ref")
                if masks_draft_ref is None:
                    masks_draft_ref = f"events/{event_id}/masks_draft.npz"
                else:
                    masks_draft_ref = str(masks_draft_ref)
                masks_arr = np.zeros((0, 0, 0), dtype=np.uint8)
                masks_draft_arr = None
                prompts_data: Dict[str, Any] = {}
                try:
                    with zf.open(masks_ref, "r") as f:
                        masks_arr = read_npz_bytes(f.read())
                except KeyError:
                    pass
                try:
                    with zf.open(masks_draft_ref, "r") as f:
                        masks_draft_arr = read_npz_bytes(f.read())
                except KeyError:
                    masks_draft_arr = None
                prompts_data = read_json(zf, prompts_ref, default={})
                event_payloads[event_id] = {
                    "masks": masks_arr,
                    "masks_draft": masks_draft_arr,
                    "prompts": prompts_data,
                }

            extracted: Dict[str, str] = {}
            embedded_map = embed_index.get("embedded", {})
            if embedded_map:
                if extract_embedded_to is None:
                    extract_root = Path(tempfile.mkdtemp(prefix="sdproj_embedded_"))
                else:
                    extract_root = Path(extract_embedded_to)
                    extract_root.mkdir(parents=True, exist_ok=True)
                for image_id, arcname in embedded_map.items():
                    try:
                        out_path = extract_root / Path(arcname).name
                        with zf.open(arcname, "r") as src_f, out_path.open("wb") as out_f:
                            out_f.write(src_f.read())
                        extracted[str(image_id)] = str(out_path)
                    except KeyError:
                        continue

        return LoadedProject(
            project_state=project_state,
            images_manifest=images_manifest,
            roi_data=roi_data,
            event_payloads=event_payloads,
            embedded_image_paths=extracted,
        )
