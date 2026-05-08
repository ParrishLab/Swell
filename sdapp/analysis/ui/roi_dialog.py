from __future__ import annotations

from dataclasses import dataclass
import tkinter as tk
from tkinter import messagebox
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageTk

from sdapp.analysis.core.viewport import (
    ViewportState,
    clamp_viewport_center,
    compute_fit_scale,
    compute_transform,
    fit_viewport,
    zoom_viewport_at,
    pan_viewport,
)
from sdapp.analysis.ui.theme import SPACING, apply_theme
from sdapp.shared.ui.bootstrap import center_window_on_screen, semantic_button_options, ttk

ROI_ICON_LABELS = {
    "zoom_in": "Zoom In",
    "zoom_out": "Zoom Out",
    "fit": "Fit Image",
}


@dataclass(frozen=True)
class RoiDialogConfig:
    context: str = "analysis"
    title: str = "Draw ROI"
    image_label: str = "Reference image"
    allow_reset_local: bool = False


def _dialog_transform_resample(resample):
    if resample in (Image.Resampling.NEAREST, Image.Resampling.BILINEAR, Image.Resampling.BICUBIC):
        return resample
    return Image.Resampling.BICUBIC


def _compute_roi_transform(state, *, canvas_width: int, canvas_height: int, image_width: int, image_height: int):
    viewport_state = state.get("viewport_state")
    if viewport_state is None:
        viewport_state = fit_viewport(image_width, image_height)
        state["viewport_state"] = viewport_state
    return compute_transform(
        viewport_state,
        canvas_width=max(1, int(canvas_width)),
        canvas_height=max(1, int(canvas_height)),
        image_width=max(1, int(image_width)),
        image_height=max(1, int(image_height)),
    )


def _clamp_roi_viewport(state, *, canvas_width: int, canvas_height: int, image_width: int, image_height: int):
    viewport_state = state.get("viewport_state")
    if viewport_state is None:
        viewport_state = fit_viewport(image_width, image_height)
    state["viewport_state"] = clamp_viewport_center(
        viewport_state,
        image_width=image_width,
        image_height=image_height,
        canvas_sizes=[(canvas_width, canvas_height)],
    )
    return state["viewport_state"]


def _canvas_radius_to_image_radius(scale: float, canvas_radius_px: float) -> float:
    safe_scale = max(1e-6, float(scale))
    return float(canvas_radius_px) / safe_scale


def _normalize_roi_context(context: str | RoiDialogConfig | dict[str, Any] | None, *, allow_reset_local: bool) -> RoiDialogConfig:
    if isinstance(context, RoiDialogConfig):
        return RoiDialogConfig(
            context=str(context.context or "analysis").strip().lower() or "analysis",
            title=str(context.title or "Draw ROI"),
            image_label=str(context.image_label or "Reference image"),
            allow_reset_local=bool(context.allow_reset_local or allow_reset_local),
        )
    if isinstance(context, dict):
        return RoiDialogConfig(
            context=str(context.get("context", "analysis") or "analysis").strip().lower() or "analysis",
            title=str(context.get("title", "Draw ROI") or "Draw ROI"),
            image_label=str(context.get("image_label", "Reference image") or "Reference image"),
            allow_reset_local=bool(context.get("allow_reset_local", allow_reset_local)),
        )
    normalized = str(context or "analysis").strip().lower() or "analysis"
    if normalized not in {"host", "analysis", "auto_detect"}:
        normalized = "analysis"
    title = {
        "host": "Draw Global ROI",
        "analysis": "Draw ROI",
        "auto_detect": "Draw Auto-detect ROI",
    }.get(normalized, "Draw ROI")
    return RoiDialogConfig(context=normalized, title=title, allow_reset_local=bool(allow_reset_local))


def _roi_destination_label(config: RoiDialogConfig) -> str:
    if config.context == "host":
        return "Global project ROI"
    if config.context == "auto_detect":
        return "Auto-detect specific ROI"
    return "Event-local ROI"


def _roi_save_actions(config: RoiDialogConfig) -> list[tuple[str, str, str]]:
    if config.context == "host":
        return [("global", "Save Global ROI", "primary")]
    if config.context == "auto_detect":
        return [("auto_detect", "Save Auto-detect ROI", "primary")]
    return [
        ("global_and_local", "Overwrite Global and Save Local", "secondary"),
        ("local", "Save Local ROI", "primary"),
    ]


def _clean_polygon(raw_polygon: Any) -> list[tuple[int, int]]:
    points: list[tuple[int, int]] = []
    if not isinstance(raw_polygon, (list, tuple)):
        return points
    for raw in raw_polygon:
        if not isinstance(raw, (list, tuple)) or len(raw) < 2:
            continue
        try:
            points.append((int(float(raw[0])), int(float(raw[1]))))
        except (TypeError, ValueError):
            continue
    return points


def _normalize_roi_polygons(initial_roi_polygons=None, initial_roi_points=None) -> list[list[tuple[int, int]]]:
    polygons: list[list[tuple[int, int]]] = []
    if isinstance(initial_roi_polygons, list):
        for raw_polygon in initial_roi_polygons:
            polygon = _clean_polygon(raw_polygon)
            if polygon:
                polygons.append(polygon)
    if not polygons:
        polygon = _clean_polygon(initial_roi_points)
        if polygon:
            polygons.append(polygon)
    return polygons


def _closed_region_indices(regions: list[list[tuple[int, int]]], closed_regions: set[int]) -> list[int]:
    return [idx for idx, region in enumerate(regions) if idx in closed_regions and len(region) >= 3]


def _build_roi_result(
    regions: list[list[tuple[int, int]]],
    closed_regions: set[int],
    *,
    image_shape: tuple[int, int],
    target_scope: str,
) -> dict[str, Any]:
    h, w = int(image_shape[0]), int(image_shape[1])
    roi_mask = np.zeros((h, w), dtype=np.uint8)
    polygons: list[list[tuple[int, int]]] = []
    for idx in _closed_region_indices(regions, closed_regions):
        polygon = list(regions[idx])
        polygons.append(polygon)
        pts = np.array(polygon, dtype=np.int32).reshape((-1, 1, 2))
        cv2.fillPoly(roi_mask, [pts], 1)
    first = polygons[0] if polygons else []
    return {
        "target_scope": str(target_scope),
        "roi_mask": roi_mask.astype(bool),
        "roi_points": list(first),
        "roi_polygons": [list(poly) for poly in polygons],
    }


def _attach_tooltip(widget, text: str) -> None:
    tip = {"window": None}

    def show(event):
        if tip["window"] is not None:
            return
        top = tk.Toplevel(widget)
        top.withdraw()
        top.overrideredirect(True)
        label = ttk.Label(top, text=str(text), padding=(6, 3), style="AppMeta.TLabel")
        label.pack()
        top.geometry(f"+{int(event.x_root) + 10}+{int(event.y_root) + 10}")
        top.deiconify()
        tip["window"] = top

    def hide(_event=None):
        top = tip.get("window")
        tip["window"] = None
        if top is not None:
            try:
                top.destroy()
            except Exception:
                pass

    widget.bind("<Enter>", show, add="+")
    widget.bind("<Leave>", hide, add="+")


def _call_preserving_geometry(window, callback):
    top = None
    before = None
    try:
        top = window.winfo_toplevel()
        if bool(top.winfo_exists()) and str(top.state()) != "withdrawn":
            before = str(top.geometry())
    except Exception:
        top = None
        before = None
    try:
        return callback()
    finally:
        if top is not None and before:
            try:
                if bool(top.winfo_exists()) and str(top.geometry()) != before:
                    top.geometry(before)
            except Exception:
                pass


def open_roi_dialog(
    root,
    img_u8,
    initial_roi_points=None,
    allow_reset_local=False,
    pick_image_callback=None,
    *,
    context: str | RoiDialogConfig | dict[str, Any] | None = None,
    initial_roi_polygons=None,
    image_label: str | None = None,
):
    config = _normalize_roi_context(context, allow_reset_local=bool(allow_reset_local))
    if image_label:
        config = RoiDialogConfig(
            context=config.context,
            title=config.title,
            image_label=str(image_label),
            allow_reset_local=config.allow_reset_local,
        )

    popup = tk.Toplevel(root)
    popup.withdraw()
    full_title = f"{config.title} - {image_label}" if image_label else config.title
    popup.title(full_title)
    popup.resizable(True, True)
    popup.geometry("1120x820")
    popup.minsize(900, 700)
    apply_theme(popup)
    popup.columnconfigure(0, weight=1)
    popup.rowconfigure(0, weight=1)

    img_h, img_w = img_u8.shape[:2]
    img_rgb = cv2.cvtColor(img_u8, cv2.COLOR_GRAY2RGB)
    result = {"value": None}

    shell = ttk.Frame(popup, padding=SPACING.outer, style="AppShell.TFrame")
    shell.grid(row=0, column=0, sticky="nsew")
    shell.columnconfigure(0, weight=1)
    shell.rowconfigure(1, weight=1)

    top_bar = ttk.Frame(shell, style="AppShell.TFrame")
    top_bar.grid(row=0, column=0, sticky="ew", pady=(0, SPACING.inner))
    top_bar.columnconfigure(0, weight=1)
    title_var = tk.StringVar(value=config.title)
    image_var = tk.StringVar(value=config.image_label)
    ttk.Label(top_bar, textvariable=title_var, style="AppSectionTitle.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Label(top_bar, textvariable=image_var, style="AppMeta.TLabel").grid(row=1, column=0, sticky="w")

    body = ttk.Frame(shell, style="AppShell.TFrame")
    body.grid(row=1, column=0, sticky="nsew")
    body.columnconfigure(0, weight=1)
    body.columnconfigure(1, weight=0)
    body.rowconfigure(0, weight=1)

    canvas_shell = ttk.Frame(body, padding=SPACING.card, style="AppInset.TFrame")
    canvas_shell.grid(row=0, column=0, sticky="nsew", padx=(0, SPACING.inner))
    canvas_shell.columnconfigure(0, weight=1)
    canvas_shell.rowconfigure(0, weight=1)
    canvas = tk.Canvas(canvas_shell, width=760, height=620, bg="black", highlightthickness=0, cursor="cross")
    canvas.grid(row=0, column=0, sticky="nsew")

    side = ttk.Frame(body, width=270, style="AppSurface.TFrame")
    side.grid(row=0, column=1, sticky="ns")
    side.grid_propagate(False)

    destination_var = tk.StringVar(value=f"Saving to: {_roi_destination_label(config)}")
    state_var = tk.StringVar(value="")
    region_var = tk.StringVar(value="")
    points_var = tk.StringVar(value="")
    area_var = tk.StringVar(value="")
    instruction_var = tk.StringVar(value="Click the image to add points. Use Close Polygon when the region is complete.")

    ttk.Label(side, text="ROI Status", style="AppMeta.TLabel").pack(anchor="w", pady=(0, SPACING.inner))
    ttk.Label(side, textvariable=destination_var, style="AppMeta.TLabel", wraplength=250).pack(anchor="w", pady=(0, SPACING.gap))
    ttk.Label(side, textvariable=state_var, style="AppMeta.TLabel", wraplength=250).pack(anchor="w", pady=(0, SPACING.gap))
    ttk.Label(side, textvariable=region_var, style="AppMeta.TLabel", wraplength=250).pack(anchor="w", pady=(0, SPACING.gap))
    ttk.Label(side, textvariable=points_var, style="AppMeta.TLabel", wraplength=250).pack(anchor="w", pady=(0, SPACING.gap))
    ttk.Label(side, textvariable=area_var, style="AppMeta.TLabel", wraplength=250).pack(anchor="w", pady=(0, SPACING.outer))

    ttk.Separator(side, orient="horizontal").pack(fill="x", pady=(0, SPACING.inner))
    ttk.Label(side, textvariable=instruction_var, style="AppMeta.TLabel", wraplength=250).pack(anchor="w", pady=(0, SPACING.inner))

    state = {
        "regions": _normalize_roi_polygons(initial_roi_polygons, initial_roi_points),
        "closed_regions": set(),
        "active_region_idx": 0,
        "selected_idx": None,
        "dragging": False,
        "viewport_state": fit_viewport(img_w, img_h),
        "space_pan_requested": False,
        "pan_active": False,
        "pan_last_x": None,
        "pan_last_y": None,
        "viewport_initialized": False,
        "last_canvas_size": None,
    }
    if not state["regions"]:
        state["regions"] = [[]]
    else:
        state["closed_regions"] = {idx for idx, region in enumerate(state["regions"]) if len(region) >= 3}
    state["active_region_idx"] = max(0, min(int(state["active_region_idx"]), len(state["regions"]) - 1))

    buttons: dict[str, Any] = {}

    def active_region() -> list[tuple[int, int]]:
        return state["regions"][int(state["active_region_idx"])]

    def current_transform():
        return _compute_roi_transform(
            state,
            canvas_width=max(1, int(canvas.winfo_width())),
            canvas_height=max(1, int(canvas.winfo_height())),
            image_width=img_w,
            image_height=img_h,
        )

    def refocus_canvas():
        try:
            canvas.focus_set()
        except Exception:
            pass

    def event_to_image_xy(event):
        px, py = current_transform().canvas_to_image(event.x, event.y)
        return int(px), int(py)

    def has_closed_region() -> bool:
        return bool(_closed_region_indices(state["regions"], state["closed_regions"]))

    def has_drawn_content() -> bool:
        return any(region for region in state["regions"])

    def union_area() -> int:
        if not has_closed_region():
            return 0
        return int(np.count_nonzero(_build_roi_result(
            state["regions"],
            state["closed_regions"],
            image_shape=(img_h, img_w),
            target_scope="preview",
        )["roi_mask"]))

    def active_closed() -> bool:
        return int(state["active_region_idx"]) in state["closed_regions"]

    def refresh_controls():
        if not state["regions"]:
            state["regions"] = [[]]
            state["active_region_idx"] = 0
        active_idx = int(state["active_region_idx"])
        if active_idx >= len(state["regions"]):
            active_idx = max(0, len(state["regions"]) - 1)
            state["active_region_idx"] = active_idx
        region = active_region()
        closed_count = len(_closed_region_indices(state["regions"], state["closed_regions"]))
        state_var.set("Active polygon: Closed" if active_closed() else "Active polygon: Open")
        region_var.set(f"Regions: {closed_count} closed / {len(state['regions'])} total")
        points_var.set(f"Region {active_idx + 1} points: {len(region)}")
        area = union_area()
        area_var.set(f"ROI area: {area:,} px" if area > 0 else "ROI area: n/a")
        instruction_var.set(
            "Click an edge to insert a point. Drag points to adjust."
            if active_closed()
            else "Click the image to add points. Use Close Polygon when the region is complete."
        )
        if "close" in buttons:
            buttons["close"].configure(state="normal" if len(region) >= 3 and not active_closed() else "disabled")
        if "new" in buttons:
            buttons["new"].configure(state="normal" if has_closed_region() else "disabled")
        if "delete" in buttons:
            buttons["delete"].configure(state="normal" if state["selected_idx"] is not None else "disabled")
        if "delete_region" in buttons:
            buttons["delete_region"].configure(state="normal" if bool(region) else "disabled")
        for key, button in buttons.items():
            if key.startswith("save:"):
                button.configure(state="normal" if has_closed_region() else "disabled")

    def render_background():
        avail_w = max(1, int(canvas.winfo_width()))
        avail_h = max(1, int(canvas.winfo_height()))
        _clamp_roi_viewport(
            state,
            canvas_width=avail_w,
            canvas_height=avail_h,
            image_width=img_w,
            image_height=img_h,
        )
        transform = current_transform()
        pil_src = Image.fromarray(img_rgb)
        pil_canvas = pil_src.transform(
            (avail_w, avail_h),
            Image.Transform.AFFINE,
            data=(
                1.0 / float(transform.scale),
                0.0,
                -float(transform.offset_x) / float(transform.scale),
                0.0,
                1.0 / float(transform.scale),
                -float(transform.offset_y) / float(transform.scale),
            ),
            resample=_dialog_transform_resample(Image.Resampling.BICUBIC),
            fillcolor=(0, 0, 0),
        )
        tk_img = ImageTk.PhotoImage(pil_canvas)
        popup._tk_img = tk_img
        canvas.delete("bg")
        canvas.create_image(0, 0, image=tk_img, anchor="nw", tags="bg")
        canvas.tag_lower("bg")
        state["last_canvas_size"] = (avail_w, avail_h)
        state["viewport_initialized"] = True

    def redraw():
        canvas.delete("overlay")
        transform = current_transform()
        for region_idx, region in enumerate(state["regions"]):
            if not region:
                continue
            is_active = region_idx == int(state["active_region_idx"])
            color = "#00ff66" if is_active else "#61a8ff"
            for point_idx, (px, py) in enumerate(region):
                x, y = transform.image_to_canvas(px, py)
                selected = is_active and state["selected_idx"] == point_idx
                r = 7 if selected else 5
                outline = "yellow" if selected else color
                canvas.create_oval(x - r, y - r, x + r, y + r, fill=color, outline=outline, width=2 if selected else 1, tags="overlay")
            if len(region) >= 2:
                pts = []
                for px, py in region:
                    x, y = transform.image_to_canvas(px, py)
                    pts.extend([x, y])
                canvas.create_line(*pts, fill=color, width=2, tags="overlay")
            if len(region) >= 3:
                x0, y0 = region[0]
                x1, y1 = region[-1]
                cx0, cy0 = transform.image_to_canvas(x0, y0)
                cx1, cy1 = transform.image_to_canvas(x1, y1)
                canvas.create_line(
                    cx0,
                    cy0,
                    cx1,
                    cy1,
                    fill=color,
                    width=2 if region_idx in state["closed_regions"] else 1,
                    dash=() if region_idx in state["closed_regions"] else (3, 2),
                    tags="overlay",
                )
        refresh_controls()

    def nearest_point_idx(px, py, max_dist_px=None, *, region_idx=None):
        if region_idx is None:
            region_idx = int(state["active_region_idx"])
        region = state["regions"][int(region_idx)] if 0 <= int(region_idx) < len(state["regions"]) else []
        if not region:
            return None
        if max_dist_px is None:
            max_dist_px = _canvas_radius_to_image_radius(current_transform().scale, 10.0)
        best_idx = None
        best_d2 = (max_dist_px**2) + 1
        for idx, (x, y) in enumerate(region):
            d2 = (x - px) ** 2 + (y - py) ** 2
            if d2 < best_d2:
                best_d2 = d2
                best_idx = idx
        return best_idx if best_d2 <= (max_dist_px**2) else None

    def nearest_point_hit(px, py, max_dist_px=None):
        if max_dist_px is None:
            max_dist_px = _canvas_radius_to_image_radius(current_transform().scale, 10.0)
        best_region = None
        best_point = None
        best_d2 = (max_dist_px**2) + 1
        for region_idx, region in enumerate(state["regions"]):
            for point_idx, (x, y) in enumerate(region):
                d2 = (x - px) ** 2 + (y - py) ** 2
                if d2 < best_d2:
                    best_d2 = d2
                    best_region = region_idx
                    best_point = point_idx
        if best_region is None or best_d2 > (max_dist_px**2):
            return None
        return int(best_region), int(best_point)

    def dist_point_to_segment(px, py, ax, ay, bx, by):
        abx = bx - ax
        aby = by - ay
        apx = px - ax
        apy = py - ay
        ab2 = abx * abx + aby * aby
        if ab2 == 0:
            return np.hypot(px - ax, py - ay), 0.0
        t = max(0.0, min(1.0, (apx * abx + apy * aby) / ab2))
        cx = ax + t * abx
        cy = ay + t * aby
        return np.hypot(px - cx, py - cy), t

    def nearest_segment_insert_idx(px, py, max_dist_px=None, *, region_idx=None):
        if region_idx is None:
            region_idx = int(state["active_region_idx"])
        region_idx = int(region_idx)
        region = state["regions"][region_idx] if 0 <= region_idx < len(state["regions"]) else []
        if region_idx not in state["closed_regions"] or len(region) < 3:
            return None
        if max_dist_px is None:
            max_dist_px = _canvas_radius_to_image_radius(current_transform().scale, 8.0)
        best = None
        best_dist = max_dist_px + 1
        for idx in range(len(region)):
            a = region[idx]
            b = region[(idx + 1) % len(region)]
            dist, _ = dist_point_to_segment(px, py, a[0], a[1], b[0], b[1])
            if dist < best_dist:
                best_dist = dist
                best = idx + 1
        return best if best_dist <= max_dist_px else None

    def nearest_segment_hit(px, py, max_dist_px=None):
        if max_dist_px is None:
            max_dist_px = _canvas_radius_to_image_radius(current_transform().scale, 8.0)
        best_region = None
        best_insert = None
        best_dist = max_dist_px + 1
        for region_idx, region in enumerate(state["regions"]):
            if region_idx not in state["closed_regions"] or len(region) < 3:
                continue
            for idx in range(len(region)):
                a = region[idx]
                b = region[(idx + 1) % len(region)]
                dist, _ = dist_point_to_segment(px, py, a[0], a[1], b[0], b[1])
                if dist < best_dist:
                    best_dist = dist
                    best_region = region_idx
                    best_insert = idx + 1
        if best_region is None or best_dist > max_dist_px:
            return None
        return int(best_region), int(best_insert)

    def start_new_region_with_point(px, py):
        state["regions"].append([(px, py)])
        state["active_region_idx"] = len(state["regions"]) - 1
        state["selected_idx"] = 0
        state["dragging"] = True

    def on_click(event):
        refocus_canvas()
        if state["pan_active"]:
            return "break"
        px, py = event_to_image_xy(event)
        if not (0 <= px < img_w and 0 <= py < img_h):
            return None
        point_hit = nearest_point_hit(px, py)
        if point_hit is not None:
            region_idx, point_idx = point_hit
            state["active_region_idx"] = region_idx
            state["selected_idx"] = point_idx
            state["dragging"] = True
        else:
            segment_hit = nearest_segment_hit(px, py)
            if segment_hit is not None:
                region_idx, insert_idx = segment_hit
                state["active_region_idx"] = region_idx
                state["regions"][region_idx].insert(insert_idx, (px, py))
                state["selected_idx"] = insert_idx
                state["dragging"] = True
            elif active_closed():
                start_new_region_with_point(px, py)
            else:
                region = active_region()
                region.append((px, py))
                state["selected_idx"] = len(region) - 1
                state["dragging"] = True
        redraw()
        return None

    def on_drag(event):
        refocus_canvas()
        if state["pan_active"]:
            return "break"
        if state["selected_idx"] is None:
            return None
        px, py = event_to_image_xy(event)
        px = max(0, min(px, img_w - 1))
        py = max(0, min(py, img_h - 1))
        active_region()[int(state["selected_idx"])] = (px, py)
        redraw()
        return None

    def on_release(_event):
        if state["pan_active"]:
            state["pan_active"] = False
            state["pan_last_x"] = None
            state["pan_last_y"] = None
            canvas.config(cursor="cross")
            return "break"
        state["dragging"] = False
        redraw()
        return None

    def close_active_region():
        region = active_region()
        if len(region) < 3:
            messagebox.showwarning("ROI", "Need at least 3 points to close this ROI region.", parent=popup)
            return
        state["closed_regions"].add(int(state["active_region_idx"]))
        state["selected_idx"] = None
        redraw()

    def on_double_click(event):
        if active_closed() or len(active_region()) < 3:
            return None
        px, py = event_to_image_xy(event)
        first_idx = nearest_point_idx(
            px,
            py,
            max_dist_px=_canvas_radius_to_image_radius(current_transform().scale, 10.0),
        )
        if first_idx == 0:
            close_active_region()
        return None

    def on_enter(_event=None):
        if not active_closed() and len(active_region()) >= 3:
            close_active_region()
            return "break"
        if has_closed_region() and len(_roi_save_actions(config)) == 1:
            on_finish(_roi_save_actions(config)[0][0])
            return "break"
        return None

    def on_mouse_wheel(event):
        refocus_canvas()
        delta = getattr(event, "delta", 0)
        num = getattr(event, "num", None)
        direction = 0
        if delta:
            direction = 1 if float(delta) > 0 else -1
        elif num in (4, 5):
            direction = 1 if int(num) == 4 else -1
        if direction == 0:
            return None
        current_state = state["viewport_state"]
        step = 1.25 if direction > 0 else (1.0 / 1.25)
        state["viewport_state"] = zoom_viewport_at(
            current_state,
            image_width=img_w,
            image_height=img_h,
            canvas_width=max(1, int(canvas.winfo_width())),
            canvas_height=max(1, int(canvas.winfo_height())),
            anchor_canvas_x=float(getattr(event, "x", canvas.winfo_width() / 2.0)),
            anchor_canvas_y=float(getattr(event, "y", canvas.winfo_height() / 2.0)),
            new_zoom_factor=float(current_state.zoom_factor) * float(step),
            shared_canvas_sizes=[(max(1, int(canvas.winfo_width())), max(1, int(canvas.winfo_height())))],
        )
        render_background()
        redraw()
        return "break"

    def set_space_pan_active(_event=None):
        refocus_canvas()
        state["space_pan_requested"] = True
        try:
            canvas.config(cursor="fleur")
        except Exception:
            pass
        return "break"

    def clear_space_pan_active(_event=None):
        state["space_pan_requested"] = False
        if not state["pan_active"]:
            try:
                canvas.config(cursor="cross")
            except Exception:
                pass
        return "break"

    def start_pan(event):
        if not bool(state["space_pan_requested"]):
            return None
        refocus_canvas()
        state["pan_active"] = True
        state["selected_idx"] = None
        state["dragging"] = False
        state["pan_last_x"] = float(event.x)
        state["pan_last_y"] = float(event.y)
        canvas.config(cursor="fleur")
        return "break"

    def drag_pan(event):
        if not state["pan_active"]:
            return None
        last_x = state["pan_last_x"]
        last_y = state["pan_last_y"]
        if last_x is None or last_y is None:
            state["pan_last_x"] = float(event.x)
            state["pan_last_y"] = float(event.y)
            return "break"
        dx = float(event.x) - float(last_x)
        dy = float(event.y) - float(last_y)
        state["pan_last_x"] = float(event.x)
        state["pan_last_y"] = float(event.y)
        state["viewport_state"] = pan_viewport(
            state["viewport_state"],
            image_width=img_w,
            image_height=img_h,
            canvas_width=max(1, int(canvas.winfo_width())),
            canvas_height=max(1, int(canvas.winfo_height())),
            delta_canvas_x=dx,
            delta_canvas_y=dy,
            shared_canvas_sizes=[(max(1, int(canvas.winfo_width())), max(1, int(canvas.winfo_height())))],
        )
        render_background()
        redraw()
        return "break"

    def on_canvas_configure(_event=None):
        width = max(1, int(canvas.winfo_width()))
        height = max(1, int(canvas.winfo_height()))
        previous_size = state.get("last_canvas_size")
        if state.get("viewport_initialized") and previous_size and tuple(previous_size) != (width, height):
            old_w, old_h = int(previous_size[0]), int(previous_size[1])
            old_transform = compute_transform(
                state["viewport_state"],
                canvas_width=max(1, old_w),
                canvas_height=max(1, old_h),
                image_width=img_w,
                image_height=img_h,
            )
            next_fit = compute_fit_scale(width, height, img_w, img_h)
            if next_fit > 1e-9:
                current = state["viewport_state"]
                state["viewport_state"] = ViewportState(
                    center_x=float(current.center_x),
                    center_y=float(current.center_y),
                    zoom_factor=max(float(current.min_zoom), min(float(current.max_zoom), old_transform.scale / float(next_fit))),
                    min_zoom=float(current.min_zoom),
                    max_zoom=float(current.max_zoom),
                )
                _clamp_roi_viewport(
                    state,
                    canvas_width=width,
                    canvas_height=height,
                    image_width=img_w,
                    image_height=img_h,
                )
        render_background()
        redraw()

    def zoom_in():
        width = max(1, int(canvas.winfo_width()))
        height = max(1, int(canvas.winfo_height()))
        state["viewport_state"] = zoom_viewport_at(
            state["viewport_state"],
            image_width=img_w,
            image_height=img_h,
            canvas_width=width,
            canvas_height=height,
            anchor_canvas_x=width / 2.0,
            anchor_canvas_y=height / 2.0,
            new_zoom_factor=float(state["viewport_state"].zoom_factor) * 1.25,
            shared_canvas_sizes=[(width, height)],
        )
        render_background()
        redraw()

    def zoom_out():
        width = max(1, int(canvas.winfo_width()))
        height = max(1, int(canvas.winfo_height()))
        state["viewport_state"] = zoom_viewport_at(
            state["viewport_state"],
            image_width=img_w,
            image_height=img_h,
            canvas_width=width,
            canvas_height=height,
            anchor_canvas_x=width / 2.0,
            anchor_canvas_y=height / 2.0,
            new_zoom_factor=float(state["viewport_state"].zoom_factor) / 1.25,
            shared_canvas_sizes=[(width, height)],
        )
        render_background()
        redraw()

    def reset_view():
        state["viewport_state"] = fit_viewport(img_w, img_h)
        render_background()
        redraw()

    def on_undo():
        region = active_region()
        if region:
            region.pop()
            state["selected_idx"] = None
            if len(region) < 3:
                state["closed_regions"].discard(int(state["active_region_idx"]))
            redraw()

    def on_new_region():
        if not has_closed_region():
            return
        state["regions"].append([])
        state["active_region_idx"] = len(state["regions"]) - 1
        state["selected_idx"] = None
        redraw()

    def on_clear():
        if has_drawn_content() and not _call_preserving_geometry(
            popup,
            lambda: messagebox.askyesno("Clear All ROIs", "Clear all ROI regions?", parent=popup),
        ):
            return
        state["regions"] = [[]]
        state["closed_regions"] = set()
        state["active_region_idx"] = 0
        state["selected_idx"] = None
        redraw()

    def on_change_image():
        nonlocal img_u8, img_rgb, img_w, img_h
        if not callable(pick_image_callback):
            return
        if has_drawn_content() and not _call_preserving_geometry(
            popup,
            lambda: messagebox.askyesno(
                "Change Image",
                "Changing the image clears the current ROI regions. Continue?",
                parent=popup,
            ),
        ):
            return
        def pick():
            try:
                return pick_image_callback(popup)
            except TypeError:
                return pick_image_callback()

        new_img = _call_preserving_geometry(popup, pick)
        if new_img is None:
            return
        img_u8 = new_img
        img_rgb = cv2.cvtColor(img_u8, cv2.COLOR_GRAY2RGB)
        img_h, img_w = img_u8.shape[:2]
        state["regions"] = [[]]
        state["closed_regions"] = set()
        state["active_region_idx"] = 0
        state["selected_idx"] = None
        state["viewport_state"] = fit_viewport(img_w, img_h)
        image_var.set(config.image_label)
        render_background()
        redraw()

    def on_delete_selected():
        if state["selected_idx"] is None:
            return
        del active_region()[int(state["selected_idx"])]
        state["selected_idx"] = None
        if len(active_region()) < 3:
            state["closed_regions"].discard(int(state["active_region_idx"]))
        redraw()

    def on_delete_active_region():
        region_idx = int(state["active_region_idx"])
        if region_idx < 0 or region_idx >= len(state["regions"]) or not state["regions"][region_idx]:
            return
        if not _call_preserving_geometry(
            popup,
            lambda: messagebox.askyesno(
                "Delete Selected ROI",
                f"Delete ROI region {region_idx + 1}?",
                parent=popup,
            ),
        ):
            return
        del state["regions"][region_idx]
        state["closed_regions"] = {
            idx if idx < region_idx else idx - 1
            for idx in state["closed_regions"]
            if idx != region_idx
        }
        if not state["regions"]:
            state["regions"] = [[]]
            state["closed_regions"] = set()
            state["active_region_idx"] = 0
        else:
            state["active_region_idx"] = min(region_idx, len(state["regions"]) - 1)
        state["selected_idx"] = None
        state["dragging"] = False
        redraw()

    def on_cancel(_event=None):
        has_points = any(len(r) > 0 for r in state["regions"])
        if has_points:
            if not messagebox.askyesno("Discard Changes", "Discard unsaved points?", parent=popup):
                return
        popup.destroy()

    popup.protocol("WM_DELETE_WINDOW", on_cancel)
    popup.bind("<Escape>", on_cancel, add="+")

    def on_finish(target_scope: str):
        if not has_closed_region():
            if len(active_region()) >= 3:
                close_active_region()
            else:
                messagebox.showwarning("ROI", "Close at least one ROI region before saving.", parent=popup)
                return
        result["value"] = _build_roi_result(
            state["regions"],
            state["closed_regions"],
            image_shape=(img_h, img_w),
            target_scope=target_scope,
        )
        popup.destroy()

    canvas.bind("<Button-1>", start_pan, add="+")
    canvas.bind("<Button-1>", on_click, add="+")
    canvas.bind("<B1-Motion>", drag_pan, add="+")
    canvas.bind("<B1-Motion>", on_drag, add="+")
    canvas.bind("<ButtonRelease-1>", on_release)
    canvas.bind("<Double-Button-1>", on_double_click)
    canvas.bind("<Configure>", on_canvas_configure)
    canvas.bind("<MouseWheel>", on_mouse_wheel)
    canvas.bind("<Button-4>", on_mouse_wheel)
    canvas.bind("<Button-5>", on_mouse_wheel)

    if callable(pick_image_callback):
        ttk.Button(top_bar, text="Change Image", command=on_change_image, **semantic_button_options("secondary")).grid(
            row=0, column=1, rowspan=2, sticky="e"
        )

    controls = ttk.Frame(side, style="AppSurface.TFrame")
    controls.pack(fill="x", pady=(0, SPACING.inner))
    buttons["close"] = ttk.Button(controls, text="Close Polygon", command=close_active_region, **semantic_button_options("primary"))
    buttons["close"].pack(fill="x", pady=(0, SPACING.gap))
    buttons["new"] = ttk.Button(controls, text="New Region", command=on_new_region, **semantic_button_options("secondary"))
    buttons["new"].pack(fill="x", pady=(0, SPACING.gap))
    ttk.Button(controls, text="Undo Point", command=on_undo, **semantic_button_options("secondary")).pack(fill="x", pady=(0, SPACING.gap))
    buttons["delete"] = ttk.Button(controls, text="Delete Point", command=on_delete_selected, **semantic_button_options("secondary"))
    buttons["delete"].pack(fill="x", pady=(0, SPACING.gap))
    buttons["delete_region"] = ttk.Button(
        controls,
        text="Delete Selected ROI",
        command=on_delete_active_region,
        **semantic_button_options("danger"),
    )
    buttons["delete_region"].pack(fill="x", pady=(0, SPACING.gap))
    ttk.Button(controls, text="Clear All ROIs", command=on_clear, **semantic_button_options("danger")).pack(fill="x", pady=(0, SPACING.gap))

    zoom_row = ttk.Frame(side, style="AppSurface.TFrame")
    zoom_row.pack(fill="x", pady=(SPACING.inner, 0))
    zoom_in_btn = ttk.Button(zoom_row, text=ROI_ICON_LABELS["zoom_in"], width=10, command=zoom_in, **semantic_button_options("secondary"))
    zoom_in_btn.pack(side="left", padx=(0, SPACING.gap))
    _attach_tooltip(zoom_in_btn, "Zoom in")
    zoom_out_btn = ttk.Button(zoom_row, text=ROI_ICON_LABELS["zoom_out"], width=10, command=zoom_out, **semantic_button_options("secondary"))
    zoom_out_btn.pack(side="left", padx=(0, SPACING.gap))
    _attach_tooltip(zoom_out_btn, "Zoom out")
    fit_btn = ttk.Button(zoom_row, text=ROI_ICON_LABELS["fit"], width=10, command=reset_view, **semantic_button_options("secondary"))
    fit_btn.pack(side="left")
    _attach_tooltip(fit_btn, "Fit image")

    actions = ttk.Frame(shell, style="AppShell.TFrame")
    actions.grid(row=2, column=0, sticky="ew", pady=(SPACING.inner, 0))
    ttk.Button(actions, text="Cancel", command=on_cancel, **semantic_button_options("secondary")).pack(side="right")
    for scope, label, kind in _roi_save_actions(config):
        button = ttk.Button(actions, text=label, command=lambda s=scope: on_finish(s), **semantic_button_options(kind))
        button.pack(side="right", padx=(0, SPACING.gap))
        buttons[f"save:{scope}"] = button
    if bool(config.allow_reset_local):
        ttk.Button(
            actions,
            text="Use Global ROI",
            command=lambda: (result.__setitem__("value", {"target_scope": "reset_local_roi"}), popup.destroy()),
            **semantic_button_options("secondary"),
        ).pack(side="right", padx=(0, SPACING.gap))

    popup.bind("<KeyPress-space>", set_space_pan_active, add="+")
    popup.bind("<space>", set_space_pan_active, add="+")
    popup.bind("<KeyRelease-space>", clear_space_pan_active, add="+")
    popup.bind("<Return>", on_enter, add="+")
    canvas.bind("<KeyPress-space>", set_space_pan_active, add="+")
    canvas.bind("<space>", set_space_pan_active, add="+")
    canvas.bind("<KeyRelease-space>", clear_space_pan_active, add="+")
    canvas.bind("<Return>", on_enter, add="+")
    popup.bind("<Key-plus>", lambda _e: (zoom_in(), "break")[1], add="+")
    popup.bind("<Key-equal>", lambda _e: (zoom_in(), "break")[1], add="+")
    popup.bind("<Key-minus>", lambda _e: (zoom_out(), "break")[1], add="+")
    popup.bind("<Key-underscore>", lambda _e: (zoom_out(), "break")[1], add="+")
    popup.bind("<Key-0>", lambda _e: (reset_view(), "break")[1], add="+")

    center_window_on_screen(popup, width=1120, height=820)
    popup.deiconify()
    popup.update_idletasks()
    render_background()
    redraw()
    refocus_canvas()
    popup.grab_set()
    popup.wait_window()
    return result["value"]
