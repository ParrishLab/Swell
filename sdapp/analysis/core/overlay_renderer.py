from __future__ import annotations

"""Slider overlay rendering helpers shared by app orchestration layer."""

import time

import tkinter as tk


_LEVERAGE_CMAP = None


def _leverage_hex(norm: float) -> str:
    """Map a leverage value in [0,1] to a hex color.

    High leverage -> red ("edit here"); low/zero -> green ("settled").
    """
    global _LEVERAGE_CMAP
    if _LEVERAGE_CMAP is None:
        from matplotlib import pyplot as plt

        _LEVERAGE_CMAP = plt.get_cmap("RdYlGn")
    # RdYlGn: 0.0 = red, 1.0 = green. Invert so high leverage = red.
    rgba = _LEVERAGE_CMAP(1.0 - max(0.0, min(1.0, float(norm))))
    r, g, b = (int(round(float(c) * 255.0)) for c in rgba[:3])
    return f"#{r:02x}{g:02x}{b:02x}"


def _draw_leverage_heatmap(app, canvas, w, h, total) -> None:
    """Render the per-frame leverage strip along the bottom of the slider overlay.

    Absolute scale: leverage below the floor reads green; a uniformly green strip
    means nothing is worth correcting.
    """
    from sdapp.analysis.core.leverage import LEVERAGE_FLOOR

    seg_state = getattr(app, "seg_state", None)
    cache = getattr(seg_state, "leverage_cache", None) if seg_state is not None else None
    if not cache:
        return
    floor = float(LEVERAGE_FLOOR)
    denom = max(1e-6, 1.0 - floor)
    for idx, value in cache.items():
        value = float(value)
        norm = 0.0 if value < floor else (value - floor) / denom
        left_raw = app._frame_to_overlay_x(idx - 0.5, width=w, total_frames=total)
        right_raw = app._frame_to_overlay_x(idx + 0.5, width=w, total_frames=total)
        left = max(0.0, min(left_raw, right_raw))
        right = min(float(w), max(left_raw, right_raw))
        if right - left < 1.0:
            right = min(float(w), left + 1.0)
        canvas.create_rectangle(left, h - 4, right, h, fill=_leverage_hex(norm), outline="")
        app._slider_overlay_regions.append((left, right, f"Leverage {value:.2f} (frame {idx + 1})"))

    suggested = getattr(seg_state, "leverage_suggested_frame", None)
    if suggested is not None:
        x = app._frame_to_overlay_x(int(suggested), width=w, total_frames=total)
        left = max(0.0, x - 2.0)
        right = min(float(w), x + 2.0)
        canvas.create_rectangle(left, h - 7, right, h, fill="#ffffff", outline="")
        app._slider_overlay_regions.append(
            (left, right, f"Suggested correction: frame {int(suggested) + 1}")
        )


def _debug_log(app, message: str) -> None:
    logger = getattr(app, "log_debug", None)
    if callable(logger):
        try:
            logger("Overlay", str(message))
        except Exception:
            return


def _safe_spinbox_value(widget) -> str:
    try:
        return str(widget.get())
    except Exception:
        return "<unreadable>"


def recompute_slider_jump_markers(app) -> None:
    """Recompute marker metadata and keep range spinboxes synchronized."""
    t0 = time.perf_counter()
    frame_count = app._get_frame_count() if hasattr(app, "_get_frame_count") else 0
    if frame_count <= 0:
        _debug_log(app, "Marker recompute aborted: frame_count<=0")
        app.slider_jump_markers = {}
        redraw_slider_overlay(app)
        return

    markers = {}
    user_frames = app._collect_user_defined_frames()
    nonempty_mask_frames = app._collect_nonempty_final_mask_frames()
    _debug_log(
        app,
        "Marker recompute inputs "
        f"frame_count={frame_count} "
        f"user_frames={sorted(int(i) for i in user_frames)[:12]} "
        f"nonempty_mask_frames={sorted(int(i) for i in nonempty_mask_frames)[:12]} "
        f"active_event_id={getattr(app, 'active_event_id', None)}",
    )

    for frame_idx in sorted(user_frames):
        markers[frame_idx] = "user"

    if nonempty_mask_frames:
        start_idx = min(nonempty_mask_frames)
        end_idx = max(nonempty_mask_frames)
        markers[start_idx] = "start"
        if end_idx != start_idx:
            markers[end_idx] = "end"
        _debug_log(app, f"Marker bounds derived from masks start_idx={start_idx} end_idx={end_idx}")

        if hasattr(app, "spin_prop_start") and hasattr(app, "spin_prop_end"):
            start_display = start_idx + 1
            end_display = end_idx + 1
            before_start = _safe_spinbox_value(app.spin_prop_start)
            before_end = _safe_spinbox_value(app.spin_prop_end)
            try:
                if int(app.spin_prop_start.get()) != start_display:
                    app._set_spinbox_value(app.spin_prop_start, start_display)
            except (ValueError, TypeError, tk.TclError):
                app._set_spinbox_value(app.spin_prop_start, start_display)
            try:
                if int(app.spin_prop_end.get()) != end_display:
                    app._set_spinbox_value(app.spin_prop_end, end_display)
            except (ValueError, TypeError, tk.TclError):
                app._set_spinbox_value(app.spin_prop_end, end_display)
            _debug_log(
                app,
                "Propagation spinboxes synced "
                f"before=({before_start},{before_end}) "
                f"after=({_safe_spinbox_value(app.spin_prop_start)},{_safe_spinbox_value(app.spin_prop_end)})",
            )

        if (
            getattr(app, "_export_range_auto_follow", True)
            and hasattr(app, "spin_export_start")
            and hasattr(app, "spin_export_end")
        ):
            start_display = start_idx + 1
            end_display = end_idx + 1
            before_start = _safe_spinbox_value(app.spin_export_start)
            before_end = _safe_spinbox_value(app.spin_export_end)
            try:
                if int(app.spin_export_start.get()) != start_display:
                    app._set_spinbox_value(app.spin_export_start, start_display)
            except (ValueError, TypeError, tk.TclError):
                app._set_spinbox_value(app.spin_export_start, start_display)
            try:
                if int(app.spin_export_end.get()) != end_display:
                    app._set_spinbox_value(app.spin_export_end, end_display)
            except (ValueError, TypeError, tk.TclError):
                app._set_spinbox_value(app.spin_export_end, end_display)
            _debug_log(
                app,
                "Export spinboxes synced "
                f"before=({before_start},{before_end}) "
                f"after=({_safe_spinbox_value(app.spin_export_start)},{_safe_spinbox_value(app.spin_export_end)}) "
                f"auto_follow={getattr(app, '_export_range_auto_follow', None)}",
            )

        if (
            getattr(app, "_analysis_range_auto_follow", True)
            and hasattr(app, "spin_analysis_start")
            and hasattr(app, "spin_analysis_end")
        ):
            start_display = start_idx + 1
            end_display = end_idx + 1
            before_start = _safe_spinbox_value(app.spin_analysis_start)
            before_end = _safe_spinbox_value(app.spin_analysis_end)
            try:
                if int(app.spin_analysis_start.get()) != start_display:
                    app._set_spinbox_value(app.spin_analysis_start, start_display)
            except (ValueError, TypeError, tk.TclError):
                app._set_spinbox_value(app.spin_analysis_start, start_display)
            try:
                if int(app.spin_analysis_end.get()) != end_display:
                    app._set_spinbox_value(app.spin_analysis_end, end_display)
            except (ValueError, TypeError, tk.TclError):
                app._set_spinbox_value(app.spin_analysis_end, end_display)
            _debug_log(
                app,
                "Analysis spinboxes synced "
                f"before=({before_start},{before_end}) "
                f"after=({_safe_spinbox_value(app.spin_analysis_start)},{_safe_spinbox_value(app.spin_analysis_end)}) "
                f"auto_follow={getattr(app, '_analysis_range_auto_follow', None)}",
            )
    else:
        _debug_log(app, "No nonempty mask frames detected during marker recompute")

    app.slider_jump_markers = markers
    redraw_slider_overlay(app)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    app.log_debug("Perf", f"Marker recompute elapsed={elapsed_ms:.2f}ms markers={len(markers)}")
    _debug_log(app, f"Marker recompute result markers={markers}")


def find_clicked_marker_frame(app, x_px: float) -> int | None:
    """Resolve click position on overlay canvas to nearest marker frame."""
    if not app.slider_jump_markers:
        return None

    if app._slider_marker_bounds:
        for frame_idx, (left, right) in app._slider_marker_bounds.items():
            if float(left) <= float(x_px) <= float(right):
                return frame_idx

    nearest_frame = None
    nearest_dist = float("inf")
    for frame_idx in app.slider_jump_markers:
        marker_x = app._frame_to_overlay_x(frame_idx)
        dist = abs(float(x_px) - marker_x)
        if dist < nearest_dist:
            nearest_dist = dist
            nearest_frame = frame_idx

    if nearest_dist <= float(app._slider_marker_hit_tolerance_px):
        return nearest_frame
    return None


def redraw_slider_overlay(app) -> None:
    """Render propagated coverage and marker bands on slider overlay canvas."""
    t0 = time.perf_counter()
    if not hasattr(app, "slider_overlay"):
        return
    canvas = app.slider_overlay
    canvas.delete("all")
    app._slider_overlay_regions = []

    w = canvas.winfo_width()
    h = canvas.winfo_height()
    if w <= 2 or h <= 2:
        return

    canvas.create_rectangle(0, 0, w, h, fill="#232830", outline="")

    total = app._get_frame_count() if hasattr(app, "_get_frame_count") else 0
    if total <= 0:
        _debug_log(app, "Slider overlay redraw aborted: total<=0")
        return

    _draw_leverage_heatmap(app, canvas, w, h, total)

    marker_positions = []
    for frame_idx, marker_type in sorted(app.slider_jump_markers.items()):
        x = app._frame_to_overlay_x(frame_idx, width=w, total_frames=total)
        marker_positions.append((frame_idx, marker_type, x))

    marker_bounds = {}
    if marker_positions:
        gap_px = 1.5
        for frame_idx, _marker_type, x in marker_positions:
            left_limit = app._frame_to_overlay_x(frame_idx - 0.5, width=w, total_frames=total)
            right_limit = app._frame_to_overlay_x(frame_idx + 0.5, width=w, total_frames=total)
            left = max(0.0, min(left_limit, right_limit) + (gap_px / 2.0))
            right = min(float(w), max(left_limit, right_limit) - (gap_px / 2.0))
            if right - left < 2.0:
                left = max(0.0, x - 1.0)
                right = min(float(w), x + 1.0)
            marker_bounds[frame_idx] = (left, right)

    coverage_indices = set(app.propagated_frame_indices) | set(app.slider_jump_markers.keys())
    coverage_spans = app._build_frame_spans(coverage_indices)
    for start_idx, end_idx in coverage_spans:
        x0 = app._frame_to_overlay_x(start_idx, width=w, total_frames=total)
        x1 = app._frame_to_overlay_x(end_idx, width=w, total_frames=total)
        left = min(x0, x1)
        right = max(x0, x1)
        left = max(0, left - 2.0)
        right = min(w, right + 2.0)
        if right - left < 5:
            right = min(w, left + 5)
        canvas.create_rectangle(left, 4, right, h - 4, fill="#2ecfd0", outline="")
        app._slider_overlay_regions.append((left, right, f"Coverage: frames {start_idx + 1}–{end_idx + 1}"))

    for frame_idx, marker_type, x in marker_positions:
        left, right = marker_bounds.get(frame_idx, (x - 1.0, x + 1.0))
        if marker_type == "start":
            color = "#00d26a"
            band_left = max(0.0, left - 1.5)
            band_right = min(float(w), right + 1.5)
            canvas.create_rectangle(band_left, 2, band_right, h - 2, fill=color, outline="")
            app._slider_overlay_regions.append((left, right, f"Propagation start: frame {frame_idx + 1}"))
        elif marker_type == "end":
            color = "#ff5c5c"
            band_left = max(0.0, left - 1.5)
            band_right = min(float(w), right + 1.5)
            canvas.create_rectangle(band_left, 2, band_right, h - 2, fill=color, outline="")
            app._slider_overlay_regions.append((left, right, f"Propagation end: frame {frame_idx + 1}"))
        else:
            color = "#b26bff"
            canvas.create_rectangle(left, 3, right, h - 3, fill=color, outline="")
            app._slider_overlay_regions.append((left, right, f"Prompt frame {frame_idx + 1}"))

    app._slider_marker_bounds = marker_bounds
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    app.log_debug("Perf", f"Slider overlay redraw elapsed={elapsed_ms:.2f}ms")
    _debug_log(
        app,
        f"Slider overlay redraw state total={total} canvas=({w},{h}) "
        f"markers={len(app.slider_jump_markers)} coverage_spans={coverage_spans}",
    )
