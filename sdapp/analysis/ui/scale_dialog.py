import tkinter as tk
from tkinter import messagebox, simpledialog

import cv2
import numpy as np
from PIL import Image, ImageTk

from sdapp.analysis.ui.theme import SPACING, apply_theme
from sdapp.shared.ui.bootstrap import center_window_on_screen, semantic_button_options, ttk


def open_scale_dialog(root, img_u8, snap_scale_points_axis, refine_scale_bar_points, compute_scale, initial_scale_points=None):
    popup = tk.Toplevel(root)
    popup.withdraw()
    popup.title("Set Scale - First Original Frame")
    popup.resizable(True, True)
    popup.geometry("1080x860")
    popup.minsize(900, 760)
    apply_theme(popup)
    popup.columnconfigure(0, weight=1)
    popup.rowconfigure(0, weight=1)

    shell = ttk.Frame(popup, padding=SPACING.outer, style="AppShell.TFrame")
    shell.grid(row=0, column=0, sticky="nsew")
    shell.columnconfigure(0, weight=1)
    shell.rowconfigure(0, weight=1)
    shell.rowconfigure(1, weight=0)

    img_h, img_w = img_u8.shape[:2]
    max_w, max_h = 900, 700
    initial_fit_ratio = min(max_w / img_w, max_h / img_h, 1.0)

    canvas_shell = ttk.Frame(shell, padding=SPACING.card, style="Inset.TFrame")
    canvas_shell.grid(row=0, column=0, sticky="nsew")
    x_scroll = ttk.Scrollbar(canvas_shell, orient="horizontal")
    y_scroll = ttk.Scrollbar(canvas_shell, orient="vertical")
    canvas = tk.Canvas(
        canvas_shell,
        width=max_w,
        height=max_h,
        bg="black",
        xscrollcommand=x_scroll.set,
        yscrollcommand=y_scroll.set,
    )
    x_scroll.config(command=canvas.xview)
    y_scroll.config(command=canvas.yview)
    canvas.grid(row=0, column=0, sticky="nsew")
    y_scroll.grid(row=0, column=1, sticky="ns")
    x_scroll.grid(row=1, column=0, sticky="ew")
    canvas_shell.rowconfigure(0, weight=1)
    canvas_shell.columnconfigure(0, weight=1)

    marker_radius_canvas_px = 10.0
    preview_linewidth_px = 17
    zoom_step = 1.25
    zoom_min = 1.0
    zoom_max = 12.0

    tool_mode_var = tk.StringVar(value="edit")
    axis_lock_var = tk.BooleanVar(value=True)
    points_seed = []
    if isinstance(initial_scale_points, list) and len(initial_scale_points) >= 2:
        for pt in list(initial_scale_points)[:2]:
            if not isinstance(pt, (list, tuple)) or len(pt) < 2:
                points_seed = []
                break
            try:
                px = int(np.clip(round(float(pt[0])), 0, img_w - 1))
                py = int(np.clip(round(float(pt[1])), 0, img_h - 1))
            except Exception:
                points_seed = []
                break
            points_seed.append((px, py))

    state = {
        "points": points_seed,
        "preview": None,
        "dragging_idx": None,
        "is_panning": False,
        "hit_radius_canvas_px": 14.0,
        "zoom_factor": 1.0,
        "fit_ratio": initial_fit_ratio,
        "offset_x": 0.0,
        "offset_y": 0.0,
    }
    result = {"value": None}

    def get_scale():
        return max(1e-6, float(state["fit_ratio"]) * float(state["zoom_factor"]))

    def event_to_image_xy(event):
        s = get_scale()
        px = int((canvas.canvasx(event.x) - float(state["offset_x"])) / s)
        py = int((canvas.canvasy(event.y) - float(state["offset_y"])) / s)
        return px, py

    def image_to_canvas_xy(px, py):
        s = get_scale()
        return float(state["offset_x"]) + float(px) * s, float(state["offset_y"]) + float(py) * s

    def current_hit_radius_img():
        zoom_mult = max(1.0, float(state["zoom_factor"]))
        point_radius_canvas = min(24.0, marker_radius_canvas_px * zoom_mult)
        hit_radius_canvas = point_radius_canvas + 6.0
        return hit_radius_canvas / get_scale()

    def nearest_scale_point_idx(px, py, max_dist_px_img=None):
        if not state["points"]:
            return None
        if max_dist_px_img is None:
            max_dist_px_img = current_hit_radius_img()
        best_idx = None
        best_dist = float("inf")
        for i, (qx, qy) in enumerate(state["points"]):
            d = float(np.hypot(float(px - qx), float(py - qy)))
            if d <= max_dist_px_img and d < best_dist:
                best_idx = i
                best_dist = d
        return best_idx

    def nearest_edit_point_idx(px, py, max_dist_px_img=None):
        if len(state["points"]) == 2:
            compute_preview()
            prev = state.get("preview")
            if prev is not None:
                p_ref = [prev["p1_ref"], prev["p2_ref"]]
                if max_dist_px_img is None:
                    max_dist_px_img = current_hit_radius_img()
                best_idx = None
                best_dist = float("inf")
                for i, (qx, qy) in enumerate(p_ref):
                    d = float(np.hypot(float(px - qx), float(py - qy)))
                    if d <= max_dist_px_img and d < best_dist:
                        best_idx = i
                        best_dist = d
                if best_idx is not None:
                    return best_idx
        return nearest_scale_point_idx(px, py, max_dist_px_img=max_dist_px_img)

    def render_background():
        view_w = max(1, int(canvas.winfo_width()))
        view_h = max(1, int(canvas.winfo_height()))
        fit_ratio = max(1e-6, min(float(view_w) / float(img_w), float(view_h) / float(img_h)))
        state["fit_ratio"] = fit_ratio
        s = get_scale()
        disp_w = max(1, int(round(img_w * s)))
        disp_h = max(1, int(round(img_h * s)))
        region_w = max(view_w, disp_w)
        region_h = max(view_h, disp_h)
        offset_x = max(0.0, (float(region_w) - float(disp_w)) * 0.5)
        offset_y = max(0.0, (float(region_h) - float(disp_h)) * 0.5)
        img_rgb = cv2.cvtColor(img_u8, cv2.COLOR_GRAY2RGB)
        img_resized = cv2.resize(img_rgb, (disp_w, disp_h), interpolation=cv2.INTER_LINEAR)
        tk_img = ImageTk.PhotoImage(Image.fromarray(img_resized))
        popup._tk_img = tk_img
        state["offset_x"] = offset_x
        state["offset_y"] = offset_y
        canvas.delete("bg")
        canvas.create_image(offset_x, offset_y, image=tk_img, anchor="nw", tags="bg")
        canvas.tag_lower("bg")
        canvas.configure(scrollregion=(0, 0, region_w, region_h))

    def apply_zoom(new_factor, center_canvas_x=None, center_canvas_y=None):
        old_scale = get_scale()
        new_factor = float(np.clip(new_factor, zoom_min, zoom_max))
        if abs(new_factor - state["zoom_factor"]) < 1e-9:
            return
        if center_canvas_x is None or center_canvas_y is None:
            view_w = max(1, canvas.winfo_width())
            view_h = max(1, canvas.winfo_height())
            center_canvas_x = canvas.canvasx(view_w / 2.0)
            center_canvas_y = canvas.canvasy(view_h / 2.0)
        center_img_x = (float(center_canvas_x) - float(state["offset_x"])) / old_scale
        center_img_y = (float(center_canvas_y) - float(state["offset_y"])) / old_scale
        state["zoom_factor"] = new_factor
        render_background()
        redraw()
        new_scale = get_scale()
        disp_w = max(1, int(round(img_w * new_scale)))
        disp_h = max(1, int(round(img_h * new_scale)))
        view_w = max(1, canvas.winfo_width())
        view_h = max(1, canvas.winfo_height())
        region_w = max(view_w, disp_w)
        region_h = max(view_h, disp_h)
        target_x = float(state["offset_x"]) + center_img_x * new_scale - (view_w / 2.0)
        target_y = float(state["offset_y"]) + center_img_y * new_scale - (view_h / 2.0)
        max_x = max(0.0, float(region_w - view_w))
        max_y = max(0.0, float(region_h - view_h))
        target_x = float(np.clip(target_x, 0.0, max_x))
        target_y = float(np.clip(target_y, 0.0, max_y))
        canvas.xview_moveto(target_x / float(max(1, region_w)))
        canvas.yview_moveto(target_y / float(max(1, region_h)))

    def compute_preview():
        if len(state["points"]) != 2:
            state["preview"] = None
            return
        raw_p1, raw_p2 = state["points"][0], state["points"][1]
        if axis_lock_var.get():
            p1_snap, p2_snap, axis_mode = snap_scale_points_axis(raw_p1, raw_p2)
        else:
            p1_snap, p2_snap, axis_mode = raw_p1, raw_p2, "free"
        endpoint_window_px = max(3.0, marker_radius_canvas_px / get_scale())
        refine = refine_scale_bar_points(
            img_u8,
            p1_snap,
            p2_snap,
            linewidth=preview_linewidth_px,
            endpoint_window_px=endpoint_window_px,
            force_axis=axis_lock_var.get(),
        )
        state["preview"] = {
            "p1_snap": p1_snap,
            "p2_snap": p2_snap,
            "p1_ref": refine["p1_ref"],
            "p2_ref": refine["p2_ref"],
            "refined_ok": refine["refined_ok"],
            "axis_mode": axis_mode,
            "endpoint_window_px": endpoint_window_px,
            "score": float(refine.get("score", 1.0)),
            "fallback": bool(refine.get("fallback", False)),
        }

    def redraw():
        canvas.delete("overlay")
        zoom_mult = max(1.0, float(state["zoom_factor"]))
        point_radius = min(24.0, marker_radius_canvas_px * zoom_mult)
        line_width = min(8.0, max(2.0, 2.0 * zoom_mult))
        if len(state["points"]) < 2:
            for px, py in state["points"]:
                x, y = image_to_canvas_xy(px, py)
                canvas.create_oval(
                    x - point_radius,
                    y - point_radius,
                    x + point_radius,
                    y + point_radius,
                    outline="yellow",
                    width=max(2, int(round(line_width))),
                    tags="overlay",
                )
        if len(state["points"]) == 2:
            compute_preview()
            prev = state["preview"]
            if prev is not None:
                rx1, ry1 = prev["p1_ref"]
                rx2, ry2 = prev["p2_ref"]
                cc1x, cc1y = image_to_canvas_xy(rx1, ry1)
                cc2x, cc2y = image_to_canvas_xy(rx2, ry2)
                canvas.create_line(
                    cc1x,
                    cc1y,
                    cc2x,
                    cc2y,
                    fill="#1b75bc",
                    width=max(2, int(round(line_width))),
                    tags="overlay",
                )
                canvas.create_oval(
                    cc1x - point_radius,
                    cc1y - point_radius,
                    cc1x + point_radius,
                    cc1y + point_radius,
                    outline="yellow" if state["dragging_idx"] == 0 else "#1b75bc",
                    width=max(2, int(round(line_width))),
                    tags="overlay",
                )
                canvas.create_oval(
                    cc2x - point_radius,
                    cc2y - point_radius,
                    cc2x + point_radius,
                    cc2y + point_radius,
                    outline="yellow" if state["dragging_idx"] == 1 else "#1b75bc",
                    width=max(2, int(round(line_width))),
                    tags="overlay",
                )

    def on_click(event):
        mode = tool_mode_var.get()
        if mode == "pan":
            state["is_panning"] = True
            canvas.scan_mark(event.x, event.y)
            return
        if mode in ("zoom_in", "zoom_out"):
            current = float(state["zoom_factor"])
            if mode == "zoom_in":
                next_factor = current * zoom_step
            else:
                next_factor = current / zoom_step
            apply_zoom(next_factor, canvas.canvasx(event.x), canvas.canvasy(event.y))
            return
        px, py = event_to_image_xy(event)
        if not (0 <= px < img_w and 0 <= py < img_h):
            return
        near_idx = nearest_edit_point_idx(px, py)
        if near_idx is not None:
            state["dragging_idx"] = near_idx
        elif len(state["points"]) < 2:
            state["points"].append((px, py))
            state["dragging_idx"] = len(state["points"]) - 1
        else:
            return
        redraw()

    def on_drag(event):
        if state["is_panning"]:
            pan_drag_to_pointer()
            return
        if state["dragging_idx"] is None:
            return
        px, py = event_to_image_xy(event)
        px = int(np.clip(px, 0, img_w - 1))
        py = int(np.clip(py, 0, img_h - 1))
        if len(state["points"]) == 2 and axis_lock_var.get():
            _, _, axis_mode = snap_scale_points_axis(state["points"][0], state["points"][1])
            old_px, old_py = state["points"][state["dragging_idx"]]
            if axis_mode == "vertical":
                px = int(old_px)
            else:
                py = int(old_py)
        state["points"][state["dragging_idx"]] = (px, py)
        redraw()

    def on_release(_event):
        state["dragging_idx"] = None
        if state["is_panning"]:
            state["is_panning"] = False

    def on_undo():
        if state["points"]:
            state["points"].pop()
            state["dragging_idx"] = None
            redraw()

    def on_clear():
        state["points"] = []
        state["dragging_idx"] = None
        redraw()

    def pan_drag_to_pointer():
        px = popup.winfo_pointerx() - canvas.winfo_rootx()
        py = popup.winfo_pointery() - canvas.winfo_rooty()
        canvas.scan_dragto(int(px), int(py), gain=1)

    def on_set_scale(target_scope: str):
        if len(state["points"]) != 2:
            messagebox.showwarning("Set Scale", "Select exactly 2 points for scale bar.", parent=popup)
            return
        mm_length = simpledialog.askfloat(
            "Scale Length",
            "Scale bar length (millimeters):",
            minvalue=1e-9,
            parent=popup,
        )
        if mm_length is None:
            return
        compute_preview()
        prev = state["preview"]
        if prev is None:
            return
        p1_snap, p2_snap = prev["p1_snap"], prev["p2_snap"]
        p1_ref, p2_ref = prev["p1_ref"], prev["p2_ref"]
        refined_ok = prev["refined_ok"]
        axis_mode = prev["axis_mode"]
        fallback = bool(prev.get("fallback", False))
        scale_points_used = (p1_ref, p2_ref) if refined_ok else (p1_snap, p2_snap)
        scale_data = compute_scale(scale_points_used, mm_length)
        result["value"] = {
            "target_scope": str(target_scope),
            "px_per_mm": scale_data["px_per_mm"],
            "scale_points": [tuple(map(float, scale_points_used[0])), tuple(map(float, scale_points_used[1]))],
            "axis_mode": axis_mode,
            "refined_ok": refined_ok,
            "fallback": fallback,
        }
        popup.destroy()

    canvas.bind("<Button-1>", on_click)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    canvas.bind("<Configure>", lambda _event: (render_background(), redraw()))
    popup.focus_set()
    render_background()
    redraw()
    controls = ttk.Frame(shell, padding=(0, SPACING.inner, 0, 0), style="Surface.TFrame")
    controls.grid(row=1, column=0, sticky="ew")
    controls.columnconfigure(0, weight=1)
    controls.columnconfigure(1, weight=1)

    tool_buttons = {}

    def sync_tool_buttons(*_args):
        active_mode = tool_mode_var.get()
        for mode_name, button in tool_buttons.items():
            button.configure(style="SegmentedActive.TButton" if mode_name == active_mode else "Segmented.TButton")

    left_controls = ttk.Frame(controls, style="Surface.TFrame")
    left_controls.grid(row=0, column=0, sticky="w")
    ttk.Button(left_controls, text="Undo", command=on_undo, **semantic_button_options("secondary")).pack(side="left", padx=(0, SPACING.gap))
    ttk.Button(left_controls, text="Clear", command=on_clear, **semantic_button_options("secondary")).pack(side="left", padx=(0, SPACING.gap))
    tool_strip = ttk.Frame(left_controls, style="Surface.TFrame")
    tool_strip.pack(side="left", padx=(SPACING.inner, SPACING.gap))
    for index, (mode_name, label) in enumerate((("edit", "Edit"), ("pan", "Pan"), ("zoom_in", "Zoom In"), ("zoom_out", "Zoom Out"))):
        button = ttk.Button(
            tool_strip,
            text=label,
            command=lambda value=mode_name: tool_mode_var.set(value),
            style="Segmented.TButton",
        )
        button.pack(side="left", padx=(0 if index == 0 else 1, 0))
        tool_buttons[mode_name] = button
    ttk.Checkbutton(left_controls, text="Axis Lock", variable=axis_lock_var, command=redraw).pack(side="left", padx=(SPACING.inner, 0))
    tool_mode_var.trace_add("write", sync_tool_buttons)
    sync_tool_buttons()

    right_controls = ttk.Frame(controls, style="Surface.TFrame")
    right_controls.grid(row=0, column=1, sticky="e")
    ttk.Button(right_controls, text="Cancel", command=popup.destroy, **semantic_button_options("secondary")).pack(side="right")
    ttk.Button(right_controls, text="Set Local Scale", command=lambda: on_set_scale("local"), **semantic_button_options("secondary")).pack(
        side="right", padx=(0, SPACING.gap)
    )
    ttk.Button(right_controls, text="Set Global Scale", command=lambda: on_set_scale("global"), **semantic_button_options("primary")).pack(
        side="right", padx=(0, SPACING.gap)
    )

    center_window_on_screen(popup, width=1080, height=860)
    popup.deiconify()
    popup.grab_set()
    popup.wait_window()
    return result["value"]
