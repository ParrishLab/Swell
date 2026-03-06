import os
import shutil
from types import MethodType

import cv2
import numpy as np
import torch
from tkinter import messagebox


class SegmentationActions:
    def _apply_mps_sam2_dtype_guard(self):
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

    def _init_sam2_background(self):
        try:
            output_folder = self.entry_output.get()
            model_path = self.entry_model.get().strip()
            if model_path and not os.path.isabs(model_path):
                model_path = os.path.join(self.app_root, model_path)
            if not model_path or not os.path.exists(model_path):
                raise RuntimeError(f"Model file not found: {model_path}")
            if output_folder and not os.path.isabs(output_folder):
                output_folder = os.path.join(self.app_root, output_folder)
            if not os.path.exists(output_folder):
                os.makedirs(output_folder)
            self.temp_dir = os.path.join(output_folder, "temp_sam_interactive")
            if os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
            os.makedirs(self.temp_dir)

            if not self.frames_sub_viz:
                raise RuntimeError("No frames loaded. Import images first.")

            self.log_info("Model", "Preparing temporary frames for SAM2...")
            for i, f_8bit in enumerate(self.frames_sub_viz):
                cv2.imwrite(
                    os.path.join(self.temp_dir, f"{i:05d}.jpg"),
                    cv2.cvtColor(f_8bit, cv2.COLOR_GRAY2BGR),
                )

            device = "mps" if torch.backends.mps.is_available() else "cpu"
            if device == "cpu" and torch.cuda.is_available():
                device = "cuda"
            self.log_info("Model", f"Initializing SAM2 on {device}...")

            from sam2.build_sam import build_sam2_video_predictor

            is_2_1 = "2.1" in model_path

            config_name = "sam2.1_hiera_b+.yaml"
            if "small" in model_path or "hiera_s" in model_path:
                config_name = "sam2.1_hiera_s.yaml" if is_2_1 else "sam2_hiera_s.yaml"
            elif "large" in model_path or "hiera_l" in model_path:
                config_name = "sam2.1_hiera_l.yaml" if is_2_1 else "sam2_hiera_l.yaml"
            elif "tiny" in model_path or "hiera_t" in model_path:
                config_name = "sam2.1_hiera_t.yaml" if is_2_1 else "sam2_hiera_t.yaml"
            else:
                config_name = "sam2.1_hiera_b+.yaml" if is_2_1 else "sam2_hiera_b+.yaml"

            cname = f"configs/sam2.1/{config_name}" if is_2_1 else f"configs/sam2/{config_name}"

            base_dir = self.app_root
            local_cname = os.path.join(
                base_dir, "configs", "sam2.1" if is_2_1 else "sam2", config_name
            )
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
            self.predictor = build_sam2_video_predictor(cname, model_path, device=device)
            if device == "mps":
                self._apply_mps_sam2_dtype_guard()
            self.inference_state = self.predictor.init_state(video_path=self.temp_dir)
            self.model_ready = True
            self.inference_manager.on_model_ready(self.predictor, self.inference_state)
            self.log_success("Model", "SAM2 model is ready.")
            if self._ui_alive():
                self.root.after(0, lambda: self.lbl_status.configure(text="Status: Model Ready", foreground="green"))
                self.root.after(0, lambda: self.btn_run.configure(state="normal"))
                self.root.after(0, self._process_pending_points)

        except Exception as e:
            msg = str(e)
            self.log_error("Model", f"SAM2 initialization failed: {msg}")
            self.inference_manager.on_model_unloaded()
            if self._ui_alive():
                self.root.after(0, lambda: self.lbl_status.configure(text="Status: Model Error", foreground="red"))
                self.root.after(
                    0, lambda m=msg: messagebox.showerror("Model Init Error", f"Failed to initialize SAM2 Model:\n{m}")
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
            )
            return

        self.inference_manager.trigger_propagation(prop_start, prop_end, self.current_frame_idx)
