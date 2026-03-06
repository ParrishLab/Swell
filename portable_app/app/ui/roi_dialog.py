import tkinter as tk
from tkinter import messagebox, ttk

import cv2
import numpy as np
from PIL import Image, ImageTk


def open_roi_dialog(root, img_u8, initial_roi_points=None):
    popup = tk.Toplevel(root)
    popup.title("Draw ROI - First Original Frame")
    popup.transient(root)
    popup.grab_set()

    img_h, img_w = img_u8.shape[:2]
    max_w, max_h = 900, 700
    ratio = min(max_w / img_w, max_h / img_h, 1.0)
    disp_w, disp_h = int(img_w * ratio), int(img_h * ratio)

    img_rgb = cv2.cvtColor(img_u8, cv2.COLOR_GRAY2RGB)
    img_resized = cv2.resize(img_rgb, (disp_w, disp_h), interpolation=cv2.INTER_LINEAR)
    pil_img = Image.fromarray(img_resized)
    tk_img = ImageTk.PhotoImage(pil_img)

    canvas = tk.Canvas(popup, width=disp_w, height=disp_h, bg="black")
    canvas.pack(padx=8, pady=8)
    canvas.create_image(0, 0, image=tk_img, anchor="nw")
    popup._tk_img = tk_img

    points_seed = list(initial_roi_points) if initial_roi_points else []
    state = {
        "points": points_seed,
        "selected_idx": None,
        "closed": bool(points_seed),
        "dragging": False,
    }
    result = {"value": None}

    def redraw():
        canvas.delete("overlay")
        if not state["points"]:
            return
        for i, (px, py) in enumerate(state["points"]):
            x = px * ratio
            y = py * ratio
            if state["selected_idx"] == i:
                canvas.create_oval(x - 7, y - 7, x + 7, y + 7, fill="#00ff66", outline="yellow", width=2, tags="overlay")
            else:
                canvas.create_oval(x - 5, y - 5, x + 5, y + 5, fill="#00ff66", outline="#00ff66", tags="overlay")
        if len(state["points"]) >= 2:
            pts = []
            for px, py in state["points"]:
                pts.extend([px * ratio, py * ratio])
            canvas.create_line(*pts, fill="#00ff66", width=2, tags="overlay")
            if len(state["points"]) >= 3 and state["closed"]:
                x0, y0 = state["points"][0]
                x1, y1 = state["points"][-1]
                canvas.create_line(
                    x0 * ratio,
                    y0 * ratio,
                    x1 * ratio,
                    y1 * ratio,
                    fill="#00ff66",
                    width=2,
                    tags="overlay",
                )
            elif len(state["points"]) >= 3:
                x0, y0 = state["points"][0]
                x1, y1 = state["points"][-1]
                canvas.create_line(
                    x0 * ratio,
                    y0 * ratio,
                    x1 * ratio,
                    y1 * ratio,
                    fill="#00ff66",
                    width=1,
                    dash=(3, 2),
                    tags="overlay",
                )

    def nearest_point_idx(px, py, max_dist_px=None):
        if not state["points"]:
            return None
        if max_dist_px is None:
            max_dist_px = max(8.0, 12.0 / max(ratio, 1e-6))
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
            max_dist_px = max(6.0, 10.0 / max(ratio, 1e-6))
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
        px = int(event.x / ratio)
        py = int(event.y / ratio)
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
        if state["selected_idx"] is None:
            return
        px = int(event.x / ratio)
        py = int(event.y / ratio)
        px = max(0, min(px, img_w - 1))
        py = max(0, min(py, img_h - 1))
        state["points"][state["selected_idx"]] = (px, py)
        redraw()

    def on_release(_event):
        state["dragging"] = False
        redraw()

    def on_double_click(event):
        if state["closed"]:
            return
        if len(state["points"]) < 3:
            return
        px = int(event.x / ratio)
        py = int(event.y / ratio)
        first_idx = nearest_point_idx(px, py, max_dist_px=10)
        if first_idx == 0:
            state["closed"] = True
            state["selected_idx"] = 0
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

    def on_delete_selected():
        if state["selected_idx"] is None:
            return
        del state["points"][state["selected_idx"]]
        state["selected_idx"] = None
        redraw()

    def on_finish():
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
            "roi_mask": roi_mask.astype(bool),
            "roi_points": list(state["points"]),
        }
        popup.destroy()

    canvas.bind("<Button-1>", on_click)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    canvas.bind("<Double-Button-1>", on_double_click)
    controls = ttk.Frame(popup)
    controls.pack(fill="x", padx=8, pady=(0, 8))
    ttk.Label(
        controls,
        text="Click to add/select points. Double-click first point to close. Drag to move. Click edge to insert.",
    ).pack(side="top", anchor="w", pady=(0, 4))
    ttk.Button(controls, text="Undo Point", command=on_undo).pack(side="left", padx=3)
    ttk.Button(controls, text="Delete Selected", command=on_delete_selected).pack(side="left", padx=3)
    ttk.Button(controls, text="Clear", command=on_clear).pack(side="left", padx=3)
    ttk.Button(controls, text="Save ROI", command=on_finish).pack(side="right", padx=3)
    ttk.Button(controls, text="Cancel", command=popup.destroy).pack(side="right", padx=3)

    redraw()
    popup.wait_window()
    return result["value"]
