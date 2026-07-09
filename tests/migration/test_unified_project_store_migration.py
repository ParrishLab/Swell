from __future__ import annotations

import io
import json
import zipfile

import numpy as np
import pytest

from swell.shared.models import EventMeta, StackRef, UnifiedProjectState
from swell.shared.errors import ProjectLoadError
from swell.shared.persistence import UnifiedProjectStore


def _state() -> UnifiedProjectState:
    return UnifiedProjectState(
        stack_ref=StackRef(
            input_dir="/tmp/in",
            frame_count=5,
            frame_height=16,
            frame_width=16,
            dtype="uint8",
        ),
        events=[EventMeta(event_id="event_0001", label="E1", start_idx=1, end_idx=3, flags={})],
        active_event_id="event_0001",
        analysis_sidecar={
            "event_0001": {
                "prompts": {"points": []},
                "masks_committed": np.zeros((3, 16, 16), dtype=np.uint8),
            }
        },
        metadata={
            "session_id": "session_abc",
            "model_checkpoint": {
                "checkpoint_id": "sam2.1_hiera_base_plus",
                "filename": "sam2.1_hiera_base_plus.pt",
                "path": "/tmp/models/sam2.1_hiera_base_plus.pt",
                "sha256": "abc123",
                "source": "managed_default",
            },
        },
    )


def test_canonical_swell_layout_is_single_stack(tmp_path) -> None:
    store = UnifiedProjectStore()
    out = tmp_path / "single_stack.swell"
    store.save(out, _state())

    with zipfile.ZipFile(out, "r") as zf:
        names = set(zf.namelist())
        assert "manifest.json" in names
        assert "stack.json" in names
        assert "events.json" in names
        assert "analysis_sidecar.json" in names
        assert "events/event_0001/prompts.json" in names
        assert "events/event_0001/masks.npz" in names
        assert all(not name.startswith("sd_sets/") for name in names)

        events = json.loads(zf.read("events.json").decode("utf-8"))
        assert events[0]["global_start_idx"] == 1
        assert events[0]["global_end_idx"] == 3


def test_canonical_store_roundtrip_preserves_analysis_payload(tmp_path) -> None:
    store = UnifiedProjectStore()
    out = tmp_path / "roundtrip.swell"
    store.save(out, _state())

    loaded = store.load(out)
    assert loaded.stack_ref is not None
    assert loaded.stack_ref.frame_count == 5
    assert loaded.active_event_id == "event_0001"
    assert len(loaded.events) == 1
    payload = loaded.analysis_sidecar["event_0001"]
    assert payload["prompts"] == {"points": []}
    assert payload["masks_committed"].shape == (3, 16, 16)
    checkpoint_meta = loaded.metadata.get("model_checkpoint")
    assert isinstance(checkpoint_meta, dict)
    assert checkpoint_meta.get("checkpoint_id") == "sam2.1_hiera_base_plus"


def _stack_dir_with_frames(tmp_path, names) -> str:
    stack_dir = tmp_path / "frames"
    stack_dir.mkdir()
    for name in names:
        (stack_dir / name).write_bytes(b"fake-image-bytes")
    return str(stack_dir)


def test_embed_source_images_writes_index_and_extracts(tmp_path) -> None:
    store = UnifiedProjectStore()
    frame_names = ["frame_001.png", "frame_002.png", "frame_003.png"]
    stack_dir = _stack_dir_with_frames(tmp_path, frame_names)

    state = _state()
    state.stack_ref = StackRef(
        input_dir=stack_dir, frame_count=3, frame_height=16, frame_width=16, dtype="uint8"
    )
    state.metadata["embed_source_images"] = True

    out = tmp_path / "embedded.swell"
    store.save(out, state)

    with zipfile.ZipFile(out, "r") as zf:
        names = set(zf.namelist())
        assert "images_embedded.json" in names
        assert {f"images/{n}" for n in frame_names} <= names
        index = json.loads(zf.read("images_embedded.json").decode("utf-8"))
        assert set(index["embedded"]) == set(frame_names)

    extract_to = tmp_path / "extracted"
    extracted = store.extract_embedded_images(out, extract_to)
    assert extracted is not None
    extracted_files = {p.name for p in extract_to.iterdir() if p.is_file() and not p.name.startswith(".")}
    assert extracted_files == set(frame_names)


def test_embed_source_images_missing_source_raises(tmp_path) -> None:
    store = UnifiedProjectStore()
    state = _state()
    state.stack_ref = StackRef(
        input_dir=str(tmp_path / "missing"), frame_count=3, frame_height=16, frame_width=16, dtype="uint8"
    )
    state.metadata["embed_source_images"] = True

    with pytest.raises(FileNotFoundError, match="no supported image files"):
        store.save(tmp_path / "missing_embed.swell", state)


def test_embed_source_images_override_preserves_persisted_stack_ref(tmp_path) -> None:
    store = UnifiedProjectStore()
    frame_names = ["frame_001.png", "frame_002.png"]
    extracted_dir = _stack_dir_with_frames(tmp_path, frame_names)
    original_dir = str(tmp_path / "original_missing")
    state = _state()
    state.stack_ref = StackRef(
        input_dir=original_dir, frame_count=2, frame_height=16, frame_width=16, dtype="uint8"
    )
    state.metadata["embed_source_images"] = True

    out = tmp_path / "override_embed.swell"
    store.save(out, state, embedded_images_input_dir=extracted_dir)

    with zipfile.ZipFile(out, "r") as zf:
        stack = json.loads(zf.read("stack.json").decode("utf-8"))
        names = set(zf.namelist())
        assert stack["input_dir"] == original_dir
        assert {f"images/{name}" for name in frame_names} <= names


def test_embed_source_images_duplicate_basenames_extract_distinct_files(tmp_path) -> None:
    store = UnifiedProjectStore()
    dir_a = tmp_path / "A"
    dir_b = tmp_path / "B"
    dir_a.mkdir()
    dir_b.mkdir()
    img_a = dir_a / "1.png"
    img_b = dir_b / "1.png"
    img_a.write_bytes(b"from-a")
    img_b.write_bytes(b"from-b")
    original_dir = str(tmp_path / "original_missing")
    state = _state()
    state.stack_ref = StackRef(
        input_dir=original_dir, frame_count=2, frame_height=16, frame_width=16, dtype="uint8"
    )
    state.metadata["embed_source_images"] = True

    out = tmp_path / "duplicate_basename_embed.swell"
    store.save(out, state, embedded_images_input_dir=[img_a, img_b])

    with zipfile.ZipFile(out, "r") as zf:
        names = set(zf.namelist())
        assert "images/1.png" in names
        assert "images/1_2.png" in names
        index = json.loads(zf.read("images_embedded.json").decode("utf-8"))
        assert index["embedded"] == {"1.png": "images/1.png", "1_2.png": "images/1_2.png"}

    extract_to = tmp_path / "dupe_extract"
    extracted = store.extract_embedded_images(out, extract_to)

    assert extracted is not None
    assert (extract_to / "1.png").read_bytes() == b"from-a"
    assert (extract_to / "1_2.png").read_bytes() == b"from-b"


def test_embed_toggle_off_keeps_reference_only(tmp_path) -> None:
    store = UnifiedProjectStore()
    stack_dir = _stack_dir_with_frames(tmp_path, ["frame_001.png"])
    state = _state()
    state.stack_ref = StackRef(
        input_dir=stack_dir, frame_count=1, frame_height=16, frame_width=16, dtype="uint8"
    )
    # embed flag not set -> reference-only (v2-equivalent) layout

    out = tmp_path / "ref_only.swell"
    store.save(out, state)

    with zipfile.ZipFile(out, "r") as zf:
        names = set(zf.namelist())
        assert not any(name.startswith("images/") for name in names)
        assert "images_embedded.json" not in names
    assert store.extract_embedded_images(out) is None


def test_v2_project_without_embed_index_loads(tmp_path) -> None:
    # Craft a schema-v2 container with no embedded-images index.
    out = tmp_path / "legacy_v2.swell"
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(
                {
                    "schema_version": 2,
                    "active_event_id": None,
                    "metadata": {},
                    "persistence": {"owner": "host_sdproj"},
                }
            ),
        )
        zf.writestr(
            "stack.json",
            json.dumps(
                {
                    "input_dir": "/tmp/in",
                    "frame_count": 4,
                    "frame_height": 8,
                    "frame_width": 8,
                    "dtype": "uint8",
                }
            ),
        )
        zf.writestr("events.json", json.dumps([]))
        zf.writestr("analysis_sidecar.json", json.dumps({}))

    store = UnifiedProjectStore()
    loaded = store.load(out)
    assert loaded.stack_ref is not None
    assert loaded.stack_ref.frame_count == 4
    assert store.extract_embedded_images(out) is None


def test_future_host_schema_version_is_rejected(tmp_path) -> None:
    out = tmp_path / "future.swell"
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(
                {
                    "schema_version": 999,
                    "active_event_id": None,
                    "metadata": {},
                    "persistence": {"owner": "host_sdproj"},
                }
            ),
        )
        zf.writestr(
            "stack.json",
            json.dumps(
                {
                    "input_dir": "/tmp/in",
                    "frame_count": 4,
                    "frame_height": 8,
                    "frame_width": 8,
                    "dtype": "uint8",
                }
            ),
        )
        zf.writestr("events.json", json.dumps([]))
        zf.writestr("analysis_sidecar.json", json.dumps({}))

    with pytest.raises(ProjectLoadError, match="Unsupported host project schema version"):
        UnifiedProjectStore().load(out)
