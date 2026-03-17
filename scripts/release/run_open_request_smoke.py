#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sdapp.shared.services import SingleInstanceBridge


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smoke test that a launch command forwards a .sdproj open request to a running instance bridge."
    )
    parser.add_argument(
        "--app-cmd",
        nargs=argparse.REMAINDER,
        required=True,
        help="Application command used to launch SDApp (for example: path/to/SDApp.exe or python -m sdapp.main).",
    )
    parser.add_argument("--timeout-sec", type=float, default=8.0, help="Timeout for process execution and bridge receive.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    app_cmd = [str(part) for part in list(args.app_cmd or []) if str(part).strip()]
    if not app_cmd:
        print("OPEN_REQUEST_SMOKE:FAIL:missing_app_cmd")
        return 1

    timeout = max(2.0, float(args.timeout_sec))
    received: list[str] = []
    received_event = threading.Event()

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            open_port = int(probe.getsockname()[1])
    except OSError:
        print("OPEN_REQUEST_SMOKE:FAIL:bind_unavailable")
        return 1

    old_port_env = os.environ.get("SDAPP_INSTANCE_BRIDGE_PORT")
    os.environ["SDAPP_INSTANCE_BRIDGE_PORT"] = str(open_port)
    bridge = SingleInstanceBridge()

    def _on_open(path: str) -> None:
        received.append(str(path))
        received_event.set()

    try:
        if not bridge.start_listener(_on_open):
            print("OPEN_REQUEST_SMOKE:FAIL:listener_unavailable")
            return 1
        with tempfile.TemporaryDirectory(prefix="sdapp_open_request_smoke_") as tmp:
            project_path = (Path(tmp) / "open_request_smoke.sdproj").resolve()
            project_path.write_text("{}", encoding="utf-8")
            cmd = list(app_cmd) + [str(project_path)]

            try:
                child_env = dict(os.environ)
                proc = subprocess.run(
                    cmd,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    env=child_env,
                )
            except subprocess.TimeoutExpired:
                print("OPEN_REQUEST_SMOKE:FAIL:launch_timeout")
                return 1

            if int(proc.returncode) != 0:
                detail = (proc.stderr or proc.stdout or "").strip().replace("\n", " ")
                print(f"OPEN_REQUEST_SMOKE:FAIL:launch_returncode_{proc.returncode}:{detail}")
                return 1

            if not received_event.wait(timeout):
                print("OPEN_REQUEST_SMOKE:FAIL:no_open_request_received")
                return 1

            received_path = Path(str(received[0])).expanduser().resolve()
            if received_path != project_path:
                print(
                    "OPEN_REQUEST_SMOKE:FAIL:path_mismatch:"
                    f"expected={project_path};received={received_path}"
                )
                return 1
    finally:
        bridge.stop()
        if old_port_env is None:
            os.environ.pop("SDAPP_INSTANCE_BRIDGE_PORT", None)
        else:
            os.environ["SDAPP_INSTANCE_BRIDGE_PORT"] = old_port_env

    print("OPEN_REQUEST_SMOKE:PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
