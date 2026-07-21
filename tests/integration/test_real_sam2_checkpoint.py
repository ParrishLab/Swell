from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from swell.analysis.core.segmentation import _candidate_model_config_names
from swell.analysis.model.sam2_runtime import ModelState, SAM2RuntimeService


CHECKPOINT_ENV = "SWELL_TEST_SAM2_CHECKPOINT"


@pytest.mark.skipif(
    not str(os.environ.get(CHECKPOINT_ENV, "")).strip(),
    reason=f"set {CHECKPOINT_ENV} to run real SAM2 checkpoint integration",
)
def test_real_sam2_checkpoint_initializes_and_segments(tmp_path: Path) -> None:
    torch = pytest.importorskip("torch")
    pytest.importorskip("sam2")
    from hydra import initialize_config_dir
    from hydra.core.global_hydra import GlobalHydra
    from sam2.build_sam import build_sam2_video_predictor

    checkpoint = Path(os.environ[CHECKPOINT_ENV]).expanduser().resolve()
    assert checkpoint.is_file(), f"checkpoint does not exist: {checkpoint}"
    resource_root = Path(__file__).resolve().parents[2] / "swell" / "resources"
    config_override = str(os.environ.get("SWELL_TEST_SAM2_CONFIG", "")).strip()
    device = str(os.environ.get("SWELL_TEST_SAM2_DEVICE", "cpu")).strip() or "cpu"
    if device == "cuda" and not torch.cuda.is_available():
        pytest.skip("SWELL_TEST_SAM2_DEVICE=cuda but CUDA is unavailable")
    if device == "mps" and not torch.backends.mps.is_available():
        pytest.skip("SWELL_TEST_SAM2_DEVICE=mps but MPS is unavailable")

    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    frames = np.zeros((3, 64, 64), dtype=np.uint8)
    frames[:, 20:44, 20:44] = 180
    for idx, frame in enumerate(frames):
        Image.fromarray(frame).convert("RGB").save(frames_dir / f"{idx:05d}.jpg", quality=95)

    candidates = [config_override] if config_override else _candidate_model_config_names(str(checkpoint), None)
    config_names: list[str] = []
    for candidate in candidates:
        candidate_path = Path(candidate)
        if candidate_path.suffix != ".yaml":
            candidate_path = candidate_path.with_suffix(".yaml")
        if candidate_path.parent == Path("."):
            family = "sam2.1" if candidate_path.name.startswith("sam2.1_") else "sam2"
            candidate_path = Path(family) / candidate_path.name
        local_path = resource_root / "configs" / candidate_path
        if local_path.is_file():
            config_names.append(f"configs/{candidate_path.as_posix()}")
    assert config_names, "no compatible packaged SAM2 configs were found"

    GlobalHydra.instance().clear()
    initialize_config_dir(config_dir=str(resource_root), job_name="swell_real_sam2_test", version_base=None)

    def build_predictor(model_path: str, _temp_dir: str):
        errors: list[str] = []
        for config_name in config_names:
            try:
                predictor = build_sam2_video_predictor(config_name, model_path, device=device)
                return predictor, predictor.init_state(video_path=str(frames_dir))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{config_name}: {exc}")
        raise RuntimeError("; ".join(errors))

    runtime = SAM2RuntimeService()
    status = runtime.ensure_initialized(
        model_path=str(checkpoint),
        frames_viz=frames,
        build_predictor=build_predictor,
    )

    assert status.state is ModelState.READY, status.message
    predictor = runtime.predictor
    state = runtime.inference_state
    frame_idx, object_ids, logits = predictor.add_new_points_or_box(
        inference_state=state,
        frame_idx=0,
        obj_id=1,
        points=np.array([[32.0, 32.0]], dtype=np.float32),
        labels=np.array([1], dtype=np.int32),
    )
    assert int(frame_idx) == 0
    assert list(object_ids) == [1]
    assert np.asarray(logits[0].detach().cpu()).shape[-2:] == (64, 64)
    runtime.shutdown()
    GlobalHydra.instance().clear()
