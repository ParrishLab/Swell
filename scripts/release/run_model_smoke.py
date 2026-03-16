#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sdapp.analysis.model import DeterministicCpuFallbackPredictor, SAM2RuntimeService


def main() -> int:
    runtime = SAM2RuntimeService()
    with tempfile.TemporaryDirectory(prefix="sdapp_model_smoke_") as tmp:
        tmp_dir = Path(tmp)
        model_path = tmp_dir / "model_smoke.pt"
        model_path.write_bytes(b"sdapp-model-smoke")
        frames_viz = np.random.default_rng(42).integers(0, 255, size=(8, 48, 48), dtype=np.uint8)

        def _build_predictor(_model_path: str, _temp_dir: str):
            predictor = DeterministicCpuFallbackPredictor(
                frame_count=int(frames_viz.shape[0]),
                frame_shape=(int(frames_viz.shape[1]), int(frames_viz.shape[2])),
            )
            state = predictor.init_state(video_path=None)
            return predictor, state

        status = runtime.ensure_initialized(
            model_path=str(model_path),
            frames_viz=frames_viz,
            build_predictor=_build_predictor,
        )
        if status.state != "READY":
            print(f"MODEL_SMOKE:FAIL:{status.message or 'not_ready'}")
            return 1
        if runtime.predictor is None or runtime.inference_state is None:
            print("MODEL_SMOKE:FAIL:runtime_objects_missing")
            return 1
    print("MODEL_SMOKE:PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
