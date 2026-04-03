from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET

import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_generate_compatibility_manifest_script_outputs_expected_fields(tmp_path: Path) -> None:
    script = ROOT / "scripts" / "release" / "generate_compatibility_manifest.py"
    output_path = tmp_path / "compatibility.json"

    subprocess.run(
        [sys.executable, str(script), "--repo-root", str(ROOT), "--output", str(output_path)],
        check=True,
        cwd=str(ROOT),
    )

    data = json.loads(output_path.read_text(encoding="utf-8"))
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert data["app_version"] == pyproject["project"]["version"]
    assert data["python_requires"] == pyproject["project"]["requires-python"]
    assert data["runtime_policy"]["cpu_guaranteed"] is True
    assert data["runtime_policy"]["mps_best_effort"] is True
    assert data["runtime_policy"]["cuda_packaged"] is False
    assert data["supported_checkpoints"] == [
        {"id": "sam2.1_hiera_base_plus", "filename": "sam2.1_hiera_base_plus.pt"}
    ]
    assert data["supported_platforms"] == [
        {"arch": "arm64", "os": "macos"},
        {"arch": "x86_64", "os": "macos"},
        {"arch": "x86_64", "os": "windows"},
    ]


def test_generate_compatibility_manifest_is_deterministic(tmp_path: Path) -> None:
    script = ROOT / "scripts" / "release" / "generate_compatibility_manifest.py"
    out1 = tmp_path / "compatibility_a.json"
    out2 = tmp_path / "compatibility_b.json"

    subprocess.run([sys.executable, str(script), "--repo-root", str(ROOT), "--output", str(out1)], check=True, cwd=str(ROOT))
    subprocess.run([sys.executable, str(script), "--repo-root", str(ROOT), "--output", str(out2)], check=True, cwd=str(ROOT))

    assert out1.read_text(encoding="utf-8") == out2.read_text(encoding="utf-8")


def test_generate_checksums_script_writes_sha256sums(tmp_path: Path) -> None:
    if sys.platform.startswith("win"):
        pytest.skip("Bash checksum script is not a required path on Windows CI.")

    shasum_available = bool(shutil.which("shasum") or shutil.which("sha256sum"))
    if not shasum_available:
        pytest.skip("No checksum tool available in environment.")
    bash_bin = shutil.which("bash")
    if not bash_bin:
        pytest.skip("bash is not available in environment.")
    # On GitHub Windows runners, `bash` may point to WSL and still fail when no distro is installed.
    try:
        probe = subprocess.run(
            [bash_bin, "-lc", "echo ok"],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        pytest.skip("bash is not runnable in environment.")
    if probe.returncode != 0:
        pytest.skip("bash is present but not runnable in environment.")

    script = ROOT / "scripts" / "release" / "generate_checksums.sh"
    artifact_dir = tmp_path / "dist"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "a.txt").write_text("alpha", encoding="utf-8")
    (artifact_dir / "b.bin").write_bytes(b"\x00\x01\x02\x03")

    output_path = artifact_dir / "SHA256SUMS.txt"
    subprocess.run(["bash", str(script), str(artifact_dir), str(output_path)], check=True, cwd=str(ROOT))

    lines = [line.strip() for line in output_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 2
    assert any("a.txt" in line for line in lines)
    assert any("b.bin" in line for line in lines)


def test_generate_appcasts_script_writes_platform_feeds(tmp_path: Path) -> None:
    script = ROOT / "scripts" / "release" / "generate_appcasts.py"
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = str(pyproject["project"]["version"])
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    (dist_dir / "sdapp-macos-arm64.zip").write_bytes(b"mac")
    (dist_dir / "sdapp-macos-arm64-signature.json").write_text(
        json.dumps({"archive": "sdapp-macos-arm64.zip", "ed_signature": "abc123=", "length": 3}),
        encoding="utf-8",
    )
    (dist_dir / f"SDApp-Setup-{version}.exe").write_bytes(b"win")

    subprocess.run(
        [
            sys.executable,
            str(script),
            "--repo-root",
            str(ROOT),
            "--dist-dir",
            str(dist_dir),
            "--output-dir",
            str(dist_dir),
            "--release-tag",
            f"v{version}",
            "--github-repo",
            "ClayDunford/Combined-tool-test",
            "--published-at",
            "Mon, 23 Mar 2026 12:00:00 +0000",
        ],
        check=True,
        cwd=str(ROOT),
    )

    windows_feed = ET.parse(dist_dir / "appcast-windows.xml").getroot()
    mac_feed = ET.parse(dist_dir / "appcast-macos.xml").getroot()
    windows_url = windows_feed.find("./channel/item/enclosure").attrib["url"]
    mac_url = mac_feed.find("./channel/item/enclosure").attrib["url"]
    mac_sig = mac_feed.find("./channel/item/enclosure").attrib[
        "{http://www.andymatuschak.org/xml-namespaces/sparkle}edSignature"
    ]

    assert windows_url.endswith(f"/SDApp-Setup-{version}.exe")
    assert mac_url.endswith("/sdapp-macos-arm64.zip")
    assert mac_sig == "abc123="


def test_sign_macos_update_script_parses_sign_update_output(tmp_path: Path) -> None:
    script = ROOT / "scripts" / "release" / "sign_macos_update.py"
    archive = tmp_path / "sdapp-macos-arm64.zip"
    archive.write_bytes(b"payload")
    if os.name == "nt":
        sign_update = tmp_path / "sign_update.cmd"
        sign_update.write_text(
            "@echo off\n"
            "echo sparkle:edSignature=\"signed123=\" length=\"7\"\n",
            encoding="utf-8",
        )
    else:
        sign_update = tmp_path / "sign_update"
        sign_update.write_text(
            "#!/bin/bash\n"
            "echo 'sparkle:edSignature=\"signed123=\" length=\"7\"'\n",
            encoding="utf-8",
        )
        sign_update.chmod(0o755)
    output = tmp_path / "signature.json"

    subprocess.run(
        [
            sys.executable,
            str(script),
            "--repo-root",
            str(ROOT),
            "--archive",
            str(archive),
            "--output",
            str(output),
            "--sign-update",
            str(sign_update),
        ],
        check=True,
        cwd=str(ROOT),
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["archive"] == "sdapp-macos-arm64.zip"
    assert payload["ed_signature"] == "signed123="
    assert payload["length"] == 7


def test_model_smoke_script_passes() -> None:
    script = ROOT / "scripts" / "release" / "run_model_smoke.py"
    proc = subprocess.run([sys.executable, str(script)], cwd=str(ROOT), capture_output=True, text=True, check=True)
    assert "MODEL_SMOKE:PASS" in proc.stdout


def test_segmentation_workflow_smoke_script_passes() -> None:
    script = ROOT / "scripts" / "release" / "run_segmentation_workflow_smoke.py"
    proc = subprocess.run([sys.executable, str(script)], cwd=str(ROOT), capture_output=True, text=True, check=True)
    assert "SEGMENTATION_WORKFLOW_SMOKE:PASS" in proc.stdout


def test_validate_model_runtime_script_accepts_specified_modules() -> None:
    script = ROOT / "scripts" / "release" / "validate_model_runtime.py"
    proc = subprocess.run(
        [sys.executable, str(script), "--modules", "json,sys"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    assert "MODEL_RUNTIME_VALIDATION:PASS" in proc.stdout


def test_validate_model_runtime_script_fails_for_missing_module() -> None:
    script = ROOT / "scripts" / "release" / "validate_model_runtime.py"
    proc = subprocess.run(
        [sys.executable, str(script), "--modules", "this_module_should_not_exist_12345"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "MODEL_RUNTIME_VALIDATION:FAIL" in proc.stdout


def test_validate_windows_installer_metadata_script_passes() -> None:
    script = ROOT / "scripts" / "release" / "validate_windows_installer_metadata.py"
    proc = subprocess.run(
        [sys.executable, str(script), "--repo-root", str(ROOT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    assert "WINDOWS_INSTALLER_VALIDATION:PASS" in proc.stdout


def test_open_request_smoke_script_passes_for_python_entrypoint() -> None:
    try:
        import tkinter  # noqa: F401
    except Exception:
        pytest.skip("tkinter is unavailable in environment.")
    script = ROOT / "scripts" / "release" / "run_open_request_smoke.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--app-cmd",
            sys.executable,
            "-m",
            "sdapp.main",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if "OPEN_REQUEST_SMOKE:FAIL:bind_unavailable" in proc.stdout:
        pytest.skip("localhost bind is unavailable in environment.")
    assert proc.returncode == 0
    assert "OPEN_REQUEST_SMOKE:PASS" in proc.stdout


def test_launch_probe_script_passes_for_short_lived_gui_like_process(tmp_path: Path) -> None:
    sleeper = tmp_path / "sleep_app.py"
    sleeper.write_text(
        "import time\n"
        "time.sleep(10)\n",
        encoding="utf-8",
    )
    script = ROOT / "scripts" / "release" / "run_launch_probe.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--probe-seconds",
            "0.5",
            "--app-cmd",
            sys.executable,
            str(sleeper),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "LAUNCH_PROBE:PASS" in proc.stdout


def test_launch_probe_bundle_mode_uses_open_semantics(monkeypatch, tmp_path: Path) -> None:
    import importlib.util
    import plistlib

    bundle = tmp_path / "SDApp.app"
    info = bundle / "Contents" / "Info.plist"
    info.parent.mkdir(parents=True)
    info.write_bytes(plistlib.dumps({"CFBundleExecutable": "SDApp"}))

    run_calls = []
    pgrep_calls = iter(
        [
            subprocess.CompletedProcess(args=["pgrep"], returncode=1, stdout="", stderr=""),
            subprocess.CompletedProcess(args=["pgrep"], returncode=0, stdout="123\n", stderr=""),
            subprocess.CompletedProcess(args=["pgrep"], returncode=0, stdout="123\n", stderr=""),
            subprocess.CompletedProcess(args=["pgrep"], returncode=1, stdout="", stderr=""),
        ]
    )
    kill_calls = []
    monotonic_values = iter([0.0, 0.1, 0.2, 1.2, 1.3, 1.4, 1.5, 1.6, 6.3])

    def _fake_run(args, **kwargs):
        run_calls.append(list(args))
        if list(args[:2]) == ["open", "-n"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        if list(args[:2]) == ["pgrep", "-x"]:
            return next(pgrep_calls)
        raise AssertionError(f"unexpected run args: {args}")

    script = ROOT / "scripts" / "release" / "run_launch_probe.py"
    spec = importlib.util.spec_from_file_location("test_run_launch_probe", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    monkeypatch.setattr(subprocess, "run", _fake_run)
    monkeypatch.setattr(module.time, "sleep", lambda _secs: None)
    monkeypatch.setattr(module.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(module.os, "kill", lambda pid, sig: kill_calls.append((pid, sig)))

    rc = module.main(["--bundle-path", str(bundle), "--probe-seconds", "1"])

    assert rc == 0
    assert ["open", "-n", str(bundle.resolve())] in run_calls
    assert any(pid == 123 for pid, _sig in kill_calls)
