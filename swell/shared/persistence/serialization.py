from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from swell.shared.frame_source.stack_files import is_supported_stack_file, list_stack_files
from swell.shared.persistence.embedded_images import reserve_embedded_image_arcname
from swell.shared.persistence.event_path import allocate_event_path_segment
from swell.shared.persistence.zip_io import read_json, read_npz, write_json, write_npz
from .schema import (
    EMBEDDED_IMAGES_INDEX_KEY,
    METADATA_GLOBAL_METRICS_DEFAULTS_KEY,
    METRICS_SETTINGS_KEY,
)


def _embedded_source_files(input_source: Any) -> list[Path]:
    if isinstance(input_source, (str, Path)):
        return list_stack_files(input_source)
    try:
        return [Path(p) for p in list(input_source or []) if is_supported_stack_file(p)]
    except TypeError:
        return list_stack_files(input_source)


def encode_embedded_images(input_dir: Any, zf, *, require_sources: bool = False) -> dict[str, Any] | None:
    """Embed the stack's source image files verbatim into the project zip.

    Mirrors the analysis-side ``embed_images`` behaviour: each unique source file is
    written under ``images/`` and indexed by its filename. Returns the index manifest
    (``{"embedded": {name: arcname}}``) or ``None`` when nothing was embedded and
    ``require_sources`` is false.
    """
    embedded: dict[str, str] = {}
    used_arcnames: set[str] = set()
    files = _embedded_source_files(input_dir)
    for src in files:
        if not src.exists() or not src.is_file():
            continue
        arcname = reserve_embedded_image_arcname(src.name, used_arcnames)
        zf.write(src, arcname=arcname)
        key = src.name if src.name not in embedded else Path(arcname).name
        embedded[key] = arcname
    if not embedded:
        if require_sources:
            source = str(input_dir or "").strip() or "<empty>"
            if not files:
                raise FileNotFoundError(
                    "Embedding source images is enabled, but no supported image files were found in "
                    f"the stack folder: {source}"
                )
            raise OSError(
                "Embedding source images is enabled, but none of the supported source files could be "
                f"read from: {source}"
            )
        return None
    return {EMBEDDED_IMAGES_INDEX_KEY: embedded}


def encode_metadata_for_write(metadata: dict[str, Any], zf) -> dict[str, Any]:
    encoded = dict(metadata or {})
    global_metrics_defaults = encoded.get(METADATA_GLOBAL_METRICS_DEFAULTS_KEY)
    if not isinstance(global_metrics_defaults, dict):
        return encoded
    global_defaults_entry = dict(global_metrics_defaults)
    global_roi_mask = global_defaults_entry.pop("roi_mask", None)
    if global_roi_mask is not None:
        global_roi_ref = "global/roi_mask.npz"
        write_npz(zf, global_roi_ref, global_roi_mask)
        global_defaults_entry["roi_mask_ref"] = global_roi_ref
    encoded[METADATA_GLOBAL_METRICS_DEFAULTS_KEY] = global_defaults_entry
    return encoded


def decode_metadata_from_read(metadata: dict[str, Any], zf) -> dict[str, Any]:
    decoded = dict(metadata or {})
    global_metrics_defaults = decoded.get(METADATA_GLOBAL_METRICS_DEFAULTS_KEY)
    if not isinstance(global_metrics_defaults, dict):
        return decoded
    global_defaults = dict(global_metrics_defaults)
    roi_mask_ref = global_defaults.pop("roi_mask_ref", None)
    if isinstance(roi_mask_ref, str):
        global_roi_mask = read_npz(zf, roi_mask_ref)
        if global_roi_mask is not None:
            global_defaults["roi_mask"] = np.asarray(global_roi_mask, dtype=bool).copy()
    decoded[METADATA_GLOBAL_METRICS_DEFAULTS_KEY] = global_defaults
    return decoded


def encode_analysis_sidecar(sidecar: dict[str, Any], zf) -> dict[str, Any]:
    sidecar_manifest: dict[str, Any] = {}
    used_event_segments: set[str] = set()
    for event_id, payload in dict(sidecar or {}).items():
        key = str(event_id)
        event_segment = allocate_event_path_segment(key, used_event_segments)
        event_base = f"events/{event_segment}"
        if not isinstance(payload, dict):
            sidecar_manifest[key] = payload
            continue
        entry: dict[str, Any] = {}
        prompts = payload.get("prompts")
        if isinstance(prompts, dict):
            prompts_ref = f"{event_base}/prompts.json"
            write_json(zf, prompts_ref, prompts)
            entry["prompts_ref"] = prompts_ref
        masks_committed = payload.get("masks_committed")
        if masks_committed is not None:
            masks_ref = f"{event_base}/masks.npz"
            write_npz(zf, masks_ref, masks_committed)
            entry["masks_committed_ref"] = masks_ref
        masks_draft = payload.get("masks_draft")
        if masks_draft is not None:
            draft_ref = f"{event_base}/masks_draft.npz"
            write_npz(zf, draft_ref, masks_draft)
            entry["masks_draft_ref"] = draft_ref

        metrics_settings = payload.get(METRICS_SETTINGS_KEY)
        if isinstance(metrics_settings, dict):
            metrics_entry = dict(metrics_settings)
            roi_mask = metrics_entry.pop("roi_mask", None)
            if roi_mask is not None:
                roi_ref = f"{event_base}/roi_mask.npz"
                write_npz(zf, roi_ref, roi_mask)
                metrics_entry["roi_mask_ref"] = roi_ref
            entry[METRICS_SETTINGS_KEY] = metrics_entry

        for key_name in (
            "propagation_completed",
            "analysis_output_dir",
            "prompts_frame_origin",
            "masks_committed_frame_origin",
            "masks_draft_frame_origin",
            "encoding",
            "frame_count",
            "shape",
            "blob_ref",
        ):
            if key_name in payload:
                entry[key_name] = payload.get(key_name)
        sidecar_manifest[key] = entry
    return sidecar_manifest


def decode_analysis_sidecar(sidecar_raw: Any, zf) -> dict[str, Any]:
    sidecar: dict[str, Any] = {}
    if not isinstance(sidecar_raw, dict):
        return sidecar

    for event_id, entry in sidecar_raw.items():
        key = str(event_id)
        if not isinstance(entry, dict):
            sidecar[key] = entry
            continue
        loaded_entry = dict(entry)
        prompts_ref = loaded_entry.pop("prompts_ref", None)
        if isinstance(prompts_ref, str):
            loaded_entry["prompts"] = read_json(zf, prompts_ref, default={})
        masks_ref = loaded_entry.pop("masks_committed_ref", None)
        if isinstance(masks_ref, str):
            masks = read_npz(zf, masks_ref)
            if masks is not None:
                loaded_entry["masks_committed"] = masks
        draft_ref = loaded_entry.pop("masks_draft_ref", None)
        if isinstance(draft_ref, str):
            draft = read_npz(zf, draft_ref)
            if draft is not None:
                loaded_entry["masks_draft"] = draft
        metrics_settings = loaded_entry.get(METRICS_SETTINGS_KEY)
        if isinstance(metrics_settings, dict):
            metrics_entry = dict(metrics_settings)
            roi_mask_ref = metrics_entry.pop("roi_mask_ref", None)
            if isinstance(roi_mask_ref, str):
                roi_mask = read_npz(zf, roi_mask_ref)
                if roi_mask is not None:
                    metrics_entry["roi_mask"] = np.asarray(roi_mask, dtype=bool).copy()
            loaded_entry[METRICS_SETTINGS_KEY] = metrics_entry
        sidecar[key] = loaded_entry
    return sidecar
