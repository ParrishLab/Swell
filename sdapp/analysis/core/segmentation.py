import os
import importlib.util
import tempfile
from pathlib import Path
from types import MethodType

import cv2
import numpy as np
from tkinter import filedialog, messagebox

from sdapp.analysis.model import DeterministicCpuFallbackPredictor

try:
    import torch
except Exception:
    torch = None


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
        configured_model = str(self.entry_model.get() or "").strip() if hasattr(self, "entry_model") else ""
        manual_override = str(getattr(self, "_manual_model_override", "") or "").strip()
        return service.resolve_checkpoint(
            project_checkpoint_meta=project_meta,
            configured_model=configured_model,
            manual_override=manual_override,
        )

    def _prompt_checkpoint_onboarding(self):
        service = getattr(self, "checkpoint_runtime", None)
        if service is None:
            return None
        descriptor = service.default_descriptor()
        if descriptor is None:
            return None
        response = messagebox.askyesnocancel(
            "Model Checkpoint Required",
            (
                "No local SAM2 checkpoint is available.\n\n"
                "Yes = Download approved default checkpoint\n"
                "No = Select a local checkpoint file\n"
                "Cancel = Keep model tools disabled"
            ),
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
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Select SAM2 Checkpoint",
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
            "Checkpoint Mismatch",
            (
                f"{detail}\n\n"
                "Yes = Switch to project-recorded checkpoint\n"
                "No = Continue with current checkpoint\n"
                "Cancel = Disable model tools (review-only)"
            ),
            parent=self.root,
        )
        if response is None:
            return model_path, checkpoint_id, source, False
        if response is False:
            return model_path, checkpoint_id, source, True
        recorded_path = str((recorded or {}).get("path") or "").strip()
        if recorded_path and os.path.exists(recorded_path):
            return recorded_path, str((recorded or {}).get("checkpoint_id") or "").strip() or None, "project_recorded", True
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Select Project-Recorded Checkpoint",
            filetypes=[("PyTorch model", "*.pt *.pth"), ("All files", "*.*")],
        )
        if not selected:
            return model_path, checkpoint_id, source, False
        selected_path = str(os.path.abspath(selected))
        selected_id = service.infer_checkpoint_id_from_path(selected_path)
        self._manual_model_override = selected_path
        return selected_path, selected_id, "project_recorded_override", True

    def _init_sam2_background(self):
        try:
            if self.frames_sub_viz is None:
                raise RuntimeError("No frames loaded. Import images first.")
            frames_viz = np.asarray(self.frames_sub_viz)
            if frames_viz.ndim != 3 or int(frames_viz.shape[0]) <= 0:
                raise RuntimeError("No valid visualization frames are available. Import images first.")

            if importlib.util.find_spec("sam2") is None or torch is None:
                reason = "SAM2 missing" if importlib.util.find_spec("sam2") is None else "Torch missing"
                self._initialize_cpu_fallback(frames_viz, reason=reason)
                return

            resource_root = getattr(self, "resource_root", self.app_root)
            resolution = self._resolve_sam2_checkpoint()
            if resolution is None or not bool(getattr(resolution, "ok", False)):
                onboarding = self._prompt_checkpoint_onboarding()
                if onboarding is None:
                    runtime = getattr(self, "sam2_runtime", None)
                    if runtime is not None:
                        runtime.disable("checkpoint unavailable")
                    self.log_warn("Model", "No checkpoint selected; model tools remain disabled.")
                    self.inference_manager.on_model_unloaded()
                    if self._ui_alive():
                        self.root.after(0, lambda: self._set_activity_message("Checkpoint Missing"))
                    return
                model_path = str(onboarding.get("path", "")).strip()
                checkpoint_id = str(onboarding.get("checkpoint_id", "") or "").strip() or None
                source = str(onboarding.get("source", "") or "manual_override")
            else:
                model_path = str(resolution.path or "").strip()
                checkpoint_id = str(resolution.checkpoint_id or "").strip() or None
                source = str(resolution.source or "resolved")
            if not model_path or not os.path.exists(model_path):
                raise RuntimeError(f"Model file not found: {model_path}")

            model_path, checkpoint_id, source, allowed = self._resolve_mismatch_choice(model_path, checkpoint_id, source)
            if not allowed:
                runtime = getattr(self, "sam2_runtime", None)
                if runtime is not None:
                    runtime.disable("checkpoint mismatch")
                self.log_warn("Model", "Checkpoint mismatch unresolved; model tools disabled.")
                self.inference_manager.on_model_unloaded()
                if self._ui_alive():
                    self.root.after(0, lambda: self._set_activity_message("Model Disabled"))
                return

            runtime = getattr(self, "sam2_runtime", None)
            if runtime is None:
                raise RuntimeError("SAM2 runtime service is unavailable.")

            def _build_predictor(normalized_model_path: str, temp_dir: str):
                self.log_info("Model", "Preparing temporary frames for SAM2...")
                for i, f_8bit in enumerate(frames_viz):
                    cv2.imwrite(
                        os.path.join(temp_dir, f"{i:05d}.jpg"),
                        cv2.cvtColor(np.asarray(f_8bit, dtype=np.uint8), cv2.COLOR_GRAY2BGR),
                    )

                device = "mps" if torch.backends.mps.is_available() else "cpu"
                if device == "cpu" and torch.cuda.is_available():
                    device = "cuda"
                self.log_info("Model", f"Initializing SAM2 on {device}...")

                from sam2.build_sam import build_sam2_video_predictor

                is_2_1 = "2.1" in normalized_model_path

                config_name = "sam2.1_hiera_b+.yaml"
                if "small" in normalized_model_path or "hiera_s" in normalized_model_path:
                    config_name = "sam2.1_hiera_s.yaml" if is_2_1 else "sam2_hiera_s.yaml"
                elif "large" in normalized_model_path or "hiera_l" in normalized_model_path:
                    config_name = "sam2.1_hiera_l.yaml" if is_2_1 else "sam2_hiera_l.yaml"
                elif "tiny" in normalized_model_path or "hiera_t" in normalized_model_path:
                    config_name = "sam2.1_hiera_t.yaml" if is_2_1 else "sam2_hiera_t.yaml"
                else:
                    config_name = "sam2.1_hiera_b+.yaml" if is_2_1 else "sam2_hiera_b+.yaml"

                cname = f"configs/sam2.1/{config_name}" if is_2_1 else f"configs/sam2/{config_name}"

                base_dir = resource_root
                local_cname = os.path.join(base_dir, "configs", "sam2.1" if is_2_1 else "sam2", config_name)
                if os.path.exists(local_cname):
                    try:
                        from hydra import initialize_config_dir
                        from hydra.core.global_hydra import GlobalHydra

                        GlobalHydra.instance().clear()
                        initialize_config_dir(config_dir=base_dir, job_name="sam2_app")
                    except Exception as e:
                        self.log_warn("Model", f"Failed to initialize Hydra config dir: {e}")
                    self.log_debug("Model", f"Using local configs at: {base_dir}/configs")
                else:
                    if not os.path.exists(cname):
                        raise RuntimeError(f"Config file not found: {cname}")

                self.log_debug("Model", f"Using config: {cname}")
                predictor = build_sam2_video_predictor(cname, normalized_model_path, device=device)
                self.predictor = predictor
                if device == "mps":
                    self._apply_mps_sam2_dtype_guard()
                    predictor = self.predictor
                inference_state = predictor.init_state(video_path=temp_dir)
                return predictor, inference_state

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
                self.entry_model.delete(0, "end")
                self.entry_model.insert(0, str(model_path))
            except Exception:
                pass
            self.log_success("Model", "SAM2 model is ready.")
            if self._ui_alive():
                self.root.after(0, lambda: self._set_activity_message("Model Ready"))
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
                self.root.after(0, lambda: self._set_activity_message("Model Error"))
                self.root.after(
                    0,
                    lambda m=msg: messagebox.showerror(
                        "Model Init Error",
                        f"Failed to initialize SAM2 Model:\n{m}",
                        parent=self.root,
                    ),
                )

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
        self._prune_empty_point_frames()

        total_frames = len(self.frames_raw) if self.frames_raw is not None else 0
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
