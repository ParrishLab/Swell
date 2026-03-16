from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tomllib

import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_generate_compatibility_manifest_script_outputs_expected_fields(tmp_path: Path) -> None:
    script = ROOT / "scripts" / "release" / "generate_compatibility_manifest.py"
    output_path = tmp_path / "compatibility.json"

    subprocess.run(
        ["python3", str(script), "--repo-root", str(ROOT), "--output", str(output_path)],
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
    assert data["supported_platforms"] == [
        {"arch": "arm64", "os": "macos"},
        {"arch": "x86_64", "os": "macos"},
    ]


def test_generate_compatibility_manifest_is_deterministic(tmp_path: Path) -> None:
    script = ROOT / "scripts" / "release" / "generate_compatibility_manifest.py"
    out1 = tmp_path / "compatibility_a.json"
    out2 = tmp_path / "compatibility_b.json"

    subprocess.run(["python3", str(script), "--repo-root", str(ROOT), "--output", str(out1)], check=True, cwd=str(ROOT))
    subprocess.run(["python3", str(script), "--repo-root", str(ROOT), "--output", str(out2)], check=True, cwd=str(ROOT))

    assert out1.read_text(encoding="utf-8") == out2.read_text(encoding="utf-8")


def test_generate_checksums_script_writes_sha256sums(tmp_path: Path) -> None:
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
