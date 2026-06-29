from __future__ import annotations

"""Slider overlay rendering helpers shared by app orchestration layer."""

import time

import tkinter as tk

from swell.shared.ui.theme import APP_COLORS


_LEVERAGE_CMAP = None

_TIMELINE_BG = APP_COLORS["raised_bg"]
_TIMELINE_TRACK = APP_COLORS["timeline_track"]
_TIMELINE_PROGRESS = APP_COLORS["accent"]
_TIMELINE_PROGRESS_TRAIL = APP_COLORS["progress_trail"]


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

    Relative scale: the worst troubled region in view reads red, calmer frames
    fade toward green. An empty cache means nothing is worth correcting.
    """
    if getattr(app, "leverage_visibility_var", None) is not None and not app.leverage_visibility_var.get():
        return

    seg_state = getattr(app, "seg_state", None)
    cache = getattr(seg_state, "leverage_cache", None) if seg_state is not None else None
    if not cache:
        return
    # Reserve a strip along the bottom of the overlay for the heatmap.
    strip_h = max(5, int(round(h * 0.35)))
    strip_top = h - strip_h
    # The cache only contains genuinely troubled regions (frames above the
    # trouble floor), so colour them relative to the worst region in view: the
    # hottest spot reads red, calmer edges fade toward green.
    vmax = max((float(v) for v in cache.values()), default=0.0)
    denom = max(1e-6, vmax)
    for idx, value in cache.items():
        value = float(value)
        norm = max(0.0, min(1.0, value / denom))
        left_raw = app._frame_to_overlay_x(idx - 0.5, width=w, total_frames=total)
        right_raw = app._frame_to_overlay_x(idx + 0.5, width=w, total_frames=total)
        left = max(0.0, min(left_raw, right_raw))
        right = min(float(w), max(left_raw, right_raw))
        if right - left < 1.0:
            right = min(float(w), left + 1.0)
        canvas.create_rectangle(
            left, strip_top, right, h,
            fill=_leverage_hex(norm), outline="", tags=("leverage_heatmap",),
        )
        app._slider_overlay_regions.append((left, right, f"Leverage {value:.2f} (frame {idx + 1})"))

    suggested = getattr(seg_state, "leverage_suggested_frame", None)
    if suggested is not None:
        x = app._frame_to_overlay_x(int(suggested), width=w, total_frames=total)
        left = max(0.0, x - 2.0)
        right = min(float(w), x + 2.0)
        # A small tick within the heatmap strip; the full-height white bar is the
        # current-frame playhead, so the suggestion stays low to avoid confusion.
        canvas.create_rectangle(
            left, strip_top, right, h, fill=APP_COLORS["white"], outline="", tags=("leverage_heatmap",),
        )
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


def _timeline_ratio(done, total) -> float:
    safe_total = max(0, int(total or 0))
    safe_done = max(0, int(done or 0))
    if safe_total <= 0:
        return 1.0
    return max(0.0, min(1.0, safe_done / safe_total))


def timeline_progress_geometry(app, *, width: int, total_frames: int, state: dict) -> dict[str, float | str] | None:
    """Compute timeline progress bounds for propagation progress rendering."""
    if width <= 2 or total_frames <= 0 or not state:
        return None
    try:
        prop_start = int(state.get("prop_start"))
        prop_end = int(state.get("prop_end"))
    except (TypeError, ValueError):
        prop_start = 0
        prop_end = total_frames - 1
    prop_start = max(0, min(prop_start, total_frames - 1))
    prop_end = max(0, min(prop_end, total_frames - 1))
    if prop_end < prop_start:
        prop_start, prop_end = prop_end, prop_start
    try:
        anchor = int(state.get("anchor"))
    except (TypeError, ValueError):
        anchor = prop_start
    anchor = max(prop_start, min(anchor, prop_end))

    range_left = app._frame_to_overlay_x(prop_start - 0.5, width=width, total_frames=total_frames)
    range_right = app._frame_to_overlay_x(prop_end + 0.5, width=width, total_frames=total_frames)
    range_left, range_right = sorted((max(0.0, range_left), min(float(width), range_right)))

    direction = str(state.get("direction") or "").lower()
    if direction in {"forward", "backward"}:
        ratio = _timeline_ratio(state.get("phase_done", 0), state.get("phase_total", 0))
        if direction == "forward":
            start_x = app._frame_to_overlay_x(anchor - 0.5, width=width, total_frames=total_frames)
            end_x = app._frame_to_overlay_x(prop_end + 0.5, width=width, total_frames=total_frames)
            start_x, end_x = sorted((max(0.0, start_x), min(float(width), end_x)))
            fill_left = start_x
            fill_right = start_x + ((end_x - start_x) * ratio)
        else:
            start_x = app._frame_to_overlay_x(prop_start - 0.5, width=width, total_frames=total_frames)
            end_x = app._frame_to_overlay_x(anchor + 0.5, width=width, total_frames=total_frames)
            start_x, end_x = sorted((max(0.0, start_x), min(float(width), end_x)))
            fill_right = end_x
            fill_left = end_x - ((end_x - start_x) * ratio)
    else:
        ratio = _timeline_ratio(state.get("done", 0), state.get("total", 0))
        fill_left = range_left
        fill_right = range_left + ((range_right - range_left) * ratio)
        direction = "aggregate"

    fill_left = max(range_left, min(float(width), fill_left))
    fill_right = min(range_right, max(0.0, fill_right))
    if fill_right < fill_left:
        fill_left, fill_right = fill_right, fill_left
    return {
        "track_left": range_left,
        "track_right": range_right,
        "fill_left": fill_left,
        "fill_right": fill_right,
        "direction": direction,
    }


def _timeline_progress_y_bounds(h: int) -> tuple[int, int]:
    y0 = 2
    y1 = max(y0 + 1, int(h) - 2)
    return y0, y1


def clear_timeline_progress_items(app) -> None:
    canvas = getattr(app, "slider_overlay", None)
    if canvas is None:
        return
    try:
        canvas.delete("timeline_progress")
        setattr(app, "_timeline_progress_item_ids", {})
    except Exception:
        return


def _progress_item_exists(canvas, item_id) -> bool:
    if item_id is None:
        return False
    try:
        return bool(canvas.type(item_id))
    except Exception:
        return False


def ensure_timeline_progress_items(app, canvas, w: int, h: int, total: int) -> dict:
    """Create or reuse progress items so animation can update coords only."""
    del total
    items = getattr(app, "_timeline_progress_item_ids", None)
    if not isinstance(items, dict):
        items = {}
    y0, y1 = _timeline_progress_y_bounds(h)
    if not _progress_item_exists(canvas, items.get("track")):
        items["track"] = canvas.create_rectangle(
            0,
            y0,
            w,
            y1,
            fill=_TIMELINE_TRACK,
            outline=_TIMELINE_PROGRESS_TRAIL,
            tags=("timeline_progress", "timeline_progress_track"),
        )
    if not _progress_item_exists(canvas, items.get("fill")):
        items["fill"] = canvas.create_rectangle(
            0,
            y0,
            0,
            y1,
            fill=_TIMELINE_PROGRESS,
            outline="",
            tags=("timeline_progress", "timeline_progress_fill"),
        )
    if not _progress_item_exists(canvas, items.get("fill_wrap")):
        items["fill_wrap"] = canvas.create_rectangle(
            0,
            y0,
            0,
            y1,
            fill=_TIMELINE_PROGRESS,
            outline="",
            tags=("timeline_progress", "timeline_progress_fill"),
        )
    setattr(app, "_timeline_progress_item_ids", items)
    try:
        canvas.tag_raise("timeline_marker")
    except Exception:
        pass
    return items


def _phase_progress_geometry(app, *, width: int, total_frames: int, state: dict, direction: str, done_key: str, total_key: str):
    safe_total = max(0, int(state.get(total_key, 0) or 0))
    safe_done = max(0, min(int(state.get(done_key, 0) or 0), safe_total))
    if safe_total <= 0 or safe_done <= 0:
        return None
    phase_state = dict(state)
    phase_state["direction"] = str(direction)
    phase_state["phase_done"] = safe_done
    phase_state["phase_total"] = safe_total
    return timeline_progress_geometry(app, width=width, total_frames=total_frames, state=phase_state)


def update_timeline_loading_progress(app) -> None:
    """Move the loading segment without redrawing static timeline items."""
    canvas = getattr(app, "slider_overlay", None)
    if canvas is None:
        return
    state = getattr(app, "_timeline_progress_state", None)
    if not state or not bool(state.get("active", False)) or str(state.get("kind") or "") != "loading":
        clear_timeline_progress_items(app)
        return
    w = canvas.winfo_width()
    h = canvas.winfo_height()
    if w <= 2 or h <= 2:
        return
    items = ensure_timeline_progress_items(app, canvas, w, h, 0)
    y0, y1 = _timeline_progress_y_bounds(h)
    canvas.coords(items["track"], 0, y0, w, y1)
    segment_w = max(18.0, float(w) * 0.22)
    period = float(w) + segment_w
    phase = (time.monotonic() * 180.0) % period
    left = phase - segment_w
    right = phase
    if right > 0 and left < float(w):
        canvas.coords(items["fill"], max(0.0, left), y0, min(float(w), right), y1)
    else:
        canvas.coords(items["fill"], 0, y0, 0, y1)
    if right > float(w):
        wrap_right = right - float(w)
        canvas.coords(items["fill_wrap"], 0, y0, min(segment_w, wrap_right), y1)
    else:
        canvas.coords(items["fill_wrap"], 0, y0, 0, y1)
    try:
        canvas.tag_raise("timeline_marker")
    except Exception:
        pass


def update_timeline_propagation_progress(app) -> None:
    """Update propagation progress coordinates without redrawing static layers."""
    canvas = getattr(app, "slider_overlay", None)
    if canvas is None:
        return
    state = getattr(app, "_timeline_progress_state", None)
    if not state or not bool(state.get("active", False)):
        clear_timeline_progress_items(app)
        return
    if str(state.get("kind") or "propagation") == "loading":
        update_timeline_loading_progress(app)
        return
    w = canvas.winfo_width()
    h = canvas.winfo_height()
    if w <= 2 or h <= 2:
        return
    total = app._get_frame_count() if hasattr(app, "_get_frame_count") else 0
    geometry = timeline_progress_geometry(app, width=w, total_frames=total, state=state)
    if geometry is None:
        clear_timeline_progress_items(app)
        return
    items = ensure_timeline_progress_items(app, canvas, w, h, total)
    y0, y1 = _timeline_progress_y_bounds(h)
    canvas.coords(items["track"], geometry["track_left"], y0, geometry["track_right"], y1)

    has_direction_totals = int(state.get("forward_total", 0) or 0) > 0 or int(state.get("backward_total", 0) or 0) > 0
    if has_direction_totals:
        forward_geometry = _phase_progress_geometry(
            app,
            width=w,
            total_frames=total,
            state=state,
            direction="forward",
            done_key="forward_done",
            total_key="forward_total",
        )
        backward_geometry = _phase_progress_geometry(
            app,
            width=w,
            total_frames=total,
            state=state,
            direction="backward",
            done_key="backward_done",
            total_key="backward_total",
        )
        if forward_geometry is not None and float(forward_geometry["fill_right"]) - float(forward_geometry["fill_left"]) >= 1.0:
            canvas.coords(items["fill"], forward_geometry["fill_left"], y0, forward_geometry["fill_right"], y1)
        else:
            canvas.coords(items["fill"], 0, y0, 0, y1)
        if backward_geometry is not None and float(backward_geometry["fill_right"]) - float(backward_geometry["fill_left"]) >= 1.0:
            canvas.coords(items["fill_wrap"], backward_geometry["fill_left"], y0, backward_geometry["fill_right"], y1)
        else:
            canvas.coords(items["fill_wrap"], 0, y0, 0, y1)
    else:
        if float(geometry["fill_right"]) - float(geometry["fill_left"]) >= 1.0:
            canvas.coords(items["fill"], geometry["fill_left"], y0, geometry["fill_right"], y1)
        else:
            canvas.coords(items["fill"], 0, y0, 0, y1)
        canvas.coords(items["fill_wrap"], 0, y0, 0, y1)
    try:
        canvas.tag_raise("timeline_marker")
    except Exception:
        pass


def _draw_timeline_progress_layer(app, canvas, w: int, h: int, total: int) -> None:
    """Restore active progress items after a static slider overlay redraw."""
    state = getattr(app, "_timeline_progress_state", None)
    if not state or not bool(state.get("active", False)):
        clear_timeline_progress_items(app)
        return
    if str(state.get("kind") or "propagation") == "loading":
        update_timeline_loading_progress(app)
    else:
        update_timeline_propagation_progress(app)


def redraw_timeline_progress(app) -> None:
    """Compatibility wrapper: timeline progress is layered onto slider_overlay."""
    redraw_slider_overlay(app)


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
    collect_bounds_frames = getattr(app, "_collect_nonempty_mask_frames_without_regions", None)
    if callable(collect_bounds_frames) and getattr(app, "seg_state", None) is not None:
        nonempty_mask_frames = collect_bounds_frames()
    else:
        nonempty_mask_frames = app._collect_nonempty_final_mask_frames()
    _debug_log(
        app,
        "Marker recompute inputs "
        f"frame_count={frame_count} "
        f"user_frames={sorted(int(i) for i in user_frames)[:12]} "
        f"nonempty_mask_frames={sorted(int(i) for i in nonempty_mask_frames)[:12]} "
        f"active_event_id={getattr(app, 'active_event_id', None)}",
    )

    # Ground-truth frames are already included in user_frames (via
    # get_prompt_anchor_frames), so they share the purple "user" marker with
    # edited/prompt frames — no separate styling.
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

    canvas.create_rectangle(0, 0, w, h, fill=_TIMELINE_BG, outline="")

    total = app._get_frame_count() if hasattr(app, "_get_frame_count") else 0
    if total <= 0:
        _draw_timeline_progress_layer(app, canvas, w, h, 0)
        _debug_log(app, "Slider overlay redraw aborted: total<=0")
        return

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
        canvas.create_rectangle(left, 4, right, h - 4, fill=_TIMELINE_PROGRESS, outline="")
        app._slider_overlay_regions.append((left, right, f"Coverage: frames {start_idx + 1}–{end_idx + 1}"))

    _draw_timeline_progress_layer(app, canvas, w, h, total)

    # Heatmap sits above coverage/progress but below the marker bands, which are
    # raised last so start/end/prompt markers stay legible.
    _draw_leverage_heatmap(app, canvas, w, h, total)

    for frame_idx, marker_type, x in marker_positions:
        left, right = marker_bounds.get(frame_idx, (x - 1.0, x + 1.0))
        if marker_type == "start":
            color = APP_COLORS["success"]
            band_left = max(0.0, left - 1.5)
            band_right = min(float(w), right + 1.5)
            canvas.create_rectangle(band_left, 2, band_right, h - 2, fill=color, outline="", tags=("timeline_marker",))
            app._slider_overlay_regions.append((left, right, f"Propagation start: frame {frame_idx + 1}"))
        elif marker_type == "end":
            color = APP_COLORS["danger"]
            band_left = max(0.0, left - 1.5)
            band_right = min(float(w), right + 1.5)
            canvas.create_rectangle(band_left, 2, band_right, h - 2, fill=color, outline="", tags=("timeline_marker",))
            app._slider_overlay_regions.append((left, right, f"Propagation end: frame {frame_idx + 1}"))
        else:
            color = APP_COLORS["purple"]
            canvas.create_rectangle(left, 3, right, h - 3, fill=color, outline="", tags=("timeline_marker",))
            app._slider_overlay_regions.append((left, right, f"Prompt frame {frame_idx + 1}"))

    app._slider_marker_bounds = marker_bounds
    try:
        canvas.tag_raise("timeline_marker")
    except Exception:
        pass
    # Draw the current-frame playhead last so it stays on top of every band.
    update_slider_playhead(app)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    app.log_debug("Perf", f"Slider overlay redraw elapsed={elapsed_ms:.2f}ms")
    _debug_log(
        app,
        f"Slider overlay redraw state total={total} canvas=({w},{h}) "
        f"markers={len(app.slider_jump_markers)} coverage_spans={coverage_spans}",
    )


def update_slider_playhead(app) -> None:
    """Position the current-frame playhead on the slider overlay.

    This is cheap (one canvas item) so it can run on every frame change without
    a full overlay redraw, keeping the playhead in sync as the user scrubs.
    """
    canvas = getattr(app, "slider_overlay", None)
    if canvas is None:
        return
    canvas.delete("timeline_playhead")
    w = canvas.winfo_width()
    h = canvas.winfo_height()
    if w <= 2 or h <= 2:
        return
    total = app._get_frame_count() if hasattr(app, "_get_frame_count") else 0
    if total <= 0:
        return
    idx = max(0, min(int(getattr(app, "current_frame_idx", 0)), total - 1))
    x = app._frame_to_overlay_x(idx, width=w, total_frames=total)
    left = max(0.0, x - 1.0)
    right = min(float(w), x + 1.0)
    canvas.create_rectangle(
        left, 0, right, h, fill=APP_COLORS["white"], outline="", tags=("timeline_playhead",)
    )
