from __future__ import annotations

import os
import tempfile
import zipfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from sdapp.shared.models import EventMeta, StackRef, UnifiedProjectState
from sdapp.shared.persistence.schema import (
    ACTIVE_EVENT_ID_FIELD,
    ANALYSIS_SIDECAR_FILENAME,
    EMBEDDED_IMAGES_FILENAME,
    EMBEDDED_IMAGES_INDEX_KEY,
    EVENTS_FILENAME,
    HOST_PERSISTENCE_OWNER,
    HOST_PROJECT_SCHEMA_VERSION,
    MANIFEST_FILENAME,
    METADATA_EMBED_IMAGES_KEY,
    METADATA_FIELD,
    PERSISTENCE_BLOCK_FIELD,
    PERSISTENCE_OWNER_FIELD,
    SCHEMA_VERSION_FIELD,
    STACK_FILENAME,
)
from sdapp.shared.persistence.serialization import (
    decode_analysis_sidecar,
    decode_metadata_from_read,
    encode_analysis_sidecar,
    encode_embedded_images,
    encode_metadata_for_write,
)
from sdapp.shared.errors import ProjectLoadError
from sdapp.shared.persistence.zip_io import read_json, read_npz, touch_extract_dir_marker, write_json, write_npz


def _coerce_stack_ref(raw: dict[str, Any] | None) -> StackRef | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ProjectLoadError("Stack reference data must be a dictionary.")
    try:
        return StackRef(
            input_dir=str(raw["input_dir"]),
            frame_count=int(raw["frame_count"]),
            frame_height=int(raw["frame_height"]),
            frame_width=int(raw["frame_width"]),
            dtype=str(raw.get("dtype", "uint8")),
        )
    except KeyError as e:
        raise ProjectLoadError(f"Missing required stack reference field: {e}")
    except ValueError as e:
        raise ProjectLoadError(f"Invalid value in stack reference: {e}")
    except Exception as e:
        raise ProjectLoadError(f"Failed to load stack reference: {e}")


def _coerce_events(raw: Any) -> list[EventMeta]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ProjectLoadError("Events data must be a list.")
    
    out: list[EventMeta] = []
    for i, event in enumerate(raw):
        if not isinstance(event, dict):
            raise ProjectLoadError(f"Event at index {i} must be a dictionary.")
        try:
            start = event.get("global_start_idx", event.get("start_idx", event.get("frame_start")))
            end = event.get("global_end_idx", event.get("end_idx", event.get("frame_end")))
            
            if start is None or end is None:
                raise KeyError("Missing start or end index for event.")

            event_id = event.get("event_id", event.get("id"))
            if event_id is None:
                raise KeyError("Missing event_id.")

            out.append(
                EventMeta(
                    event_id=str(event_id),
                    label=str(event.get("label", event_id)),
                    global_start_idx=int(start),
                    global_end_idx=int(end),
                    flags=dict(event.get("flags", {})),
                )
            )
        except KeyError as e:
            raise ProjectLoadError(f"Missing required event field at index {i}: {e}")
        except ValueError as e:
            raise ProjectLoadError(f"Invalid value in event at index {i}: {e}")
        except Exception as e:
            raise ProjectLoadError(f"Failed to load event at index {i}: {e}")
    return out


class UnifiedProjectStore:
    persistence_owner = HOST_PERSISTENCE_OWNER

    def save(
        self,
        target_path: str | Path,
        state: UnifiedProjectState,
        *,
        embedded_images_input_dir: str | Path | None = None,
    ) -> None:
        target = Path(target_path).expanduser().resolve()
        if target.suffix.lower() != ".sdproj":
            target = target.with_suffix(".sdproj")
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(suffix=".sdproj.tmp", dir=str(target.parent))
        os.close(fd)
        tmp_path = Path(tmp_name)
        try:
            with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                metadata = encode_metadata_for_write(dict(state.metadata or {}), zf)
                manifest = {
                    SCHEMA_VERSION_FIELD: HOST_PROJECT_SCHEMA_VERSION,
                    ACTIVE_EVENT_ID_FIELD: state.active_event_id,
                    METADATA_FIELD: metadata,
                    PERSISTENCE_BLOCK_FIELD: {PERSISTENCE_OWNER_FIELD: HOST_PERSISTENCE_OWNER},
                }
                write_json(zf, MANIFEST_FILENAME, manifest)
                write_json(zf, STACK_FILENAME, asdict(state.stack_ref) if state.stack_ref is not None else None)
                if state.metadata.get(METADATA_EMBED_IMAGES_KEY) and state.stack_ref is not None:
                    source_dir = embedded_images_input_dir or state.stack_ref.input_dir
                    embed_manifest = encode_embedded_images(source_dir, zf, require_sources=True)
                    write_json(zf, EMBEDDED_IMAGES_FILENAME, embed_manifest)
                write_json(
                    zf,
                    EVENTS_FILENAME,
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
                sidecar_manifest = encode_analysis_sidecar(dict(state.analysis_sidecar), zf)
                write_json(zf, ANALYSIS_SIDECAR_FILENAME, sidecar_manifest)
            tmp_path.replace(target)
        finally:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    def load(self, source_path: str | Path) -> UnifiedProjectState:
        src = Path(source_path).expanduser().resolve()
        with zipfile.ZipFile(src, "r") as zf:
            manifest = read_json(zf, MANIFEST_FILENAME, default={})
            if not isinstance(manifest, dict) or not manifest:
                raise ValueError("Not a host .sdproj container")
            try:
                schema_version = int(manifest.get(SCHEMA_VERSION_FIELD, 1))
            except Exception as exc:
                raise ProjectLoadError("Invalid host project schema version.") from exc
            if schema_version > HOST_PROJECT_SCHEMA_VERSION:
                raise ProjectLoadError(
                    f"Unsupported host project schema version {schema_version}; "
                    f"this build supports up to {HOST_PROJECT_SCHEMA_VERSION}."
                )
            persistence = manifest.get(PERSISTENCE_BLOCK_FIELD, {}) if isinstance(manifest, dict) else {}
            owner = persistence.get(PERSISTENCE_OWNER_FIELD)
            if owner is not None and str(owner) != HOST_PERSISTENCE_OWNER:
                raise ValueError(f"Unsupported persistence owner: {owner}")

            stack_ref = _coerce_stack_ref(read_json(zf, STACK_FILENAME, default=None))
            events = _coerce_events(read_json(zf, EVENTS_FILENAME, default=[]))
            metadata = decode_metadata_from_read(dict(manifest.get(METADATA_FIELD, {})) if isinstance(manifest, dict) else {}, zf)
            active_event_id = manifest.get(ACTIVE_EVENT_ID_FIELD) if isinstance(manifest, dict) else None
            sidecar_raw = read_json(zf, ANALYSIS_SIDECAR_FILENAME, default={})
            sidecar = decode_analysis_sidecar(sidecar_raw, zf)

            return UnifiedProjectState(
                stack_ref=stack_ref,
                events=events,
                active_event_id=str(active_event_id) if active_event_id is not None else None,
                analysis_sidecar=sidecar,
                project_path=str(src),
                dirty=False,
                metadata=metadata,
            )

    def extract_embedded_images(
        self, source_path: str | Path, dest_dir: str | Path | None = None
    ) -> str | None:
        """Extract embedded source images from a project into a directory.

        Returns the directory path containing the extracted frames (a fresh temp dir
        when ``dest_dir`` is None), or ``None`` when the project embeds no images.
        The returned directory can be handed to ``StackReader.open_stack`` unchanged.
        """
        src = Path(source_path).expanduser().resolve()
        with zipfile.ZipFile(src, "r") as zf:
            index = read_json(zf, EMBEDDED_IMAGES_FILENAME, default={EMBEDDED_IMAGES_INDEX_KEY: {}})
            embedded = index.get(EMBEDDED_IMAGES_INDEX_KEY, {}) if isinstance(index, dict) else {}
            if not embedded:
                return None
            if dest_dir is None:
                extract_root = Path(tempfile.mkdtemp(prefix="sdproj_embedded_"))
            else:
                extract_root = Path(dest_dir)
                extract_root.mkdir(parents=True, exist_ok=True)
            extracted_any = False
            for name, arcname in embedded.items():
                try:
                    out_path = extract_root / Path(str(name)).name
                    with zf.open(str(arcname), "r") as src_f, out_path.open("wb") as out_f:
                        out_f.write(src_f.read())
                    extracted_any = True
                except KeyError:
                    continue
            if not extracted_any:
                return None
            touch_extract_dir_marker(extract_root)
            return str(extract_root)
