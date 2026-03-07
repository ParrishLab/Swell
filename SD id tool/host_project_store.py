from __future__ import annotations

import io
import json
import os
import tempfile
import zipfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

from host_models import EventMeta, HostSessionState, SDSetState, StackRef


HOST_PROJECT_SCHEMA_VERSION = 1
HOST_PERSISTENCE_OWNER = "host_sdproj"


def _read_json(zf: zipfile.ZipFile, arcname: str, default: Any) -> Any:
    try:
        with zf.open(arcname, "r") as f:
            return json.loads(f.read().decode("utf-8"))
    except KeyError:
        return default


def _write_json(zf: zipfile.ZipFile, arcname: str, payload: Any) -> None:
    zf.writestr(arcname, json.dumps(payload, indent=2))


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
            out.append(
                EventMeta(
                    event_id=str(event.get("event_id", event.get("id", ""))),
                    label=str(event.get("label", event.get("event_id", event.get("id", "")))),
                    start_idx=int(event.get("start_idx", event.get("frame_start", 0))),
                    end_idx=int(event.get("end_idx", event.get("frame_end", 0))),
                    flags=dict(event.get("flags", {})),
                )
            )
        except Exception:
            continue
    return out


class HostProjectStore:
    def save(self, target_path: str | Path, state: HostSessionState) -> None:
        target = Path(target_path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(suffix=".sdproj.tmp", dir=str(target.parent))
        os.close(fd)
        tmp_path = Path(tmp_name)
        try:
            with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                manifest = {
                    "schema_version": HOST_PROJECT_SCHEMA_VERSION,
                    "active_sd_set_id": state.active_sd_set_id,
                    "metadata": dict(state.metadata),
                    "persistence": {
                        "owner": HOST_PERSISTENCE_OWNER,
                    },
                    "sd_sets": sorted(state.sd_sets.keys()),
                }
                _write_json(zf, "manifest.json", manifest)
                for sd_set_id, sd_set in state.sd_sets.items():
                    base = f"sd_sets/{sd_set_id}"
                    _write_json(zf, f"{base}/stack.json", asdict(sd_set.stack_ref) if sd_set.stack_ref is not None else None)
                    _write_json(
                        zf,
                        f"{base}/events.json",
                        [asdict(event) for event in sd_set.events],
                    )
                    _write_json(zf, f"{base}/analysis_sidecar.json", dict(sd_set.analysis_sidecar))
                    _write_json(zf, f"{base}/metadata.json", dict(sd_set.metadata))
                    _write_json(zf, f"{base}/active_event.json", {"active_event_id": sd_set.active_event_id})
            tmp_path.replace(target)
        finally:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    def load(self, source_path: str | Path) -> HostSessionState:
        src = Path(source_path).expanduser().resolve()
        with zipfile.ZipFile(src, "r") as zf:
            manifest = _read_json(zf, "manifest.json", default={})
            if not isinstance(manifest, dict) or not manifest:
                raise ValueError("Not a host multi-SD .sdproj container")
            persistence = manifest.get("persistence", {}) if isinstance(manifest, dict) else {}
            owner = persistence.get("owner")
            if owner is not None and str(owner) != HOST_PERSISTENCE_OWNER:
                raise ValueError(f"Unsupported persistence owner: {owner}")
            active_sd_set_id = manifest.get("active_sd_set_id") if isinstance(manifest, dict) else None
            metadata = dict(manifest.get("metadata", {})) if isinstance(manifest, dict) else {}
            sd_sets: dict[str, SDSetState] = {}
            for sd_set_id in list(manifest.get("sd_sets", [])) if isinstance(manifest, dict) else []:
                set_id = str(sd_set_id)
                base = f"sd_sets/{set_id}"
                stack_ref = _coerce_stack_ref(_read_json(zf, f"{base}/stack.json", default=None))
                events = _coerce_events(_read_json(zf, f"{base}/events.json", default=[]))
                sidecar = _read_json(zf, f"{base}/analysis_sidecar.json", default={})
                set_meta = _read_json(zf, f"{base}/metadata.json", default={})
                active_event = _read_json(zf, f"{base}/active_event.json", default={}).get("active_event_id")
                sd_sets[set_id] = SDSetState(
                    sd_set_id=set_id,
                    stack_ref=stack_ref,
                    events=events,
                    active_event_id=str(active_event) if active_event is not None else None,
                    analysis_sidecar=dict(sidecar) if isinstance(sidecar, dict) else {},
                    metadata=dict(set_meta) if isinstance(set_meta, dict) else {},
                )
            return HostSessionState(
                active_sd_set_id=str(active_sd_set_id) if active_sd_set_id is not None else None,
                sd_sets=sd_sets,
                project_path=str(src),
                dirty=False,
                metadata=metadata,
            )

    def load_legacy_sdsession(self, source_path: str | Path) -> HostSessionState:
        src = Path(source_path).expanduser().resolve()
        payload = json.loads(src.read_text(encoding="utf-8"))
        persistence = payload.get("persistence")
        if isinstance(persistence, dict):
            owner = persistence.get("owner")
            if owner is not None and str(owner) not in ("host_sdsession", HOST_PERSISTENCE_OWNER):
                raise ValueError(f"Unsupported persistence owner: {owner}")
        sd_set_id = "sd_set_0001"
        stack_ref = _coerce_stack_ref(payload.get("stack_ref"))
        events = _coerce_events(payload.get("events", []))
        metadata = dict(payload.get("metadata", {}))
        sidecar = payload.get("analysis_sidecar")
        if not isinstance(sidecar, dict):
            sidecar = metadata.get("analysis_sidecar", {})
        sd_set = SDSetState(
            sd_set_id=sd_set_id,
            stack_ref=stack_ref,
            events=events,
            active_event_id=payload.get("active_event_id"),
            analysis_sidecar=dict(sidecar) if isinstance(sidecar, dict) else {},
            metadata={},
        )
        return HostSessionState(
            active_sd_set_id=sd_set_id,
            sd_sets={sd_set_id: sd_set},
            project_path=str(src),
            dirty=False,
            metadata=metadata,
        )

    def load_legacy_sdproj(self, source_path: str | Path) -> HostSessionState:
        src = Path(source_path).expanduser().resolve()
        with zipfile.ZipFile(src, "r") as zf:
            state = _read_json(zf, "project_state.json", default={})
            images = _read_json(zf, "images.json", default={"images": []})
            if not state:
                raise ValueError("Invalid legacy .sdproj: missing project_state.json")
            frame_count = 0
            for ev in state.get("events", []):
                try:
                    frame_count = max(frame_count, int(ev.get("frame_end", 0)) + 1)
                except Exception:
                    continue
            frame_h = 0
            frame_w = 0
            dtype = "uint8"
            for ev in state.get("events", []):
                event_id = str(ev.get("id", ""))
                masks_ref = str(ev.get("masks_ref", f"events/{event_id}/masks.npz"))
                try:
                    with zf.open(masks_ref, "r") as f:
                        with np.load(io.BytesIO(f.read())) as npz:
                            arr = np.array(npz["masks"])
                        if arr.ndim == 3:
                            _, frame_h, frame_w = arr.shape
                            frame_count = max(frame_count, int(arr.shape[0]))
                            dtype = str(arr.dtype)
                            break
                except Exception:
                    continue
            first_image = ""
            for img in images.get("images", []):
                if isinstance(img, dict):
                    first_image = str(img.get("absolute_path", "") or img.get("relative_path", ""))
                    if first_image:
                        break
            input_dir = str(Path(first_image).parent) if first_image else ""
            stack_ref = StackRef(
                input_dir=input_dir,
                frame_count=frame_count,
                frame_height=frame_h,
                frame_width=frame_w,
                dtype=dtype,
            )
            events = _coerce_events(state.get("events", []))
            active_event = state.get("ui_state", {}).get("active_event_id")
            sd_set_id = "sd_set_0001"
            sd_set = SDSetState(
                sd_set_id=sd_set_id,
                stack_ref=stack_ref,
                events=events,
                active_event_id=str(active_event) if active_event is not None else None,
                analysis_sidecar={},
                metadata={},
            )
            return HostSessionState(
                active_sd_set_id=sd_set_id,
                sd_sets={sd_set_id: sd_set},
                project_path=str(src),
                dirty=False,
                metadata={},
            )
