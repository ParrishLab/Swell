from __future__ import annotations

import tempfile
from unittest.mock import patch
from pathlib import Path

import numpy as np

from swell.analysis.app import SwellAnalysisApp
from swell.analysis.core.segmentation import (
    CheckpointOnboardingResult,
    SegmentationActions,
    _candidate_model_config_names,
    _disable_sam2_hole_filling_without_extension,
)


class _RuntimeStub:
    def __init__(self) -> None:
        self.predictor = None
        self.inference_state = None
        self.temp_dir = None
        self.status = type("Status", (), {"message": None})()

    def ensure_initialized(self, *, model_path, frames_viz, build_predictor):
        self.predictor = object()
        self.inference_state = {"model_path": model_path, "frames": int(frames_viz.shape[0])}
        self.temp_dir = "/tmp/swell_test_model"
        return type("S", (), {"state": "READY", "message": "ok"})()


def test_init_runtime_background_uses_preflight_without_dialog_prompts() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        model_path = Path(tmp) / "sam2.1_hiera_base_plus.pt"
        model_path.write_bytes(b"model")

        app = SwellAnalysisApp.__new__(SwellAnalysisApp)
        app.frames_sub_viz = np.zeros((2, 4, 4), dtype=np.uint8)
        app._get_frame_count = lambda: 2
        app._get_visual_frame = lambda idx: app.frames_sub_viz[int(idx)]
        app.resource_root = "/tmp"
        app.app_root = "/tmp"
        app.sam2_runtime = _RuntimeStub()
        app.inference_manager = type(
            "IM",
            (),
            {"on_model_ready": staticmethod(lambda *_args, **_kwargs: None), "on_model_unloaded": staticmethod(lambda: None)},
        )()
        app.checkpoint_runtime = type("CR", (), {"build_checkpoint_metadata": staticmethod(lambda **kwargs: dict(kwargs))})()
        app._set_active_checkpoint_metadata = lambda *_args, **_kwargs: None
        model_state = {"token": "managed://sam2.1_hiera_base_plus"}
        app.get_model_token = lambda: model_state["token"]
        app.set_model_token = lambda value: model_state.__setitem__("token", str(value))
        app._ui_alive = lambda: False
        app._apply_mps_sam2_dtype_guard = lambda: None
        app._process_pending_points = lambda: None
        app.log_info = lambda *_args, **_kwargs: None
        app.log_warn = lambda *_args, **_kwargs: None
        app.log_error = lambda *_args, **_kwargs: None
        app.log_success = lambda *_args, **_kwargs: None
        app.log_debug = lambda *_args, **_kwargs: None

        with patch.object(app, "_prompt_checkpoint_onboarding", side_effect=AssertionError("prompt should not run")), patch.object(
            app,
            "_resolve_mismatch_choice",
            side_effect=AssertionError("mismatch prompt should not run"),
        ):
            app.init_runtime_background(
                CheckpointOnboardingResult(
                    ok=True,
                    mode="sam2",
                    model_path=str(model_path),
                    checkpoint_id="sam2.1_hiera_base_plus",
                    source="configured_path",
                )
            )

    assert app.model_ready is True


def test_start_model_initialization_legacy_fallback_without_runtime_service() -> None:
    app = SwellAnalysisApp.__new__(SwellAnalysisApp)
    app.checkpoint_runtime = None
    called = {"count": 0}

    app._init_sam2_background = lambda: None
    app._run_thread = lambda _target, **_kwargs: called.__setitem__("count", called["count"] + 1)

    result = app.start_model_initialization(reason="test")

    assert result.ok is True
    assert result.mode == "legacy"
    assert called["count"] == 1


def test_trigger_background_propagation_blocks_when_model_not_ready() -> None:
    app = SwellAnalysisApp.__new__(SwellAnalysisApp)
    app.model_ready = False
    app.predictor = None
    app.inference_state = None
    app.root = type("Root", (), {"after": staticmethod(lambda _ms, fn: fn())})()
    app._ui_alive = lambda: True
    app._set_activity_message = lambda _msg: None
    app.log_warn = lambda *_args, **_kwargs: None
    opened = {"count": 0}
    app.open_checkpoint_manager = lambda: opened.__setitem__("count", opened["count"] + 1)

    with patch("swell.analysis.core.segmentation.messagebox.askyesno", return_value=True):
        app._trigger_background_propagation()

    assert opened["count"] == 1


def test_resolve_checkpoint_preflight_runtime_missing_disables_model() -> None:
    app = SwellAnalysisApp.__new__(SwellAnalysisApp)
    app.checkpoint_runtime = object()
    disabled: list[dict] = []
    app._disable_model_with_status = lambda **kwargs: disabled.append(dict(kwargs))

    with patch("swell.analysis.core.segmentation.importlib.util.find_spec", return_value=None):
        result = app.resolve_checkpoint_preflight()

    assert result.ok is False
    assert result.mode == "disabled"
    assert result.source == "runtime_unavailable"
    assert disabled


def test_resolve_checkpoint_preflight_host_mode_does_not_prompt_on_missing_model() -> None:
    app = SwellAnalysisApp.__new__(SwellAnalysisApp)
    app._host_mode = True
    app.checkpoint_runtime = object()
    app._resolve_sam2_checkpoint = lambda: type("R", (), {"ok": False})()
    disabled: list[dict] = []
    app._disable_model_with_status = lambda **kwargs: disabled.append(dict(kwargs))
    app.log_error = lambda *_args, **_kwargs: None
    app._ui_alive = lambda: False
    app.root = type("Root", (), {"after": staticmethod(lambda _ms, fn: fn())})()
    app._set_activity_message = lambda _msg: None

    with patch("swell.analysis.core.segmentation.importlib.util.find_spec", return_value=object()), patch(
        "swell.analysis.core.segmentation.torch",
        object(),
    ), patch.object(
        app, "_prompt_checkpoint_onboarding", side_effect=AssertionError("onboarding should not run in host mode")
    ):
        result = app.resolve_checkpoint_preflight()

    assert result.ok is False
    assert result.source == "host_missing_model"
    assert disabled


def test_candidate_model_configs_include_cross_family_fallbacks_for_local_models() -> None:
    candidates = _candidate_model_config_names(
        model_path="C:/models/custom_local_model.pt",
        checkpoint_id=None,
    )
    assert candidates
    assert any(name.startswith("sam2.1_") for name in candidates)
    assert any(name.startswith("sam2_") for name in candidates)


def test_candidate_model_configs_respect_model_size_hints() -> None:
    candidates = _candidate_model_config_names(
        model_path="/tmp/my_hiera_l_weights.pt",
        checkpoint_id="sam2.1_hiera_large",
    )
    assert candidates[0] in {"sam2.1_hiera_l.yaml", "sam2_hiera_l.yaml"}


def test_sam2_hole_filling_disabled_when_native_extension_missing(monkeypatch) -> None:
    predictor = type("Predictor", (), {"fill_hole_area": 8})()
    warnings: list[tuple[str, str]] = []

    monkeypatch.setattr("swell.analysis.core.segmentation.importlib.util.find_spec", lambda name: None)

    changed = _disable_sam2_hole_filling_without_extension(
        predictor,
        lambda context, message: warnings.append((context, message)),
    )

    assert changed is True
    assert predictor.fill_hole_area == 0
    assert warnings == [
        ("Model", "SAM2 native extension is unavailable; disabled mask hole-filling post-processing.")
    ]


def test_sam2_hole_filling_kept_when_native_extension_available(monkeypatch) -> None:
    predictor = type("Predictor", (), {"fill_hole_area": 8})()

    monkeypatch.setattr("swell.analysis.core.segmentation.importlib.util.find_spec", lambda name: object())

    changed = _disable_sam2_hole_filling_without_extension(predictor)

    assert changed is False
    assert predictor.fill_hole_area == 8


def test_ram_recovery_target_is_reachable_after_high_available_shutdown() -> None:
    gib = 1024**3
    target = SegmentationActions._ram_recovery_target_bytes(available_bytes=4 * gib, total_bytes=8 * gib)

    assert target == 4 * gib
    assert target != 8 * gib


def test_ram_recovery_target_has_floor_but_stays_below_physical_total() -> None:
    gib = 1024**3
    target = SegmentationActions._ram_recovery_target_bytes(available_bytes=100 * 1024**2, total_bytes=8 * gib)

    assert target == 2 * gib
    assert target < 8 * gib


def test_ram_recovery_target_zero_when_memory_probe_unavailable() -> None:
    assert SegmentationActions._ram_recovery_target_bytes(available_bytes=0, total_bytes=0) == 0
