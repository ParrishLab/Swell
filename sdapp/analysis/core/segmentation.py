import os
import importlib.util
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import MethodType

import numpy as np
from tkinter import filedialog, messagebox

from sdapp.analysis.model import DeterministicCpuFallbackPredictor, build_sam2_frame_cache_key
from sdapp.shared.model_copy import (
    STATUS_MODEL_DISABLED,
    STATUS_MODEL_ERROR,
    STATUS_MODEL_FILE_MISSING,
    STATUS_MODEL_READY,
    TITLE_MODEL_FILE_REQUIRED,
    TITLE_MODEL_METADATA_MISMATCH,
    mismatch_body,
    onboarding_body,
)

try:
    import torch
except Exception:
    torch = None


class _NullTextStream:
    def write(self, text):  # type: ignore[no-untyped-def]
        return len(str(text or ""))

    def flush(self):  # type: ignore[no-untyped-def]
        return None


def _ensure_runtime_stdio() -> None:
    # In frozen GUI builds (console=False), stdout/stderr can be None.
    # Hydra/SAM2 may write to them during config/model bootstrap.
    if getattr(sys, "stdout", None) is None:
        sys.stdout = _NullTextStream()
    if getattr(sys, "stderr", None) is None:
        sys.stderr = _NullTextStream()


@dataclass(frozen=True)
class CheckpointOnboardingResult:
    ok: bool
    mode: str
    model_path: str | None = None
    checkpoint_id: str | None = None
    source: str | None = None
    message: str | None = None


def _candidate_model_config_names(model_path: str, checkpoint_id: str | None) -> list[str]:
    text = f"{str(model_path or '')} {str(checkpoint_id or '')}".lower()
    families: list[str] = []
    if "2.1" in text or "sam2.1" in text:
        families.append("sam2.1")
    elif "sam2" in text and "2.1" not in text:
        families.append("sam2")
    if not families:
        families = ["sam2.1", "sam2"]

    explicit_variant: str | None = None
    if any(token in text for token in ("base_plus", "base-plus", "hiera_b+", "b+")):
        explicit_variant = "base_plus"
    elif "small" in text or "hiera_s" in text:
        explicit_variant = "s"
    elif "large" in text or "hiera_l" in text:
        explicit_variant = "l"
    elif "tiny" in text or "hiera_t" in text:
        explicit_variant = "t"

    out: list[str] = []
    seen: set[str] = set()
    for family in families:
        if explicit_variant == "base_plus":
            # Base-plus checkpoints should only bind to base-plus model configs.
            fallback_order = [
                f"{family}_hiera_base_plus.yaml",
                f"{family}_hiera_b+.yaml",
            ]
        elif explicit_variant in {"s", "t", "l"}:
            fallback_order = [f"{family}_hiera_{explicit_variant}.yaml"]
        else:
            # Unknown variant: probe a bounded ordered set.
            fallback_order = [
                f"{family}_hiera_base_plus.yaml",
                f"{family}_hiera_b+.yaml",
                f"{family}_hiera_s.yaml",
                f"{family}_hiera_t.yaml",
                f"{family}_hiera_l.yaml",
            ]
        for name in fallback_order:
            if name not in seen:
                out.append(name)
                seen.add(name)
    return out


class SegmentationActions:
    def _apply_mps_sam2_dtype_guard(self):
        if torch is None:
            return
        if not torch.backends.mps.is_available() or self.predictor is None:
            return
        if getattr(self.predictor, "_ios_mps_dtype_guard_applied", False):
            return

        orig_single = getattr(self.predictor, "_run_single_frame_inference", None)
        if callable(orig_single):
            def wrapped_single(predictor_self, *args, **kwargs):
                out = orig_single(*args, **kwargs)
                try:
                    compact_out, pred_masks = out
                    maskmem = compact_out.get("maskmem_features") if isinstance(compact_out, dict) else None
                    if maskmem is not None and getattr(maskmem, "dtype", None) == torch.bfloat16:
                        compact_out["maskmem_features"] = maskmem.to(torch.float32)
                    return compact_out, pred_masks
                except Exception:
                    return out

            self.predictor._run_single_frame_inference = MethodType(wrapped_single, self.predictor)

        orig_mem = getattr(self.predictor, "_run_memory_encoder", None)
        if callable(orig_mem):
            def wrapped_mem(predictor_self, *args, **kwargs):
                out = orig_mem(*args, **kwargs)
                try:
                    maskmem_features, maskmem_pos_enc = out
                    if maskmem_features is not None and getattr(maskmem_features, "dtype", None) == torch.bfloat16:
                        maskmem_features = maskmem_features.to(torch.float32)
                    return maskmem_features, maskmem_pos_enc
                except Exception:
                    return out

            self.predictor._run_memory_encoder = MethodType(wrapped_mem, self.predictor)

        self.predictor._ios_mps_dtype_guard_applied = True
        self.log_info("Model", "Applied MPS dtype guard for SAM2 memory features.")

    def _has_nonempty_paint(self, frame_idx):
        return self.seg_state.has_nonempty_paint(frame_idx)

    def _process_pending_points(self):
        if not self.model_ready:
            return
        self._prune_empty_point_frames()
        self.inference_manager.enqueue_pending_point_frames(self.seg_state.get_valid_point_frames())

    def _resolve_sam2_checkpoint(self):
        service = getattr(self, "checkpoint_runtime", None)
        if service is None:
            return None
        project_meta = self._project_recorded_checkpoint_metadata() if hasattr(self, "_project_recorded_checkpoint_metadata") else None
        configured_model = self.get_model_token() if hasattr(self, "get_model_token") else ""
        manual_override = str(getattr(self, "_manual_model_override", "") or "").strip()
        return service.resolve_checkpoint(
            project_checkpoint_meta=project_meta,
            configured_model=configured_model,
            manual_override=manual_override,
        )

    def _disable_model_with_status(self, *, disable_reason: str, log_message: str, activity_message: str) -> None:
        runtime = getattr(self, "sam2_runtime", None)
        if runtime is not None:
            runtime.disable(disable_reason)
        self.log_warn("Model", log_message)
        self.inference_manager.on_model_unloaded()
        if self._ui_alive():
            self.root.after(0, lambda m=str(activity_message): self._set_activity_message(m))

    def resolve_checkpoint_preflight(self) -> CheckpointOnboardingResult:
        if getattr(self, "checkpoint_runtime", None) is None:
            return CheckpointOnboardingResult(
                ok=False,
                mode="disabled",
                message="Model runtime service is unavailable.",
                source="missing_runtime_service",
            )
        if importlib.util.find_spec("sam2") is None or torch is None:
            reason = "SAM2 missing" if importlib.util.find_spec("sam2") is None else "Torch missing"
            self._disable_model_with_status(
                disable_reason=reason,
                log_message=f"Model initialization disabled: {reason}.",
                activity_message=STATUS_MODEL_DISABLED,
            )
            return CheckpointOnboardingResult(ok=False, mode="disabled", message=reason, source="runtime_unavailable")

        resolution = self._resolve_sam2_checkpoint()
        if resolution is None or not bool(getattr(resolution, "ok", False)):
            if bool(getattr(self, "_host_mode", False)):
                self._disable_model_with_status(
                    disable_reason="model file missing",
                    log_message="No usable model file is available. Use host Model > Manage Models...",
                    activity_message=STATUS_MODEL_FILE_MISSING,
                )
                return CheckpointOnboardingResult(
                    ok=False,
                    mode="disabled",
                    message="No usable model file is configured in host mode.",
                    source="host_missing_model",
                )
            try:
                onboarding = self._prompt_checkpoint_onboarding()
            except Exception as exc:
                self.log_error("Model", f"Model setup prompt failed: {exc}")
                if self._ui_alive():
                    self.root.after(0, lambda: self._set_activity_message(STATUS_MODEL_ERROR))
                return CheckpointOnboardingResult(
                    ok=False,
                    mode="disabled",
                    message=str(exc),
                    source="onboarding_error",
                )
            if onboarding is None:
                self._disable_model_with_status(
                    disable_reason="checkpoint unavailable",
                    log_message="No model file selected; model-based tools remain disabled.",
                    activity_message=STATUS_MODEL_FILE_MISSING,
                )
                return CheckpointOnboardingResult(
                    ok=False,
                    mode="disabled",
                    message="Model file selection was cancelled.",
                    source="onboarding_cancelled",
                )
            model_path = str(onboarding.get("path", "")).strip()
            checkpoint_id = str(onboarding.get("checkpoint_id", "") or "").strip() or None
            source = str(onboarding.get("source", "") or "manual_override")
        else:
            model_path = str(resolution.path or "").strip()
            checkpoint_id = str(resolution.checkpoint_id or "").strip() or None
            source = str(resolution.source or "resolved")
        if not model_path or not os.path.exists(model_path):
            message = f"Model file not found: {model_path}"
            self.log_error("Model", message)
            if self._ui_alive():
                self.root.after(0, lambda: self._set_activity_message(STATUS_MODEL_ERROR))
            return CheckpointOnboardingResult(ok=False, mode="disabled", message=message, source="missing_model")

        model_path, checkpoint_id, source, allowed = self._resolve_mismatch_choice(model_path, checkpoint_id, source)
        if not allowed:
            self._disable_model_with_status(
                disable_reason="checkpoint mismatch",
                log_message="Model metadata mismatch unresolved; model-based tools disabled.",
                activity_message=STATUS_MODEL_DISABLED,
            )
            return CheckpointOnboardingResult(
                ok=False,
                mode="disabled",
                message="Model metadata mismatch unresolved.",
                source="mismatch",
            )
        return CheckpointOnboardingResult(
            ok=True,
            mode="sam2",
            model_path=str(model_path),
            checkpoint_id=checkpoint_id,
            source=source,
        )

    def start_model_initialization(self, *, reason: str = "manual") -> CheckpointOnboardingResult:
        if getattr(self, "checkpoint_runtime", None) is None:
            legacy_target = getattr(self, "_init_sam2_background", None)
            if callable(legacy_target) and callable(getattr(self, "_run_thread", None)):
                try:
                    self._run_thread(legacy_target, loading_text="Initializing model...")
                except TypeError:
                    self._run_thread(legacy_target)
                return CheckpointOnboardingResult(ok=True, mode="legacy", source="legacy")
        preflight = self.resolve_checkpoint_preflight()
        if not preflight.ok:
            self.log_info("Model", f"Model initialization skipped ({reason}): {preflight.message or preflight.source or 'not ready'}")
            return preflight
        self._run_thread(
            lambda p=preflight: self.init_runtime_background(p),
            loading_text="Initializing model...",
        )
        return preflight

    def _prompt_checkpoint_onboarding(self):
        service = getattr(self, "checkpoint_runtime", None)
        if service is None:
            return None
        descriptor = service.default_descriptor()
        if descriptor is None:
            return None
        response = messagebox.askyesnocancel(
            TITLE_MODEL_FILE_REQUIRED,
            onboarding_body(),
            parent=self.root,
        )
        if response is None:
            return None
        if response is True:
            path = service.download_descriptor(descriptor)
            return {
                "path": str(path),
                "checkpoint_id": descriptor.checkpoint_id,
                "source": "managed_download",
            }
        center_window = getattr(self, "_center_window", None)
        if callable(center_window):
            center_window(self.root)
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Select SAM2 Model File",
            filetypes=[("PyTorch model", "*.pt *.pth"), ("All files", "*.*")],
        )
        if not selected:
            return None
        selected_path = str(os.path.abspath(selected))
        checkpoint_id = service.infer_checkpoint_id_from_path(selected_path)
        self._manual_model_override = selected_path
        return {
            "path": selected_path,
            "checkpoint_id": checkpoint_id,
            "source": "manual_override",
        }

    def _initialize_cpu_fallback(self, frames_viz: np.ndarray, reason: str):
        runtime = getattr(self, "sam2_runtime", None)
        if runtime is None:
            raise RuntimeError("SAM2 runtime service is unavailable.")
        model_hint = None
        try:
            model_hint = self.checkpoint_runtime.managed_models_dir() / "cpu_fallback_model.pt"  # type: ignore[attr-defined]
        except Exception:
            model_hint = None
        if model_hint is None:
            model_hint = Path(tempfile.gettempdir()) / "sdapp_cpu_fallback_model.pt"
        if not model_hint.exists():
            model_hint.write_bytes(b"sdapp-cpu-fallback")

        def _build_predictor(_normalized_model_path: str, _temp_dir: str):
            predictor = DeterministicCpuFallbackPredictor(
                frame_count=int(frames_viz.shape[0]),
                frame_shape=(int(frames_viz.shape[1]), int(frames_viz.shape[2])),
            )
            return predictor, predictor.init_state(video_path=None)

        status = runtime.ensure_initialized(
            model_path=str(model_hint),
            frames_viz=frames_viz,
            build_predictor=_build_predictor,
        )
        if status.state != "READY":
            raise RuntimeError(status.message or "CPU fallback initialization failed.")
        self.predictor = runtime.predictor
        self.inference_state = runtime.inference_state
        self.temp_dir = runtime.temp_dir
        self.model_ready = True
        self.inference_manager.on_model_ready(self.predictor, self.inference_state)
        meta = {
            "checkpoint_id": "cpu_fallback",
            "filename": str(model_hint.name),
            "path": str(model_hint),
            "sha256": None,
            "source": "cpu_fallback",
        }
        self._set_active_checkpoint_metadata(meta, notify_host=True, reason="cpu_fallback_init")
        self.log_warn("Model", f"Using deterministic CPU fallback backend ({reason}).")
        if self._ui_alive():
            self.root.after(0, lambda: self._set_activity_message("Model Ready (CPU Fallback)"))
            if hasattr(self, "btn_save_masks"):
                self.root.after(0, lambda: self.btn_save_masks.configure(state="normal"))
            self.root.after(0, self._process_pending_points)

    def _resolve_mismatch_choice(self, model_path: str, checkpoint_id: str | None, source: str):
        if bool(getattr(self, "_host_mode", False)):
            return model_path, checkpoint_id, source, True
        service = getattr(self, "checkpoint_runtime", None)
        if service is None:
            return model_path, checkpoint_id, source, True
        recorded = self._project_recorded_checkpoint_metadata() if hasattr(self, "_project_recorded_checkpoint_metadata") else None
        active_meta = service.build_checkpoint_metadata(
            checkpoint_id=checkpoint_id,
            path=model_path,
            source=source,
        )
        match, detail = service.compare_checkpoint_metadata(recorded, active_meta)
        if match:
            return model_path, checkpoint_id, source, True
        response = messagebox.askyesnocancel(
            TITLE_MODEL_METADATA_MISMATCH,
            mismatch_body(detail),
            parent=self.root,
        )
        if response is None:
            return model_path, checkpoint_id, source, False
        if response is False:
            return model_path, checkpoint_id, source, True
        recorded_path = str((recorded or {}).get("path") or "").strip()
        if recorded_path and os.path.exists(recorded_path):
            return recorded_path, str((recorded or {}).get("checkpoint_id") or "").strip() or None, "project_recorded", True
        center_window = getattr(self, "_center_window", None)
        if callable(center_window):
            center_window(self.root)
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Select Project-Recorded Model File",
            filetypes=[("PyTorch model", "*.pt *.pth"), ("All files", "*.*")],
        )
        if not selected:
            return model_path, checkpoint_id, source, False
        selected_path = str(os.path.abspath(selected))
        selected_id = service.infer_checkpoint_id_from_path(selected_path)
        self._manual_model_override = selected_path
        return selected_path, selected_id, "project_recorded_override", True

    def init_runtime_background(self, preflight: CheckpointOnboardingResult):
        try:
            frame_count = int(self._get_frame_count()) if hasattr(self, "_get_frame_count") else 0
            if frame_count <= 0:
                raise RuntimeError("No frames loaded. Import images first.")
            frames_viz = np.asarray([np.asarray(self._get_visual_frame(idx), dtype=np.uint8) for idx in range(frame_count)])
            if frames_viz.ndim != 3 or int(frames_viz.shape[0]) <= 0:
                raise RuntimeError("No valid visualization frames are available. Import images first.")

            if str(preflight.mode) == "cpu_fallback":
                self._initialize_cpu_fallback(frames_viz, reason=str(preflight.message or "fallback"))
                return

            resource_root = getattr(self, "resource_root", self.app_root)
            model_path = str(preflight.model_path or "").strip()
            checkpoint_id = str(preflight.checkpoint_id or "").strip() or None
            source = str(preflight.source or "resolved")
            if not model_path or not os.path.exists(model_path):
                raise RuntimeError(f"Model file not found: {model_path}")

            runtime = getattr(self, "sam2_runtime", None)
            if runtime is None:
                raise RuntimeError("SAM2 runtime service is unavailable.")

            def _build_predictor(normalized_model_path: str, temp_dir: str):
                _ensure_runtime_stdio()
                frame_source = getattr(self, "frame_source", None)
                frame_count = int(np.asarray(frames_viz).shape[0]) if np.asarray(frames_viz).ndim >= 3 else 0
                frame_shape = tuple(int(v) for v in np.asarray(frames_viz).shape[1:3]) if frame_count > 0 else (0, 0)
                processing_opts = (
                    dict(getattr(self, "_host_processing_options", {}) or {})
                    if isinstance(getattr(self, "_host_processing_options", None), dict)
                    else {}
                )
                baseline_frames = int(getattr(self, "baseline_pre_frames", 30) or 30)
                apply_horizontal_bar_denoise = bool(processing_opts.get("apply_horizontal_bar_denoise", False))
                apply_smoothing = bool(processing_opts.get("apply_smoothing", True))
                apply_baseline_subtraction = bool(processing_opts.get("apply_baseline_subtraction", True))
                apply_global_normalization = bool(processing_opts.get("apply_global_normalization", True))
                stats = None
                if frame_source is not None and callable(getattr(frame_source, "stats", None)):
                    try:
                        stats = frame_source.stats()
                    except Exception as exc:
                        self.log_debug("Perf", f"Visualization stats unavailable for SAM export cache: {exc}")
                cache_key = build_sam2_frame_cache_key(
                    frame_source=frame_source,
                    frame_count=frame_count,
                    frame_shape=frame_shape,
                    baseline_frames=baseline_frames,
                    apply_horizontal_bar_denoise=apply_horizontal_bar_denoise,
                    apply_smoothing=apply_smoothing,
                    apply_baseline_subtraction=apply_baseline_subtraction,
                    apply_global_normalization=apply_global_normalization,
                    stats=stats,
                )
                frame_cache = getattr(self, "sam2_frame_cache", None)
                cache_dir = None
                if frame_cache is not None:
                    frame_cache.prune_expired()
                    self.log_info("Model", "Preparing cached frames for SAM2...")
                    cache_result = frame_cache.export_frames(
                        frame_source=frame_source,
                        frames_viz=frames_viz,
                        cache_key=cache_key,
                        logger=self.log_debug,
                    )
                    cache_dir = cache_result.cache_dir
                else:
                    raise RuntimeError("SAM2 frame cache service is unavailable.")

                device = "mps" if torch.backends.mps.is_available() else "cpu"
                if device == "cpu" and torch.cuda.is_available():
                    device = "cuda"
                self.log_info("Model", f"Initializing SAM2 on {device}...")
                self.log_info(
                    "Model",
                    f"Loading model file: {Path(normalized_model_path).name}"
                    + (f" (id: {checkpoint_id})" if checkpoint_id else ""),
                )

                from sam2.build_sam import build_sam2_video_predictor

                base_dir = resource_root
                try:
                    from hydra import initialize_config_dir
                    from hydra.core.global_hydra import GlobalHydra

                    GlobalHydra.instance().clear()
                    initialize_config_dir(config_dir=base_dir, job_name="sam2_app")
                except Exception as e:
                    self.log_warn("Model", f"Failed to initialize Hydra config dir: {e}")

                candidate_names = _candidate_model_config_names(normalized_model_path, checkpoint_id)
                errors: list[str] = []
                for config_name in candidate_names:
                    family = "sam2.1" if config_name.startswith("sam2.1_") else "sam2"
                    cname = f"configs/{family}/{config_name}"
                    local_cname = os.path.join(base_dir, "configs", family, config_name)
                    if not os.path.exists(local_cname):
                        continue
                    self.log_info("Model", f"Trying config: {cname}")
                    try:
                        init_t0 = time.perf_counter()
                        predictor = build_sam2_video_predictor(cname, normalized_model_path, device=device)
                        self.predictor = predictor
                        if device == "mps":
                            self._apply_mps_sam2_dtype_guard()
                            predictor = self.predictor
                        inference_state = predictor.init_state(video_path=cache_dir or temp_dir)
                        self.log_debug(
                            "Perf",
                            f"SAM predictor init elapsed={(time.perf_counter() - init_t0) * 1000.0:.1f}ms "
                            f"config={cname}",
                        )
                        return predictor, inference_state
                    except Exception as e:  # noqa: BLE001
                        errors.append(f"{cname}: {e}")
                        self.log_warn("Model", f"Config {cname} failed: {e}")

                if errors:
                    joined = "\n".join(errors[:4])
                    raise RuntimeError(
                        "Unable to initialize model with available configs. "
                        "The selected model file may be incompatible.\n"
                        f"{joined}"
                    )
                raise RuntimeError("No compatible SAM2 config files were found in resources/configs.")

            status = runtime.ensure_initialized(
                model_path=model_path,
                frames_viz=frames_viz,
                build_predictor=_build_predictor,
            )
            if status.state != "READY":
                raise RuntimeError(status.message or "SAM2 initialization failed.")

            self.predictor = runtime.predictor
            self.inference_state = runtime.inference_state
            self.temp_dir = runtime.temp_dir
            self.model_ready = True
            self.inference_manager.on_model_ready(self.predictor, self.inference_state)
            checkpoint_meta = self.checkpoint_runtime.build_checkpoint_metadata(
                checkpoint_id=checkpoint_id,
                path=model_path,
                source=source,
            )
            self._set_active_checkpoint_metadata(checkpoint_meta, notify_host=True, reason="sam2_init")
            try:
                if hasattr(self, "set_model_token"):
                    self.set_model_token(str(model_path))
            except Exception:
                pass
            self.log_success("Model", "SAM2 model is ready.")
            if self._ui_alive():
                self.root.after(0, lambda: self._set_activity_message(STATUS_MODEL_READY))
                if hasattr(self, "btn_save_masks"):
                    self.root.after(0, lambda: self.btn_save_masks.configure(state="normal"))
                self.root.after(0, self._process_pending_points)

        except Exception as e:
            msg = str(e)
            self.log_error("Model", f"SAM2 initialization failed: {msg}")
            runtime = getattr(self, "sam2_runtime", None)
            if runtime is not None:
                runtime.status.message = msg
            self.inference_manager.on_model_unloaded()
            if self._ui_alive():
                self.root.after(0, lambda: self._set_activity_message(STATUS_MODEL_ERROR))
                self.root.after(
                    0,
                    lambda m=msg: messagebox.showerror(
                        "Model Init Error",
                        f"Failed to initialize SAM2 Model:\n{m}",
                        parent=self.root,
                    ),
                )

    def _init_sam2_background(self):
        # Compatibility shim retained for legacy call sites/tests.
        preflight = self.resolve_checkpoint_preflight()
        if not preflight.ok:
            return
        self.init_runtime_background(preflight)

    def _update_mask_prediction(self, frame_idx):
        self.inference_manager.enqueue_frame_inference(frame_idx, reason="frame_update")

    def _run_single_frame_inference(self, frame_idx):
        self.inference_manager.enqueue_frame_inference(frame_idx, reason="direct_call")

    def on_sensitivity_change(self, val):
        self.lbl_sens.configure(text=f"{float(val):.1f}")
        if self.model_ready and self._has_valid_points(self.current_frame_idx):
            self.inference_manager.schedule_sensitivity_inference(self.current_frame_idx, debounce_ms=80)
        else:
            self.update_display()

    def _trigger_background_propagation(self):
        if not self.model_ready or self.predictor is None or self.inference_state is None:
            self.log_warn("Propagation", "Propagation blocked: model runtime is not ready.")
            if self._ui_alive():
                self.root.after(0, lambda: self._set_activity_message(STATUS_MODEL_DISABLED))
            open_manager = messagebox.askyesno(
                "Model Not Ready",
                (
                    "Model-based propagation is not available because the model is not ready.\n\n"
                    "Open Model Manager now to download/select a model file?"
                ),
                parent=self.root,
            )
            legacy_open = None
            try:
                legacy_open = self.__dict__.get("open_checkpoint_manager")
            except Exception:
                legacy_open = None
            if open_manager and callable(legacy_open):
                self.root.after(0, legacy_open)
                return
            open_model_manager = getattr(self, "open_model_manager", None)
            if open_manager and callable(open_model_manager):
                self.root.after(0, open_model_manager)
            elif open_manager and callable(getattr(self, "open_checkpoint_manager", None)):
                self.root.after(0, self.open_checkpoint_manager)
            return

        self._prune_empty_point_frames()

        total_frames = int(self._get_frame_count()) if hasattr(self, "_get_frame_count") else 0
        prop_start, prop_end = self._parse_clamped_frame_range(
            self.spin_prop_start,
            self.spin_prop_end,
            total_frames,
        )

        frame_range = range(prop_start, prop_end + 1) if total_frames > 0 else []

        has_mask = any(
            (idx in self.masks_cache)
            and (self.masks_cache[idx] is not None)
            and np.any(self.masks_cache[idx])
            for idx in frame_range
        )
        has_paint = any((idx in self.paint_layers) and self._has_nonempty_paint(idx) for idx in frame_range)

        if not has_mask and not has_paint:
            messagebox.showwarning(
                "No Masks",
                "No masks or paint edits found in the selected propagation range. "
                "Please create a mask or paint an edit before propagating.",
                parent=self.root,
            )
            return

        self.inference_manager.trigger_propagation(prop_start, prop_end, self.current_frame_idx)
