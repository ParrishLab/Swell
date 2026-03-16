import os

import cv2
import numpy as np
from scipy.ndimage import map_coordinates
from tkinter import filedialog, messagebox

from sdapp.analysis.core.metrics import compute_scale
from sdapp.analysis.ui.roi_dialog import open_roi_dialog
from sdapp.analysis.ui.scale_dialog import open_scale_dialog
from sdapp.analysis.utils.paths import resolve_existing_directory


class AnalysisController:
    def __init__(
        self,
        root,
        app_root,
        get_frames_raw,
        get_masks_cache,
        get_paint_layers,
        get_points,
        get_frame_names,
        get_input_folder,
        get_compose_final_mask_for_frame,
        get_nonempty_final_mask_frames,
        get_frames_per_sec,
        get_scale_px_per_mm,
        set_scale_px_per_mm,
        get_scale_points,
        set_scale_points,
        get_last_scale_image_path,
        set_last_scale_image_path,
        get_roi_mask,
        set_roi_mask,
        get_roi_points,
        set_roi_points,
        update_display,
        log_info,
        log_success,
        on_metrics_settings_changed=None,
    ):
        self.root = root
        self.app_root = app_root
        self.get_frames_raw = get_frames_raw
        self.get_masks_cache = get_masks_cache
        self.get_paint_layers = get_paint_layers
        self.get_points = get_points
        self.get_frame_names = get_frame_names
        self.get_input_folder = get_input_folder
        self.get_compose_final_mask_for_frame = get_compose_final_mask_for_frame
        self.get_nonempty_final_mask_frames = get_nonempty_final_mask_frames
        self.get_frames_per_sec = get_frames_per_sec
        self.get_scale_px_per_mm = get_scale_px_per_mm
        self.set_scale_px_per_mm = set_scale_px_per_mm
        self.get_scale_points = get_scale_points
        self.set_scale_points = set_scale_points
        self.get_last_scale_image_path = get_last_scale_image_path
        self.set_last_scale_image_path = set_last_scale_image_path
        self.get_roi_mask = get_roi_mask
        self.set_roi_mask = set_roi_mask
        self.get_roi_points = get_roi_points
        self.set_roi_points = set_roi_points
        self.update_display = update_display
        self.log_info = log_info
        self.log_success = log_success
        self.on_metrics_settings_changed = on_metrics_settings_changed

    def _get_first_frame_original_u8(self):
        frames_raw = self.get_frames_raw()
        if frames_raw is None or len(frames_raw) == 0:
            return None
        frame = frames_raw[0]
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

    def start_scale_selection(self):
        frames_raw = self.get_frames_raw()
        if frames_raw is None:
            messagebox.showwarning("No Images", "Import images first.", parent=self.root)
            return

        scale_initialdir = resolve_existing_directory(
            self.get_last_scale_image_path(),
            app_root=self.app_root,
            fallback_dir=self.app_root,
            prefer_parent_for_existing_dir=False,
        )
        if scale_initialdir == os.path.abspath(self.app_root):
            input_initialdir = resolve_existing_directory(
                self.get_input_folder(),
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
            return
        self.set_last_scale_image_path(image_path)

        img_u8 = self._load_image_u8_from_path(image_path)
        if img_u8 is None:
            messagebox.showwarning("Image Error", "Unable to read selected image for scale calibration.", parent=self.root)
            return

        result = open_scale_dialog(
            root=self.root,
            img_u8=img_u8,
            snap_scale_points_axis=self._snap_scale_points_axis,
            refine_scale_bar_points=self._refine_scale_bar_points,
            compute_scale=compute_scale,
        )
        if result is None:
            return

        self.set_scale_px_per_mm(result["px_per_mm"])
        self.set_scale_points(result["scale_points"])
        if callable(self.on_metrics_settings_changed):
            try:
                self.on_metrics_settings_changed("scale")
            except Exception:
                pass

        if result["fallback"]:
            messagebox.showwarning("Scale Refinement", "Low-confidence refinement; using selected endpoints.", parent=self.root)
        msg = f"Scale set to {result['px_per_mm']:.3f} px/mm"
        if result["refined_ok"]:
            msg += "\n(Refined from sampled intensity profile with sub-pixel edge fit.)"
        else:
            msg += "\n(Using raw click points; refinement fallback applied.)"
        msg += f"\n(Scale mode: {result['axis_mode']}.)"
        messagebox.showinfo("Scale Set", msg, parent=self.root)

    def start_roi_selection(self):
        frames_raw = self.get_frames_raw()
        if frames_raw is None:
            messagebox.showwarning("No Images", "Import images first.", parent=self.root)
            return
        img_u8 = self._get_first_frame_original_u8()
        if img_u8 is None:
            messagebox.showwarning("No Images", "Unable to read first frame.", parent=self.root)
            return

        result = open_roi_dialog(
            root=self.root,
            img_u8=img_u8,
            initial_roi_points=self.get_roi_points(),
        )
        if result is None:
            return

        self.set_roi_mask(result["roi_mask"])
        self.set_roi_points(result["roi_points"])
        self.update_display()
        if callable(self.on_metrics_settings_changed):
            try:
                self.on_metrics_settings_changed("roi")
            except Exception:
                pass
        messagebox.showinfo("ROI Set", "ROI polygon saved.", parent=self.root)
