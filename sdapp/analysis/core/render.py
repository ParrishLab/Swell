from collections import OrderedDict
import cv2
import numpy as np
import time
from PIL import Image, ImageTk
import zlib

from sdapp.shared.image_overlay import apply_mask_overlay, frame_to_rgb_u8
from sdapp.analysis.core.viewport import compute_fit_scale


class RenderActions:
    _DISPLAY_PHOTO_CACHE_MAX = 12

    def _compute_display_ratio(self, max_w, max_h, orig_w, orig_h):
        return compute_fit_scale(max_w, max_h, orig_w, orig_h)

    def _transform_resample(self, resample):
        if resample in (Image.Resampling.NEAREST, Image.Resampling.BILINEAR, Image.Resampling.BICUBIC):
            return resample
        return Image.Resampling.BICUBIC

    def _render_array_to_canvas_image(self, canvas, img_arr, *, resample, fill_value):
        canvas_w = max(1, int(canvas.winfo_width()))
        canvas_h = max(1, int(canvas.winfo_height()))
        src = np.asarray(img_arr, dtype=np.uint8)
        src_h, src_w = src.shape[:2]
        transform = self._get_canvas_viewport_transform(canvas, src_w, src_h)
        pil_src = Image.fromarray(src)
        fillcolor = fill_value if pil_src.mode == "L" else tuple(int(v) for v in fill_value)
        pil_canvas = pil_src.transform(
            (canvas_w, canvas_h),
            Image.Transform.AFFINE,
            data=(
                1.0 / float(transform.scale),
                0.0,
                -float(transform.offset_x) / float(transform.scale),
                0.0,
                1.0 / float(transform.scale),
                -float(transform.offset_y) / float(transform.scale),
            ),
            resample=self._transform_resample(resample),
            fillcolor=fillcolor,
        )
        return pil_canvas, transform

    def _array_content_token(self, arr) -> tuple:
        source = np.asarray(arr)
        if source.size == 0:
            return tuple(source.shape), str(source.dtype), 0
        contiguous = np.ascontiguousarray(source)
        return tuple(int(v) for v in contiguous.shape), str(contiguous.dtype), int(zlib.crc32(contiguous))

    def _canvas_is_visible(self, canvas) -> bool:
        checker = getattr(canvas, "winfo_ismapped", None)
        if not callable(checker):
            return True
        try:
            return bool(checker())
        except Exception:
            return True

    def _display_photo_cache(self) -> OrderedDict:
        cache = getattr(self, "_display_photo_cache_store", None)
        if isinstance(cache, OrderedDict):
            return cache
        cache = OrderedDict()
        self._display_photo_cache_store = cache
        return cache

    def _cache_photo(self, key: tuple, image: ImageTk.PhotoImage) -> None:
        cache = self._display_photo_cache()
        cache[key] = image
        cache.move_to_end(key)
        while len(cache) > int(self._DISPLAY_PHOTO_CACHE_MAX):
            cache.popitem(last=False)

    def _cached_canvas_photo(self, canvas, img_arr, *, resample, fill_value, token: tuple):
        src = np.asarray(img_arr, dtype=np.uint8)
        src_h, src_w = src.shape[:2]
        transform = self._get_canvas_viewport_transform(canvas, src_w, src_h)
        fill_key = fill_value if isinstance(fill_value, (int, float, str)) else tuple(int(v) for v in fill_value)
        key = (
            int(canvas.winfo_width()),
            int(canvas.winfo_height()),
            int(src_w),
            int(src_h),
            round(float(transform.scale), 8),
            round(float(transform.offset_x), 4),
            round(float(transform.offset_y), 4),
            int(self._transform_resample(resample)),
            fill_key,
            tuple(token),
        )
        cache = self._display_photo_cache()
        cached = cache.get(key)
        if cached is not None:
            cache.move_to_end(key)
            return cached, transform
        pil_img, rendered_transform = self._render_array_to_canvas_image(
            canvas,
            src,
            resample=resample,
            fill_value=fill_value,
        )
        photo = ImageTk.PhotoImage(pil_img)
        self._cache_photo(key, photo)
        return photo, rendered_transform

    def _draw_pending_frames_placeholder(self) -> None:
        total = int(self._get_frame_count()) if hasattr(self, "_get_frame_count") else 0
        idx = max(0, min(int(getattr(self, "current_frame_idx", 0)), max(0, total - 1)))
        if hasattr(self, "frame_status_var"):
            self.frame_status_var.set(f"Frame {idx + 1} / {max(1, total)}")
        if hasattr(self, "frame_meta_var"):
            self.frame_meta_var.set("Preparing frames…")
        if hasattr(self, "slider_value"):
            self.slider_value.set(str(idx + 1))

        preview = dict(getattr(self, "_host_launch_preparation", {}) or {})
        preview_idx = preview.get("local_frame_idx")
        preview_viz = preview.get("viz_frame")
        preview_raw = preview.get("raw_frame")
        if preview_viz is not None and preview_idx is not None and int(preview_idx) == idx:
            img_arr_gray = np.asarray(preview_viz, dtype=np.uint8)
            img_arr = frame_to_rgb_u8(img_arr_gray)
            img_pil_left, left_transform = self._render_array_to_canvas_image(
                self.canvas_left,
                img_arr,
                resample=Image.Resampling.LANCZOS,
                fill_value=(241, 241, 241),
            )
            self.tk_img_left = ImageTk.PhotoImage(img_pil_left)
            self.canvas_left.delete("all")
            self.canvas_left.create_image(0, 0, image=self.tk_img_left, anchor="nw")
            self.canvas_left.create_text(12, 12, text="Preparing frames...", fill="orange", anchor="nw")

            right_pil, _ = self._render_array_to_canvas_image(
                self.canvas_right,
                frame_to_rgb_u8(img_arr_gray),
                resample=Image.Resampling.LANCZOS,
                fill_value=(241, 241, 241),
            )
            self.tk_img_right = ImageTk.PhotoImage(right_pil)
            self.canvas_right.delete("all")
            self.canvas_right.create_image(0, 0, image=self.tk_img_right, anchor="nw")
            self.canvas_right.create_text(12, 12, text="Preparing frames...", fill="orange", anchor="nw")

            if preview_raw is not None:
                orig_h, orig_w = np.asarray(preview_raw).shape[:2]
                self._draw_overlay_elements(left_transform, np.asarray(preview_raw).shape)
            self.canvas_preview.delete("all")
            return

        for canvas in (self.canvas_left, self.canvas_right, self.canvas_preview):
            canvas.delete("all")
            canvas.create_text(
                max(40, int(canvas.winfo_width()) // 2),
                max(40, int(canvas.winfo_height()) // 2),
                text="Preparing frames...",
                fill="gray",
            )

    def on_slider_move(self, val):
        self.current_frame_idx = int(float(val))
        self.update_display()
        if hasattr(self, "_schedule_analysis_prewarm"):
            self._schedule_analysis_prewarm(self.current_frame_idx)
        if getattr(self, "_initial_frame_nav_ts", None) is not None:
            elapsed_ms = (time.perf_counter() - float(self._initial_frame_nav_ts)) * 1000.0
            self.log_debug("Perf", f"First-frame navigation elapsed={elapsed_ms:.1f}ms")
            self._initial_frame_nav_ts = None

    def update_display(self, update_preview=True):
        t0 = time.perf_counter()
        frame_count = int(self._get_frame_count()) if hasattr(self, "_get_frame_count") else 0
        if frame_count <= 0:
            self._draw_pending_frames_placeholder()
            return

        idx = max(0, min(int(self.current_frame_idx), max(0, frame_count - 1)))
        fname = self.frame_names[idx] if hasattr(self, "frame_names") and idx < len(self.frame_names) else ""
        display_idx = idx + 1
        display_total = frame_count
        if hasattr(self, "frame_status_var"):
            self.frame_status_var.set(f"Frame {display_idx} / {display_total}")
        if hasattr(self, "frame_meta_var"):
            self.frame_meta_var.set(fname or "No file loaded")
        if hasattr(self, "slider_value"):
            self.slider_value.set(str(display_idx))

        img_arr_gray = self._get_visual_frame(idx) if hasattr(self, "_get_visual_frame") else None
        if img_arr_gray is None:
            self._draw_pending_frames_placeholder()
            return
        img_arr_gray = np.asarray(img_arr_gray, dtype=np.uint8)
        visual_token = self._array_content_token(img_arr_gray)
        img_arr = frame_to_rgb_u8(img_arr_gray)

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

        final_mask_any = bool(np.any(final_mask))
        final_mask_token = ("mask",) + self._array_content_token(final_mask) if final_mask_any else ("mask-empty", tuple(final_mask.shape))
        if final_mask_any:
            img_arr = apply_mask_overlay(img_arr, final_mask)

        left_resample = Image.Resampling.NEAREST if self.is_dragging and self.tool_mode.get() in ["brush", "eraser"] else Image.Resampling.LANCZOS
        self.tk_img_left, left_transform = self._cached_canvas_photo(
            self.canvas_left,
            img_arr,
            resample=left_resample,
            fill_value=(241, 241, 241),
            token=("left", int(idx), visual_token, final_mask_token, bool(self.is_dragging), str(self.tool_mode.get())),
        )
        self.canvas_left.delete("all")
        self.canvas_left.create_image(0, 0, image=self.tk_img_left, anchor="nw")

        self._draw_brush_cursor_on_canvas()

        raw_frame = self._get_raw_frame(idx) if hasattr(self, "_get_raw_frame") else None
        if raw_frame is None:
            raw_shape = tuple(int(v) for v in img_arr_gray.shape[:2])
        else:
            raw_shape = tuple(int(v) for v in np.asarray(raw_frame).shape[:2])
        self._draw_overlay_elements(left_transform, raw_shape)

        if update_preview and self._canvas_is_visible(self.canvas_preview):
            if final_mask_any:
                mask_uint8 = (final_mask * 255).astype(np.uint8)
                self.tk_preview, _ = self._cached_canvas_photo(
                    self.canvas_preview,
                    mask_uint8,
                    resample=Image.Resampling.NEAREST,
                    fill_value=0,
                    token=("preview", int(idx), final_mask_token),
                )
                self.canvas_preview.delete("all")
                self.canvas_preview.create_image(0, 0, image=self.tk_preview, anchor="nw")
            else:
                self.canvas_preview.delete("all")

        if not self.is_dragging and self._canvas_is_visible(self.canvas_right):
            img_arr_right = frame_to_rgb_u8(img_arr_gray)
            self.tk_img_right, _ = self._cached_canvas_photo(
                self.canvas_right,
                img_arr_right,
                resample=Image.Resampling.LANCZOS,
                fill_value=(241, 241, 241),
                token=("right", int(idx), visual_token),
            )
            self.canvas_right.delete("all")
            self.canvas_right.create_image(0, 0, image=self.tk_img_right, anchor="nw")
            self._draw_analysis_overlay_on_right(idx)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        self.log_debug("Perf", f"Display redraw elapsed={elapsed_ms:.2f}ms")

    def _get_display_transform(self, canvas, img_w, img_h):
        if hasattr(self, "_get_canvas_viewport_transform"):
            transform = self._get_canvas_viewport_transform(canvas, img_w, img_h)
            return transform.scale, transform.offset_x, transform.offset_y
        canvas_w = canvas.winfo_width()
        canvas_h = canvas.winfo_height()
        ratio = self._compute_display_ratio(canvas_w, canvas_h, img_w, img_h)
        offset_x = (canvas_w - int(img_w * ratio)) // 2
        offset_y = (canvas_h - int(img_h * ratio)) // 2
        return ratio, offset_x, offset_y

    def _resize_maintain_aspect(self, pil_img, max_w, max_h):
        orig_w, orig_h = pil_img.size
        # Keep fit-to-canvas behavior but avoid aggressive upscaling on small images.
        self.display_ratio = self._compute_display_ratio(max_w, max_h, orig_w, orig_h)

        mode = self.tool_mode.get()
        use_nearest = self.is_dragging and mode in ["brush", "eraser"]
        method = Image.Resampling.NEAREST if use_nearest else Image.Resampling.LANCZOS

        return pil_img.resize((int(orig_w * self.display_ratio), int(orig_h * self.display_ratio)), method)

    def _draw_overlay_elements(self, transform, img_shape):
        idx = self.current_frame_idx

        if idx in self.points:
            for pt_i, pt in enumerate(self.points[idx]):
                cx, cy = transform.image_to_canvas(pt["x"], pt["y"])
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
        raw_frame = self._get_raw_frame(idx) if hasattr(self, "_get_raw_frame") else None
        if raw_frame is None:
            return
        h, w = np.asarray(raw_frame).shape[:2]
        transform = self._get_canvas_viewport_transform(self.canvas_right, w, h)

        roi_polygons = getattr(self, "roi_polygons", None)
        polygons = roi_polygons if isinstance(roi_polygons, list) and roi_polygons else []
        if not polygons and hasattr(self, "roi_points") and self.roi_points:
            polygons = [self.roi_points]
        for polygon in polygons:
            pts = []
            for x, y in polygon:
                cx, cy = transform.image_to_canvas(x, y)
                pts.extend([cx, cy])
            if len(pts) >= 4:
                self.canvas_right.create_line(*pts, fill="#00ff66", width=2)
            if len(pts) >= 6 and self.roi_mask is not None:
                self.canvas_right.create_line(*pts[:2], *pts[-2:], fill="#00ff66", width=2)
