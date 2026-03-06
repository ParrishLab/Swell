from __future__ import annotations

"""External mask import orchestration for SDSegmentationApp."""

import numpy as np
from tkinter import messagebox

from app.core.mask_import import guess_mask_mapping


def import_external_masks(app) -> None:
    """Import masks from files/folder, align them, and apply to active event."""
    if app.frames_raw is None:
        messagebox.showwarning("No Data", "Import images first.")
        return

    mask_paths = app.mask_import_dialog.choose_paths(app.root)
    if not mask_paths:
        return
    try:
        masks = app.mask_import_dialog.load_external_mask_images(mask_paths)
    except Exception as exc:
        messagebox.showerror("Import Masks", str(exc))
        return
    if not masks:
        return
    base_shape = app.frames_raw[0].shape[:2]
    for m in masks:
        if tuple(m.shape[:2]) != tuple(base_shape):
            messagebox.showerror(
                "Import Masks",
                f"Mask dimensions must match imported frames ({base_shape[1]}x{base_shape[0]}).",
            )
            return

    frame_count = len(app.frames_raw)
    event_ranges = {}
    for event_id, state in app.event_states.items():
        start_idx = int(state.get("frame_start", 0))
        end_idx = int(state.get("frame_end", max(0, frame_count - 1)))
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
        frames_raw=app.frames_raw,
        frames_sub_viz=app.frames_sub_viz,
        masks=masks,
        guessed_offset=int(guessed_offset),
    )
    if offset is None:
        return
    if offset < 0 or offset >= frame_count:
        messagebox.showerror("Import Masks", "Computed frame offset is out of bounds.")
        return

    event_id = str(app.active_event_id or "sd_event_001")
    if event_id not in app.event_states:
        app.event_states[event_id] = {
            "id": event_id,
            "label": event_id,
            "points": {},
            "paint_layers": {},
            "masks_committed": {},
            "masks_draft": None,
            "use_draft": False,
            "frame_start": 0,
            "frame_end": max(0, frame_count - 1),
            "propagation_completed": True,
            "analysis_output_dir": None,
        }
    event_state = app.event_states[event_id]
    committed = app.project_session_service.copy_masks_dict(event_state.get("masks_committed", {}))
    applied = 0
    for idx, mask in enumerate(masks):
        frame_idx = offset + idx
        if frame_idx < 0 or frame_idx >= frame_count:
            continue
        committed[int(frame_idx)] = np.asarray(mask, dtype=bool).copy()
        applied += 1
    if applied <= 0:
        messagebox.showwarning("Import Masks", "No masks were mapped into the current frame range.")
        return

    event_state["masks_committed"] = committed
    event_state["masks_draft"] = None
    event_state["propagation_completed"] = True
    start_idx, end_idx = app.project_session_service.event_mask_bounds(committed, frame_count)
    event_state["frame_start"] = start_idx
    event_state["frame_end"] = end_idx

    if event_id == app.active_event_id:
        app.project_session_service.load_event_into_seg_state(
            event_id=str(event_id),
            event_states=app.event_states,
            seg_state=app.seg_state,
        )
        app.active_event_id = str(event_id)
        nonempty = app._collect_nonempty_final_mask_frames()
        app._set_propagated_frames(nonempty, mark_dirty=False)
        app.update_display()
    app._mark_project_dirty("import_external_masks")
    messagebox.showinfo(
        "Import Masks",
        f"Imported {applied} mask frame(s) using '{guess.get('strategy')}' mapping into event '{event_id}'.",
    )
