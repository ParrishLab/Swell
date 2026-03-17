from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

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
