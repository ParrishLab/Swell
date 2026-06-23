import tkinter as tk
from swell.shared.ui import dialogs as messagebox

import cv2
import numpy as np
from PIL import Image, ImageTk

from swell.analysis.ui.theme import SPACING, apply_theme
from swell.shared.ui.bootstrap import center_window_on_screen, semantic_button_options, ttk


def _scale_save_actions(context: str, allow_reset_local: bool) -> list[tuple[str, str, str]]:
    if context == "host":
        return [("global", "Set Global Scale", "primary")]
    return [
        ("global", "Set Global Scale", "secondary"),
        ("local", "Set Local Scale", "primary"),
    ]


def open_scale_dialog(
    root,
    img_u8,
    snap_scale_points_axis,
    refine_scale_bar_points,
    compute_scale,
    initial_scale_points=None,
    initial_axis_lock=None,
    allow_reset_local=False,
    pick_image_callback=None,
    initial_length_mm=None,
    context: str = "analysis",
    initial_manual_px_per_mm=None,
    image_label: str | None = None,
):
    popup = tk.Toplevel(root)
    popup.withdraw()
    base_title = "Set Scale"
    full_title = f"{base_title} - {image_label}" if image_label else base_title
    popup.title(full_title)
    popup.resizable(True, True)
    popup.minsize(1120, 820)
    apply_theme(popup)
    popup.columnconfigure(0, weight=1)
    popup.rowconfigure(0, weight=1)

    # Access palette for scrollbar colors
    from swell.shared.ui.theme import _theme_palette
    palette = _theme_palette(ttk.Style())

    shell = ttk.Frame(popup, padding=SPACING.outer, style="AppShell.TFrame")
    shell.grid(row=0, column=0, sticky="nsew")
    shell.columnconfigure(0, weight=1)
    shell.rowconfigure(1, weight=1)

    top_bar = ttk.Frame(shell, style="AppShell.TFrame")
    top_bar.grid(row=0, column=0, sticky="ew", pady=(0, SPACING.inner))
    top_bar.columnconfigure(0, weight=1)
    ttk.Label(top_bar, text=full_title, style="AppSectionTitle.TLabel").grid(row=0, column=0, sticky="w")

    body = ttk.Frame(shell, style="AppShell.TFrame")
    body.grid(row=1, column=0, sticky="nsew")
    body.columnconfigure(0, weight=1)
    body.columnconfigure(1, weight=0)
    body.rowconfigure(0, weight=1)

    img_h, img_w = img_u8.shape[:2]
    max_w, max_h = 760, 620
    initial_fit_ratio = min(max_w / img_w, max_h / img_h, 1.0)

    canvas_shell = ttk.Frame(body, padding=SPACING.card, style="AppInset.TFrame")
    canvas_shell.grid(row=0, column=0, sticky="nsew", padx=(0, SPACING.inner))
    
    x_scroll = ttk.Scrollbar(canvas_shell, orient="horizontal")
    y_scroll = ttk.Scrollbar(canvas_shell, orient="vertical")
    
    canvas = tk.Canvas(
        canvas_shell,
        width=max_w,
        height=max_h,
        bg="black",
        highlightthickness=0,
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

    axis_lock_var = tk.BooleanVar(value=bool(True if initial_axis_lock is None else initial_axis_lock))
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
        "space_pan_requested": False,
        "hit_radius_canvas_px": 14.0,
        "zoom_factor": 1.0,
        "fit_ratio": initial_fit_ratio,
        "offset_x": 0.0,
        "offset_y": 0.0,
        "manual_mode_active": bool(initial_manual_px_per_mm is not None),
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

    btn_set_local = None
    btn_set_global = None

    def redraw():
        canvas.delete("overlay")
        zoom_mult = max(1.0, float(state["zoom_factor"]))
        point_radius = min(24.0, marker_radius_canvas_px * zoom_mult)
        line_width = min(8.0, max(2.0, 2.0 * zoom_mult))
        
        # Update button states and manual/point-based UI interlocking
        is_manual = bool(state["manual_mode_active"])
        num_pts = len(state["points"])
        
        if is_manual:
            point_based_state = "disabled"
            manual_input_state = "!disabled"
            is_ready = True
        else:
            point_based_state = "!disabled"
            manual_input_state = "!disabled"
            is_ready = (num_pts == 2)

        # Disable point-based configuration
        for w in [length_entry, axis_lock_check, btn_undo, btn_clear]:
            if w is not None:
                try:
                    w.state([point_based_state])
                except Exception:
                    pass

        for btn in [btn_set_local, btn_set_global]:
            if btn is not None:
                btn.state(["!disabled"] if is_ready else ["disabled"])

        if not is_manual:
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
        if bool(int(getattr(event, "state", 0)) & 0x0001) or bool(state["space_pan_requested"]):
            state["is_panning"] = True
            canvas.scan_mark(event.x, event.y)
            return "break"
        px, py = event_to_image_xy(event)
        if not (0 <= px < img_w and 0 <= py < img_h):
            return
        near_idx = nearest_edit_point_idx(px, py)
        if near_idx is not None:
            state["dragging_idx"] = near_idx
        elif len(state["points"]) < 2:
            state["points"].append((px, py))
            state["dragging_idx"] = len(state["points"]) - 1
            if len(state["points"]) == 2:
                length_entry.focus_set()
                length_entry.selection_range(0, tk.END)
        else:
            return
        redraw()

    def on_drag(event):
        if state["is_panning"]:
            pan_drag_to_pointer()
            return "break"
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
            return "break"

    def on_mouse_wheel(event):
        delta = getattr(event, "delta", 0)
        num = getattr(event, "num", None)
        direction = 0
        if delta:
            direction = 1 if float(delta) > 0 else -1
        elif num in (4, 5):
            direction = 1 if int(num) == 4 else -1
        if direction == 0:
            return None
        current = float(state["zoom_factor"])
        next_factor = current * zoom_step if direction > 0 else current / zoom_step
        apply_zoom(next_factor, canvas.canvasx(event.x), canvas.canvasy(event.y))
        return "break"

    def on_undo():
        if state["points"]:
            state["points"].pop()
            state["dragging_idx"] = None
            redraw()

    def on_clear():
        state["points"] = []
        state["dragging_idx"] = None
        redraw()

    def on_change_image():
        nonlocal img_u8, img_w, img_h
        if not callable(pick_image_callback):
            return
        new_img = pick_image_callback()
        if new_img is None:
            return
        img_u8 = new_img
        img_h, img_w = img_u8.shape[:2]
        state["points"] = []
        state["preview"] = None
        state["dragging_idx"] = None
        state["zoom_factor"] = 1.0
        state["offset_x"] = 0.0
        state["offset_y"] = 0.0
        render_background()
        redraw()

    def set_space_pan_active(_event=None):
        state["space_pan_requested"] = True
        try:
            canvas.config(cursor="fleur")
        except Exception:
            pass
        return "break"

    def clear_space_pan_active(_event=None):
        state["space_pan_requested"] = False
        if not state["is_panning"]:
            try:
                canvas.config(cursor="cross")
            except Exception:
                pass
        return "break"

    def pan_drag_to_pointer():
        px = popup.winfo_pointerx() - canvas.winfo_rootx()
        py = popup.winfo_pointery() - canvas.winfo_rooty()
        canvas.scan_dragto(int(px), int(py), gain=1)

    def zoom_in():
        width = max(1, int(canvas.winfo_width()))
        height = max(1, int(canvas.winfo_height()))
        apply_zoom(float(state["zoom_factor"]) * zoom_step, canvas.canvasx(width / 2.0), canvas.canvasy(height / 2.0))

    def zoom_out():
        width = max(1, int(canvas.winfo_width()))
        height = max(1, int(canvas.winfo_height()))
        apply_zoom(float(state["zoom_factor"]) / zoom_step, canvas.canvasx(width / 2.0), canvas.canvasy(height / 2.0))

    def reset_view():
        view_w = max(1, int(canvas.winfo_width()))
        view_h = max(1, int(canvas.winfo_height()))
        fit_ratio = max(1e-6, min(float(view_w) / float(img_w), float(view_h) / float(img_h)))
        if fit_ratio <= 0:
            return
        state["zoom_factor"] = 1.0
        render_background()
        redraw()
        canvas.xview_moveto(0.0)
        canvas.yview_moveto(0.0)

    def on_cancel(_event=None):
        if state["points"]:
            if not messagebox.askyesno("Discard Changes", "Discard unsaved points?", parent=popup):
                return
        popup.destroy()

    def on_apply_manual():
        try:
            val = float(manual_scale_var.get())
            if val <= 0:
                raise ValueError()
            state["manual_mode_active"] = True
            redraw()
        except ValueError:
            messagebox.showwarning("Manual Scale", "Please enter a valid positive number for pixels per mm.", parent=popup)

    def on_clear_manual():
        manual_scale_var.set("")
        state["manual_mode_active"] = False
        redraw()

    def on_set_scale(target_scope: str):
        if state["manual_mode_active"]:
            try:
                manual_val = float(manual_scale_var.get())
                if manual_val > 0:
                    result["value"] = {
                        "target_scope": str(target_scope),
                        "px_per_mm": manual_val,
                        "scale_points": [],  # No points for manual entry
                        "axis_mode": "manual",
                        "axis_lock": bool(axis_lock_var.get()),
                        "refined_ok": False,
                        "fallback": False,
                    }
                    popup.destroy()
                    return
            except (ValueError, TypeError):
                pass
            messagebox.showwarning("Set Scale", "Please enter a valid manual scale value.", parent=popup)
            return

        if len(state["points"]) != 2:
            messagebox.showwarning("Set Scale", "Select exactly 2 points for scale bar, or enter a manual pixel value.", parent=popup)
            return
        try:
            mm_length = float(mm_length_var.get())
            if mm_length <= 0:
                raise ValueError()
        except ValueError:
            messagebox.showwarning("Set Scale", "Please enter a valid positive number for length (mm).", parent=popup)
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
            "axis_lock": bool(axis_lock_var.get()),
            "refined_ok": refined_ok,
            "fallback": fallback,
        }
        popup.destroy()

    popup.protocol("WM_DELETE_WINDOW", on_cancel)
    popup.bind("<Escape>", on_cancel, add="+")

    status_var = tk.StringVar(value="Step 1: Click on the image to place the first endpoint.")
    
    init_len = "1.0"
    if initial_length_mm is not None:
        try:
            val = float(initial_length_mm)
            if val > 0:
                init_len = str(val)
        except (ValueError, TypeError):
            pass
    mm_length_var = tk.StringVar(value=init_len)
    
    init_manual = ""
    if initial_manual_px_per_mm is not None:
        try:
            val = float(initial_manual_px_per_mm)
            if val > 0:
                init_manual = f"{val:.6f}"
        except (ValueError, TypeError):
            pass
    manual_scale_var = tk.StringVar(value=init_manual)
    manual_scale_var.trace_add("write", lambda *args: redraw())

    canvas.bind("<Button-1>", on_click)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    canvas.bind("<Configure>", lambda _event: (render_background(), redraw()))
    canvas.bind("<MouseWheel>", on_mouse_wheel)
    canvas.bind("<Button-4>", on_mouse_wheel)
    canvas.bind("<Button-5>", on_mouse_wheel)
    popup.focus_set()
    render_background()

    # 1. Right-side Toolbar
    side = ttk.Frame(body, width=270, style="AppSurface.TFrame")
    side.grid(row=0, column=1, sticky="ns")
    side.grid_propagate(False)

    # Manual Entry Section (Top)
    ttk.Label(side, text="MANUAL SCALE ENTRY", style="AppSectionTitle.TLabel").pack(anchor="w", pady=(0, 2))
    
    manual_input_frame = ttk.Frame(side, style="AppSurface.TFrame")
    manual_input_frame.pack(fill="x", pady=(0, 2))
    ttk.Label(manual_input_frame, text="Pixels per mm:", style="AppSurfaceMeta.TLabel").pack(side="left")
    manual_entry = ttk.Entry(manual_input_frame, textvariable=manual_scale_var, width=12, style="AppCompact.TEntry")
    manual_entry.pack(side="left", padx=(SPACING.gap, 0))
    
    manual_btns_frame = ttk.Frame(side, style="AppSurface.TFrame")
    manual_btns_frame.pack(fill="x", pady=(SPACING.gap, 0))
    ttk.Button(manual_btns_frame, text="Apply Manual", command=on_apply_manual, **semantic_button_options("secondary")).pack(side="left", padx=(0, SPACING.gap))
    ttk.Button(manual_btns_frame, text="Clear", command=on_clear_manual, **semantic_button_options("secondary")).pack(side="left")
    
    ttk.Label(side, text="(Overrides points when applied)", style="AppMicro.TLabel").pack(anchor="w", pady=(2, 0))

    ttk.Separator(side, orient="horizontal").pack(fill="x", pady=SPACING.inner)

    # Point-Based Scale Section (Middle)
    ttk.Label(side, text="POINT-BASED SCALE", style="AppSectionTitle.TLabel").pack(anchor="w", pady=(0, 2))
    
    config_frame = ttk.Frame(side, style="AppSurface.TFrame")
    config_frame.pack(fill="x", pady=(0, SPACING.inner))
    
    ttk.Label(config_frame, text="Length (mm):", style="AppSurfaceMeta.TLabel").pack(anchor="w")
    length_entry = ttk.Entry(config_frame, textvariable=mm_length_var, width=12, style="AppCompact.TEntry")
    length_entry.pack(anchor="w", pady=(2, SPACING.gap))
    
    axis_lock_check = ttk.Checkbutton(config_frame, text="Axis Lock", variable=axis_lock_var, command=redraw, style="AppSurface.TCheckbutton")
    axis_lock_check.pack(anchor="w")

    # History controls
    history_frame = ttk.Frame(side, style="AppSurface.TFrame")
    history_frame.pack(fill="x", pady=(SPACING.inner, 0))
    btn_undo = ttk.Button(history_frame, text="Undo Last Point", command=on_undo, **semantic_button_options("secondary"))
    btn_undo.pack(fill="x", pady=(0, SPACING.gap))
    btn_clear = ttk.Button(history_frame, text="Clear All Points", command=on_clear, **semantic_button_options("secondary"))
    btn_clear.pack(fill="x")
    
    if callable(pick_image_callback):
        ttk.Button(side, text="Change Image", command=on_change_image, **semantic_button_options("secondary")).pack(fill="x", pady=(SPACING.inner, 0))

    # Zoom controls (matching ROI dialog style)
    zoom_row = ttk.Frame(side, style="AppSurface.TFrame")
    zoom_row.pack(fill="x", pady=(SPACING.outer, 0))
    ttk.Button(zoom_row, text="Zoom In", width=10, command=zoom_in, **semantic_button_options("secondary")).pack(side="left", padx=(0, SPACING.gap))
    ttk.Button(zoom_row, text="Zoom Out", width=10, command=zoom_out, **semantic_button_options("secondary")).pack(side="left", padx=(0, SPACING.gap))
    ttk.Button(zoom_row, text="Fit", width=5, command=reset_view, **semantic_button_options("secondary")).pack(side="left")

    # 2. Bottom Action Bar
    actions = ttk.Frame(shell, style="AppShell.TFrame")
    actions.grid(row=2, column=0, sticky="ew", pady=(SPACING.inner, 0))
    
    ttk.Button(actions, text="Cancel", command=on_cancel, **semantic_button_options("secondary")).pack(side="right")
    
    save_targets = _scale_save_actions(context, allow_reset_local)
    for scope, label, kind in reversed(save_targets):
        btn = ttk.Button(
            actions, 
            text=label, 
            command=lambda s=scope: on_set_scale(s), 
            **semantic_button_options(kind)
        )
        btn.pack(side="right", padx=(0, SPACING.gap))
        if scope == "local":
            btn_set_local = btn
        elif scope == "global":
            btn_set_global = btn

    if bool(allow_reset_local):
        ttk.Button(
            actions,
            text="Use Global Scale",
            command=lambda: (result.__setitem__("value", {"target_scope": "reset_local_scale"}), popup.destroy()),
            **semantic_button_options("secondary"),
        ).pack(side="right", padx=(0, SPACING.gap))

    # Initialize UI state
    redraw()
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
    try:
        canvas.config(cursor="cross")
    except Exception:
        pass

    center_window_on_screen(popup, width=1120, height=820)
    popup.deiconify()
    popup.grab_set()
    popup.wait_window()
    return result["value"]
