from __future__ import annotations

import importlib.metadata
from pathlib import Path


def detect_app_version() -> str:
    try:
        return importlib.metadata.version("sdapp")
    except Exception:
        pass

    pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
    if pyproject_path.exists():
        try:
            import tomllib

            with pyproject_path.open("rb") as handle:
                payload = tomllib.load(handle)
            return str(payload.get("project", {}).get("version", "0.0.0"))
        except Exception:
            pass

    return "0.0.0"


def format_window_title(base_title: str, version: str | None = None) -> str:
    resolved_version = str(version or detect_app_version()).strip() or "0.0.0"
    return f"{str(base_title).strip()} v{resolved_version}"
