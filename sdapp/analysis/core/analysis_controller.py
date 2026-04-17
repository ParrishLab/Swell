import os
from pathlib import Path

import cv2
import numpy as np
from scipy.ndimage import map_coordinates
from tkinter import filedialog, messagebox

from sdapp.analysis.core.analysis_context import AnalysisContext
from sdapp.analysis.core.metrics import compute_scale
from sdapp.analysis.ui.roi_dialog import open_roi_dialog
from sdapp.analysis.ui.scale_dialog import open_scale_dialog
from sdapp.analysis.utils.paths import resolve_existing_directory


class AnalysisController:
    def __init__(self, root, app_root, ctx: AnalysisContext):
        self.root = root
        self.app_root = app_root
        self.get_frame_count = ctx.get_frame_count
        self.get_raw_frame = ctx.get_raw_frame
        self.get_masks_cache = ctx.get_masks_cache
        self.get_paint_layers = ctx.get_paint_layers
        self.get_points = ctx.get_points
        self.get_frame_names = ctx.get_frame_names
        self.get_import_source_hint = ctx.get_import_source_hint
        self.get_current_image_source_paths = ctx.get_current_image_source_paths
        self.get_current_frame_idx = ctx.get_current_frame_idx
        self.get_compose_final_mask_for_frame = ctx.get_compose_final_mask_for_frame
        self.get_nonempty_final_mask_frames = ctx.get_nonempty_final_mask_frames
        self.get_frames_per_sec = ctx.get_frames_per_sec
        self.get_scale_px_per_mm = ctx.get_scale_px_per_mm
        self.set_scale_px_per_mm = ctx.set_scale_px_per_mm
        self.get_scale_points = ctx.get_scale_points
        self.set_scale_points = ctx.set_scale_points
        self.get_scale_axis_lock = ctx.get_scale_axis_lock
        self.set_scale_axis_lock = ctx.set_scale_axis_lock
        self.get_last_scale_image_path = ctx.get_last_scale_image_path
        self.set_last_scale_image_path = ctx.set_last_scale_image_path
        self.get_roi_mask = ctx.get_roi_mask
        self.set_roi_mask = ctx.set_roi_mask
        self.get_roi_points = ctx.get_roi_points
        self.set_roi_points = ctx.set_roi_points
        self.update_display = ctx.update_display
        self.apply_host_metrics_settings = ctx.apply_host_metrics_settings
        self.clear_local_metrics_override = ctx.clear_local_metrics_override
        self.log_info = ctx.log_info
        self.log_success = ctx.log_success
        self.on_metrics_settings_changed = ctx.on_metrics_settings_changed
        self.emit_host_global_metrics_update = ctx.emit_host_global_metrics_update
        self.autosave_project_after_metrics_commit = ctx.autosave_project_after_metrics_commit
        self.get_scale_is_local_override = ctx.get_scale_is_local_override
        self.set_scale_is_local_override = ctx.set_scale_is_local_override
        self.get_roi_is_local_override = ctx.get_roi_is_local_override
        self.set_roi_is_local_override = ctx.set_roi_is_local_override
        self.refresh_metrics_status = ctx.refresh_metrics_status

    def _has_loaded_frames(self) -> bool:
        try:
            return int(self.get_frame_count()) > 0
        except Exception:
            return False

    def _same_path(self, p1, p2):
        try:
            return os.path.normcase(os.path.abspath(str(p1))) == os.path.normcase(os.path.abspath(str(p2)))
        except Exception:
            return str(p1) == str(p2)

    def _project_source_initialdir(self):
        try:
            source_paths = list(self.get_current_image_source_paths() or [])
        except Exception:
            source_paths = []
        app_root_abs = os.path.abspath(self.app_root)
        for raw_path in source_paths:
            if not isinstance(raw_path, str) or not raw_path.strip():
                continue
            candidate = resolve_existing_directory(
                raw_path,
                app_root=self.app_root,
                fallback_dir=self.app_root,
                prefer_parent_for_existing_dir=False,
            )
            if not self._same_path(candidate, app_root_abs):
                return candidate
        return None

    def _current_frame_picker_defaults(self) -> tuple[str | None, str]:
        preferred_dir: str | None = None
        preferred_file = ""
        try:
            current_idx = max(0, int(self.get_current_frame_idx()))
        except Exception:
            current_idx = 0
        try:
            source_paths = list(self.get_current_image_source_paths() or [])
        except Exception:
            source_paths = []
        if current_idx < len(source_paths):
            raw = str(source_paths[current_idx] or "").strip()
            if raw:
                source_path = Path(raw).expanduser()
                if source_path.name:
                    preferred_file = source_path.name
                parent = source_path.parent
                if parent.exists() and parent.is_dir():
                    preferred_dir = str(parent.resolve())
        if not preferred_file:
            try:
                frame_names = list(self.get_frame_names() or [])
            except Exception:
                frame_names = []
            if current_idx < len(frame_names):
                preferred_file = Path(str(frame_names[current_idx])).name
        return preferred_dir, str(preferred_file or "")

    def _get_first_frame_original_u8(self):
        if not self._has_loaded_frames():
            return None
        frame = self.get_raw_frame(0)
        if frame.ndim == 3:
            frame = frame[:, :, 0]
        frame = frame.astype(np.float32)
        frame_u8 = cv2.normalize(frame, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        return frame_u8

    def _load_image_u8_from_path(self, image_path):
        if not image_path:
            return None
        img = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)
        if img is None:
            return None
        if img.ndim == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        img = img.astype(np.float32)
        return cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)

    def _sample_line_profile(self, img_u8, p1, p2, linewidth=7):
        x1, y1 = float(p1[0]), float(p1[1])
        x2, y2 = float(p2[0]), float(p2[1])
        dx = x2 - x1
        dy = y2 - y1
        length = float(np.hypot(dx, dy))
        if length < 3.0:
            return None, None, None

        ux, uy = dx / length, dy / length
        nx, ny = -uy, ux

        n_samples = max(int(np.ceil(length)) + 1, 16)
        t_vals = np.linspace(0.0, length, n_samples)
        offsets = np.linspace(-linewidth / 2.0, linewidth / 2.0, max(3, int(linewidth)))

        sampled_rows = []
        img_f = img_u8.astype(np.float32)
        for off in offsets:
            xs = x1 + ux * t_vals + nx * off
            ys = y1 + uy * t_vals + ny * off
            vals = map_coordinates(img_f, [ys, xs], order=1, mode="nearest")
            sampled_rows.append(vals)

        profile = np.mean(np.vstack(sampled_rows), axis=0)
        kernel = np.array([1.0, 2.0, 3.0, 2.0, 1.0], dtype=np.float32)
        kernel /= np.sum(kernel)
        profile = np.convolve(profile, kernel, mode="same")
        return profile, t_vals, (ux, uy, x1, y1, length, n_samples)

    def _subpixel_peak_index(self, y, idx):
        if idx <= 0 or idx >= (len(y) - 1):
            return float(idx)
        y_m1 = float(y[idx - 1])
        y_0 = float(y[idx])
        y_p1 = float(y[idx + 1])
        denom = (y_m1 - 2.0 * y_0 + y_p1)
        if abs(denom) < 1e-12:
            return float(idx)
        delta = 0.5 * (y_m1 - y_p1) / denom
        delta = float(np.clip(delta, -1.0, 1.0))
        return float(idx) + delta

    def _refine_candidate_subpixel(self, profile, idx):
        return self._subpixel_peak_index(profile, idx)

    def _snap_scale_points_axis(self, p1, p2):
        x1, y1 = float(p1[0]), float(p1[1])
        x2, y2 = float(p2[0]), float(p2[1])
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        if dx >= dy:
            y = (y1 + y2) * 0.5
            return (x1, y), (x2, y), "horizontal"
        x = (x1 + x2) * 0.5
        return (x, y1), (x, y2), "vertical"

    def _compute_axis_unit(self, p1, p2):
        x1, y1 = float(p1[0]), float(p1[1])
        x2, y2 = float(p2[0]), float(p2[1])
        dx = x2 - x1
        dy = y2 - y1
        if abs(dx) >= abs(dy):
            ux = 1.0 if dx >= 0 else -1.0
            uy = 0.0
            axis_mode = "horizontal"
        else:
            ux = 0.0
            uy = 1.0 if dy >= 0 else -1.0
            axis_mode = "vertical"
        nx, ny = -uy, ux
        return ux, uy, nx, ny, axis_mode

    def _refine_scale_bar_points(self, img_u8, p1, p2, linewidth=7, endpoint_window_px=8, force_axis=False):
        if img_u8 is None or img_u8.size == 0:
            return {
                "p1_ref": p1,
                "p2_ref": p2,
                "refined_ok": False,
                "score": 1.0,
                "fallback": True,
                "axis_mode": "unknown",
                "p1_snap": p1,
                "p2_snap": p2,
            }

        if force_axis:
            p1_used, p2_used, axis_mode = self._snap_scale_points_axis(p1, p2)
            ux, uy, _, _, _ = self._compute_axis_unit(p1_used, p2_used)
        else:
            p1_used = (float(p1[0]), float(p1[1]))
            p2_used = (float(p2[0]), float(p2[1]))
            dx = float(p2_used[0] - p1_used[0])
            dy = float(p2_used[1] - p1_used[1])
            length = float(np.hypot(dx, dy))
            if length < 1e-6:
                return {
                    "p1_ref": p1_used,
                    "p2_ref": p2_used,
                    "refined_ok": False,
                    "score": 1.0,
                    "fallback": True,
                    "axis_mode": "free",
                    "p1_snap": p1_used,
                    "p2_snap": p2_used,
                }
            ux = dx / length
            uy = dy / length
            axis_mode = "free"

        profile, t_vals, _ = self._sample_line_profile(img_u8, p1_used, p2_used, linewidth=linewidth)
        if profile is None:
            return {
                "p1_ref": p1_used,
                "p2_ref": p2_used,
                "refined_ok": False,
                "score": 1.0,
                "fallback": True,
                "axis_mode": axis_mode,
                "p1_snap": p1_used,
                "p2_snap": p2_used,
            }

        abs_grad = np.abs(np.gradient(profile))
        n = len(abs_grad)
        if n < 8:
            return {
                "p1_ref": p1_used,
                "p2_ref": p2_used,
                "refined_ok": False,
                "score": 1.0,
                "fallback": True,
                "axis_mode": axis_mode,
                "p1_snap": p1_used,
                "p2_snap": p2_used,
            }

        spacing = float(t_vals[-1] / max(1, (len(t_vals) - 1)))
        window = max(3, int(np.ceil(float(endpoint_window_px) / max(spacing, 1e-9))))
        window = min(window, max(3, n // 2))
        left_slice = abs_grad[:window]
        right_slice = abs_grad[n - window :]
        if left_slice.size == 0 or right_slice.size == 0:
            return {
                "p1_ref": p1_used,
                "p2_ref": p2_used,
                "refined_ok": False,
                "score": 1.0,
                "fallback": True,
                "axis_mode": axis_mode,
                "p1_snap": p1_used,
                "p2_snap": p2_used,
            }

        idx_left = int(np.argmax(left_slice))
        idx_right = int(np.argmax(right_slice)) + (n - window)
        if idx_right <= idx_left:
            return {
                "p1_ref": p1_used,
                "p2_ref": p2_used,
                "refined_ok": False,
                "score": 1.0,
                "fallback": True,
                "axis_mode": axis_mode,
                "p1_snap": p1_used,
                "p2_snap": p2_used,
            }

        idx_left_sub = self._refine_candidate_subpixel(abs_grad, idx_left)
        idx_right_sub = self._refine_candidate_subpixel(abs_grad, idx_right)
        t_left = float(idx_left_sub * spacing)
        t_right = float(idx_right_sub * spacing)
        p1_ref = (float(p1_used[0] + ux * t_left), float(p1_used[1] + uy * t_left))
        p2_ref = (float(p1_used[0] + ux * t_right), float(p1_used[1] + uy * t_right))
        h, w = img_u8.shape[:2]
        p1_ref = (float(np.clip(p1_ref[0], 0, w - 1)), float(np.clip(p1_ref[1], 0, h - 1)))
        p2_ref = (float(np.clip(p2_ref[0], 0, w - 1)), float(np.clip(p2_ref[1], 0, h - 1)))
        score = abs(float(t_right - t_left))

        return {
            "p1_ref": p1_ref,
            "p2_ref": p2_ref,
            "refined_ok": True,
            "score": score,
            "fallback": False,
            "axis_mode": axis_mode,
            "p1_snap": p1_used,
            "p2_snap": p2_used,
        }

    def _capture_scale_selection(self):
        if not self._has_loaded_frames():
            messagebox.showwarning("No Images", "Import images first.", parent=self.root)
            return None

        image_path = ""
        last_scale_image_path = str(self.get_last_scale_image_path() or "").strip()
        if last_scale_image_path and os.path.isfile(last_scale_image_path):
            image_path = last_scale_image_path
        else:
            scale_initialdir = resolve_existing_directory(
                self.get_last_scale_image_path(),
                app_root=self.app_root,
                fallback_dir=self.app_root,
                prefer_parent_for_existing_dir=False,
            )
            app_root_abs = os.path.abspath(self.app_root)
            if self._same_path(scale_initialdir, app_root_abs):
                project_initialdir = self._project_source_initialdir()
                if project_initialdir:
                    scale_initialdir = project_initialdir
            if self._same_path(scale_initialdir, app_root_abs):
                input_initialdir = resolve_existing_directory(
                    self.get_import_source_hint(),
                    app_root=self.app_root,
                    fallback_dir=self.app_root,
                    prefer_parent_for_existing_dir=False,
                )
                scale_initialdir = input_initialdir

            image_path = filedialog.askopenfilename(
                parent=self.root,
                title="Select Image for Scale Calibration",
                initialdir=scale_initialdir,
                filetypes=[
                    ("Image files", "*.png *.jpg *.jpeg *.tif *.tiff *.bmp"),
                    ("All files", "*.*"),
                ],
            )
            if not image_path:
                return None
            self.set_last_scale_image_path(image_path)

        img_u8 = self._load_image_u8_from_path(image_path)
        if img_u8 is None:
            messagebox.showwarning("Image Error", "Unable to read selected image for scale calibration.", parent=self.root)
            return None

        initial_scale_points = []
        try:
            raw_scale_points = list(self.get_scale_points() or [])
        except Exception:
            raw_scale_points = []
        if len(raw_scale_points) >= 2:
            initial_scale_points = list(raw_scale_points[:2])

        result = open_scale_dialog(
            root=self.root,
            img_u8=img_u8,
            snap_scale_points_axis=self._snap_scale_points_axis,
            refine_scale_bar_points=self._refine_scale_bar_points,
            compute_scale=compute_scale,
            initial_scale_points=initial_scale_points,
            initial_axis_lock=self.get_scale_axis_lock(),
            allow_reset_local=bool(self.get_scale_is_local_override()),
        )
        if result is None:
            return None
        result["image_path"] = str(image_path)
        return result

    def _apply_local_scale_selection(self, result) -> None:
        self.set_scale_px_per_mm(result["px_per_mm"])
        self.set_scale_points(result["scale_points"])
        self.set_scale_axis_lock(bool(result.get("axis_lock", True)))
        self.set_last_scale_image_path(result.get("image_path", ""))
        self.set_scale_is_local_override(True)
        self.refresh_metrics_status()
        if callable(self.on_metrics_settings_changed):
            try:
                self.on_metrics_settings_changed("scale")
            except Exception:
                pass

        if result["fallback"]:
            messagebox.showwarning("Scale Refinement", "Low-confidence refinement; using selected endpoints.", parent=self.root)
        autosave_result = self.autosave_project_after_metrics_commit("local_scale")
        if isinstance(autosave_result, dict) and not bool(autosave_result.get("ok", False)):
            message = str(autosave_result.get("message", "Project autosave did not complete."))
            messagebox.showwarning("Scale Set", message, parent=self.root)
            return
        msg = f"Scale set to {result['px_per_mm']:.3f} px/mm"
        if result["refined_ok"]:
            msg += "\n(Refined from sampled intensity profile with sub-pixel edge fit.)"
        else:
            msg += "\n(Using raw click points; refinement fallback applied.)"
        msg += f"\n(Scale mode: {result['axis_mode']}.)"
        messagebox.showinfo("Scale Set", msg, parent=self.root)

    def _capture_roi_selection(self):
        if not self._has_loaded_frames():
            messagebox.showwarning("No Images", "Import images first.", parent=self.root)
            return None

        roi_initialdir = self._project_source_initialdir()
        if not roi_initialdir:
            roi_initialdir = resolve_existing_directory(
                self.get_import_source_hint(),
                app_root=self.app_root,
                fallback_dir=self.app_root,
                prefer_parent_for_existing_dir=False,
            )
        preferred_dir, preferred_file = self._current_frame_picker_defaults()
        if preferred_dir:
            roi_initialdir = preferred_dir

        image_path = filedialog.askopenfilename(
            parent=self.root,
            title="Select Image for ROI",
            initialdir=roi_initialdir,
            initialfile=preferred_file,
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.tif *.tiff *.bmp"),
                ("All files", "*.*"),
            ],
        )
        if not image_path:
            return None

        img_u8 = self._load_image_u8_from_path(image_path)
        if img_u8 is None:
            messagebox.showwarning("Image Error", "Unable to read selected image for ROI.", parent=self.root)
            return None

        result = open_roi_dialog(
            root=self.root,
            img_u8=img_u8,
            initial_roi_points=self.get_roi_points(),
            allow_reset_local=bool(self.get_roi_is_local_override()),
        )
        if result is None:
            return None
        return result

    def _apply_local_roi_selection(self, result) -> None:
        self.set_roi_mask(result["roi_mask"])
        self.set_roi_points(result["roi_points"])
        self.set_roi_is_local_override(True)
        self.refresh_metrics_status()
        self.update_display()
        if callable(self.on_metrics_settings_changed):
            try:
                self.on_metrics_settings_changed("roi")
            except Exception:
                pass
        autosave_result = self.autosave_project_after_metrics_commit("local_roi")
        if isinstance(autosave_result, dict) and not bool(autosave_result.get("ok", False)):
            message = str(autosave_result.get("message", "Project autosave did not complete."))
            messagebox.showwarning("ROI Set", message, parent=self.root)
            return
        messagebox.showinfo("ROI Set", "ROI polygon saved.", parent=self.root)

    def _reset_local_metric_override(self, *, override_kind: str, keys: list[str], title: str, success_message: str) -> None:
        if not callable(self.clear_local_metrics_override):
            messagebox.showwarning(title, "Local override reset is unavailable in this context.", parent=self.root)
            return
        result = self.clear_local_metrics_override(
            f"reset_local_{override_kind}",
            [str(key) for key in keys],
        )
        if isinstance(result, dict) and not bool(result.get("ok", False)):
            message = str(result.get("message", f"Unable to reset local {override_kind} override."))
            messagebox.showwarning(title, message, parent=self.root)
            return
        if isinstance(result, dict):
            metrics_settings = result.get("metrics_settings")
            local_metrics_settings = result.get("local_metrics_settings")
            if callable(getattr(self, "apply_host_metrics_settings", None)):
                try:
                    self.apply_host_metrics_settings(
                        metrics_settings if isinstance(metrics_settings, dict) else None,
                        local_metrics_settings if isinstance(local_metrics_settings, dict) else None,
                    )
                except Exception:
                    pass
        autosave_result = self.autosave_project_after_metrics_commit(f"reset_local_{override_kind}")
        if isinstance(autosave_result, dict) and not bool(autosave_result.get("ok", False)):
            message = str(autosave_result.get("message", "Project autosave did not complete."))
            messagebox.showwarning(title, message, parent=self.root)
            return
        messagebox.showinfo(title, success_message, parent=self.root)

    def reset_local_scale_override(self) -> None:
        self._reset_local_metric_override(
            override_kind="scale",
            keys=["scale_px_per_mm", "scale_points", "scale_axis_lock", "scale_image_path"],
            title="Scale Reset",
            success_message="Local scale override cleared. This event now uses the global scale.",
        )

    def reset_local_roi_override(self) -> None:
        self._reset_local_metric_override(
            override_kind="roi",
            keys=["roi_points", "roi_mask"],
            title="ROI Reset",
            success_message="Local ROI override cleared. This event now uses the global ROI.",
        )

    def start_local_scale_selection(self):
        result = self._capture_scale_selection()
        if result is None:
            return
        if str(result.get("target_scope", "")).lower() == "reset_local_scale":
            self.reset_local_scale_override()
            return
        self._apply_local_scale_selection(result)

    def _apply_global_scale_selection(self, result) -> None:
        payload = {
            "scale_px_per_mm": float(result["px_per_mm"]),
            "scale_points": [[float(pt[0]), float(pt[1])] for pt in list(result.get("scale_points", []))],
            "scale_axis_lock": bool(result.get("axis_lock", True)),
        }
        scale_image_path = str(result.get("image_path", "") or "").strip()
        if scale_image_path:
            payload["scale_image_path"] = scale_image_path
        update_result = self.emit_host_global_metrics_update("global_scale", payload)
        if isinstance(update_result, dict) and not bool(update_result.get("ok", False)):
            message = str(update_result.get("message", "Host rejected global scale update."))
            messagebox.showwarning("Global Scale", message, parent=self.root)
            return
        if not bool(self.get_scale_is_local_override()):
            self.set_scale_px_per_mm(result["px_per_mm"])
            self.set_scale_points(result["scale_points"])
            self.set_scale_axis_lock(bool(result.get("axis_lock", True)))
            self.set_last_scale_image_path(scale_image_path)
            self.set_scale_is_local_override(False)
        self.refresh_metrics_status()
        autosave_result = self.autosave_project_after_metrics_commit("global_scale")
        if isinstance(autosave_result, dict) and not bool(autosave_result.get("ok", False)):
            message = str(autosave_result.get("message", "Project autosave did not complete."))
            messagebox.showwarning("Global Scale", message, parent=self.root)
            return
        msg = f"Global scale set to {result['px_per_mm']:.3f} px/mm"
        if result["refined_ok"]:
            msg += "\n(Refined from sampled intensity profile with sub-pixel edge fit.)"
        else:
            msg += "\n(Using raw click points; refinement fallback applied.)"
        msg += f"\n(Scale mode: {result['axis_mode']}.)"
        messagebox.showinfo("Global Scale Set", msg, parent=self.root)

    def start_global_scale_selection(self):
        result = self._capture_scale_selection()
        if result is None:
            return
        if str(result.get("target_scope", "")).lower() == "reset_local_scale":
            self.reset_local_scale_override()
            return
        self._apply_global_scale_selection(result)

    def start_local_roi_selection(self):
        result = self._capture_roi_selection()
        if result is None:
            return
        if str(result.get("target_scope", "")).lower() == "reset_local_roi":
            self.reset_local_roi_override()
            return
        self._apply_local_roi_selection(result)

    def _apply_global_roi_selection(self, result) -> None:
        payload = {
            "roi_points": [[float(pt[0]), float(pt[1])] for pt in list(result.get("roi_points", []))],
            "roi_mask": np.asarray(result.get("roi_mask"), dtype=bool).copy() if result.get("roi_mask") is not None else None,
        }
        update_result = self.emit_host_global_metrics_update("global_roi", payload)
        if isinstance(update_result, dict) and not bool(update_result.get("ok", False)):
            message = str(update_result.get("message", "Host rejected global ROI update."))
            messagebox.showwarning("Global ROI", message, parent=self.root)
            return
        if not bool(self.get_roi_is_local_override()):
            self.set_roi_mask(result["roi_mask"])
            self.set_roi_points(result["roi_points"])
            self.set_roi_is_local_override(False)
        self.refresh_metrics_status()
        if not bool(self.get_roi_is_local_override()):
            self.update_display()
        autosave_result = self.autosave_project_after_metrics_commit("global_roi")
        if isinstance(autosave_result, dict) and not bool(autosave_result.get("ok", False)):
            message = str(autosave_result.get("message", "Project autosave did not complete."))
            messagebox.showwarning("Global ROI", message, parent=self.root)
            return
        messagebox.showinfo("Global ROI Set", "Global ROI polygon saved.", parent=self.root)

    def start_global_roi_selection(self):
        result = self._capture_roi_selection()
        if result is None:
            return
        if str(result.get("target_scope", "")).lower() == "reset_local_roi":
            self.reset_local_roi_override()
            return
        self._apply_global_roi_selection(result)

    def start_scale_selection(self):
        result = self._capture_scale_selection()
        if result is None:
            return
        if str(result.get("target_scope", "")).lower() == "reset_local_scale":
            self.reset_local_scale_override()
            return
        if str(result.get("target_scope", "local")).lower() == "global":
            self._apply_global_scale_selection(result)
            return
        self._apply_local_scale_selection(result)

    def start_roi_selection(self):
        result = self._capture_roi_selection()
        if result is None:
            return
        if str(result.get("target_scope", "")).lower() == "reset_local_roi":
            self.reset_local_roi_override()
            return
        if str(result.get("target_scope", "local")).lower() == "global":
            self._apply_global_roi_selection(result)
            return
        self._apply_local_roi_selection(result)
