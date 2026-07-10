from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

import swell.shared.services.checkpoint_runtime_service as checkpoint_module
from swell.shared.services.checkpoint_runtime_service import (
    CheckpointRuntimeService,
    MODEL_CHECKPOINT_METADATA_KEY,
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


def test_internal_metadata_key_remains_legacy_checkpoint_key() -> None:
    # Keep persisted contract stable while UI terminology says "model".
    assert MODEL_CHECKPOINT_METADATA_KEY == "model_checkpoint"


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
    monkeypatch.setenv("SWELL_MODELS_DIR", str((tmp_path / "managed_models").resolve()))
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
    monkeypatch.setenv("SWELL_MODELS_DIR", str((tmp_path / "managed_models").resolve()))
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

    def _raise_http_error(_request, timeout=120, context=None):  # noqa: ARG001
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


def test_download_descriptor_uses_fallback_url_when_primary_fails(tmp_path: Path, monkeypatch) -> None:
    catalog = _write_catalog(tmp_path / "catalog.json")
    monkeypatch.setenv("SWELL_MODELS_DIR", str((tmp_path / "managed_models").resolve()))
    service = CheckpointRuntimeService(catalog_path=catalog)
    descriptor = service.default_descriptor()
    assert descriptor is not None
    descriptor = type(
        "D",
        (),
        {
            "checkpoint_id": descriptor.checkpoint_id,
            "filename": descriptor.filename,
            "download_url": "https://example.invalid/primary.pt",
            "sha256": None,
        },
    )()

    attempted: list[str] = []
    real_fallback = checkpoint_module.FALLBACK_DOWNLOAD_URLS_BY_ID.get("sam2.1_hiera_base_plus", [])[0]

    def _fake_download(url: str, out_path: Path) -> None:
        attempted.append(str(url))
        if str(url).endswith("/primary.pt"):
            raise RuntimeError("HTTP Error 403: Forbidden")
        out_path.write_bytes(b"ok")

    monkeypatch.setattr(service, "_download_url_to_file", _fake_download)
    target = service.download_descriptor(descriptor)

    assert target.exists()
    assert attempted[0].endswith("/primary.pt")
    assert any(url == real_fallback for url in attempted[1:])


def test_app_data_root_uses_xdg_location_on_linux(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(checkpoint_module.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))

    assert checkpoint_module._app_data_root() == (tmp_path / "xdg-data" / "swell").resolve()


def test_replace_file_with_retry_eventually_succeeds(monkeypatch, tmp_path: Path) -> None:
    service = CheckpointRuntimeService(catalog_path=_write_catalog(tmp_path / "catalog.json"))
    src = tmp_path / "src.bin"
    dst = tmp_path / "dst.bin"
    src.write_bytes(b"new")
    dst.write_bytes(b"old")
    calls = {"count": 0}
    real_replace = Path.replace

    def _flaky_replace(self, target):  # noqa: ANN001
        if self == src and calls["count"] < 2:
            calls["count"] += 1
            raise PermissionError("locked")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", _flaky_replace)

    service._replace_file_with_retry(src, dst, retries=4, sleep_s=0.0)
    assert dst.read_bytes() == b"new"
