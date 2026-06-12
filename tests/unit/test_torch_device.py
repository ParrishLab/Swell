from __future__ import annotations

import sys
import types

import pytest

from sdapp.shared.torch_device import (
    DEVICE_ENV_VAR,
    device_env_override,
    resolve_torch_device,
)


def _fake_torch(*, mps: bool, cuda: bool) -> types.ModuleType:
    module = types.ModuleType("torch")
    backends = types.SimpleNamespace(
        mps=types.SimpleNamespace(is_available=lambda: mps)
    )
    module.backends = backends  # type: ignore[attr-defined]
    module.cuda = types.SimpleNamespace(is_available=lambda: cuda)  # type: ignore[attr-defined]
    return module


@pytest.fixture
def fake_torch(monkeypatch):
    def _install(*, mps: bool, cuda: bool):
        monkeypatch.setitem(sys.modules, "torch", _fake_torch(mps=mps, cuda=cuda))

    return _install


# --- SDAPP_DEVICE override -------------------------------------------------

@pytest.mark.parametrize("value,expected", [("cpu", "cpu"), ("mps", "mps"), ("cuda", "cuda")])
def test_env_override_valid(monkeypatch, value, expected):
    monkeypatch.setenv(DEVICE_ENV_VAR, value)
    assert device_env_override() == expected


def test_env_override_is_case_insensitive_and_trimmed(monkeypatch):
    monkeypatch.setenv(DEVICE_ENV_VAR, "  CUDA  ")
    assert device_env_override() == "cuda"


@pytest.mark.parametrize("value", ["", "gpu", "metal", "xpu"])
def test_env_override_invalid_returns_none(monkeypatch, value):
    monkeypatch.setenv(DEVICE_ENV_VAR, value)
    assert device_env_override() is None


def test_override_forces_cpu_without_touching_torch(monkeypatch):
    # Force CPU even when an accelerator would otherwise be picked, and prove no
    # torch import is required for the override path (escape-hatch guarantee).
    monkeypatch.setitem(sys.modules, "torch", None)
    monkeypatch.setenv(DEVICE_ENV_VAR, "cpu")
    assert resolve_torch_device() == "cpu"


def test_override_forces_accelerator_regardless_of_availability(monkeypatch, fake_torch):
    fake_torch(mps=False, cuda=False)
    monkeypatch.setenv(DEVICE_ENV_VAR, "cuda")
    assert resolve_torch_device() == "cuda"


# --- auto-detection order: mps -> cuda -> cpu ------------------------------

def test_auto_prefers_mps(monkeypatch, fake_torch):
    monkeypatch.delenv(DEVICE_ENV_VAR, raising=False)
    fake_torch(mps=True, cuda=True)
    assert resolve_torch_device() == "mps"


def test_auto_uses_cuda_when_no_mps(monkeypatch, fake_torch):
    monkeypatch.delenv(DEVICE_ENV_VAR, raising=False)
    fake_torch(mps=False, cuda=True)
    assert resolve_torch_device() == "cuda"


def test_auto_falls_back_to_cpu(monkeypatch, fake_torch):
    monkeypatch.delenv(DEVICE_ENV_VAR, raising=False)
    fake_torch(mps=False, cuda=False)
    assert resolve_torch_device() == "cpu"
