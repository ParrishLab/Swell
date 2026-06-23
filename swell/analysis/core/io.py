import os
from pathlib import Path

import cv2
import numpy as np
import tifffile
from tkinter import filedialog
from swell.shared.ui import dialogs as messagebox

from swell.analysis.core.frame_source import EagerFrameSource
from swell.shared.frame_source import build_visualization_stack
from swell.analysis.utils.paths import resolve_existing_directory


class IOActions:
    _supported_image_extensions = {".tif", ".tiff", ".jpg", ".jpeg", ".png", ".bmp"}

    def browse_input_folder(self):
        initialdir = resolve_existing_directory(
            self.get_input_source_hint(),
            app_root=self.app_root,
            fallback_dir=self.app_root,
            prefer_parent_for_existing_dir=True,
        )
        folder = filedialog.askdirectory(parent=self.root, initialdir=initialdir)
        if not folder:
            return
        self._selected_import_files = None
        self.set_input_source_hint(folder)
        return folder

    def _validate_selected_files(self, paths):
        valid_files = []
        rejected = []
        seen = set()
        for raw_path in paths:
            path = Path(raw_path)
            norm = str(path.resolve()) if path.exists() else str(path)
            if norm in seen:
                rejected.append((path.name, "duplicate"))
                continue
            seen.add(norm)

            if path.suffix.lower() not in self._supported_image_extensions:
                rejected.append((path.name, "unsupported extension"))
                continue
            if not path.exists():
                rejected.append((path.name, "missing path"))
                continue
            if path.is_dir():
                rejected.append((path.name, "is a directory"))
                continue
            if not os.access(path, os.R_OK):
                rejected.append((path.name, "not readable"))
                continue
            valid_files.append(path)
        return valid_files, rejected

    def browse_input_files(self):
        initialdir = resolve_existing_directory(
            self.get_input_source_hint(),
            app_root=self.app_root,
            fallback_dir=self.app_root,
            prefer_parent_for_existing_dir=True,
        )
        selected = filedialog.askopenfilenames(
            parent=self.root,
            title="Select Image File(s)",
            initialdir=initialdir,
            filetypes=[
                ("Image files", "*.tif *.tiff *.jpg *.jpeg *.png *.bmp"),
                ("All files", "*.*"),
            ],
        )
        if not selected:
            return None

        valid_files, rejected = self._validate_selected_files(selected)
        if rejected:
            for name, reason in rejected:
                self.log_warn("Import", f"Rejected file '{name}': {reason}")

        if not valid_files:
            rejected_msg = ", ".join(name for name, _reason in rejected[:4])
            suffix = "..." if len(rejected) > 4 else ""
            details = f" Rejected: {rejected_msg}{suffix}" if rejected else ""
            messagebox.showwarning("Input Error", f"No valid image files selected.{details}", parent=self.root)
            return None

        if rejected:
            skipped_names = ", ".join(name for name, _reason in rejected[:4])
            suffix = "..." if len(rejected) > 4 else ""
            messagebox.showwarning(
                "Input Warning",
                (
                    f"Selected {len(valid_files)} valid file(s); skipped {len(rejected)} invalid/unsupported file(s): "
                    f"{skipped_names}{suffix}"
                ),
                parent=self.root,
            )

        self._selected_import_files = list(valid_files)
        label = valid_files[0].as_posix() if len(valid_files) == 1 else f"{len(valid_files)} selected files"
        self.set_input_source_hint(label)
        return list(valid_files)

    def browse_input_primary(self, mode):
        if str(mode).lower() == "files":
            return self.browse_input_files()
        return self.browse_input_folder()

    def _start_import(self):
        selected_files = list(getattr(self, "_selected_import_files", []) or [])
        if selected_files:
            self._start_import_with_files(selected_files, source_label=f"{len(selected_files)} selected file(s)")
            return

        input_folder = self.get_input_source_hint()
        if input_folder and os.path.isfile(input_folder):
            path = Path(input_folder)
            if path.suffix.lower() in self._supported_image_extensions:
                self._start_import_with_files([path], source_label=path.name)
                return
            messagebox.showwarning("Input Error", "Selected file type is not supported.", parent=self.root)
            return
        if not input_folder or not os.path.isdir(input_folder):
            messagebox.showwarning("Input Error", "Please select a valid input image folder.", parent=self.root)
            return

        image_files = self._collect_image_files_from_folder(input_folder)
        if not image_files:
            messagebox.showwarning("Input Error", "No supported images found in selected folder.", parent=self.root)
            return

        self._start_import_with_files(image_files, source_label=input_folder)

    def _start_import_files(self):
        # Compatibility entry point for callers that still use the file-import path.
        return self.browse_input_files()

    def _start_import_with_files(self, image_files, source_label):
        if hasattr(self, "_has_loaded_stack") and self._has_loaded_stack():
            proceed = messagebox.askyesno(
                "Replace Current Stack?",
                "Importing a new stack will clear the current masks, points, and edits. Continue?",
                parent=self.root,
            )
            if not proceed:
                return

        self._set_busy(True, "Status: Loading...", "orange")
        self.log_info("Import", f"Started import from: {source_label}")
        self._current_image_source_paths = [str(Path(p)) for p in image_files]
        self._run_thread(lambda: self._process_stack(list(image_files)), loading_text="Loading image stack...")

    def _collect_image_files_from_folder(self, input_folder):
        image_files = []
        for ext in sorted(self._supported_image_extensions):
            image_files.extend(list(Path(input_folder).glob(f"*{ext}")))
            image_files.extend(list(Path(input_folder).glob(f"*{ext.upper()}")))
        return sorted(list(set(image_files)))

    def _as_gray_frames(self, img):
        arr = np.asarray(img)
        if arr.ndim < 2:
            return []
        if arr.ndim == 2:
            return [arr]
        if arr.ndim == 3 and arr.shape[-1] in (3, 4) and arr.shape[0] > 4 and arr.shape[1] > 4:
            return [cv2.cvtColor(arr[:, :, :3], cv2.COLOR_RGB2GRAY)]

        frames = []
        for sub_arr in arr:
            frames.extend(self._as_gray_frames(sub_arr))
        return frames

    def _load_frames_and_names(self, image_files):
        frames = []
        frame_names = []
        base_shape = None

        for fpath in image_files:
            try:
                if fpath.suffix.lower() in [".tif", ".tiff"]:
                    img = tifffile.imread(str(fpath))
                    loaded_frames = self._as_gray_frames(img)
                else:
                    img = cv2.imread(str(fpath), cv2.IMREAD_UNCHANGED)
                    if img is not None and img.ndim == 3:
                        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                    if img is None:
                        self.log_warn("Import", f"Unable to read: {fpath.name}")
                        continue
                    if img.ndim == 2:
                        loaded_frames = [img]
                    elif img.ndim == 3 and img.shape[2] in (3, 4):
                        loaded_frames = [cv2.cvtColor(img[:, :, :3], cv2.COLOR_RGB2GRAY)]
                    else:
                        loaded_frames = self._as_gray_frames(img)

                if img is None:
                    self.log_warn("Import", f"Unable to read: {fpath.name}")
                    continue

                if not loaded_frames:
                    self.log_warn("Import", f"No usable frames in: {fpath.name}")
                    continue

                for page_idx, f_img in enumerate(loaded_frames, start=1):
                    if f_img.ndim != 2:
                        self.log_warn("Import", f"Unsupported frame shape in {fpath.name}: {f_img.shape}")
                        continue

                    if base_shape is None:
                        base_shape = f_img.shape
                    elif f_img.shape != base_shape:
                        self.log_warn("Import", f"Dimension mismatch at {fpath.name}. Skipping frame.")
                        continue

                    frames.append(f_img)
                    if len(loaded_frames) > 1:
                        frame_names.append(f"{fpath.name}_p{page_idx}")
                    else:
                        frame_names.append(fpath.name)

            except Exception as exc:
                self.log_warn("Import", f"Skipping {fpath.name}: {exc}")
                continue

        return frames, frame_names

    def _process_stack(self, image_files):
        try:
            self.cleanup_temp_files()
            frames, frame_names = self._load_frames_and_names(image_files)
            self.frame_names = list(frame_names)
            if not frames:
                self.root.after(0, lambda: messagebox.showwarning("Input Error", "No valid image frames found.", parent=self.root))
                self.root.after(0, lambda: self._set_busy(False, "Status: Idle", "gray"))
                return

            frames_raw, frames_sub, frames_sub_viz = self._prepare_frame_arrays(frames)

            self.root.after(
                0,
                lambda: self._apply_loaded_stack(
                    frames_raw,
                    frames_sub,
                    frames_sub_viz,
                    list(self.frame_names),
                    source_paths=list(self._current_image_source_paths),
                ),
            )

        except Exception as e:
            self.log_error("Import", f"Import failed: {e}")
            if hasattr(self, "btn_save_masks"):
                self.root.after(0, lambda: self.btn_save_masks.configure(state="disabled"))
            self.root.after(0, lambda: self.lbl_status.configure(text=f"Error: {str(e)}", foreground="red"))
            self.root.after(0, lambda: self._set_busy(False, "Status: Error", "red"))

    def _prepare_frame_arrays(self, frames):
        self.log_info("Import", "Preparing shared preprocessing pipeline...")
        source = EagerFrameSource(raw_frames=[np.asarray(frame, dtype=np.float32, copy=False) for frame in frames])
        return build_visualization_stack(
            source,
            baseline_frames=max(1, int(self.get_baseline_frame_count())),
            apply_smoothing=True,
            apply_baseline_subtraction=True,
            apply_global_normalization=True,
        )

    def _finalize_load_ui(self, *, preserve_workspace_state: bool = False):
        count = int(self._get_frame_count()) if hasattr(self, "_get_frame_count") else 0
        if count == 0:
            self._set_data_controls_enabled(False)
            self._set_busy(False, "Status: Idle", "gray")
            return

        self.slider.configure(to=count - 1)
        self.current_frame_idx = max(0, min(int(self.current_frame_idx), count - 1))
        if not bool(preserve_workspace_state):
            self.points.clear()
            self.seg_state.invalidate_user_frames()
            self.seg_state.invalidate_final_mask_frames()
            self.selected_point = None
            self._export_range_auto_follow = True
            self._set_spinbox_value(self.spin_prop_start, 1)
            self._set_spinbox_value(self.spin_prop_end, count)

        if self._get_frames_raw() is None or self._get_frames_sub_viz() is None:
            self.update_display()
            self._set_data_controls_enabled(False)
            self._set_busy(True, "Status: Preparing frames...", "orange")
            return

        self.update_display()
        if not bool(preserve_workspace_state):
            self._recompute_slider_jump_markers()
        self._set_data_controls_enabled(True)
        self._set_busy(False, "Status: Ready", "green")
        self.log_success("Import", f"Completed import with {count} frame(s).")
