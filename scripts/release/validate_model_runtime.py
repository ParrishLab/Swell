#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
import sys


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate required model runtime dependencies are installed.")
    parser.add_argument(
        "--modules",
        default="torch,sam2,hydra,omegaconf",
        help="Comma-separated module names to validate.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    modules = [part.strip() for part in str(args.modules).split(",") if part.strip()]
    missing: list[str] = []
    for module_name in modules:
        try:
            importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001
            missing.append(f"{module_name}:{exc.__class__.__name__}:{exc}")

    if missing:
        print("MODEL_RUNTIME_VALIDATION:FAIL")
        for detail in missing:
            print(f" - {detail}")
        print('Install model extras before packaging: python -m pip install -e ".[model]"')
        return 1
    print("MODEL_RUNTIME_VALIDATION:PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
