from __future__ import annotations

"""External mask import workflow for the analysis window."""

import numpy as np
from tkinter import messagebox

from sdapp.analysis.core.mask_import import guess_mask_mapping


def import_external_masks(app) -> None:
    """Import masks from files/folder, align them, and apply to active event."""
    frames_raw = app._get_frames_raw() if hasattr(app, "_get_frames_raw") else app.frames_raw
    frames_sub_viz = app._get_frames_sub_viz() if hasattr(app, "_get_frames_sub_viz") else app.frames_sub_viz
    frame_count = app._get_frame_count() if hasattr(app, "_get_frame_count") else (len(frames_raw) if frames_raw is not None else 0)
    frame_shape = app._get_frame_shape() if hasattr(app, "_get_frame_shape") else tuple(frames_raw[0].shape[:2])

    if frames_raw is None or frame_count <= 0:
        messagebox.showwarning("No Images", "Import images first.", parent=app.root)
        return

    mask_paths = app.mask_import_dialog.choose_paths(app.root)
    if not mask_paths:
        return
    try:
        masks = app.mask_import_dialog.load_external_mask_images(mask_paths)
    except Exception as exc:
        messagebox.showerror("Import Masks", str(exc), parent=app.root)
        return
    if not masks:
        return
    base_shape = frame_shape
    for m in masks:
        if tuple(m.shape[:2]) != tuple(base_shape):
            messagebox.showerror(
                "Import Masks",
                f"Mask dimensions must match imported frames ({base_shape[1]}x{base_shape[0]}).",
                parent=app.root,
            )
            return

    event_ranges = {}
    for event_id, record in app.event_records.items():
        start_idx = int(record.metadata.start_idx)
        end_idx = int(record.metadata.end_idx)
        start_idx = max(0, min(start_idx, max(0, frame_count - 1)))
        end_idx = max(0, min(end_idx, max(0, frame_count - 1)))
        if end_idx < start_idx:
            start_idx, end_idx = end_idx, start_idx
        event_ranges[str(event_id)] = (start_idx, end_idx)
    guess = guess_mask_mapping(mask_paths, frame_count, event_ranges)
    guessed_offset = guess.get("offset")
    if guessed_offset is None:
        guessed_offset = 0
    offset = app.mask_import_dialog.ask_alignment(
        root=app.root,
        frames_raw=frames_raw,
        frames_sub_viz=frames_sub_viz,
        masks=masks,
        guessed_offset=int(guessed_offset),
    )
    if offset is None:
        return
    if offset < 0 or offset >= frame_count:
        messagebox.showerror("Import Masks", "Computed frame offset is out of bounds.", parent=app.root)
        return

    event_id = str(app.active_event_id or "sd_event_001")
    event_record = app.project_session_service.ensure_event_record(event_id, frame_count, app.event_records)
    committed = app.project_session_service.copy_masks_dict(event_record.analysis.masks_committed)
    applied = 0
    for idx, mask in enumerate(masks):
        frame_idx = offset + idx
        if frame_idx < 0 or frame_idx >= frame_count:
            continue
        committed[int(frame_idx)] = np.asarray(mask, dtype=bool).copy()
        applied += 1
    if applied <= 0:
        messagebox.showwarning("Import Masks", "No masks were mapped into the current frame range.", parent=app.root)
        return

    event_record.analysis.masks_committed = committed
    event_record.analysis.masks_draft = None
    event_record.analysis.use_draft = False
    event_record.metadata.propagation_completed = True
    start_idx, end_idx = app.project_session_service.event_mask_bounds(committed, frame_count)
    event_record.metadata.start_idx = start_idx
    event_record.metadata.end_idx = end_idx

    if event_id == app.active_event_id:
        app.analysis_workspace.open_event(str(event_id))
        nonempty = app._collect_nonempty_final_mask_frames()
        app._set_propagated_frames(nonempty, mark_dirty=False)
        app.update_display()
    app._mark_project_dirty("import_external_masks")
    messagebox.showinfo(
        "Import Masks",
        f"Imported {applied} mask frame(s) using '{guess.get('strategy')}' mapping into event '{event_id}'.",
        parent=app.root,
    )
