import cv2
import numpy as np
import time
from PIL import Image, ImageTk


class RenderActions:
    def on_slider_move(self, val):
        self.current_frame_idx = int(float(val))
        self.update_display()
        if hasattr(self, "_mark_project_dirty"):
            self._mark_project_dirty("frame_change")

    def update_display(self, update_preview=True):
        t0 = time.perf_counter()
        if self.frames_sub_viz is None:
            return

        idx = self.current_frame_idx
        fname = self.frame_names[idx] if hasattr(self, "frame_names") and idx < len(self.frame_names) else ""
        display_idx = idx + 1
        display_total = len(self.frames_sub_viz)
        self.lbl_frame.configure(text=f"Frame: {display_idx} / {display_total}  [{fname}]")
        if hasattr(self, "slider_value"):
            self.slider_value.set(str(display_idx))

        img_arr_gray = self.frames_sub_viz[idx]
        img_arr = cv2.cvtColor(img_arr_gray, cv2.COLOR_GRAY2RGB)

        final_mask = None
        if idx in self.masks_cache and self.masks_cache[idx] is not None:
            final_mask = self.masks_cache[idx].astype(bool)
        else:
            final_mask = np.zeros(img_arr.shape[:2], dtype=bool)

        # Guard against stale mask sizes after re-import
        if final_mask.shape != img_arr.shape[:2]:
            self.log_warn(
                "Render",
                f"Mask shape mismatch for frame {idx + 1} ({final_mask.shape} vs {img_arr.shape[:2]}). Clearing.",
            )
            self.seg_state.clear_mask(idx)
            self.seg_state.clear_paint_layer(idx)
            self._recompute_slider_jump_markers()
            final_mask = np.zeros(img_arr.shape[:2], dtype=bool)

        if idx in self.paint_layers:
            plus = self.paint_layers[idx]["plus"]
            minus = self.paint_layers[idx]["minus"]
            if plus.shape != img_arr.shape[:2] or minus.shape != img_arr.shape[:2]:
                self.log_warn(
                    "Render",
                    f"Paint layer shape mismatch for frame {idx + 1} ({plus.shape} vs {img_arr.shape[:2]}). Clearing.",
                )
                self.seg_state.clear_paint_layer(idx)
                self._recompute_slider_jump_markers()
            else:
                final_mask = (final_mask | plus) & ~minus

        if np.any(final_mask):
            overlay = np.zeros_like(img_arr)
            overlay[final_mask] = [0, 255, 255]
            alpha = 0.3
            img_arr[final_mask] = (img_arr[final_mask] * (1 - alpha) + overlay[final_mask] * alpha).astype(
                np.uint8
            )

        img_pil_left = Image.fromarray(img_arr)

        w, h = self.canvas_left.winfo_width(), self.canvas_left.winfo_height()
        if w > 1 and h > 1:
            img_pil_left = self._resize_maintain_aspect(img_pil_left, w, h)

        self.tk_img_left = ImageTk.PhotoImage(img_pil_left)
        self.canvas_left.delete("all")
        self.canvas_left.create_image(w // 2, h // 2, image=self.tk_img_left, anchor="center")

        self._draw_brush_cursor_on_canvas()

        orig_h, orig_w = self.frames_raw[idx].shape[:2]
        ratio, offset_x, offset_y = self._get_display_transform(self.canvas_left, orig_w, orig_h)
        self._draw_overlay_elements(w, h, self.frames_raw[idx].shape, ratio, offset_x, offset_y)

        if update_preview:
            if np.any(final_mask):
                mask_uint8 = (final_mask * 255).astype(np.uint8)
                preview_pil = Image.fromarray(mask_uint8)

                pw = self.preview_frame.winfo_width() - 10
                ph = self.preview_frame.winfo_height() - 10
                if pw < 10 or ph < 10:
                    pw, ph = 140, 140

                p_ratio = min(pw / orig_w, ph / orig_h)
                new_w, new_h = int(orig_w * p_ratio), int(orig_h * p_ratio)

                preview_pil = preview_pil.resize((new_w, new_h), Image.Resampling.NEAREST)

                self.tk_preview = ImageTk.PhotoImage(preview_pil)
                self.canvas_preview.delete("all")
                self.canvas_preview.create_image(pw // 2 + 5, ph // 2 + 5, image=self.tk_preview, anchor="center")
            else:
                self.canvas_preview.delete("all")
                self.canvas_preview.create_text(70, 70, text="No Mask", fill="gray")

        if not self.is_dragging:
            img_arr_right = cv2.cvtColor(self.frames_sub_viz[idx], cv2.COLOR_GRAY2RGB)
            img_pil_right = Image.fromarray(img_arr_right)
            if w > 1 and h > 1:
                img_pil_right = self._resize_maintain_aspect(
                    img_pil_right, self.canvas_right.winfo_width(), self.canvas_right.winfo_height()
                )
            self.tk_img_right = ImageTk.PhotoImage(img_pil_right)
            self.canvas_right.delete("all")
            rw = self.canvas_right.winfo_width()
            rh = self.canvas_right.winfo_height()
            self.canvas_right.create_image(rw // 2, rh // 2, image=self.tk_img_right, anchor="center")
            self._draw_analysis_overlay_on_right(idx)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        self.log_debug("Perf", f"Display redraw elapsed={elapsed_ms:.2f}ms")

    def _get_display_transform(self, canvas, img_w, img_h):
        canvas_w = canvas.winfo_width()
        canvas_h = canvas.winfo_height()
        ratio = min(canvas_w / img_w, canvas_h / img_h)
        offset_x = (canvas_w - int(img_w * ratio)) // 2
        offset_y = (canvas_h - int(img_h * ratio)) // 2
        return ratio, offset_x, offset_y

    def _resize_maintain_aspect(self, pil_img, max_w, max_h):
        orig_w, orig_h = pil_img.size
        # Keep fit-to-canvas behavior but avoid aggressive upscaling on small images.
        self.display_ratio = min(max_w / orig_w, max_h / orig_h, 1.0)

        mode = self.tool_mode.get()
        use_nearest = self.is_dragging and mode in ["brush", "eraser"]
        method = Image.Resampling.NEAREST if use_nearest else Image.Resampling.LANCZOS

        return pil_img.resize((int(orig_w * self.display_ratio), int(orig_h * self.display_ratio)), method)

    def _draw_overlay_elements(self, canvas_w, canvas_h, img_shape, ratio, offset_x, offset_y):
        idx = self.current_frame_idx

        if idx in self.points:
            for pt_i, pt in enumerate(self.points[idx]):
                cx = int(pt["x"] * ratio + offset_x)
                cy = int(pt["y"] * ratio + offset_y)
                color = "#00FF00" if pt["label"] == 1 else "#FF0000"

                is_selected = False
                if self.selected_point:
                    s_idx, s_pt_i = self.selected_point
                    if s_idx == idx and s_pt_i == pt_i:
                        is_selected = True

                if is_selected:
                    self.canvas_left.create_oval(cx - 5, cy - 5, cx + 5, cy + 5, fill=color, outline="yellow", width=2)
                else:
                    self.canvas_left.create_oval(cx - 3, cy - 3, cx + 3, cy + 3, fill=color, outline="white")

    def _draw_analysis_overlay_on_right(self, idx):
        if self.frames_raw is None:
            return
        h, w = self.frames_raw[idx].shape[:2]
        ratio, offset_x, offset_y = self._get_display_transform(self.canvas_right, w, h)

        if hasattr(self, "roi_points") and self.roi_points:
            pts = []
            for x, y in self.roi_points:
                pts.extend([x * ratio + offset_x, y * ratio + offset_y])
            if len(pts) >= 4:
                self.canvas_right.create_line(*pts, fill="#00ff66", width=2)
            if len(pts) >= 6 and self.roi_mask is not None:
                self.canvas_right.create_line(*pts[:2], *pts[-2:], fill="#00ff66", width=2)
