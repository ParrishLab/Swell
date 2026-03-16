from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any
from urllib.request import urlopen


MANAGED_URI_PREFIX = "managed://"
MODEL_CHECKPOINT_METADATA_KEY = "model_checkpoint"


@dataclass(frozen=True)
class CheckpointDescriptor:
    checkpoint_id: str
    filename: str
    download_url: str | None = None
    sha256: str | None = None
    is_default: bool = False


@dataclass(frozen=True)
class CheckpointResolution:
    ok: bool
    path: str | None
    source: str
    checkpoint_id: str | None = None
    descriptor: CheckpointDescriptor | None = None
    message: str | None = None


def _app_data_root() -> Path:
    if os.name == "nt":
        appdata = os.environ.get("APPDATA", "")
        if appdata.strip():
            return Path(appdata).expanduser().resolve() / "sdapp"
        return Path.home().resolve() / "AppData" / "Roaming" / "sdapp"
    return Path.home().resolve() / "Library" / "Application Support" / "sdapp"


def managed_models_dir() -> Path:
    env_override = str(os.environ.get("SDAPP_MODELS_DIR", "")).strip()
    if env_override:
        path = Path(env_override).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    candidates = [
        _app_data_root() / "models",
        Path.home().resolve() / ".sdapp" / "models",
        Path(tempfile.gettempdir()).resolve() / "sdapp" / "models",
    ]
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError:
            continue
    raise RuntimeError("Unable to create a writable managed model directory.")


def is_managed_uri(value: str | None) -> bool:
    raw = str(value or "").strip()
    return raw.startswith(MANAGED_URI_PREFIX) and len(raw) > len(MANAGED_URI_PREFIX)


def managed_uri_to_id(value: str | None) -> str | None:
    if not is_managed_uri(value):
        return None
    return str(value).strip()[len(MANAGED_URI_PREFIX) :].strip() or None


class CheckpointRuntimeService:
    def __init__(self, *, catalog_path: str | Path | None = None) -> None:
        self.catalog_path = (
            Path(catalog_path).expanduser().resolve()
            if catalog_path is not None
            else (Path(__file__).resolve().parents[2] / "resources" / "checkpoints_catalog.json")
        )
        self._catalog_cache: list[CheckpointDescriptor] | None = None

    def load_catalog(self) -> list[CheckpointDescriptor]:
        if self._catalog_cache is not None:
            return list(self._catalog_cache)
        if not self.catalog_path.exists():
            self._catalog_cache = []
            return []
        raw = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            self._catalog_cache = []
            return []
        items = raw.get("checkpoints", [])
        out: list[CheckpointDescriptor] = []
        for item in list(items or []):
            if not isinstance(item, dict):
                continue
            checkpoint_id = str(item.get("id", "")).strip()
            filename = str(item.get("filename", "")).strip()
            if not checkpoint_id or not filename:
                continue
            out.append(
                CheckpointDescriptor(
                    checkpoint_id=checkpoint_id,
                    filename=filename,
                    download_url=(str(item.get("download_url")).strip() or None) if item.get("download_url") else None,
                    sha256=(str(item.get("sha256")).strip().lower() or None) if item.get("sha256") else None,
                    is_default=bool(item.get("default", False)),
                )
            )
        self._catalog_cache = out
        return list(out)

    @staticmethod
    def managed_models_dir() -> Path:
        return managed_models_dir()

    def find_descriptor(self, checkpoint_id: str | None) -> CheckpointDescriptor | None:
        key = str(checkpoint_id or "").strip()
        if not key:
            return None
        for descriptor in self.load_catalog():
            if descriptor.checkpoint_id == key:
                return descriptor
        return None

    def default_descriptor(self) -> CheckpointDescriptor | None:
        catalog = self.load_catalog()
        for descriptor in catalog:
            if descriptor.is_default:
                return descriptor
        return catalog[0] if catalog else None

    def descriptor_path(self, descriptor: CheckpointDescriptor) -> Path:
        return managed_models_dir() / str(descriptor.filename)

    def build_checkpoint_metadata(
        self,
        *,
        checkpoint_id: str | None,
        path: str | Path,
        source: str,
        file_sha256: str | None = None,
    ) -> dict[str, Any]:
        p = Path(path).expanduser().resolve()
        sha = file_sha256 or self.compute_sha256(p)
        return {
            "checkpoint_id": (str(checkpoint_id).strip() if checkpoint_id else None),
            "filename": p.name,
            "path": str(p),
            "sha256": str(sha or "").strip().lower() or None,
            "source": str(source or "").strip() or "unknown",
        }

    @staticmethod
    def normalize_metadata(payload: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None
        out = {
            "checkpoint_id": (str(payload.get("checkpoint_id", "")).strip() or None),
            "filename": (str(payload.get("filename", "")).strip() or None),
            "path": (str(payload.get("path", "")).strip() or None),
            "sha256": (str(payload.get("sha256", "")).strip().lower() or None),
            "source": (str(payload.get("source", "")).strip() or None),
        }
        if not any(out.values()):
            return None
        return out

    def compute_sha256(self, path: str | Path) -> str | None:
        target = Path(path).expanduser().resolve()
        if not target.exists() or not target.is_file():
            return None
        h = sha256()
        with target.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    def resolve_checkpoint(
        self,
        *,
        project_checkpoint_meta: dict[str, Any] | None = None,
        configured_model: str | None = None,
        manual_override: str | None = None,
    ) -> CheckpointResolution:
        project_meta = self.normalize_metadata(project_checkpoint_meta)
        if project_meta is not None:
            candidate = str(project_meta.get("path") or "").strip()
            if candidate:
                path = Path(candidate).expanduser().resolve()
                if path.exists() and path.is_file():
                    descriptor = self.find_descriptor(project_meta.get("checkpoint_id"))
                    return CheckpointResolution(
                        ok=True,
                        path=str(path),
                        source="project_recorded",
                        checkpoint_id=(project_meta.get("checkpoint_id") or None),
                        descriptor=descriptor,
                    )

        default_descriptor = self.default_descriptor()
        if default_descriptor is not None:
            managed_path = self.descriptor_path(default_descriptor)
            if managed_path.exists() and managed_path.is_file():
                return CheckpointResolution(
                    ok=True,
                    path=str(managed_path.resolve()),
                    source="managed_default",
                    checkpoint_id=default_descriptor.checkpoint_id,
                    descriptor=default_descriptor,
                )

        manual = str(manual_override or "").strip()
        if manual:
            p = Path(manual).expanduser().resolve()
            if p.exists() and p.is_file():
                return CheckpointResolution(
                    ok=True,
                    path=str(p),
                    source="manual_override",
                    checkpoint_id=self.infer_checkpoint_id_from_path(p),
                    descriptor=self.find_descriptor(self.infer_checkpoint_id_from_path(p)),
                )

        configured = str(configured_model or "").strip()
        if configured:
            descriptor = None
            if is_managed_uri(configured):
                checkpoint_id = managed_uri_to_id(configured)
                descriptor = self.find_descriptor(checkpoint_id)
                if descriptor is not None:
                    managed_path = self.descriptor_path(descriptor)
                    if managed_path.exists() and managed_path.is_file():
                        return CheckpointResolution(
                            ok=True,
                            path=str(managed_path.resolve()),
                            source="configured_managed_uri",
                            checkpoint_id=descriptor.checkpoint_id,
                            descriptor=descriptor,
                        )
                return CheckpointResolution(
                    ok=False,
                    path=None,
                    source="configured_managed_uri",
                    checkpoint_id=checkpoint_id,
                    descriptor=descriptor,
                    message=f"Managed checkpoint is not available locally: {configured}",
                )

            p = Path(configured).expanduser().resolve()
            if p.exists() and p.is_file():
                return CheckpointResolution(
                    ok=True,
                    path=str(p),
                    source="configured_path",
                    checkpoint_id=self.infer_checkpoint_id_from_path(p),
                    descriptor=self.find_descriptor(self.infer_checkpoint_id_from_path(p)),
                )

        return CheckpointResolution(
            ok=False,
            path=None,
            source="missing",
            message="No valid checkpoint path is available.",
        )

    def infer_checkpoint_id_from_path(self, path: str | Path) -> str | None:
        p = Path(path).expanduser().resolve()
        filename = p.name.lower()
        for descriptor in self.load_catalog():
            if filename == descriptor.filename.lower():
                return descriptor.checkpoint_id
        return None

    def download_descriptor(self, descriptor: CheckpointDescriptor) -> Path:
        if not descriptor.download_url:
            raise RuntimeError(f"Checkpoint '{descriptor.checkpoint_id}' has no download URL.")
        target = self.descriptor_path(descriptor)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            suffix=f".{descriptor.filename}.tmp",
            dir=str(target.parent),
        )
        os.close(fd)
        tmp_path = Path(tmp_name)
        try:
            with urlopen(descriptor.download_url, timeout=120) as response, tmp_path.open("wb") as out:
                shutil.copyfileobj(response, out)
            digest = self.compute_sha256(tmp_path)
            if descriptor.sha256 and digest and digest.lower() != descriptor.sha256.lower():
                raise RuntimeError(
                    f"Checksum mismatch for '{descriptor.checkpoint_id}'. "
                    f"Expected {descriptor.sha256}, got {digest}."
                )
            tmp_path.replace(target)
            return target.resolve()
        finally:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    def compare_checkpoint_metadata(
        self,
        recorded: dict[str, Any] | None,
        active: dict[str, Any] | None,
    ) -> tuple[bool, str]:
        a = self.normalize_metadata(recorded)
        b = self.normalize_metadata(active)
        if a is None or b is None:
            return False, "Checkpoint metadata is missing."
        if a.get("sha256") and b.get("sha256") and a.get("sha256") != b.get("sha256"):
            return False, "Checkpoint hash differs from recorded project checkpoint."
        if a.get("checkpoint_id") and b.get("checkpoint_id") and a.get("checkpoint_id") != b.get("checkpoint_id"):
            return False, "Checkpoint id differs from recorded project checkpoint."
        if a.get("filename") and b.get("filename") and a.get("filename") != b.get("filename"):
            return False, "Checkpoint filename differs from recorded project checkpoint."
        return True, "Checkpoint metadata matches."
