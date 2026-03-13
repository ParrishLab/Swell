from __future__ import annotations

import os
import tempfile
import zipfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

from sdapp.shared.models import EventMeta, StackRef, UnifiedProjectState
from sdapp.shared.persistence.zip_io import read_json, read_npz, write_json, write_npz

HOST_PROJECT_SCHEMA_VERSION = 2
HOST_PERSISTENCE_OWNER = "host_sdproj"


def _coerce_stack_ref(raw: dict[str, Any] | None) -> StackRef | None:
    if not isinstance(raw, dict):
        return None
    try:
        return StackRef(
            input_dir=str(raw.get("input_dir", "")),
            frame_count=int(raw.get("frame_count", 0)),
            frame_height=int(raw.get("frame_height", 0)),
            frame_width=int(raw.get("frame_width", 0)),
            dtype=str(raw.get("dtype", "uint8")),
        )
    except Exception:
        return None


def _coerce_events(raw: Any) -> list[EventMeta]:
    out: list[EventMeta] = []
    for event in list(raw or []):
        if not isinstance(event, dict):
            continue
        try:
            start = event.get("global_start_idx", event.get("start_idx", event.get("frame_start", 0)))
            end = event.get("global_end_idx", event.get("end_idx", event.get("frame_end", 0)))
            out.append(
                EventMeta(
                    event_id=str(event.get("event_id", event.get("id", ""))),
                    label=str(event.get("label", event.get("event_id", event.get("id", "")))),
                    global_start_idx=int(start),
                    global_end_idx=int(end),
                    flags=dict(event.get("flags", {})),
                )
            )
        except Exception:
            continue
    return out


class UnifiedProjectStore:
    persistence_owner = HOST_PERSISTENCE_OWNER

    def save(self, target_path: str | Path, state: UnifiedProjectState) -> None:
        target = Path(target_path).expanduser().resolve()
        if target.suffix.lower() != ".sdproj":
            target = target.with_suffix(".sdproj")
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(suffix=".sdproj.tmp", dir=str(target.parent))
        os.close(fd)
        tmp_path = Path(tmp_name)
        try:
            with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                metadata = dict(state.metadata or {})
                global_metrics_defaults = metadata.get("global_metrics_defaults")
                if isinstance(global_metrics_defaults, dict):
                    global_defaults_entry = dict(global_metrics_defaults)
                    global_roi_mask = global_defaults_entry.pop("roi_mask", None)
                    if global_roi_mask is not None:
                        global_roi_ref = "global/roi_mask.npz"
                        write_npz(zf, global_roi_ref, global_roi_mask)
                        global_defaults_entry["roi_mask_ref"] = global_roi_ref
                    metadata["global_metrics_defaults"] = global_defaults_entry
                manifest = {
                    "schema_version": HOST_PROJECT_SCHEMA_VERSION,
                    "active_event_id": state.active_event_id,
                    "metadata": metadata,
                    "persistence": {"owner": HOST_PERSISTENCE_OWNER},
                }
                write_json(zf, "manifest.json", manifest)
                write_json(zf, "stack.json", asdict(state.stack_ref) if state.stack_ref is not None else None)
                write_json(
                    zf,
                    "events.json",
                    [
                        {
                            "event_id": str(event.event_id),
                            "label": str(event.label),
                            "global_start_idx": int(event.start_idx),
                            "global_end_idx": int(event.end_idx),
                            "flags": dict(event.flags),
                        }
                        for event in state.events
                    ],
                )

                sidecar_manifest: dict[str, Any] = {}
                for event_id, payload in dict(state.analysis_sidecar).items():
                    key = str(event_id)
                    event_base = f"events/{key}"
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
                    metrics_settings = payload.get("metrics_settings")
                    if isinstance(metrics_settings, dict):
                        metrics_entry = dict(metrics_settings)
                        roi_mask = metrics_entry.pop("roi_mask", None)
                        if roi_mask is not None:
                            roi_ref = f"{event_base}/roi_mask.npz"
                            write_npz(zf, roi_ref, roi_mask)
                            metrics_entry["roi_mask_ref"] = roi_ref
                        entry["metrics_settings"] = metrics_entry
                    for k in ("propagation_completed", "analysis_output_dir", "encoding", "frame_count", "shape", "blob_ref"):
                        if k in payload:
                            entry[k] = payload.get(k)
                    sidecar_manifest[key] = entry

                write_json(zf, "analysis_sidecar.json", sidecar_manifest)
            tmp_path.replace(target)
        finally:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    def load(self, source_path: str | Path) -> UnifiedProjectState:
        src = Path(source_path).expanduser().resolve()
        with zipfile.ZipFile(src, "r") as zf:
            manifest = read_json(zf, "manifest.json", default={})
            if not isinstance(manifest, dict) or not manifest:
                raise ValueError("Not a host .sdproj container")
            persistence = manifest.get("persistence", {}) if isinstance(manifest, dict) else {}
            owner = persistence.get("owner")
            if owner is not None and str(owner) != HOST_PERSISTENCE_OWNER:
                raise ValueError(f"Unsupported persistence owner: {owner}")

            stack_ref = _coerce_stack_ref(read_json(zf, "stack.json", default=None))
            events = _coerce_events(read_json(zf, "events.json", default=[]))
            metadata = dict(manifest.get("metadata", {})) if isinstance(manifest, dict) else {}
            global_metrics_defaults = metadata.get("global_metrics_defaults")
            if isinstance(global_metrics_defaults, dict):
                global_defaults = dict(global_metrics_defaults)
                roi_mask_ref = global_defaults.pop("roi_mask_ref", None)
                if isinstance(roi_mask_ref, str):
                    global_roi_mask = read_npz(zf, roi_mask_ref)
                    if global_roi_mask is not None:
                        global_defaults["roi_mask"] = np.asarray(global_roi_mask, dtype=bool).copy()
                metadata["global_metrics_defaults"] = global_defaults
            active_event_id = manifest.get("active_event_id") if isinstance(manifest, dict) else None

            sidecar_raw = read_json(zf, "analysis_sidecar.json", default={})
            sidecar: dict[str, Any] = {}
            if isinstance(sidecar_raw, dict):
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
                    metrics_settings = loaded_entry.get("metrics_settings")
                    if isinstance(metrics_settings, dict):
                        metrics_entry = dict(metrics_settings)
                        roi_mask_ref = metrics_entry.pop("roi_mask_ref", None)
                        if isinstance(roi_mask_ref, str):
                            roi_mask = read_npz(zf, roi_mask_ref)
                            if roi_mask is not None:
                                metrics_entry["roi_mask"] = np.asarray(roi_mask, dtype=bool).copy()
                        loaded_entry["metrics_settings"] = metrics_entry
                    sidecar[key] = loaded_entry

            return UnifiedProjectState(
                stack_ref=stack_ref,
                events=events,
                active_event_id=str(active_event_id) if active_event_id is not None else None,
                analysis_sidecar=sidecar,
                project_path=str(src),
                dirty=False,
                metadata=metadata,
            )
