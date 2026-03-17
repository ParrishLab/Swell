from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

import sdapp.shared.services.checkpoint_runtime_service as checkpoint_module
from sdapp.shared.services.checkpoint_runtime_service import (
    CheckpointRuntimeService,
    is_managed_uri,
    managed_uri_to_id,
)


def _write_catalog(path: Path) -> Path:
    payload = {
        "checkpoints": [
            {
                "id": "sam2.1_hiera_base_plus",
                "filename": "sam2.1_hiera_base_plus.pt",
                "download_url": None,
                "sha256": None,
                "default": True,
            }
        ]
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_managed_uri_helpers() -> None:
    assert is_managed_uri("managed://sam2.1_hiera_base_plus")
    assert managed_uri_to_id("managed://sam2.1_hiera_base_plus") == "sam2.1_hiera_base_plus"
    assert not is_managed_uri("models/x.pt")
    assert managed_uri_to_id("models/x.pt") is None


def test_resolution_prefers_project_recorded(tmp_path: Path) -> None:
    catalog = _write_catalog(tmp_path / "catalog.json")
    service = CheckpointRuntimeService(catalog_path=catalog)
    project_path = tmp_path / "project_model.pt"
    project_path.write_bytes(b"project")
    manual_path = tmp_path / "manual_model.pt"
    manual_path.write_bytes(b"manual")
    resolved = service.resolve_checkpoint(
        project_checkpoint_meta={
            "checkpoint_id": "sam2.1_hiera_base_plus",
            "path": str(project_path),
            "filename": project_path.name,
        },
        configured_model="managed://sam2.1_hiera_base_plus",
        manual_override=str(manual_path),
    )
    assert resolved.ok is True
    assert resolved.source == "project_recorded"
    assert resolved.path == str(project_path.resolve())


def test_resolution_uses_managed_default_before_manual_override(tmp_path: Path, monkeypatch) -> None:
    catalog = _write_catalog(tmp_path / "catalog.json")
    monkeypatch.setenv("SDAPP_MODELS_DIR", str((tmp_path / "managed_models").resolve()))
    service = CheckpointRuntimeService(catalog_path=catalog)
    managed_dir = service.managed_models_dir()
    managed_file = managed_dir / "sam2.1_hiera_base_plus.pt"
    managed_file.parent.mkdir(parents=True, exist_ok=True)
    managed_file.write_bytes(b"managed")
    manual_path = tmp_path / "manual_model.pt"
    manual_path.write_bytes(b"manual")
    resolved = service.resolve_checkpoint(
        project_checkpoint_meta=None,
        configured_model="managed://sam2.1_hiera_base_plus",
        manual_override=str(manual_path),
    )
    assert resolved.ok is True
    assert resolved.source == "managed_default"
    assert resolved.path == str(managed_file.resolve())


def test_compare_metadata_detects_mismatch(tmp_path: Path) -> None:
    catalog = _write_catalog(tmp_path / "catalog.json")
    service = CheckpointRuntimeService(catalog_path=catalog)
    a = {"checkpoint_id": "sam2.1_hiera_base_plus", "filename": "a.pt", "sha256": "abc"}
    b = {"checkpoint_id": "sam2.1_hiera_base_plus", "filename": "a.pt", "sha256": "def"}
    ok, message = service.compare_checkpoint_metadata(a, b)
    assert ok is False
    assert "hash" in message.lower()


def test_download_descriptor_raises_clear_error_on_http_403(tmp_path: Path, monkeypatch) -> None:
    catalog = _write_catalog(tmp_path / "catalog.json")
    monkeypatch.setenv("SDAPP_MODELS_DIR", str((tmp_path / "managed_models").resolve()))
    service = CheckpointRuntimeService(catalog_path=catalog)
    descriptor = service.default_descriptor()
    assert descriptor is not None
    descriptor = type(
        "D",
        (),
        {
            "checkpoint_id": descriptor.checkpoint_id,
            "filename": descriptor.filename,
            "download_url": "https://example.invalid/model.pt",
            "sha256": None,
        },
    )()

    def _raise_http_error(_request, timeout=120):  # noqa: ARG001
        raise HTTPError(
            url="https://example.invalid/model.pt",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(checkpoint_module, "urlopen", _raise_http_error)

    with pytest.raises(RuntimeError) as exc_info:
        service.download_descriptor(descriptor)
    assert "forbidden" in str(exc_info.value).lower()
