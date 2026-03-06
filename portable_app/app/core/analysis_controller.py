import os

import cv2
import numpy as np
import pandas as pd
from scipy.ndimage import map_coordinates
from tkinter import filedialog, messagebox

from app.core.metrics import (
    compute_frame_metrics,
    compute_roi_metrics,
    compute_scale,
    extract_primary_boundary,
    generate_metrics_plots,
    smooth_boundary_fft,
    write_metrics_outputs,
)
from app.ui.roi_dialog import open_roi_dialog
from app.ui.scale_dialog import open_scale_dialog
from app.utils.paths import resolve_existing_directory


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
        get_output_folder,
        get_export_range,
        get_seconds_per_frame,
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
        get_analysis_range,
        update_display,
        log_info,
        log_success,
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
        self.get_output_folder = get_output_folder
        self.get_export_range = get_export_range
        self.get_analysis_range = get_analysis_range
        self.get_seconds_per_frame = get_seconds_per_frame
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

    def _default_analysis_range(self):
        frames_raw = self.get_frames_raw()
        frame_count = len(frames_raw) if frames_raw is not None else 0
        if frame_count <= 0:
            return 0, -1
        return 0, frame_count - 1

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
            messagebox.showwarning("No Images", "Import images first.")
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
            messagebox.showwarning("Image Error", "Unable to read selected image for scale calibration.")
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

        if result["fallback"]:
            messagebox.showwarning("Scale Refinement", "Low-confidence refinement; using selected endpoints.")
        msg = f"Scale set to {result['px_per_mm']:.3f} px/mm"
        if result["refined_ok"]:
            msg += "\n(Refined from sampled intensity profile with sub-pixel edge fit.)"
        else:
            msg += "\n(Using raw click points; refinement fallback applied.)"
        msg += f"\n(Scale mode: {result['axis_mode']}.)"
        messagebox.showinfo("Scale Set", msg)

    def start_roi_selection(self):
        frames_raw = self.get_frames_raw()
        if frames_raw is None:
            messagebox.showwarning("No Images", "Import images first.")
            return
        img_u8 = self._get_first_frame_original_u8()
        if img_u8 is None:
            messagebox.showwarning("No Images", "Unable to read first frame.")
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
        messagebox.showinfo("ROI Set", "ROI polygon saved.")

    def run_metrics_analysis(self):
        frames_raw = self.get_frames_raw()
        masks_cache = self.get_masks_cache()
        paint_layers = self.get_paint_layers()
        points = self.get_points()
        roi_mask = self.get_roi_mask()
        scale_px_per_mm = self.get_scale_px_per_mm()

        if frames_raw is None:
            messagebox.showwarning("No Images", "Import images first.")
            return
        if scale_px_per_mm is None:
            messagebox.showwarning("Missing Scale", "Set scale before running metrics.")
            return
        if roi_mask is None:
            messagebox.showwarning("Missing ROI", "Draw ROI before running metrics.")
            return

        total_frames = len(frames_raw)
        try:
            analysis_start, analysis_end = self.get_analysis_range()
        except Exception:
            analysis_start, analysis_end = 0, total_frames - 1
        analysis_start = max(0, min(int(analysis_start), total_frames - 1))
        analysis_end = max(0, min(int(analysis_end), total_frames - 1))

        try:
            sec_per_frame = self.get_seconds_per_frame()
            if sec_per_frame <= 0:
                raise ValueError("Seconds/frame must be > 0")
        except (TypeError, ValueError):
            messagebox.showwarning("Invalid Input", "Seconds/frame must be a positive number.")
            return

        selected_frame_indices = sorted(
            frame_idx
            for frame_idx in self.get_nonempty_final_mask_frames()
            if analysis_start <= frame_idx <= analysis_end
        )

        if not selected_frame_indices:
            messagebox.showwarning("No Masks", "No generated masks found in selected analysis range.")
            return

        has_propagated_mask_in_range = False
        for frame_idx in selected_frame_indices:
            if frame_idx not in masks_cache:
                continue
            mask_val = masks_cache.get(frame_idx)
            if mask_val is None or not np.any(mask_val):
                continue
            has_direct_input = False
            if frame_idx in points and points[frame_idx]:
                has_direct_input = True
            if frame_idx in paint_layers:
                layer = paint_layers[frame_idx]
                if np.any(layer["plus"]) or np.any(layer["minus"]):
                    has_direct_input = True
            if not has_direct_input:
                has_propagated_mask_in_range = True
                break

        if not has_propagated_mask_in_range:
            proceed_without_propagation = messagebox.askyesno(
                "No Propagated Masks Detected",
                "No propagated masks were found in the selected range.\n\n"
                "You can continue and compute metrics from currently available masks, "
                "or cancel and run propagation first.\n\n"
                "Continue anyway?",
            )
            if not proceed_without_propagation:
                return

        start_idx = selected_frame_indices[0]
        end_idx = selected_frame_indices[-1]
        self.log_info(
            "Metrics",
            f"Started metrics analysis for {len(selected_frame_indices)} generated-mask frames "
            f"(span {start_idx + 1}-{end_idx + 1}).",
        )

        boundaries = []
        frame_rows = []
        for frame_idx in selected_frame_indices:
            mask = self.get_compose_final_mask_for_frame(frame_idx)
            if mask is None:
                mask = np.zeros_like(frames_raw[0], dtype=bool)
            # Restrict all downstream metrics (area + speed) to the selected ROI only.
            mask = mask & roi_mask
            boundary = extract_primary_boundary(mask)
            if boundary is not None:
                boundary = smooth_boundary_fft(boundary, n_keep=25)
            boundaries.append(boundary)
            frame_rows.append(frame_idx)

        valid_boundaries = sum(1 for b in boundaries if b is not None)
        if valid_boundaries < 2:
            messagebox.showwarning("Not Enough Data", "Need at least 2 frames with masks in selected range.")
            return

        frame_metrics = compute_frame_metrics(boundaries, min_dist_px=2.0)
        roi_metrics = compute_roi_metrics(
            roi_mask,
            frame_metrics["areas_px"],
            frame_metrics["avg_dist_px"],
            scale_px_per_mm,
            sec_per_frame,
        )

        area_mm2 = roi_metrics["area_mm2"]
        speed_um_per_sec = roi_metrics["speed_um_per_sec"]
        rel_area_pct = (
            (frame_metrics["areas_px"] / roi_metrics["roi_pixels"] * 100.0)
            if roi_metrics["roi_pixels"] > 0
            else np.full_like(frame_metrics["areas_px"], np.nan)
        )

        frame_df = pd.DataFrame(
            {
                "frame_index": frame_rows,
                "frame_display": [f + 1 for f in frame_rows],
                "time_sec": [(f - start_idx) * sec_per_frame for f in frame_rows],
                "area_px": frame_metrics["areas_px"],
                "area_mm2": area_mm2,
                "avg_dist_px": frame_metrics["avg_dist_px"],
                "speed_um_per_sec": speed_um_per_sec,
                "relative_area_pct": rel_area_pct,
            }
        )

        summary = {
            "overall_avg_speed_um_per_sec": roi_metrics["overall_avg_speed_um_per_sec"],
            "max_area_mm2": roi_metrics["max_area_mm2"],
            "relative_area_pct": roi_metrics["relative_area_pct"],
            "roi_area_mm2": roi_metrics["roi_area_mm2"],
            "roi_pixels": roi_metrics["roi_pixels"],
            "px_per_mm": roi_metrics["px_per_mm"],
            "um_per_px": roi_metrics["um_per_px"],
            "mm_per_px": roi_metrics["mm_per_px"],
            "sec_per_frame": roi_metrics["sec_per_frame"],
            "range_start_frame": start_idx + 1,
            "range_end_frame": end_idx + 1,
        }

        output_folder = self.get_output_folder()
        if output_folder and not os.path.isabs(output_folder):
            output_folder = os.path.join(self.app_root, output_folder)
        analysis_dir = os.path.join(output_folder, "metrics_analysis")
        write_metrics_outputs(analysis_dir, frame_df, summary)
        generate_metrics_plots(analysis_dir, frame_df, summary)
        self.log_success(
            "Metrics",
            (
                f"Completed metrics analysis ({len(selected_frame_indices)} generated-mask frames, "
                f"{valid_boundaries} valid boundaries). Output: {analysis_dir}"
            ),
        )
        messagebox.showinfo("Metrics Complete", f"Saved metrics analysis to:\n{analysis_dir}")
