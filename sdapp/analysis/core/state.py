import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from sdapp.analysis.utils.paths import get_app_root, get_resources_root, resolve_path, get_runtime_root


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
                default_model="models/sam2.1_hiera_base_plus.pt",
                default_baseline=30,
            )

        data: Dict[str, Any] = {}
        try:
            data = json.loads(config_path.read_text())
        except Exception:
            # Fall back to defaults if config is invalid
            return cls(
                default_output="output",
                default_model="models/sam2.1_hiera_base_plus.pt",
                default_baseline=30,
            )

        return cls(
            default_output=str(data.get("default_output", "output")),
            default_model=str(data.get("default_model", "models/sam2.1_hiera_base_plus.pt")),
            default_baseline=int(data.get("default_baseline", 30)),
        )

    def output_path(self) -> Path:
        candidate = Path(self.default_output)
        if candidate.is_absolute():
            return candidate
        return (get_runtime_root() / candidate).resolve()

    def model_path(self) -> Path:
        return resolve_path(self.default_model)
