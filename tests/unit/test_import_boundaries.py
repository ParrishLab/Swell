from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SDAPP = ROOT / "sdapp"


def _iter_python_files(base: Path):
    for path in base.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        yield path


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(str(alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.add(str(node.module))
    return modules


def test_shared_layer_does_not_import_host_or_analysis() -> None:
    bad: list[str] = []
    for path in _iter_python_files(SDAPP / "shared"):
        mods = _imported_modules(path)
        if any(m.startswith("sdapp.host") or m.startswith("sdapp.analysis") for m in mods):
            bad.append(str(path.relative_to(ROOT)))
    assert bad == []


def test_analysis_layer_does_not_import_host_layer() -> None:
    bad: list[str] = []
    for path in _iter_python_files(SDAPP / "analysis"):
        mods = _imported_modules(path)
        if any(m.startswith("sdapp.host") for m in mods):
            bad.append(str(path.relative_to(ROOT)))
    assert bad == []


def test_host_layer_has_no_local_import_fallback_shims() -> None:
    bad: list[str] = []
    for path in _iter_python_files(SDAPP / "host"):
        text = path.read_text(encoding="utf-8")
        if "except ImportError" in text and "from ." in text:
            bad.append(str(path.relative_to(ROOT)))
    assert bad == []


def test_analysis_layer_has_no_local_import_fallback_shims() -> None:
    bad: list[str] = []
    for path in _iter_python_files(SDAPP / "analysis"):
        text = path.read_text(encoding="utf-8")
        if "except ImportError" in text and "from ." in text:
            bad.append(str(path.relative_to(ROOT)))
    assert bad == []
