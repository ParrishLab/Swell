from __future__ import annotations

import importlib
import multiprocessing
import sys
from typing import Sequence

from sdapp.host.ui.root_window import run_host_app
from sdapp.shared.services import SingleInstanceBridge


def _parse_launch_project_path(argv: Sequence[str]) -> str | None:
    for token in list(argv)[1:]:
        candidate = str(token or "").strip()
        if not candidate:
            continue
        if candidate.startswith("-"):
            continue
        return candidate
    return None


def _parse_main_args(argv: Sequence[str]) -> tuple[bool, bool, str | None]:
    args = list(argv)
    smoke_test = any(str(token) == "--smoke-test" for token in args[1:])
    smoke_model_runtime = any(str(token) == "--smoke-model-runtime" for token in args[1:])
    filtered = [
        args[0]
    ] + [
        token
        for token in args[1:]
        if str(token) not in {"--smoke-test", "--smoke-model-runtime"}
    ]
    return smoke_test, smoke_model_runtime, _parse_launch_project_path(filtered)


def _run_smoke_test(importer=importlib.import_module, *, include_model_runtime: bool = False) -> tuple[bool, str]:
    modules = [
        "sdapp.host.ui.root_window",
        "sdapp.shared.persistence.unified_project_store",
        "sdapp.shared.services.unified_project_service",
        "sdapp.shared.menu.factory",
    ]
    if not bool(getattr(sys, "frozen", False)):
        modules.insert(0, "sdapp.main")
    if include_model_runtime:
        modules.extend(
            [
                "torch",
                "sam2",
            ]
        )
    for module_name in modules:
        try:
            importer(module_name)
        except Exception as exc:
            return False, f"{module_name}:{exc.__class__.__name__}:{exc}"
    return True, "ok"


def main(argv: Sequence[str] | None = None) -> int:
    multiprocessing.freeze_support()
    args = list(argv) if argv is not None else list(sys.argv)
    smoke_test, smoke_model_runtime, launch_project_path = _parse_main_args(args)

    if smoke_test:
        ok, detail = _run_smoke_test(include_model_runtime=smoke_model_runtime)
        if ok:
            print("SMOKE_TEST:PASS")
            return 0
        print(f"SMOKE_TEST:FAIL:{detail}")
        return 1

    bridge = SingleInstanceBridge()
    if launch_project_path and bridge.send_open_request(launch_project_path):
        return 0
    run_host_app(initial_project_path=launch_project_path, instance_bridge=bridge)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
