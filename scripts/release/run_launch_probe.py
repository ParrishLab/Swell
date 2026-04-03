#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
import plistlib
import signal
import subprocess
import sys
import time


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify that an app launch path stays alive briefly without crashing."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--app-cmd",
        nargs=argparse.REMAINDER,
        help="Application command to launch directly.",
    )
    group.add_argument(
        "--bundle-path",
        help="Path to a macOS .app bundle to launch via LaunchServices semantics.",
    )
    parser.add_argument("--probe-seconds", type=float, default=5.0, help="How long the process must stay alive.")
    parser.add_argument("--shutdown-seconds", type=float, default=5.0, help="How long to wait for termination.")
    return parser.parse_args(argv)


def _pgrep_exact(name: str) -> set[int]:
    proc = subprocess.run(
        ["pgrep", "-x", str(name)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode not in (0, 1):
        detail = (proc.stderr or proc.stdout or "").strip().replace("\n", " ")
        raise RuntimeError(f"pgrep_failed:{detail}")
    return {int(line.strip()) for line in (proc.stdout or "").splitlines() if line.strip()}


def _terminate_pids(pids: set[int], shutdown_seconds: float) -> None:
    pending = {int(pid) for pid in pids if int(pid) > 0}
    for pid in list(pending):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pending.discard(pid)
    deadline = time.monotonic() + shutdown_seconds
    while pending and time.monotonic() < deadline:
        for pid in list(pending):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                pending.discard(pid)
        time.sleep(0.1)
    for pid in list(pending):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _probe_direct_command(app_cmd: list[str], probe_seconds: float, shutdown_seconds: float) -> tuple[bool, str]:
    proc = subprocess.Popen(
        app_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + probe_seconds
        while time.monotonic() < deadline:
            rc = proc.poll()
            if rc is not None:
                stdout, stderr = proc.communicate()
                detail = (stderr or stdout or "").strip().replace("\n", " ")
                return False, f"early_exit_{rc}:{detail}"
            time.sleep(0.1)
        return True, "ok"
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=shutdown_seconds)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=shutdown_seconds)


def _probe_macos_bundle(bundle_path: Path, probe_seconds: float, shutdown_seconds: float) -> tuple[bool, str]:
    if sys.platform != "darwin":
        return False, "unsupported_platform"
    info_path = bundle_path / "Contents" / "Info.plist"
    if not bundle_path.exists():
        return False, f"missing_bundle:{bundle_path}"
    if not info_path.exists():
        return False, f"missing_info_plist:{info_path}"
    try:
        payload = plistlib.loads(info_path.read_bytes())
    except Exception as exc:  # noqa: BLE001
        return False, f"invalid_info_plist:{exc.__class__.__name__}:{exc}"
    executable_name = str(payload.get("CFBundleExecutable", "")).strip()
    if not executable_name:
        return False, "missing_bundle_executable"

    try:
        baseline_pids = _pgrep_exact(executable_name)
    except RuntimeError as exc:
        return False, str(exc)

    opener = subprocess.run(
        ["open", "-n", str(bundle_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if opener.returncode != 0:
        detail = (opener.stderr or opener.stdout or "").strip().replace("\n", " ")
        return False, f"open_failed_{opener.returncode}:{detail}"

    launched_pids: set[int] = set()
    deadline = time.monotonic() + probe_seconds
    try:
        while time.monotonic() < deadline:
            current_pids = _pgrep_exact(executable_name)
            launched_pids = current_pids - baseline_pids
            if launched_pids:
                break
            time.sleep(0.1)
        if not launched_pids:
            return False, "no_launched_process"

        while time.monotonic() < deadline:
            current_pids = _pgrep_exact(executable_name)
            if not (current_pids & launched_pids):
                return False, "bundle_process_exited_early"
            time.sleep(0.1)
        return True, "ok"
    except RuntimeError as exc:
        return False, str(exc)
    finally:
        _terminate_pids(launched_pids, shutdown_seconds)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    probe_seconds = max(1.0, float(args.probe_seconds))
    shutdown_seconds = max(1.0, float(args.shutdown_seconds))

    if args.bundle_path:
        ok, detail = _probe_macos_bundle(Path(str(args.bundle_path)).expanduser().resolve(), probe_seconds, shutdown_seconds)
    else:
        app_cmd = [str(part) for part in list(args.app_cmd or []) if str(part).strip()]
        if not app_cmd:
            print("LAUNCH_PROBE:FAIL:missing_app_cmd")
            return 1
        ok, detail = _probe_direct_command(app_cmd, probe_seconds, shutdown_seconds)

    if not ok:
        print(f"LAUNCH_PROBE:FAIL:{detail}")
        return 1
    print("LAUNCH_PROBE:PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
