from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk


class MaskImportDialogService:
    def path_natural_key(self, path: str | Path):
        parts = re.split(r"(\d+)", Path(path).name.lower())
        key = []
        for part in parts:
            if part.isdigit():
                key.append(int(part))
            else:
                key.append(part)
        return key

    def collect_mask_paths_from_folder(self, folder: str | Path) -> list[Path]:
        p = Path(folder)
        if not p.exists() or not p.is_dir():
            return []
        exts = {".tif", ".tiff", ".jpg", ".jpeg", ".png", ".bmp"}
        out = [x for x in p.iterdir() if x.is_file() and x.suffix.lower() in exts]
        return sorted(out, key=self.path_natural_key)

    def choose_paths(self, root) -> list[Path]:
        mode = {"value": None}
        top = tk.Toplevel(root)
        top.title("Import External Masks")
        top.transient(root)
        top.grab_set()
        ttk.Label(top, text="Choose import source:", padding=10).pack(fill="x")
        btns = ttk.Frame(top, padding=(10, 0, 10, 10))
        btns.pack(fill="x")

        def pick(value):
            mode["value"] = value
            top.destroy()

        ttk.Button(btns, text="From Folder...", command=lambda: pick("folder")).pack(side="left")
        ttk.Button(btns, text="From Files...", command=lambda: pick("files")).pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="Cancel", command=top.destroy).pack(side="right")
        root.wait_window(top)

        if mode["value"] is None:
            return []
        if mode["value"] == "folder":
            folder = filedialog.askdirectory(parent=root, title="Select Mask Folder")
            if not folder:
                return []
            return self.collect_mask_paths_from_folder(folder)
        selected = filedialog.askopenfilenames(
            parent=root,
            title="Import External Masks",
            filetypes=[("Image files", "*.tif *.tiff *.png *.jpg *.jpeg *.bmp"), ("All files", "*.*")],
        )
        if not selected:
            return []
        return sorted([Path(p) for p in selected], key=self.path_natural_key)

    def load_external_mask_images(self, paths: list[Path]) -> list[np.ndarray]:
        masks = []
        for raw_path in paths:
            img = cv2.imread(str(raw_path), cv2.IMREAD_GRAYSCALE)
            if img is None:
                raise RuntimeError(f"Unable to read mask file: {Path(raw_path).name}")
            masks.append((img > 0))
        return masks

    def build_mask_preview_image(self, frame_idx: int, mask: np.ndarray, frames_raw, frames_sub_viz):
        if frames_sub_viz and 0 <= frame_idx < len(frames_sub_viz):
            base_u8 = np.asarray(frames_sub_viz[frame_idx], dtype=np.uint8)
        else:
            raw = np.asarray(frames_raw[frame_idx], dtype=np.float32)
            base_u8 = cv2.normalize(raw, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        rgb = cv2.cvtColor(base_u8, cv2.COLOR_GRAY2RGB)
        overlay = rgb.copy()
        overlay[np.asarray(mask, dtype=bool)] = (0, 255, 255)
        mixed = cv2.addWeighted(rgb, 0.7, overlay, 0.3, 0.0)
        return Image.fromarray(mixed)

    def ask_alignment(
        self,
        root,
        frames_raw,
        frames_sub_viz,
        masks: list[np.ndarray],
        guessed_offset: int,
    ) -> Optional[int]:
        if not masks:
            return None
        top = tk.Toplevel(root)
        top.title("Mask Alignment Preview")
        top.transient(root)
        top.grab_set()
        result = {"offset": None}

        offset_var = tk.IntVar(value=int(guessed_offset) + 1)
        mask_idx_var = tk.IntVar(value=1)
        info_var = tk.StringVar(value="")

        control = ttk.Frame(top, padding=8)
        control.pack(fill="x")
        row_a = ttk.Frame(control)
        row_a.pack(fill="x", pady=(0, 4))
        row_b = ttk.Frame(control)
        row_b.pack(fill="x")
        ttk.Label(row_a, text="Mask Preview Index:").pack(side="left")
        scrub = tk.Scale(
            row_a,
            from_=1,
            to=max(1, len(masks)),
            orient="horizontal",
            showvalue=True,
            length=320,
            variable=mask_idx_var,
        )
        scrub.pack(side="left", padx=6)
        ttk.Label(row_b, text="Start Frame (1-based):").pack(side="left")
        align = tk.Scale(
            row_b,
            from_=1,
            to=max(1, len(frames_raw)),
            orient="horizontal",
            showvalue=True,
            length=320,
            variable=offset_var,
        )
        align.pack(side="left", padx=6)
        ttk.Label(row_b, textvariable=info_var).pack(side="left", padx=8)

        canvas = tk.Canvas(top, width=760, height=460, bg="#1f2023", highlightthickness=0)
        canvas.pack(fill="both", expand=True, padx=8, pady=8)
        image_ref = {"tk": None}

        def redraw(*_args):
            try:
                start_idx = int(offset_var.get()) - 1
                mask_idx = int(mask_idx_var.get()) - 1
            except Exception:
                start_idx = -1
                mask_idx = -1
            canvas.delete("all")
            if mask_idx < 0 or mask_idx >= len(masks):
                info_var.set("Invalid mask index")
                return
            frame_idx = start_idx + mask_idx
            if start_idx < 0 or frame_idx < 0 or frame_idx >= len(frames_raw):
                info_var.set("Out of range")
                return
            info_var.set(f"Mask {mask_idx + 1}/{len(masks)} -> frame {frame_idx + 1}")
            pil = self.build_mask_preview_image(frame_idx, masks[mask_idx], frames_raw, frames_sub_viz)
            cw = max(1, canvas.winfo_width())
            ch = max(1, canvas.winfo_height())
            if cw < 20 or ch < 20:
                return
            target_w = max(1, cw - 10)
            target_h = max(1, ch - 10)
            resampling = Image.Resampling.BILINEAR if hasattr(Image, "Resampling") else Image.BILINEAR
            pil.thumbnail((target_w, target_h), resampling)
            tk_img = ImageTk.PhotoImage(pil)
            image_ref["tk"] = tk_img
            canvas.create_image(cw // 2, ch // 2, image=tk_img, anchor="center")

        def apply_and_close():
            try:
                frame_idx = int(offset_var.get()) - 1
            except Exception:
                frame_idx = -1
            if frame_idx < 0 or frame_idx >= len(frames_raw):
                messagebox.showwarning("Alignment", "Choose a valid start frame.")
                return
            result["offset"] = frame_idx
            top.destroy()

        btns = ttk.Frame(top, padding=(8, 0, 8, 8))
        btns.pack(fill="x")
        ttk.Button(btns, text="Cancel", command=top.destroy).pack(side="right")
        ttk.Button(btns, text="Apply", command=apply_and_close).pack(side="right", padx=(0, 8))

        scrub.configure(command=lambda _v: redraw())
        align.configure(command=lambda _v: redraw())
        canvas.bind("<Configure>", redraw)
        redraw()
        root.wait_window(top)
        return result["offset"]
