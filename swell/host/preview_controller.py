from __future__ import annotations

from collections import OrderedDict
from collections.abc import MutableMapping

import numpy as np
from PIL import Image, ImageTk
import tkinter as tk
from tkinter import ttk

from swell.host.controllers import HostWindowController
from swell.host.ui_geometry import linear_value_to_x, linear_x_to_value, normalize_overlay_bounds
from swell.shared.frame_source import normalize_visual_frame
from swell.shared.frame_source.preprocessing import _sample_percentile_pixels, finite_percentile_bounds
from swell.shared.ui.theme import APP_COLORS


class HostPreviewController:
    def __init__(self, app) -> None:
        self.app = app

    def apply_live_frame_position(self, idx: int) -> None:
        stack_info = getattr(self.app, "stack_info", None)
        if stack_info is None:
            return
        frame_count = int(getattr(stack_info, "frame_count", 0) or 0)
        if frame_count <= 0:
            return
        frame_idx = max(0, min(int(idx), frame_count - 1))
        self.app.current_frame_idx = frame_idx
        self.redraw_main_overlay()
        self.app.dc_trace_controller.update_for_frame(frame_idx)

    def schedule_main_preview_update(self, idx: int) -> None:
        frame_idx = int(idx)
        self.app._pending_main_frame_idx = frame_idx
        self.apply_live_frame_position(frame_idx)
        pending_after_id = getattr(self.app, "_pending_main_after_id", None)
        if pending_after_id is not None:
            try:
                self.app.root.after_cancel(pending_after_id)
            except Exception:
                pass
        self.app._pending_main_after_id = self.app.root.after(16, self.flush_main_preview_update)

    def flush_main_preview_update(self) -> None:
        self.app._pending_main_after_id = None
        if self.app._pending_main_frame_idx is None:
            return
        idx = int(self.app._pending_main_frame_idx)
        self.app._pending_main_frame_idx = None
        self.update_preview(idx)

    def _normalized_frame_cache(self) -> MutableMapping:
        cache = getattr(self.app, "_normalized_frame_u8_cache", None)
        if isinstance(cache, MutableMapping):
            return cache
        cache = OrderedDict()
        self.app._normalized_frame_u8_cache = cache
        return cache

    @staticmethod
    def _promote_cached(cache: MutableMapping, key):
        promote = getattr(cache, "promote", None)
        if callable(promote):
            return promote(key)
        value = cache.get(key)
        move_to_end = getattr(cache, "move_to_end", None)
        if callable(move_to_end):
            move_to_end(key)
        return value

    @staticmethod
    def normalized_cache_key(frame_idx: int, contrast_mode: str = "default") -> tuple[int, str]:
        return int(frame_idx), str(contrast_mode or "default")

    def _cache_normalized_frame(self, key: tuple[int, str], frame_u8: np.ndarray) -> None:
        cache = self._normalized_frame_cache()
        cache[key] = frame_u8  # LRUCache auto-promotes and evicts

    def normalize_frame_percentile(self, frame: np.ndarray, cache_key: tuple[int, str] | None = None) -> np.ndarray:
        if cache_key is not None:
            cache = self._normalized_frame_cache()
            cached = cache.get(cache_key)
            if cached is not None:
                return self._promote_cached(cache, cache_key)
        sample = _sample_percentile_pixels(frame)
        p1, p99 = finite_percentile_bounds(sample, max_pixels=max(1, int(sample.size)))
        frame_u8 = normalize_visual_frame(frame, p1=p1, p99=p99)
        if cache_key is not None:
            self._cache_normalized_frame(cache_key, frame_u8)
        return frame_u8

    def get_normalized_reader_frame(self, frame_idx: int, *, contrast_mode: str = "default") -> np.ndarray:
        if self.app.reader is None:
            raise RuntimeError("Stack not loaded.")
        cache_key = self.normalized_cache_key(frame_idx, contrast_mode=contrast_mode)
        cache = self._normalized_frame_cache()
        cached = cache.get(cache_key)
        if cached is not None:
            return self._promote_cached(cache, cache_key)
        raw = self.app.reader.read_frame(int(frame_idx), use_cache=True)
        return self.normalize_frame_percentile(raw, cache_key=cache_key)

    @staticmethod
    def apply_display_contrast(frame_u8: np.ndarray, factor: float) -> np.ndarray:
        if factor <= 0:
            return frame_u8
        adjusted = (frame_u8.astype(np.float32) - 127.5) * factor + 127.5
        return np.clip(adjusted, 0.0, 255.0).astype(np.uint8)

    def render_preview_image(
        self,
        frame: np.ndarray,
        label: ttk.Label,
        fallback_size: tuple[int, int],
        pre_normalized: bool = False,
        contrast_factor: float = 1.0,
    ) -> ImageTk.PhotoImage:
        if pre_normalized and frame.dtype == np.uint8:
            frame_u8 = frame
        else:
            frame_u8 = self.normalize_frame_percentile(frame)
        if abs(contrast_factor - 1.0) > 1e-6:
            frame_u8 = self.apply_display_contrast(frame_u8, contrast_factor)

        img = Image.fromarray(frame_u8)
        max_w = label.winfo_width() - 12
        max_h = label.winfo_height() - 12
        if max_w < 120 or max_h < 120:
            max_w, max_h = fallback_size
        img.thumbnail((max_w, max_h), Image.Resampling.BILINEAR)
        return ImageTk.PhotoImage(img)

    def cache_main_render(self, key: tuple[int, int, int], image: ImageTk.PhotoImage) -> None:
        self.app._main_render_cache[key] = image  # LRUCache auto-promotes and evicts

    def update_preview(self, frame_idx: int) -> None:
        if self.app.reader is None or self.app.stack_info is None:
            return
        frame_idx = max(0, min(frame_idx, self.app.stack_info.frame_count - 1))
        self.apply_live_frame_position(frame_idx)
        max_w = self.app.preview_label.winfo_width() - 12
        max_h = self.app.preview_label.winfo_height() - 12
        if max_w < 120 or max_h < 120:
            max_w, max_h = (1100, 800)
        cache_key = (int(frame_idx), int(max_w), int(max_h))
        cache = self.app._main_render_cache
        image = cache.get(cache_key)
        if image is not None:
            image = self._promote_cached(cache, cache_key)
        else:
            try:
                frame = self.get_normalized_reader_frame(frame_idx)
                image = self.render_preview_image(
                    frame,
                    self.app.preview_label,
                    fallback_size=(1100, 800),
                    pre_normalized=True,
                    contrast_factor=1.0,
                )
                self.cache_main_render(cache_key, image)
                setattr(self.app, "_preview_decode_error_shown", False)
            except Exception as exc:
                project_controller = getattr(self.app, "_get_project_controller", lambda: None)()
                ensure_stack = getattr(project_controller, "ensure_active_stack_available", None)
                if callable(ensure_stack) and bool(ensure_stack(title="Preview Load")):
                    try:
                        frame = self.get_normalized_reader_frame(frame_idx)
                        image = self.render_preview_image(
                            frame,
                            self.app.preview_label,
                            fallback_size=(1100, 800),
                            pre_normalized=True,
                            contrast_factor=1.0,
                        )
                        self.cache_main_render(cache_key, image)
                        setattr(self.app, "_preview_decode_error_shown", False)
                    except Exception as retry_exc:
                        exc = retry_exc
                    else:
                        self.app.tk_preview_image = image
                        self.app.preview_label.configure(image=image)
                        frame_name = self.app.reader.get_frame_name(frame_idx)
                        self.app.preview_label_info.set(f"Frame {frame_idx + 1}")
                        self.app.preview_label_meta.set(str(frame_name or "No file loaded"))
                        return
                self.app._set_status("Preview load failed.")
                self.app._log_error(f"Preview decode failed for frame {frame_idx}: {exc}")
                if not bool(getattr(self.app, "_preview_decode_error_shown", False)):
                    self.app._preview_decode_error_shown = True
                    self.app._show_warning(
                        "Preview Decode Error",
                        (
                            "Unable to decode one or more stack frames. "
                            "If this is a compressed TIFF stack, required codecs may be missing in this build."
                            f"\n\nDetails: {exc}"
                        ),
                    )
                return
        self.app.tk_preview_image = image
        self.app.preview_label.configure(image=image)

        frame_name = self.app.reader.get_frame_name(frame_idx)
        self.app.preview_label_info.set(f"Frame {frame_idx + 1}")
        self.app.preview_label_meta.set(str(frame_name or "No file loaded"))

    def scale_value_to_x(
        self,
        scale: tk.Scale | None,
        canvas: tk.Canvas | None,
        value: int,
        start_idx: int,
        end_idx: int,
        width: float,
    ) -> float:
        if scale is not None and canvas is not None:
            try:
                sx, _sy = scale.coords(value)
                x_abs = scale.winfo_rootx() + float(sx)
                cx_abs = canvas.winfo_rootx()
                x_canvas = x_abs - cx_abs
                if 0.0 <= x_canvas <= float(width):
                    return x_canvas
            except Exception:
                pass
        return linear_value_to_x(value, start_idx, end_idx, width)

    def scale_x_to_value(
        self,
        scale: tk.Scale | None,
        canvas: tk.Canvas | None,
        x_px: float,
        start_idx: int,
        end_idx: int,
        width: float,
    ) -> int:
        if scale is not None and canvas is not None:
            try:
                x_abs = canvas.winfo_rootx() + float(x_px)
                sx = x_abs - scale.winfo_rootx()
                low_x, _ = scale.coords(start_idx)
                high_x, _ = scale.coords(end_idx)
                left = float(min(low_x, high_x))
                right = float(max(low_x, high_x))
                if right > left:
                    frac = max(0.0, min(1.0, (float(sx) - left) / (right - left)))
                    idx = int(round(start_idx + frac * float(end_idx - start_idx)))
                    return max(start_idx, min(end_idx, idx))
            except Exception:
                pass
        return linear_x_to_value(x_px, width, start_idx, end_idx)

    def draw_overlay_bar(
        self,
        canvas: tk.Canvas | None,
        scale: tk.Scale | None,
        start_idx: int,
        end_idx: int,
        spans: list[tuple[int, int, str]],
        markers: list[tuple[int, str]],
        hover_regions: list[tuple[float, float, str]] | None = None,
    ) -> None:
        if canvas is None:
            return
        canvas.delete("all")
        w = canvas.winfo_width()
        h = canvas.winfo_height()
        if w <= 2 or h <= 2:
            return

        canvas.create_rectangle(0, 0, w, h, fill=APP_COLORS["raised_bg"], outline="")
        if end_idx < start_idx:
            return

        for span_start, span_end, color in spans:
            left_x = self.scale_value_to_x(scale, canvas, span_start, start_idx, end_idx, w)
            right_x = self.scale_value_to_x(scale, canvas, span_end, start_idx, end_idx, w)
            left = max(0.0, min(left_x, right_x))
            right = min(float(w), max(left_x, right_x))
            if right - left < 5.0:
                right = min(float(w), left + 5.0)
            canvas.create_rectangle(left, 3, right, h - 3, fill=color, outline="")

        for marker_idx, color in markers:
            x = self.scale_value_to_x(scale, canvas, marker_idx, start_idx, end_idx, w)
            left = max(0.0, x - 2.0)
            right = min(float(w), x + 2.0)
            canvas.create_rectangle(left, 2, right, h - 2, fill=color, outline="")
        self.app._main_overlay_regions = list(hover_regions or [])

    def redraw_main_overlay(self) -> None:
        if self.app.preview_overlay is None or self.app.stack_info is None:
            return
        frame_count = int(self.app.stack_info.frame_count)
        if frame_count <= 0:
            self.draw_overlay_bar(self.app.preview_overlay, self.app.preview_scale, 0, 0, [], [], [])
            return

        spans = [(event.start_idx, event.end_idx, APP_COLORS["purple"]) for event in self.app.events]
        markers = [(self.app.current_frame_idx, APP_COLORS["white"])]
        hover_regions: list[tuple[float, float, str]] = []
        width = max(1, self.app.preview_overlay.winfo_width())
        for event in self.app.events:
            left = self.scale_value_to_x(self.app.preview_scale, self.app.preview_overlay, event.start_idx, 0, frame_count - 1, width)
            right = self.scale_value_to_x(self.app.preview_scale, self.app.preview_overlay, event.end_idx, 0, frame_count - 1, width)
            label = str(getattr(event, "label", "") or getattr(event, "event_id", "")).strip() or str(getattr(event, "event_id", "Event"))
            hover_regions.append((min(left, right), max(left, right), f"{label}: frames {event.start_idx + 1}–{event.end_idx + 1}"))
        marker_x = self.scale_value_to_x(self.app.preview_scale, self.app.preview_overlay, self.app.current_frame_idx, 0, frame_count - 1, width)
        hover_regions.append((max(0.0, marker_x - 4.0), min(float(width), marker_x + 4.0), f"Current frame {self.app.current_frame_idx + 1}"))
        self.draw_overlay_bar(self.app.preview_overlay, self.app.preview_scale, 0, frame_count - 1, spans, markers, hover_regions)

    def on_main_overlay_click(self, event) -> None:
        if self.app.preview_overlay is None or self.app.stack_info is None:
            return
        frame_count = int(self.app.stack_info.frame_count)
        if frame_count <= 0:
            return

        clicked_idx = self.scale_x_to_value(
            self.app.preview_scale,
            self.app.preview_overlay,
            event.x,
            0,
            frame_count - 1,
            self.app.preview_overlay.winfo_width(),
        )

        clicked_event = None
        for ev in self.app.events:
            if ev.start_idx <= clicked_idx <= ev.end_idx:
                clicked_event = ev
                break

        if clicked_event is not None:
            self.app._set_active_event_id(clicked_event.event_id)
            if self.app.tree.exists(clicked_event.event_id):
                self.app.tree.selection_set(clicked_event.event_id)
                self.app.tree.see(clicked_event.event_id)
            target_idx = clicked_event.start_idx
            display_name = str(getattr(clicked_event, "label", "") or getattr(clicked_event, "event_id", "")).strip()
            self.app._log_info(f"Overlay click: selected {display_name} and jumped to frame {target_idx}.")
        else:
            target_idx = clicked_idx
            self.app._log_info(f"Overlay click: jumped to frame {target_idx}.")

        self.app.preview_scale.set(target_idx)
        self.update_preview(target_idx)

    def update_popup_mini_raw(self, frame_idx: int) -> None:
        if self.app.reader is None or self.app._popup.mark_mini_canvas is None or self.app._popup.mark_mini_frame is None:
            return
        raw_u8 = self.get_normalized_reader_frame(frame_idx)
        pil = Image.fromarray(raw_u8)
        canvas_w = max(40, self.app._popup.mark_mini_canvas.winfo_width())
        canvas_h = max(40, self.app._popup.mark_mini_canvas.winfo_height())
        max_w = max(40, canvas_w - 8)
        max_h = max(40, canvas_h - 8)
        pil.thumbnail((max_w, max_h), Image.Resampling.BILINEAR)
        self.app._popup.mark_popup_mini_image = ImageTk.PhotoImage(pil)
        self.app._popup.mark_mini_canvas.delete("all")
        self.app._popup.mark_mini_canvas.create_image(canvas_w // 2, canvas_h // 2, image=self.app._popup.mark_popup_mini_image, anchor="center")

    def popup_update_window_info(self) -> None:
        if self.app._popup.mark_window_info_var is None:
            return
        baseline_count = self.app._popup.mark_baseline_count_var.get().strip() if self.app._popup.mark_baseline_count_var is not None else "30"
        baseline_end = self.app._popup.mark_baseline_end_var.get().strip() if self.app._popup.mark_baseline_end_var is not None else "0"
        self.app._popup.mark_window_info_var.set(
            f"Frames: [{self.app._popup.mark_popup_local_start + 1}, {self.app._popup.mark_popup_local_end + 1}] | "
            f"Baseline: count={baseline_count}, end={baseline_end}{self.app._popup.mark_last_full_refresh_note}"
        )

    def popup_update_preview(self, frame_idx: int) -> None:
        if self.app.reader is None or self.app.stack_info is None or self.app._popup.mark_preview_label is None:
            return
        low, high = self.popup_overlay_bounds()
        frame_idx = max(low, min(frame_idx, high))
        self.app._popup.mark_popup_current_idx = frame_idx

        frame = self.app._get_popup_controller().processing_controller.get_processed_frame(frame_idx)
        contrast_factor = float(self.app._popup.mark_contrast_var.get()) if self.app._popup.mark_contrast_var is not None else 1.0
        image = self.render_preview_image(
            frame,
            self.app._popup.mark_preview_label,
            fallback_size=(1000, 700),
            pre_normalized=True,
            contrast_factor=contrast_factor,
        )
        self.app._popup.mark_popup_image = image
        self.app._popup.mark_preview_label.configure(image=image)

        self.update_popup_mini_raw(frame_idx)

        if self.app._popup.mark_frame_info_var is not None:
            frame_name = self.app.reader.get_frame_name(frame_idx)
            self.app._popup.mark_frame_info_var.set(f"Frame: {frame_idx}  [{frame_name}]")
        self.popup_update_window_info()
        self.redraw_popup_overlay()

    def popup_overlay_bounds(self) -> tuple[int, int]:
        if self.app._popup.mark_scale is None:
            return self.app._popup.mark_popup_local_start, self.app._popup.mark_popup_local_end
        start_idx = int(float(self.app._popup.mark_scale.cget("from")))
        end_idx = int(float(self.app._popup.mark_scale.cget("to")))
        if end_idx < start_idx:
            start_idx, end_idx = end_idx, start_idx
        return start_idx, end_idx

    def popup_get_normalized_mark_bounds_for_overlay(self) -> tuple[int | None, int | None]:
        start_idx: int | None = None
        end_idx: int | None = None
        if self.app._popup.mark_start_var is not None:
            raw = self.app._popup.mark_start_var.get().strip()
            if raw:
                try:
                    start_idx = int(float(raw)) - 1
                except ValueError:
                    start_idx = None
        if self.app._popup.mark_end_var is not None:
            raw = self.app._popup.mark_end_var.get().strip()
            if raw:
                try:
                    end_idx = int(float(raw)) - 1
                except ValueError:
                    end_idx = None
        frame_count = int(self.app.stack_info.frame_count) if self.app.stack_info is not None else 0
        return normalize_overlay_bounds(start_idx, end_idx, frame_count)

    def redraw_popup_overlay(self) -> None:
        if self.app._popup.mark_overlay is None:
            return
        start_idx, end_idx = self.popup_overlay_bounds()
        mark_start, mark_end = self.popup_get_normalized_mark_bounds_for_overlay()

        spans: list[tuple[int, int, str]] = []
        if self.app.stack_info is not None:
            try:
                baseline_count, baseline_end = self.app._get_popup_controller().processing_controller.parse_baseline_controls()
                baseline_start = max(0, baseline_end - baseline_count + 1)
                if baseline_end >= 0:
                    spans.append((baseline_start, baseline_end, APP_COLORS["accent_soft"]))
            except Exception:
                pass

        if mark_start is not None and mark_end is not None:
            left = min(mark_start, mark_end)
            right = max(mark_start, mark_end)
            spans.append((left, right, APP_COLORS["cyan"]))

        if self.app.stack_info is not None:
            try:
                baseline_count, baseline_end = self.app._get_popup_controller().processing_controller.parse_baseline_controls()
                baseline_start = max(0, baseline_end - baseline_count + 1)
            except Exception:
                baseline_start = None
        else:
            baseline_start = None

        # Draw baseline-start before event start/end so the event markers remain visible
        # when they are only a frame or two apart.
        markers = [(self.app._popup.mark_popup_current_idx, APP_COLORS["white"])]
        if baseline_start is not None:
            markers.append((baseline_start, APP_COLORS["info"]))
        if mark_start is not None:
            markers.append((mark_start, APP_COLORS["success"]))
        if mark_end is not None:
            markers.append((mark_end, APP_COLORS["danger"]))

        self.draw_overlay_bar(self.app._popup.mark_overlay, self.app._popup.mark_scale, start_idx, end_idx, spans, markers)
