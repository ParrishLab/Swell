from __future__ import annotations

import io
import json
import os
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import numpy as np


@dataclass
class LoadedProject:
    project_state: Dict[str, Any]
    images_manifest: Dict[str, Any]
    roi_data: Dict[str, Any]
    event_payloads: Dict[str, Dict[str, Any]]
    embedded_image_paths: Dict[str, str]


def cleanup_stale_temp_files(
    directory: str | Path,
    pattern: str = "*.sdproj.tmp",
    older_than_sec: float = 86400,
) -> int:
    base = Path(directory)
    if not base.exists() or not base.is_dir():
        return 0
    cutoff = time.time() - max(0.0, float(older_than_sec))
    removed = 0
    for p in base.glob(pattern):
        try:
            if not p.is_file():
                continue
            if p.stat().st_mtime > cutoff:
                continue
            p.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def _write_json_to_zip(zf: zipfile.ZipFile, arcname: str, payload: Dict[str, Any]) -> None:
    zf.writestr(arcname, json.dumps(payload, indent=2))


def _read_json_from_zip(zf: zipfile.ZipFile, arcname: str, default: Dict[str, Any] | None = None) -> Dict[str, Any]:
    try:
        with zf.open(arcname, "r") as f:
            return json.loads(f.read().decode("utf-8"))
    except KeyError:
        return {} if default is None else dict(default)


def _write_npz_bytes(array: np.ndarray) -> bytes:
    mem = io.BytesIO()
    np.savez_compressed(mem, masks=array)
    return mem.getvalue()


def _read_npz_bytes(blob: bytes) -> np.ndarray:
    with np.load(io.BytesIO(blob)) as npz:
        return np.array(npz["masks"])


def _fsync_parent_directory(target: Path) -> None:
    # Best-effort directory fsync to harden rename durability.
    dir_fd = None
    try:
        dir_fd = os.open(str(target.parent), os.O_RDONLY)
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        if dir_fd is not None:
            try:
                os.close(dir_fd)
            except OSError:
                pass


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
                _write_json_to_zip(zf, "project_state.json", project_state)
                _write_json_to_zip(zf, "images.json", images_manifest)
                _write_json_to_zip(zf, "roi.json", roi_data)

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
                        _write_json_to_zip(zf, "images_embedded.json", {"embedded": embedded_map})

                for event_id, payload in event_payloads.items():
                    masks = np.array(payload.get("masks", np.zeros((0, 0, 0), dtype=np.uint8)), dtype=np.uint8)
                    masks_draft = payload.get("masks_draft")
                    prompts = payload.get("prompts", {})
                    zf.writestr(f"events/{event_id}/masks.npz", _write_npz_bytes(masks))
                    if masks_draft is not None:
                        zf.writestr(
                            f"events/{event_id}/masks_draft.npz",
                            _write_npz_bytes(np.array(masks_draft, dtype=np.uint8)),
                        )
                    _write_json_to_zip(zf, f"events/{event_id}/prompts.json", prompts)

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
            project_state = _read_json_from_zip(zf, "project_state.json")
            images_manifest = _read_json_from_zip(zf, "images.json", default={"images": []})
            roi_data = _read_json_from_zip(zf, "roi.json", default={})
            embed_index = _read_json_from_zip(zf, "images_embedded.json", default={"embedded": {}})

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
                        masks_arr = _read_npz_bytes(f.read())
                except KeyError:
                    pass
                try:
                    with zf.open(masks_draft_ref, "r") as f:
                        masks_draft_arr = _read_npz_bytes(f.read())
                except KeyError:
                    masks_draft_arr = None
                prompts_data = _read_json_from_zip(zf, prompts_ref, default={})
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
