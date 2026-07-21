from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable
import gc
import shutil
import tempfile

import numpy as np
try:
    import torch
except Exception:
    torch = None


class ModelState(StrEnum):
    UNINITIALIZED = "UNINITIALIZED"
    READY = "READY"
    ERROR = "ERROR"
    DISABLED = "DISABLED"


@dataclass
class RuntimeStatus:
    state: ModelState
    message: str | None = None


class SAM2RuntimeService:
    """Hostable, idempotent SAM2 runtime wrapper."""

    def __init__(self) -> None:
        self.predictor: Any | None = None
        self.inference_state: Any | None = None
        self.model_path: str | None = None
        self.temp_dir: str | None = None
        self.status = RuntimeStatus(ModelState.UNINITIALIZED, None)

    def disable(self, message: str) -> RuntimeStatus:
        self.shutdown()
        self.status = RuntimeStatus(ModelState.DISABLED, str(message))
        return self.status

    def shutdown(self) -> None:
        self.predictor = None
        self.inference_state = None
        self.model_path = None
        if self.temp_dir:
            try:
                shutil.rmtree(self.temp_dir, ignore_errors=True)
            except Exception:
                pass
        self.temp_dir = None
        try:
            gc.collect()
            if torch is not None:
                if torch.backends.mps.is_available():
                    torch.mps.empty_cache()
                elif torch.cuda.is_available():
                    torch.cuda.empty_cache()
        except Exception:
            pass
        if self.status.state != ModelState.DISABLED:
            self.status = RuntimeStatus(ModelState.UNINITIALIZED, None)

    def ensure_initialized(
        self,
        *,
        model_path: str,
        frames_viz: np.ndarray,
        build_predictor: Callable[[str, str], tuple[Any, Any]],
    ) -> RuntimeStatus:
        """Initialize model once for the provided model path.

        `build_predictor(model_path, temp_dir)` must return `(predictor, inference_state)`.
        """
        if self.status.state == ModelState.DISABLED:
            return self.status

        requested_path = str(model_path or "").strip()
        if not requested_path:
            self.shutdown()
            self.status = RuntimeStatus(ModelState.ERROR, "Model file path is empty.")
            return self.status

        normalized_path = str(Path(requested_path).expanduser().resolve())
        if self.status.state == ModelState.READY and self.model_path == normalized_path:
            return self.status

        if not normalized_path or not Path(normalized_path).is_file():
            self.shutdown()
            self.status = RuntimeStatus(ModelState.ERROR, f"Model file not found: {normalized_path}")
            return self.status

        arr = np.asarray(frames_viz)
        if arr.ndim != 3 or arr.shape[0] <= 0:
            self.shutdown()
            self.status = RuntimeStatus(ModelState.ERROR, "No visualization frames are available for SAM2 initialization.")
            return self.status

        # Guard against ambiguous numpy truth evaluations by requiring explicit scalar checks.
        if int(arr.shape[1]) <= 0 or int(arr.shape[2]) <= 0:
            self.shutdown()
            self.status = RuntimeStatus(ModelState.ERROR, "Invalid frame shape for SAM2 initialization.")
            return self.status

        self.shutdown()
        temp_dir = tempfile.mkdtemp(prefix="swell_sam2_")
        self.temp_dir = temp_dir
        try:
            predictor, inference_state = build_predictor(normalized_path, temp_dir)
            self.predictor = predictor
            self.inference_state = inference_state
            self.model_path = normalized_path
            self.status = RuntimeStatus(ModelState.READY, "SAM2 model initialized.")
            return self.status
        except Exception as exc:  # noqa: BLE001
            self.predictor = None
            self.inference_state = None
            self.model_path = None
            if self.temp_dir:
                try:
                    shutil.rmtree(self.temp_dir, ignore_errors=True)
                except Exception:
                    pass
            self.temp_dir = None
            self.status = RuntimeStatus(ModelState.ERROR, str(exc))
            return self.status
