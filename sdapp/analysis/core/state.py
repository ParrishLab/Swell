import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from sdapp.analysis.utils.paths import get_app_root, get_resources_root, resolve_path, get_runtime_root
from sdapp.shared.services.checkpoint_runtime_service import is_managed_uri


DEFAULT_UPDATE_CHANNELS = {
    "stable": {
        "windows": "https://github.com/ClayDunford/Combined-tool-test/releases/latest/download/appcast-windows.xml",
        "macos": "https://github.com/ClayDunford/Combined-tool-test/releases/latest/download/appcast-macos.xml",
    }
}


def _default_update_channels() -> dict[str, dict[str, str]]:
    return {channel: dict(platforms) for channel, platforms in DEFAULT_UPDATE_CHANNELS.items()}


def _default_config_values() -> dict[str, Any]:
    return {
        "default_output": "output",
        "default_model": "managed://sam2.1_hiera_base_plus",
        "default_baseline": 30,
        "auto_check_enabled": True,
        "release_channel": "stable",
        "last_update_check_at": None,
        "ignored_version": None,
        "update_channels": _default_update_channels(),
    }


def _runtime_config_dir() -> Path:
    if not getattr(sys, "frozen", False):
        return get_runtime_root()

    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / "SDApp"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "SDApp"
    return Path.home() / ".config" / "sdapp"


def _config_path_candidates() -> list[Path]:
    runtime_path = _runtime_config_dir() / "config.json"
    candidates = [runtime_path]
    for base in (get_runtime_root(), get_app_root()):
        path = Path(base) / "config.json"
        if path not in candidates:
            candidates.append(path)
    packaged_default = Path(get_resources_root()) / "default_config.json"
    if packaged_default not in candidates:
        candidates.append(packaged_default)
    return candidates


@dataclass
class AppConfig:
    default_output: str
    default_model: str
    default_baseline: int
    auto_check_enabled: bool = True
    release_channel: str = "stable"
    last_update_check_at: str | None = None
    ignored_version: str | None = None
    update_channels: dict[str, dict[str, str]] = field(default_factory=_default_update_channels)

    @classmethod
    def load(cls) -> "AppConfig":
        config_path = next((path for path in _config_path_candidates() if path.exists()), None)
        defaults = _default_config_values()
        if config_path is None:
            return cls(**defaults)

        data: Dict[str, Any] = {}
        try:
            data = json.loads(config_path.read_text())
        except Exception:
            # Fall back to defaults if config is invalid
            return cls(**defaults)

        merged = dict(defaults)
        merged.update(data)
        update_channels = merged.get("update_channels", _default_update_channels())
        if not isinstance(update_channels, dict):
            update_channels = _default_update_channels()
        normalized_channels: dict[str, dict[str, str]] = _default_update_channels()
        for channel, platforms in update_channels.items():
            if not isinstance(channel, str) or not isinstance(platforms, dict):
                continue
            normalized_channels[channel] = {
                str(platform_name): str(url)
                for platform_name, url in platforms.items()
                if str(url or "").strip()
            }

        return cls(
            default_output=str(merged.get("default_output", defaults["default_output"])),
            default_model=str(merged.get("default_model", defaults["default_model"])),
            default_baseline=int(merged.get("default_baseline", defaults["default_baseline"])),
            auto_check_enabled=bool(merged.get("auto_check_enabled", defaults["auto_check_enabled"])),
            release_channel=str(merged.get("release_channel", defaults["release_channel"])),
            last_update_check_at=(
                str(merged.get("last_update_check_at")).strip()
                if merged.get("last_update_check_at") not in (None, "")
                else None
            ),
            ignored_version=(
                str(merged.get("ignored_version")).strip()
                if merged.get("ignored_version") not in (None, "")
                else None
            ),
            update_channels=normalized_channels,
        )

    def save(self) -> Path:
        target_dir = _runtime_config_dir()
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / "config.json"
        target_path.write_text(json.dumps(self.to_payload(), indent=2, sort_keys=True), encoding="utf-8")
        return target_path

    def to_payload(self) -> dict[str, Any]:
        return {
            "default_output": self.default_output,
            "default_model": self.default_model,
            "default_baseline": int(self.default_baseline),
            "auto_check_enabled": bool(self.auto_check_enabled),
            "release_channel": str(self.release_channel or "stable"),
            "last_update_check_at": self.last_update_check_at,
            "ignored_version": self.ignored_version,
            "update_channels": {
                str(channel): {str(platform_name): str(url) for platform_name, url in platforms.items()}
                for channel, platforms in self.update_channels.items()
            },
        }

    def mark_update_check(self, when: datetime | None = None) -> None:
        timestamp = when or datetime.now(timezone.utc)
        self.last_update_check_at = timestamp.astimezone(timezone.utc).replace(microsecond=0).isoformat()

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

    def appcast_url_for_platform(self, platform_name: str) -> str | None:
        channel = self.update_channels.get(str(self.release_channel or "stable"), {})
        value = channel.get(platform_name)
        if not value:
            return None
        return str(value).strip() or None
