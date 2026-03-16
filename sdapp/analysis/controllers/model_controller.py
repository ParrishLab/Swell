from __future__ import annotations

import os
from pathlib import Path
import shutil
import tkinter as tk
from tkinter import filedialog


class AnalysisModelController:
    def __init__(self, app) -> None:
        self.app = app

    def browse_model(self):
        resource_root = Path(getattr(self.app, "resource_root", self.app.app_root))
        current_text = ""
        try:
            current_text = str(self.app.entry_model.get() or "").strip()
        except Exception:
            current_text = ""

        current_abs = ""
        if current_text:
            p = Path(current_text)
            if not p.is_absolute():
                p = resource_root / p
            current_abs = str(p.resolve())

        initialdir = str((resource_root / "models").resolve())
        if current_text:
            try:
                p = Path(current_text)
                if not p.is_absolute():
                    p = resource_root / p
                if p.exists():
                    initialdir = str((p.parent if p.is_file() else p).resolve())
            except Exception:
                pass

        selected = filedialog.askopenfilename(
            parent=self.app.root,
            title="Select SAM2 Model",
            initialdir=initialdir,
            filetypes=[
                ("PyTorch model", "*.pt *.pth"),
                ("All files", "*.*"),
            ],
        )
        if not selected:
            return

        selected_abs = str(Path(selected).resolve())
        if selected_abs == current_abs:
            self.app.log_info("Model", "Selected model is unchanged; skipping reload.")
            return

        self.app.entry_model.delete(0, tk.END)
        self.app.entry_model.insert(0, selected_abs)
        self.app.log_info("Model", f"Model changed to: {Path(selected_abs).name}. Reloading...")
        self.app._run_thread(self.app._init_sam2_background)

    def shutdown_model_resources(self):
        self.app.model_ready = False
        self.app.predictor = None
        self.app.inference_state = None
        if hasattr(self.app, "sam2_runtime") and self.app.sam2_runtime is not None:
            try:
                self.app.sam2_runtime.shutdown()
            except Exception:
                pass
        try:
            if self.app.temp_dir and os.path.exists(self.app.temp_dir):
                shutil.rmtree(self.app.temp_dir, ignore_errors=True)
        except Exception:
            pass
        try:
            import torch

            if torch.backends.mps.is_available():
                torch.mps.empty_cache()
            elif torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
