from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk

from sdapp.analysis.ui.theme import SPACING, apply_theme
from sdapp.shared.ui.bootstrap import center_window_on_screen, semantic_button_options, ttk
from sdapp.shared.image_overlay import apply_mask_overlay


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
        top.withdraw()
        top.title("Import External Masks")
        top.transient(root)
        top.resizable(False, False)
        top.geometry("520x180")
        apply_theme(top)

        shell = ttk.Frame(top, padding=SPACING.outer, style="AppShell.TFrame")
        shell.pack(fill="both", expand=True)
        ttk.Label(shell, text="Choose import source", style="SectionTitle.TLabel").pack(anchor="w")
        ttk.Label(shell, text="Select a folder sequence or a set of individual mask images.", style="Meta.TLabel").pack(
            anchor="w", pady=(SPACING.gap, SPACING.inner)
        )

        btns = ttk.Frame(shell, style="AppShell.TFrame")
        btns.pack(fill="x")

        def pick(value):
            mode["value"] = value
            top.destroy()

        ttk.Button(btns, text="From Folder...", command=lambda: pick("folder"), **semantic_button_options("primary")).pack(side="left")
        ttk.Button(btns, text="From Files...", command=lambda: pick("files"), **semantic_button_options("secondary")).pack(
            side="left", padx=(SPACING.inner, 0)
        )
        ttk.Button(btns, text="Cancel", command=top.destroy, **semantic_button_options("secondary")).pack(side="right")
        center_window_on_screen(top, width=520, height=180)
        top.deiconify()
        top.grab_set()
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

    def build_mask_preview_image(self, frame_idx: int, mask: np.ndarray, *, get_raw_frame, get_visual_frame=None):
        base_frame = None
        if callable(get_visual_frame):
            try:
                base_frame = get_visual_frame(int(frame_idx))
            except Exception:
                base_frame = None
        if base_frame is None:
            base_frame = get_raw_frame(int(frame_idx))
        base_frame = np.asarray(base_frame)
        mixed = apply_mask_overlay(base_frame, mask)
        return Image.fromarray(mixed)

    def ask_alignment(
        self,
        root,
        frame_count: int,
        get_raw_frame,
        get_visual_frame,
        masks: list[np.ndarray],
        guessed_offset: int,
    ) -> Optional[int]:
        if not masks:
            return None
        top = tk.Toplevel(root)
        top.withdraw()
        top.title("Mask Alignment Preview")
        top.transient(root)
        top.geometry("920x680")
        top.minsize(920, 680)
        top.resizable(True, True)
        apply_theme(top)
        result = {"offset": None}

        offset_var = tk.IntVar(value=int(guessed_offset) + 1)
        mask_idx_var = tk.IntVar(value=1)
        info_var = tk.StringVar(value="")

        shell = ttk.Frame(top, padding=SPACING.outer, style="AppShell.TFrame")
        shell.pack(fill="both", expand=True)

        control = ttk.Frame(shell, padding=SPACING.card, style="Surface.TFrame")
        control.pack(fill="x")
        row_a = ttk.Frame(control, style="Surface.TFrame")
        row_a.pack(fill="x", pady=(0, 4))
        row_b = ttk.Frame(control, style="Surface.TFrame")
        row_b.pack(fill="x")
        ttk.Label(row_a, text="Mask Preview", style="SectionTitle.TLabel").pack(side="left")
        scrub = ttk.Scale(
            row_a,
            from_=1,
            to=max(1, len(masks)),
            orient="horizontal",
            variable=mask_idx_var,
            style="Flat.Horizontal.TScale",
        )
        scrub.pack(side="left", fill="x", expand=True, padx=(SPACING.inner, SPACING.inner))
        ttk.Label(row_a, textvariable=mask_idx_var, style="Meta.TLabel", width=4).pack(side="left")

        ttk.Label(row_b, text="Start Frame", style="Meta.TLabel").pack(side="left")
        align = ttk.Scale(
            row_b,
            from_=1,
            to=max(1, int(frame_count)),
            orient="horizontal",
            variable=offset_var,
            style="Flat.Horizontal.TScale",
        )
        align.pack(side="left", fill="x", expand=True, padx=(SPACING.inner, SPACING.inner))
        ttk.Label(row_b, textvariable=offset_var, style="Meta.TLabel", width=6).pack(side="left")
        ttk.Label(control, textvariable=info_var, style="Meta.TLabel").pack(anchor="w", pady=(SPACING.gap, 0))

        canvas_shell = ttk.Frame(shell, padding=SPACING.card, style="Inset.TFrame")
        canvas_shell.pack(fill="both", expand=True, pady=(SPACING.inner, SPACING.inner))
        canvas = tk.Canvas(canvas_shell, width=760, height=460, bg="#1f2023", highlightthickness=0)
        canvas.pack(fill="both", expand=True)
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
            if start_idx < 0 or frame_idx < 0 or frame_idx >= int(frame_count):
                info_var.set("Out of range")
                return
            info_var.set(f"Mask {mask_idx + 1}/{len(masks)} -> frame {frame_idx + 1}")
            pil = self.build_mask_preview_image(
                frame_idx,
                masks[mask_idx],
                get_raw_frame=get_raw_frame,
                get_visual_frame=get_visual_frame,
            )
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
            if frame_idx < 0 or frame_idx >= int(frame_count):
                messagebox.showwarning("Alignment", "Choose a valid start frame.", parent=top)
                return
            result["offset"] = frame_idx
            top.destroy()

        btns = ttk.Frame(shell, style="AppShell.TFrame")
        btns.pack(fill="x")
        ttk.Button(btns, text="Cancel", command=top.destroy, **semantic_button_options("secondary")).pack(side="right")
        ttk.Button(btns, text="Apply", command=apply_and_close, **semantic_button_options("primary")).pack(
            side="right", padx=(0, SPACING.inner)
        )

        scrub.configure(command=lambda _v: redraw())
        align.configure(command=lambda _v: redraw())
        canvas.bind("<Configure>", redraw)
        redraw()
        center_window_on_screen(top, width=920, height=680)
        top.deiconify()
        top.grab_set()
        root.wait_window(top)
        return result["offset"]
