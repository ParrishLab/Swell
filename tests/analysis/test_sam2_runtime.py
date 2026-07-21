from __future__ import annotations

from pathlib import Path

import numpy as np

from swell.analysis.model.sam2_runtime import ModelState, SAM2RuntimeService


def _frames() -> np.ndarray:
    return np.zeros((2, 8, 10), dtype=np.uint8)


def test_missing_and_empty_model_paths_fail_before_builder(tmp_path: Path) -> None:
    service = SAM2RuntimeService()
    calls: list[tuple[str, str]] = []

    def builder(model_path: str, temp_dir: str):
        calls.append((model_path, temp_dir))
        return object(), object()

    empty = service.ensure_initialized(model_path="", frames_viz=_frames(), build_predictor=builder)
    missing = service.ensure_initialized(
        model_path=str(tmp_path / "missing.pt"),
        frames_viz=_frames(),
        build_predictor=builder,
    )
    directory = service.ensure_initialized(
        model_path=str(tmp_path),
        frames_viz=_frames(),
        build_predictor=builder,
    )

    assert empty.state is ModelState.ERROR
    assert missing.state is ModelState.ERROR
    assert directory.state is ModelState.ERROR
    assert calls == []


def test_invalid_frame_shapes_fail_before_builder(tmp_path: Path) -> None:
    model = tmp_path / "model.pt"
    model.write_bytes(b"checkpoint")
    service = SAM2RuntimeService()

    for frames in (np.zeros((0, 8, 10)), np.zeros((2, 0, 10)), np.zeros((8, 10))):
        status = service.ensure_initialized(
            model_path=str(model),
            frames_viz=frames,
            build_predictor=lambda *_: (_ for _ in ()).throw(AssertionError("builder called")),
        )
        assert status.state is ModelState.ERROR


def test_success_is_idempotent_for_same_resolved_model(tmp_path: Path) -> None:
    model = tmp_path / "model.pt"
    model.write_bytes(b"checkpoint")
    calls: list[tuple[str, str]] = []
    service = SAM2RuntimeService()

    def builder(model_path: str, temp_dir: str):
        calls.append((model_path, temp_dir))
        return "predictor", "state"

    first = service.ensure_initialized(model_path=str(model), frames_viz=_frames(), build_predictor=builder)
    second = service.ensure_initialized(model_path=str(model), frames_viz=_frames(), build_predictor=builder)

    assert first.state is ModelState.READY
    assert second.state is ModelState.READY
    assert service.predictor == "predictor"
    assert service.inference_state == "state"
    assert calls == [(str(model.resolve()), service.temp_dir)]
    service.shutdown()


def test_switching_models_replaces_runtime_and_removes_old_temp_dir(tmp_path: Path) -> None:
    first_model = tmp_path / "first.pt"
    second_model = tmp_path / "second.pt"
    first_model.write_bytes(b"one")
    second_model.write_bytes(b"two")
    service = SAM2RuntimeService()
    built: list[str] = []

    def builder(model_path: str, temp_dir: str):
        built.append(model_path)
        Path(temp_dir, "sentinel").write_text("temporary", encoding="utf-8")
        return Path(model_path).name, object()

    service.ensure_initialized(model_path=str(first_model), frames_viz=_frames(), build_predictor=builder)
    old_temp = Path(service.temp_dir or "")
    service.ensure_initialized(model_path=str(second_model), frames_viz=_frames(), build_predictor=builder)

    assert not old_temp.exists()
    assert service.predictor == "second.pt"
    assert built == [str(first_model.resolve()), str(second_model.resolve())]
    service.shutdown()


def test_failed_build_cleans_partial_runtime_and_temp_dir(tmp_path: Path) -> None:
    model = tmp_path / "model.pt"
    model.write_bytes(b"checkpoint")
    service = SAM2RuntimeService()
    created: list[Path] = []

    def builder(_model_path: str, temp_dir: str):
        created.append(Path(temp_dir))
        Path(temp_dir, "partial.jpg").write_bytes(b"partial")
        raise RuntimeError("build failed")

    status = service.ensure_initialized(model_path=str(model), frames_viz=_frames(), build_predictor=builder)

    assert status.state is ModelState.ERROR
    assert status.message == "build failed"
    assert service.predictor is None
    assert service.inference_state is None
    assert service.model_path is None
    assert service.temp_dir is None
    assert created and not created[0].exists()


def test_disabled_runtime_is_sticky_until_reenabled_by_new_service(tmp_path: Path) -> None:
    model = tmp_path / "model.pt"
    model.write_bytes(b"checkpoint")
    service = SAM2RuntimeService()

    disabled = service.disable("CPU fallback selected")
    status = service.ensure_initialized(
        model_path=str(model),
        frames_viz=_frames(),
        build_predictor=lambda *_: (object(), object()),
    )

    assert disabled.state is ModelState.DISABLED
    assert status is disabled
    assert service.predictor is None
