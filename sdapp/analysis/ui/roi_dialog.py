import tkinter as tk
from tkinter import messagebox

import cv2
import numpy as np
from PIL import Image, ImageTk

from sdapp.analysis.core.viewport import (
    ViewportState,
    clamp_viewport_center,
    compute_transform,
    fit_viewport,
    zoom_viewport_at,
    pan_viewport,
)
from sdapp.analysis.ui.theme import SPACING, apply_theme
from sdapp.shared.ui.bootstrap import center_window_on_screen, semantic_button_options, ttk

ROI_ICON_LABELS = {
    "zoom_in": "+",
    "zoom_out": "-",
    "fit": "□",
}


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


def open_roi_dialog(root, img_u8, initial_roi_points=None, allow_reset_local=False, pick_image_callback=None):
    popup = tk.Toplevel(root)
    popup.withdraw()
    popup.title("Draw ROI - First Original Frame")
    popup.resizable(True, True)
    popup.geometry("1080x860")
    popup.minsize(900, 760)
    apply_theme(popup)
    popup.columnconfigure(0, weight=1)
    popup.rowconfigure(0, weight=1)

    img_h, img_w = img_u8.shape[:2]
    max_w, max_h = 900, 700
    img_rgb = cv2.cvtColor(img_u8, cv2.COLOR_GRAY2RGB)
    base_ratio = min(max_w / img_w, max_h / img_h, 1.0)
    initial_w = max(1, int(round(img_w * base_ratio)))
    initial_h = max(1, int(round(img_h * base_ratio)))

    shell = ttk.Frame(popup, padding=SPACING.outer, style="AppShell.TFrame")
    shell.grid(row=0, column=0, sticky="nsew")
    shell.columnconfigure(0, weight=1)
    shell.rowconfigure(0, weight=1)
    shell.rowconfigure(1, weight=0)

    canvas_shell = ttk.Frame(shell, padding=SPACING.card, style="AppInset.TFrame")
    canvas_shell.grid(row=0, column=0, sticky="nsew")
    canvas_shell.columnconfigure(0, weight=1)
    canvas_shell.rowconfigure(0, weight=1)
    canvas = tk.Canvas(canvas_shell, width=initial_w, height=initial_h, bg="black", highlightthickness=0)
    canvas.grid(row=0, column=0, sticky="nsew")

    points_seed = list(initial_roi_points) if initial_roi_points else []
    state = {
        "points": points_seed,
        "selected_idx": None,
        "closed": bool(points_seed),
        "dragging": False,
        "viewport_state": fit_viewport(img_w, img_h),
        "space_pan_requested": False,
        "pan_active": False,
        "pan_last_x": None,
        "pan_last_y": None,
    }
    result = {"value": None}

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

    def image_to_canvas_xy(px, py):
        return current_transform().image_to_canvas(px, py)

    def event_to_image_xy(event):
        px, py = current_transform().canvas_to_image(event.x, event.y)
        px = int(px)
        py = int(py)
        return px, py

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

    def redraw():
        canvas.delete("overlay")
        if not state["points"]:
            return
        transform = current_transform()
        for i, (px, py) in enumerate(state["points"]):
            x, y = transform.image_to_canvas(px, py)
            if state["selected_idx"] == i:
                canvas.create_oval(x - 7, y - 7, x + 7, y + 7, fill="#00ff66", outline="yellow", width=2, tags="overlay")
            else:
                canvas.create_oval(x - 5, y - 5, x + 5, y + 5, fill="#00ff66", outline="#00ff66", tags="overlay")
        if len(state["points"]) >= 2:
            pts = []
            for px, py in state["points"]:
                x, y = transform.image_to_canvas(px, py)
                pts.extend([x, y])
            canvas.create_line(*pts, fill="#00ff66", width=2, tags="overlay")
            if len(state["points"]) >= 3 and state["closed"]:
                x0, y0 = state["points"][0]
                x1, y1 = state["points"][-1]
                cx0, cy0 = transform.image_to_canvas(x0, y0)
                cx1, cy1 = transform.image_to_canvas(x1, y1)
                canvas.create_line(
                    cx0,
                    cy0,
                    cx1,
                    cy1,
                    fill="#00ff66",
                    width=2,
                    tags="overlay",
                )
            elif len(state["points"]) >= 3:
                x0, y0 = state["points"][0]
                x1, y1 = state["points"][-1]
                cx0, cy0 = transform.image_to_canvas(x0, y0)
                cx1, cy1 = transform.image_to_canvas(x1, y1)
                canvas.create_line(
                    cx0,
                    cy0,
                    cx1,
                    cy1,
                    fill="#00ff66",
                    width=1,
                    dash=(3, 2),
                    tags="overlay",
                )

    def nearest_point_idx(px, py, max_dist_px=None):
        if not state["points"]:
            return None
        if max_dist_px is None:
            max_dist_px = _canvas_radius_to_image_radius(current_transform().scale, 10.0)
        best_idx = None
        best_d2 = (max_dist_px**2) + 1
        for i, (x, y) in enumerate(state["points"]):
            d2 = (x - px) ** 2 + (y - py) ** 2
            if d2 < best_d2:
                best_d2 = d2
                best_idx = i
        return best_idx if best_d2 <= (max_dist_px**2) else None

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

    def nearest_segment_insert_idx(px, py, max_dist_px=None):
        if not state["closed"] or len(state["points"]) < 3:
            return None
        if max_dist_px is None:
            max_dist_px = _canvas_radius_to_image_radius(current_transform().scale, 8.0)
        best = None
        best_dist = max_dist_px + 1
        n = len(state["points"])
        for i in range(n):
            a = state["points"][i]
            b = state["points"][(i + 1) % n]
            d, _ = dist_point_to_segment(px, py, a[0], a[1], b[0], b[1])
            if d < best_dist:
                best_dist = d
                best = i + 1
        return best if best_dist <= max_dist_px else None

    def on_click(event):
        refocus_canvas()
        if state["pan_active"]:
            return "break"
        px, py = event_to_image_xy(event)
        if not (0 <= px < img_w and 0 <= py < img_h):
            return
        idx = nearest_point_idx(px, py)
        if idx is not None:
            state["selected_idx"] = idx
            state["dragging"] = True
        else:
            if state["closed"]:
                insert_idx = nearest_segment_insert_idx(px, py)
                if insert_idx is not None:
                    state["points"].insert(insert_idx, (px, py))
                    state["selected_idx"] = insert_idx
                    state["dragging"] = True
                else:
                    state["selected_idx"] = None
                    state["dragging"] = False
            else:
                state["points"].append((px, py))
                state["selected_idx"] = len(state["points"]) - 1
                state["dragging"] = True
        redraw()

    def on_drag(event):
        refocus_canvas()
        if state["pan_active"]:
            return "break"
        if state["selected_idx"] is None:
            return
        px, py = event_to_image_xy(event)
        px = max(0, min(px, img_w - 1))
        py = max(0, min(py, img_h - 1))
        state["points"][state["selected_idx"]] = (px, py)
        redraw()

    def on_release(_event):
        if state["pan_active"]:
            state["pan_active"] = False
            state["pan_last_x"] = None
            state["pan_last_y"] = None
            canvas.config(cursor="cross")
            return "break"
        state["dragging"] = False
        redraw()

    def on_double_click(event):
        if state["closed"]:
            return
        if len(state["points"]) < 3:
            return
        px, py = event_to_image_xy(event)
        first_idx = nearest_point_idx(
            px,
            py,
            max_dist_px=_canvas_radius_to_image_radius(current_transform().scale, 10.0),
        )
        if first_idx == 0:
            state["closed"] = True
            state["selected_idx"] = 0
            redraw()

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
        if state["points"]:
            state["points"].pop()
            state["selected_idx"] = None
            if len(state["points"]) < 3:
                state["closed"] = False
            redraw()

    def on_clear():
        state["points"] = []
        state["selected_idx"] = None
        state["closed"] = False
        redraw()

    def on_change_image():
        nonlocal img_u8, img_rgb, img_w, img_h
        if not callable(pick_image_callback):
            return
        new_img = pick_image_callback()
        if new_img is None:
            return
        img_u8 = new_img
        img_rgb = cv2.cvtColor(img_u8, cv2.COLOR_GRAY2RGB)
        img_h, img_w = img_u8.shape[:2]
        state["points"] = []
        state["selected_idx"] = None
        state["closed"] = False
        state["viewport_state"] = fit_viewport(img_w, img_h)
        render_background()
        redraw()

    def on_delete_selected():
        if state["selected_idx"] is None:
            return
        del state["points"][state["selected_idx"]]
        state["selected_idx"] = None
        redraw()

    def on_finish(target_scope: str):
        if len(state["points"]) < 3:
            messagebox.showwarning("ROI", "Need at least 3 points to create ROI.", parent=popup)
            return
        if not state["closed"]:
            messagebox.showwarning(
                "ROI",
                "Double-click the first point to close the ROI before saving.",
                parent=popup,
            )
            return
        roi_mask = np.zeros((img_h, img_w), dtype=np.uint8)
        pts = np.array(state["points"], dtype=np.int32).reshape((-1, 1, 2))
        cv2.fillPoly(roi_mask, [pts], 1)
        result["value"] = {
            "target_scope": str(target_scope),
            "roi_mask": roi_mask.astype(bool),
            "roi_points": list(state["points"]),
        }
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
    controls = ttk.Frame(shell, padding=(0, SPACING.inner, 0, 0), style="AppSurface.TFrame")
    controls.grid(row=1, column=0, sticky="ew")
    ttk.Label(
        controls,
        text="Click to add/select points. Double-click first point to close. Drag to move. Click edge to insert. Wheel zooms. Space-drag pans.",
        style="AppMeta.TLabel",
    ).pack(side="top", anchor="w", pady=(0, 4))
    button_opts = {"takefocus": False}
    left_controls = ttk.Frame(controls, style="AppSurface.TFrame")
    left_controls.pack(side="left")
    if callable(pick_image_callback):
        ttk.Button(left_controls, text="Change Image", command=on_change_image, **button_opts, **semantic_button_options("secondary")).pack(side="left", padx=(0, SPACING.gap))
    ttk.Button(left_controls, text="Undo Point", command=on_undo, **button_opts, **semantic_button_options("secondary")).pack(side="left", padx=(0, SPACING.gap))
    ttk.Button(left_controls, text="Delete Selected", command=on_delete_selected, **button_opts, **semantic_button_options("secondary")).pack(side="left", padx=(0, SPACING.gap))
    ttk.Button(left_controls, text="Clear", command=on_clear, **button_opts, **semantic_button_options("secondary")).pack(side="left", padx=(0, SPACING.gap))
    ttk.Button(left_controls, text=ROI_ICON_LABELS["zoom_in"], width=3, command=zoom_in, **button_opts, **semantic_button_options("secondary")).pack(side="left", padx=(SPACING.inner, SPACING.gap))
    ttk.Button(left_controls, text=ROI_ICON_LABELS["zoom_out"], width=3, command=zoom_out, **button_opts, **semantic_button_options("secondary")).pack(side="left", padx=(0, SPACING.gap))
    ttk.Button(left_controls, text=ROI_ICON_LABELS["fit"], width=3, command=reset_view, **button_opts, **semantic_button_options("secondary")).pack(side="left")
    right_controls = ttk.Frame(controls, style="AppSurface.TFrame")
    right_controls.pack(side="right")
    ttk.Button(right_controls, text="Cancel", command=popup.destroy, **button_opts, **semantic_button_options("secondary")).pack(side="right")
    if bool(allow_reset_local):
        ttk.Button(
            right_controls,
            text="Use Global ROI",
            command=lambda: (result.__setitem__("value", {"target_scope": "reset_local_roi"}), popup.destroy()),
            **button_opts,
            **semantic_button_options("secondary"),
        ).pack(side="right", padx=(0, SPACING.gap))
    ttk.Button(right_controls, text="Save Local ROI", command=lambda: on_finish("local"), **button_opts, **semantic_button_options("secondary")).pack(side="right", padx=(0, SPACING.gap))
    ttk.Button(right_controls, text="Save Global ROI", command=lambda: on_finish("global"), **button_opts, **semantic_button_options("primary")).pack(side="right", padx=(0, SPACING.gap))
    popup.bind("<KeyPress-space>", set_space_pan_active, add="+")
    popup.bind("<space>", set_space_pan_active, add="+")
    popup.bind("<KeyRelease-space>", clear_space_pan_active, add="+")
    canvas.bind("<KeyPress-space>", set_space_pan_active, add="+")
    canvas.bind("<space>", set_space_pan_active, add="+")
    canvas.bind("<KeyRelease-space>", clear_space_pan_active, add="+")
    popup.bind("<Key-plus>", lambda _e: (zoom_in(), "break")[1], add="+")
    popup.bind("<Key-equal>", lambda _e: (zoom_in(), "break")[1], add="+")
    popup.bind("<Key-minus>", lambda _e: (zoom_out(), "break")[1], add="+")
    popup.bind("<Key-underscore>", lambda _e: (zoom_out(), "break")[1], add="+")
    popup.bind("<Key-0>", lambda _e: (reset_view(), "break")[1], add="+")

    render_background()
    redraw()
    refocus_canvas()
    center_window_on_screen(popup, width=1080, height=860)
    popup.deiconify()
    popup.grab_set()
    popup.wait_window()
    return result["value"]
