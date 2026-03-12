import os
from pathlib import Path

import cv2
import numpy as np
import tifffile
from scipy.ndimage import gaussian_filter
from tkinter import filedialog, messagebox

from sdapp.analysis.utils.paths import resolve_existing_directory


class IOActions:
    _supported_image_extensions = {".tif", ".tiff", ".jpg", ".jpeg", ".png", ".bmp"}

    def browse_input_folder(self):
        initialdir = resolve_existing_directory(
            self.entry_input.get(),
            app_root=self.app_root,
            fallback_dir=self.app_root,
            prefer_parent_for_existing_dir=True,
        )
        folder = filedialog.askdirectory(initialdir=initialdir)
        if not folder:
            return
        self._selected_import_files = None
        self.entry_input.delete(0, "end")
        self.entry_input.insert(0, folder)
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
            self.entry_input.get(),
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
            messagebox.showwarning("Input Error", f"No valid image files selected.{details}")
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
            )

        self._selected_import_files = list(valid_files)
        label = str(valid_files[0]) if len(valid_files) == 1 else f"{len(valid_files)} selected files"
        self.entry_input.delete(0, "end")
        self.entry_input.insert(0, label)
        return list(valid_files)

    def browse_input_primary(self, mode):
        if str(mode).lower() == "files":
            return self.browse_input_files()
        return self.browse_input_folder()

    def browse_output(self):
        initialdir = resolve_existing_directory(
            self.entry_output.get(),
            app_root=self.app_root,
            fallback_dir=self.app_root,
            prefer_parent_for_existing_dir=True,
        )
        folder = filedialog.askdirectory(initialdir=initialdir)
        if folder:
            self.entry_output.delete(0, "end")
            self.entry_output.insert(0, folder)

    def _start_import(self):
        selected_files = list(getattr(self, "_selected_import_files", []) or [])
        if selected_files:
            self._start_import_with_files(selected_files, source_label=f"{len(selected_files)} selected file(s)")
            return

        input_folder = self.entry_input.get()
        if input_folder and os.path.isfile(input_folder):
            path = Path(input_folder)
            if path.suffix.lower() in self._supported_image_extensions:
                self._start_import_with_files([path], source_label=path.name)
                return
            messagebox.showwarning("Input Error", "Selected file type is not supported.")
            return
        if not input_folder or not os.path.isdir(input_folder):
            messagebox.showwarning("Input Error", "Please select a valid input image folder.")
            return

        image_files = self._collect_image_files_from_folder(input_folder)
        if not image_files:
            messagebox.showwarning("Input Error", "No supported images found in selected folder.")
            return

        self._start_import_with_files(image_files, source_label=input_folder)

    def _start_import_files(self):
        # Backward-compatible entry point for tests/callers.
        return self.browse_input_files()

    def _start_import_with_files(self, image_files, source_label):
        if self.frames_raw is not None:
            proceed = messagebox.askyesno(
                "Replace Current Stack?",
                "Importing a new stack will clear the current masks, points, and edits. Continue?",
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
                self.root.after(0, lambda: messagebox.showwarning("Input Error", "No valid image frames found."))
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
        frames_raw = np.array(frames).astype(np.float32)

        self.log_info("Import", "Applying smoothing...")
        frames_denoised = []
        for f in frames_raw:
            frames_denoised.append(gaussian_filter(f, sigma=0.5))
        frames_denoised = np.array(frames_denoised)

        self.log_info("Import", "Calculating baseline...")
        b_frames = int(self.spin_baseline.get())
        b_frames = min(b_frames, len(frames))
        baseline = np.median(frames_denoised[:b_frames], axis=0)
        frames_sub = frames_denoised - baseline

        self.log_info("Import", "Calculating global normalization...")
        subsample = frames_sub[::5]
        global_p1 = np.percentile(subsample, 1)
        global_p99 = np.percentile(subsample, 99)
        denom = global_p99 - global_p1
        if denom == 0:
            denom = 1e-8

        self.log_info("Import", "Generating display cache...")
        processed_viz_frames = []
        for frame in frames_sub:
            frame_clipped = np.clip(frame, global_p1, global_p99)
            f_norm = (frame_clipped - global_p1) / denom
            f_8bit = (f_norm * 255).astype(np.uint8)
            processed_viz_frames.append(f_8bit)
        return frames_raw, frames_sub, processed_viz_frames

    def _finalize_load_ui(self):
        count = len(self.frames_raw) if self.frames_raw is not None else 0
        if count == 0:
            self._set_data_controls_enabled(False)
            self._set_busy(False, "Status: Idle", "gray")
            return

        self.slider.configure(to=count - 1)
        self.current_frame_idx = 0
        self.points.clear()
        self.seg_state.invalidate_user_frames()
        self.seg_state.invalidate_final_mask_frames()
        self.selected_point = None
        self._export_range_auto_follow = True
        self._analysis_range_auto_follow = True
        self._set_spinbox_value(self.spin_prop_start, 1)
        self._set_spinbox_value(self.spin_prop_end, count)
        self._set_spinbox_value(self.spin_export_start, 1)
        self._set_spinbox_value(self.spin_export_end, count)
        if hasattr(self, "spin_analysis_start") and hasattr(self, "spin_analysis_end"):
            self._set_spinbox_value(self.spin_analysis_start, 1)
            self._set_spinbox_value(self.spin_analysis_end, count)

        self.update_display()
        self._recompute_slider_jump_markers()
        self._set_data_controls_enabled(True)
        self._set_busy(False, "Status: Ready", "green")
        self.log_success("Import", f"Completed import with {count} frame(s).")
