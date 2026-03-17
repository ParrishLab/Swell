import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from sdapp.analysis.utils.paths import get_app_root, get_resources_root, resolve_path, get_runtime_root
from sdapp.shared.services.checkpoint_runtime_service import is_managed_uri


@dataclass
class AppConfig:
    default_output: str
    default_model: str
    default_baseline: int

    @classmethod
    def load(cls) -> "AppConfig":
        config_path = get_runtime_root() / "config.json"
        if not config_path.exists():
            config_path = get_resources_root() / "config.json"
        if not config_path.exists():
            # Fall back to app root.
            config_path = get_app_root() / "config.json"
        if not config_path.exists():
            return cls(
                default_output="output",
                default_model="managed://sam2.1_hiera_base_plus",
                default_baseline=30,
            )

        data: Dict[str, Any] = {}
        try:
            data = json.loads(config_path.read_text())
        except Exception:
            # Fall back to defaults if config is invalid
            return cls(
                default_output="output",
                default_model="managed://sam2.1_hiera_base_plus",
                default_baseline=30,
            )

        return cls(
            default_output=str(data.get("default_output", "output")),
            default_model=str(data.get("default_model", "managed://sam2.1_hiera_base_plus")),
            default_baseline=int(data.get("default_baseline", 30)),
        )

    def output_path(self) -> Path:
        candidate = Path(self.default_output)
        if candidate.is_absolute():
            return candidate
        return (get_runtime_root() / candidate).resolve()

    def model_token(self) -> str:
        return str(self.default_model or "").strip()

    def model_path(self) -> Path | str:
        token = self.model_token()
        if is_managed_uri(token):
            return token
        return resolve_path(token)
