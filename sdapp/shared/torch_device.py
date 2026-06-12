from __future__ import annotations

import os

# Single source of truth for torch device selection across the app.
#
# Auto-detection order is Apple MPS, then NVIDIA CUDA, then CPU. The
# ``SDAPP_DEVICE`` environment variable forces a specific device and acts as an
# escape hatch when an accelerator misbehaves (e.g. ``SDAPP_DEVICE=cpu``). It
# follows the same convention as the other ``SDAPP_*`` overrides in the app
# (``SDAPP_MODELS_DIR``, ``SDAPP_INSTANCE_BRIDGE_PORT``).

DEVICE_ENV_VAR = "SDAPP_DEVICE"
VALID_DEVICES = ("cpu", "mps", "cuda")


def device_env_override() -> str | None:
    """Return the forced device from ``SDAPP_DEVICE`` if set to a valid value."""
    raw = str(os.environ.get(DEVICE_ENV_VAR, "")).strip().lower()
    if raw in VALID_DEVICES:
        return raw
    return None


def resolve_torch_device() -> str:
    """Resolve the torch device string for inference/segmentation work.

    Resolution order:
    1. ``SDAPP_DEVICE`` override (``cpu`` / ``mps`` / ``cuda``), forced as-is.
    2. Auto-detect: Apple MPS, then NVIDIA CUDA, then CPU.

    Returns a device *string* (not a ``torch.device``) so callers that compare
    against ``"mps"`` keep working; wrap in ``torch.device(...)`` where an
    object is required.
    """
    override = device_env_override()
    if override is not None:
        return override

    import torch

    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"
