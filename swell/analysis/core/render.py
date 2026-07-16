from collections import OrderedDict
import math
import time
import zlib

import cv2
import numpy as np
from PIL import Image, ImageTk

from swell.shared.image_overlay import apply_mask_overlay, frame_to_rgb_u8
from swell.analysis.core.viewport import compute_fit_scale
from swell.shared.ui.theme import APP_COLORS


CANVAS_FILL_RGB = (12, 16, 21)
CANVAS_FILL_HEX = APP_COLORS["canvas_bg"]

GHOST_CONTOUR_THICKNESS = 2


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

    def _segmentation_content_generation(self) -> int:
        return int(getattr(getattr(self, "seg_state", None), "content_generation", 0) or 0)

    def _mask_content_token(self, frame_idx: int, mask, *, prefix: str = "mask") -> tuple:
        source = np.asarray(mask)
        return (
            str(prefix),
            int(frame_idx),
            tuple(int(v) for v in source.shape),
            str(source.dtype),
            self._segmentation_content_generation(),
        )

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
                fill_value=CANVAS_FILL_RGB,
            )
            self.tk_img_left = ImageTk.PhotoImage(img_pil_left)
            self.canvas_left.delete("all")
            self.canvas_left.create_image(0, 0, image=self.tk_img_left, anchor="nw")
            self.canvas_left.create_text(12, 12, text="Preparing frames...", fill=APP_COLORS["warning"], anchor="nw")

            right_pil, _ = self._render_array_to_canvas_image(
                self.canvas_right,
                frame_to_rgb_u8(img_arr_gray),
                resample=Image.Resampling.LANCZOS,
                fill_value=CANVAS_FILL_RGB,
            )
            self.tk_img_right = ImageTk.PhotoImage(right_pil)
            self.canvas_right.delete("all")
            self.canvas_right.create_image(0, 0, image=self.tk_img_right, anchor="nw")
            self.canvas_right.create_text(12, 12, text="Preparing frames...", fill=APP_COLORS["warning"], anchor="nw")

            if preview_raw is not None:
                orig_h, orig_w = np.asarray(preview_raw).shape[:2]
                self._draw_overlay_elements(left_transform, np.asarray(preview_raw).shape)
            self.canvas_preview.delete("all")
            return

        for canvas in (self.canvas_left, self.canvas_right, self.canvas_preview):
            if canvas is None:
                continue
            canvas.delete("all")
            canvas.create_text(
                max(40, int(canvas.winfo_width()) // 2),
                max(40, int(canvas.winfo_height()) // 2),
                text="Preparing frames...",
                fill=APP_COLORS["muted"],
            )

    def _iter_reference_canvases(self):
        for name in ("canvas_right", "canvas_reference_popout"):
            canvas = getattr(self, name, None)
            if canvas is not None:
                yield canvas

    def _render_reference_canvas(self, canvas, idx: int, img_arr_gray, visual_token: tuple) -> None:
        img_arr_right = frame_to_rgb_u8(img_arr_gray)
        attr_name = "tk_img_reference_popout" if canvas is getattr(self, "canvas_reference_popout", None) else "tk_img_right"
        photo, _ = self._cached_canvas_photo(
            canvas,
            img_arr_right,
            resample=Image.Resampling.LANCZOS,
            fill_value=CANVAS_FILL_RGB,
            token=("reference", str(attr_name), int(idx), visual_token),
        )
        setattr(self, attr_name, photo)
        canvas.delete("all")
        canvas.create_image(0, 0, image=photo, anchor="nw")

    def _ghost_cache_entry(self, ghost_idx, ghost_mask, h, w):
        """Return cached {ring, bbox} for a ghost frame, computing on miss.

        The ghost outline is a band that sits entirely *outside* the mask: the
        mask is dilated by ``GHOST_CONTOUR_THICKNESS`` and the mask itself is
        subtracted, so the ring's inner edge is flush with the mask's outer
        edge (no overlap with the mask, no inset). ``ring`` is the boolean band
        cropped to ``bbox`` and ``bbox`` is its (y0, y1, x0, x1) extent, so the
        per-redraw blend runs cv2.addWeighted on just that ROI instead of the
        whole frame — keeping ghosts cheap to redraw while painting against them.
        """
        token = self._mask_content_token(ghost_idx, ghost_mask, prefix="ghost")
        key = (int(ghost_idx), token, (int(h), int(w)))
        entry = self._ghost_contours_cache.get(key)
        if entry is None:
            mask_bool = np.asarray(ghost_mask, dtype=bool)
            t = max(1, int(GHOST_CONTOUR_THICKNESS))
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * t + 1, 2 * t + 1))
            dilated = cv2.dilate(mask_bool.astype(np.uint8), kernel).astype(bool)
            ring = dilated & ~mask_bool
            bbox = None
            ring_sub = None
            ys, xs = np.where(ring)
            if ys.size:
                y0, y1 = int(ys.min()), int(ys.max()) + 1
                x0, x1 = int(xs.min()), int(xs.max()) + 1
                bbox = (y0, y1, x0, x1)
                ring_sub = ring[y0:y1, x0:x1]
            entry = {"ring": ring_sub, "bbox": bbox}
            self._ghost_contours_cache[key] = entry
        return token, entry

    def _draw_ghost_contour(self, img_arr, ghost_idx, color, alpha):
        """Alpha-blend one ghost frame's outside-edge outline into img_arr in place.

        Returns the (ghost_idx, content-token) pair used for display-cache
        invalidation; token is None when the ghost frame has no mask.
        """
        h, w = img_arr.shape[:2]
        ghost_mask = self.seg_state.compose_final_mask(ghost_idx, (h, w))
        if ghost_mask is None or not np.any(ghost_mask):
            return (int(ghost_idx), None)
        token, entry = self._ghost_cache_entry(ghost_idx, ghost_mask, h, w)
        bbox = entry["bbox"]
        ring = entry["ring"]
        if bbox is not None and ring is not None:
            y0, y1, x0, x1 = bbox
            roi = img_arr[y0:y1, x0:x1]
            overlay = roi.copy()
            overlay[ring] = color
            cv2.addWeighted(roi, 1.0 - alpha, overlay, alpha, 0, dst=roi)
        return (int(ghost_idx), token)

    def on_slider_move(self, val):
        raw_value = float(val)
        # A ttk.Scale is continuous, but the timeline represents discrete
        # frames.  Keep the thumb on the selected frame so it cannot drift
        # away from the integer-frame playhead while the user drags it.
        frame_idx = int(math.floor(raw_value + 0.5))
        if hasattr(self, "_get_frame_count"):
            frame_count = int(self._get_frame_count())
            if frame_count > 0:
                frame_idx = max(0, min(frame_idx, frame_count - 1))
        self.current_frame_idx = frame_idx
        if abs(raw_value - float(frame_idx)) > 1e-9 and hasattr(self, "slider"):
            # Updating the value option moves the thumb without recursively
            # invoking the scale command (which would render the frame twice).
            self.slider.configure(value=frame_idx)
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
        if hasattr(self, "_update_slider_playhead"):
            self._update_slider_playhead()

        img_arr_gray = self._get_visual_frame(idx) if hasattr(self, "_get_visual_frame") else None
        if img_arr_gray is None:
            self._draw_pending_frames_placeholder()
            return
        img_arr_gray = np.asarray(img_arr_gray, dtype=np.uint8)
        visual_token = self._array_content_token(img_arr_gray)
        img_arr = frame_to_rgb_u8(img_arr_gray)

        final_mask = self.seg_state.compose_final_mask(idx, img_arr.shape[:2])
        if final_mask is None:
            final_mask = np.zeros(img_arr.shape[:2], dtype=bool)

        if hasattr(self, "_refresh_ground_truth_controls"):
            self._refresh_ground_truth_controls(has_mask=bool(np.any(final_mask)))

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

        final_mask_any = bool(np.any(final_mask))
        final_mask_token = (
            self._mask_content_token(idx, final_mask, prefix="mask")
            if final_mask_any
            else ("mask-empty", int(idx), tuple(final_mask.shape), self._segmentation_content_generation())
        )
        mask_peek = bool(getattr(self, "_mask_peek", False))
        if final_mask_any and not mask_peek:
            img_arr = apply_mask_overlay(img_arr, final_mask)

        # Ghost outlines implementation
        ghost_enabled = False
        if getattr(self, "ghost_outlines_enabled_var", None) is not None and self.ghost_outlines_enabled_var.get():
            ghost_enabled = True

        ghost_tokens = []
        if ghost_enabled:
            n_frames = int(self.ghost_range_var.get()) if getattr(self, "ghost_range_var", None) is not None else 2
            if n_frames > 0:
                if not hasattr(self, "_ghost_contours_cache"):
                    self._ghost_contours_cache = {}
                if len(self._ghost_contours_cache) > 200:
                    self._ghost_contours_cache.clear()
                # Boolean indexing below writes into img_arr; ensure it is writable.
                if not img_arr.flags.writeable:
                    img_arr = img_arr.copy()

                for offset in range(n_frames, 0, -1):
                    alpha = max(0.1, 0.6 * (1.0 - (offset - 1) / n_frames))
                    past_idx = idx - offset
                    if past_idx >= 0:
                        ghost_tokens.append(self._draw_ghost_contour(img_arr, past_idx, (0, 191, 255), alpha))
                    future_idx = idx + offset
                    if future_idx < frame_count:
                        ghost_tokens.append(self._draw_ghost_contour(img_arr, future_idx, (255, 0, 128), alpha))

        left_resample = Image.Resampling.NEAREST if self.is_dragging and self.tool_mode.get() in ["brush", "eraser"] else Image.Resampling.LANCZOS
        self.tk_img_left, left_transform = self._cached_canvas_photo(
            self.canvas_left,
            img_arr,
            resample=left_resample,
            fill_value=CANVAS_FILL_RGB,
            # is_dragging/tool_mode only affect the resample method, which is
            # already part of the photo cache key; keeping them here would force
            # a cache miss on every tool switch.
            token=("left", int(idx), visual_token, final_mask_token, mask_peek, ghost_enabled, tuple(ghost_tokens)),
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

        if not self.is_dragging:
            for canvas in self._iter_reference_canvases():
                if self._canvas_is_visible(canvas):
                    self._render_reference_canvas(canvas, idx, img_arr_gray, visual_token)
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
                color = APP_COLORS["success"] if pt["label"] == 1 else APP_COLORS["danger"]

                is_selected = False
                if self.selected_point:
                    s_idx, s_pt_i = self.selected_point
                    if s_idx == idx and s_pt_i == pt_i:
                        is_selected = True

                if is_selected:
                    self.canvas_left.create_oval(cx - 5, cy - 5, cx + 5, cy + 5, fill=color, outline=APP_COLORS["measurement"], width=2)
                else:
                    self.canvas_left.create_oval(cx - 3, cy - 3, cx + 3, cy + 3, fill=color, outline=APP_COLORS["white"])

        boxes = getattr(self, "boxes", {}) or {}
        box = boxes.get(idx)
        if box is not None:
            try:
                x0, y0, x1, y1 = (float(v) for v in box)
            except (TypeError, ValueError):
                pass
            cx0, cy0 = transform.image_to_canvas(x0, y0)
            cx1, cy1 = transform.image_to_canvas(x1, y1)
            is_selected = False
            if self.selected_point:
                s_idx, s_kind = self.selected_point
                is_selected = s_idx == idx and s_kind == "box"
            self.canvas_left.create_rectangle(
                cx0,
                cy0,
                cx1,
                cy1,
                outline=APP_COLORS["measurement"] if is_selected else APP_COLORS["white"],
                width=3 if is_selected else 2,
            )
            if is_selected:
                handle_radius = 4
                mid_x = (cx0 + cx1) / 2.0
                mid_y = (cy0 + cy1) / 2.0
                handle_points = (
                    (cx0, cy0),
                    (mid_x, cy0),
                    (cx1, cy0),
                    (cx1, mid_y),
                    (cx1, cy1),
                    (mid_x, cy1),
                    (cx0, cy1),
                    (cx0, mid_y),
                )
                for hx, hy in handle_points:
                    self.canvas_left.create_rectangle(
                        hx - handle_radius,
                        hy - handle_radius,
                        hx + handle_radius,
                        hy + handle_radius,
                        fill=CANVAS_FILL_HEX,
                        outline=APP_COLORS["measurement"],
                        width=1,
                    )

        regions = list(getattr(self.seg_state, "persistent_regions", []) or [])
        selected_region_id = getattr(self, "selected_region_id", None)
        for region in regions:
            normalized = self.seg_state._normalize_persistent_region(region)
            if normalized is None or not bool(normalized.get("visible", True)):
                continue
            if not (int(normalized["frame_start"]) <= int(idx) <= int(normalized["frame_end"])):
                continue
            points = []
            for x, y in normalized.get("polygon") or []:
                cx, cy = transform.image_to_canvas(x, y)
                points.extend([cx, cy])
            if len(points) < 6:
                continue
            is_selected = str(normalized["id"]) == str(selected_region_id)
            if str(normalized.get("mode")) == "exclude":
                color = APP_COLORS["danger"]
            else:
                color = APP_COLORS["roi_active"] if is_selected else APP_COLORS["roi_inactive"]
            width = 3 if is_selected else 2
            self.canvas_left.create_line(*points, points[0], points[1], fill=color, width=width)
            if is_selected:
                handle_radius = 5
                for hx, hy in zip(points[0::2], points[1::2]):
                    self.canvas_left.create_oval(
                        hx - handle_radius,
                        hy - handle_radius,
                        hx + handle_radius,
                        hy + handle_radius,
                        fill=color,
                        outline=APP_COLORS["measurement"],
                        width=2,
                    )

        draft_points = []
        draft_closed = False
        draft_mode = "include"
        draft_selected_idx = None
        controller = getattr(self, "interaction_controller", None)
        if controller is not None and hasattr(controller, "get_region_draft_points"):
            draft_points = controller.get_region_draft_points()
            if hasattr(controller, "is_region_draft_closed"):
                draft_closed = bool(controller.is_region_draft_closed())
            if hasattr(controller, "get_region_draft_mode"):
                draft_mode = str(controller.get_region_draft_mode() or "include")
            if hasattr(controller, "get_region_draft_selected_idx"):
                draft_selected_idx = controller.get_region_draft_selected_idx()
        if draft_points:
            draft_color = APP_COLORS["danger"] if draft_mode == "exclude" else APP_COLORS["roi_active"]
            points = []
            for x, y in draft_points:
                cx, cy = transform.image_to_canvas(x, y)
                points.extend([cx, cy])
            if len(points) >= 4:
                line_points = list(points)
                if draft_closed and len(points) >= 6:
                    line_points.extend([points[0], points[1]])
                self.canvas_left.create_line(
                    *line_points,
                    fill=draft_color,
                    width=2,
                    dash=() if draft_closed else (3, 2),
                )
            for handle_idx, (hx, hy) in enumerate(zip(points[0::2], points[1::2])):
                # Every draft handle already carries the measurement outline, so
                # radius is the free channel for marking the selected one.
                selected = draft_selected_idx is not None and int(draft_selected_idx) == handle_idx
                radius = 7 if selected else 5
                self.canvas_left.create_oval(
                    hx - radius,
                    hy - radius,
                    hx + radius,
                    hy + radius,
                    fill=draft_color,
                    outline=APP_COLORS["measurement"],
                    width=3 if selected else 2,
                )

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
                self.canvas_right.create_line(*pts, fill=APP_COLORS["roi_active"], width=2)
            if len(pts) >= 6 and self.roi_mask is not None:
                self.canvas_right.create_line(*pts[:2], *pts[-2:], fill=APP_COLORS["roi_active"], width=2)
