from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import numpy as np
from swell.shared.persistence.schema import (
    DEFAULT_EVENT_ID,
    EMBEDDED_EXTRACT_PREFIX,
    PROJECT_TEMP_SUFFIX,
)
from swell.shared.project_naming import normalize_project_save_path
from swell.shared.persistence.embedded_images import reserve_embedded_image_arcname
from swell.shared.persistence.event_path import allocate_event_path_segment
from swell.shared.persistence.zip_io import (
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


def _build_event_segment_map(
    project_state: Dict[str, Any],
    event_payloads: Dict[str, Dict[str, Any]],
) -> dict[str, str]:
    used_segments: set[str] = set()
    mapping: dict[str, str] = {}

    for event in list(project_state.get("events", []) or []):
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("id", "")).strip()
        if not event_id or event_id in mapping:
            continue
        mapping[event_id] = allocate_event_path_segment(event_id, used_segments)

    for event_id in event_payloads.keys():
        key = str(event_id)
        if key in mapping:
            continue
        mapping[key] = allocate_event_path_segment(key, used_segments)
    return mapping


def _project_state_with_persisted_event_refs(
    project_state: Dict[str, Any],
    event_payloads: Dict[str, Dict[str, Any]],
    event_segment_by_id: dict[str, str],
) -> Dict[str, Any]:
    out = dict(project_state or {})
    events_in = list(out.get("events", []) or [])
    events_out: list[Any] = []
    for event in events_in:
        if not isinstance(event, dict):
            events_out.append(event)
            continue
        event_copy = dict(event)
        event_id = str(event_copy.get("id", "")).strip()
        segment = event_segment_by_id.get(event_id)
        if segment:
            event_copy["masks_ref"] = f"events/{segment}/masks.npz"
            event_copy["prompts_ref"] = f"events/{segment}/prompts.json"
            payload = dict(event_payloads.get(event_id, {}) or {})
            if event_copy.get("masks_draft_ref") is not None or payload.get("masks_draft") is not None:
                event_copy["masks_draft_ref"] = f"events/{segment}/masks_draft.npz"
        events_out.append(event_copy)
    out["events"] = events_out
    return out


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
        target = normalize_project_save_path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        event_segment_by_id = _build_event_segment_map(project_state, event_payloads)
        project_state_to_write = _project_state_with_persisted_event_refs(
            project_state,
            event_payloads,
            event_segment_by_id,
        )

        fd, tmp_name = tempfile.mkstemp(suffix=PROJECT_TEMP_SUFFIX, dir=str(target.parent))
        os.close(fd)
        tmp_path = Path(tmp_name)

        try:
            with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                write_json(zf, "project_state.json", project_state_to_write)
                write_json(zf, "images.json", images_manifest)
                write_json(zf, "roi.json", roi_data)

                embedded_map = {}
                if embed_images:
                    used_arcnames: set[str] = set()
                    for entry in images_manifest.get("images", []):
                        src = entry.get("absolute_path") or entry.get("relative_path")
                        if not src:
                            continue
                        src_path = Path(src)
                        if not src_path.exists() or not src_path.is_file():
                            continue
                        arcname = reserve_embedded_image_arcname(src_path.name, used_arcnames)
                        zf.write(src_path, arcname=arcname)
                        embedded_map[str(entry.get("id") or src_path.name)] = arcname
                    if embedded_map:
                        write_json(zf, "images_embedded.json", {"embedded": embedded_map})

                for event_id, payload in event_payloads.items():
                    event_key = str(event_id)
                    event_segment = event_segment_by_id.get(event_key)
                    if not event_segment:
                        continue
                    masks = np.array(payload.get("masks", np.zeros((0, 0, 0), dtype=np.uint8)), dtype=np.uint8)
                    masks_draft = payload.get("masks_draft")
                    prompts = payload.get("prompts", {})
                    zf.writestr(f"events/{event_segment}/masks.npz", write_npz_bytes(masks))
                    if masks_draft is not None:
                        zf.writestr(
                            f"events/{event_segment}/masks_draft.npz",
                            write_npz_bytes(np.array(masks_draft, dtype=np.uint8)),
                        )
                    write_json(zf, f"events/{event_segment}/prompts.json", prompts)

            # fsync with writable descriptor for cross-platform durability (Windows rejects read-only fsync).
            sync_fd = os.open(str(tmp_path), os.O_RDWR)
            try:
                os.fsync(sync_fd)
            finally:
                os.close(sync_fd)
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

        created_extract_root = False
        extract_root: Path | None = None
        try:
            with zipfile.ZipFile(src, "r") as zf:
                project_state = read_json(zf, "project_state.json", default={})
                images_manifest = read_json(zf, "images.json", default={"images": []})
                roi_data = read_json(zf, "roi.json", default={})
                embed_index = read_json(zf, "images_embedded.json", default={"embedded": {}})

                event_payloads: Dict[str, Dict[str, Any]] = {}
                for ev in project_state.get("events", []):
                    event_id = str(ev.get("id", DEFAULT_EVENT_ID))
                    masks_ref = str(ev.get("masks_ref", f"events/{event_id}/masks.npz"))
                    prompts_ref = str(ev.get("prompts_ref", f"events/{event_id}/prompts.json"))
                    masks_draft_ref = ev.get("masks_draft_ref")
                    if masks_draft_ref is None:
                        masks_draft_ref = f"events/{event_id}/masks_draft.npz"
                    else:
                        masks_draft_ref = str(masks_draft_ref)
                    masks_arr = np.zeros((0, 0, 0), dtype=np.uint8)
                    masks_draft_arr = None
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
                    event_payloads[event_id] = {
                        "masks": masks_arr,
                        "masks_draft": masks_draft_arr,
                        "prompts": read_json(zf, prompts_ref, default={}),
                    }

                extracted: Dict[str, str] = {}
                embedded_map = embed_index.get("embedded", {})
                if embedded_map:
                    if extract_embedded_to is None:
                        extract_root = Path(tempfile.mkdtemp(prefix=EMBEDDED_EXTRACT_PREFIX))
                        created_extract_root = True
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
        except Exception:
            if created_extract_root and extract_root is not None:
                shutil.rmtree(extract_root, ignore_errors=True)
            raise
