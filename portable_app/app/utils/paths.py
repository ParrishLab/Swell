from pathlib import Path
import sys


def get_bundle_root() -> Path:
    # When frozen (PyInstaller), resources are extracted to _MEIPASS
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS).resolve()
    return Path(__file__).resolve().parents[2]


def get_runtime_root() -> Path:
    # When frozen, this is the directory containing the executable
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def get_app_root() -> Path:
    # Prefer runtime root to allow external models/configs next to the app
    return get_runtime_root()


def resolve_path(path_str: str) -> Path:
    path = Path(path_str)
    if path.is_absolute():
        return path
    # Prefer runtime root; fall back to bundle root for packaged assets
    runtime_candidate = get_runtime_root() / path
    if runtime_candidate.exists():
        return runtime_candidate
    return get_bundle_root() / path


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def resolve_existing_directory(
    path_str: str,
    app_root: Path | str,
    fallback_dir: Path | str | None = None,
    prefer_parent_for_existing_dir: bool = False,
) -> str:
    app_root_path = Path(app_root).resolve()
    fallback_path = Path(fallback_dir).resolve() if fallback_dir is not None else app_root_path

    candidate_raw = (path_str or "").strip()
    if not candidate_raw:
        return str(fallback_path)

    candidate = Path(candidate_raw)
    if not candidate.is_absolute():
        candidate = (app_root_path / candidate).resolve()
    else:
        candidate = candidate.resolve()

    if candidate.is_dir():
        if prefer_parent_for_existing_dir:
            parent = candidate.parent
            return str(parent if parent.exists() else fallback_path)
        return str(candidate)

    if candidate.is_file():
        parent = candidate.parent
        return str(parent if parent.exists() else fallback_path)

    parent = candidate
    while True:
        next_parent = parent.parent
        if next_parent == parent:
            break
        parent = next_parent
        if parent.exists() and parent.is_dir():
            return str(parent)
    return str(fallback_path)
