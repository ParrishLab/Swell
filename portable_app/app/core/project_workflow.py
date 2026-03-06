from __future__ import annotations

"""Project lifecycle workflow helpers for SDSegmentationApp."""

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import filedialog, messagebox

from app.core.project_fingerprint import fingerprints_match
from app.core.project_migration import migrate_project_state
from app.core.project_schema import validate_project_state, utc_now_iso
from app.core.project_store import cleanup_stale_temp_files


@dataclass
class ProjectLoadPlan:
    project_path: str
    state: dict[str, Any]
    ui_state: dict[str, Any]
    global_state: dict[str, Any]
    image_paths: list[str]
    frame_names: list[str]
    frames_raw: list
    frames_sub: list
    frames_sub_viz: list
    event_states: dict[str, dict]
    active_event_id: str
    roi_points: list
    roi_mask: Any
    fingerprint_mismatches: list[str]


@dataclass
class CloseRequirements:
    has_running_propagation: bool
    not_saved_as_project: bool


@dataclass
class NewProjectRequirements:
    needs_discard_prompt: bool


def setup_project_menu(app) -> None:
    """Configure the top-level File menu."""
    menubar = tk.Menu(app.root)
    file_menu = tk.Menu(menubar, tearoff=False)
    file_menu.add_command(label="New Project", command=app.new_project)
    file_menu.add_command(label="Open Project...", command=app.open_project)
    file_menu.add_separator()
    file_menu.add_command(label="Save Project", command=app.save_project)
    file_menu.add_command(label="Save Project As...", command=app.save_project_as)
    file_menu.add_command(label="Convert to Project...", command=app.convert_to_project)
    file_menu.add_command(label="Import External Masks...", command=app.import_external_masks)
    file_menu.add_command(label="Recover Autosave...", command=app.recover_autosave)
    menubar.add_cascade(label="File", menu=file_menu)
    app.root.configure(menu=menubar)
    app._menu_bar = menubar


def save_project_to_path(app, target_path: str | Path, is_autosave: bool = False) -> None:
    cleanup_stale_temp_files(Path(target_path).parent, pattern="*.sdproj.tmp", older_than_sec=86400)
    state, images_manifest, roi_data, event_payloads = app._build_project_payload()
    store = getattr(getattr(app, "app_context", None), "project_store", app.project_store)
    store.save(
        target_path=target_path,
        project_state=state,
        images_manifest=images_manifest,
        roi_data=roi_data,
        event_payloads=event_payloads,
        embed_images=bool(app._project_embed_images),
    )
    if not is_autosave:
        app.current_project_path = str(target_path)
        app.project_dirty = False
        app.log_success("Project", f"Saved project: {target_path}")


def save_project(app) -> None:
    if app.current_project_path is None:
        return app.save_project_as()
    save_project_to_path(app, app.current_project_path, is_autosave=False)


def save_project_as(app) -> None:
    target = filedialog.asksaveasfilename(
        parent=app.root,
        title="Save Project As",
        defaultextension=".sdproj",
        filetypes=[("SD Project", "*.sdproj"), ("All files", "*.*")],
    )
    if not target:
        return
    app._project_embed_images = bool(
        messagebox.askyesno(
            "Embed Images?",
            "Embed source images inside project file?\n\nYes = larger but portable\nNo = reference-only",
        )
    )
    save_project_to_path(app, target, is_autosave=False)


def convert_to_project(app) -> None:
    if app.frames_raw is None:
        messagebox.showwarning("No Data", "Import images first before converting to a project.")
        return
    app.save_project_as()


def resolve_project_image_paths(app, loaded) -> list[str]:
    resolved = []
    embedded = loaded.embedded_image_paths
    for entry in loaded.images_manifest.get("images", []):
        image_id = str(entry.get("id", ""))
        if image_id in embedded:
            resolved.append(embedded[image_id])
            continue
        abs_path = entry.get("absolute_path")
        rel_path = entry.get("relative_path")
        candidate = None
        if abs_path and Path(abs_path).exists():
            candidate = abs_path
        elif rel_path and Path(rel_path).exists():
            candidate = rel_path
        elif rel_path and app.current_project_path is not None:
            p = (Path(app.current_project_path).parent / rel_path).resolve()
            if p.exists():
                candidate = str(p)
        if candidate is not None:
            resolved.append(str(candidate))
    return resolved


def apply_loaded_project(app, loaded, project_path: str | Path) -> ProjectLoadPlan:
    plan = prepare_loaded_project(app, loaded, project_path)
    apply_loaded_project_plan(app, plan)
    return plan


def prepare_loaded_project(app, loaded, project_path) -> ProjectLoadPlan:
    """Build a load plan with normalized project state and decoded image stack."""
    state = migrate_project_state(loaded.project_state)
    validate_project_state(state)
    ui_state = state.get("ui_state", {})
    project_path = str(project_path)

    image_paths = resolve_project_image_paths(app, loaded)
    if not image_paths:
        raise RuntimeError("No accessible image paths found in project.")

    frames, frame_names = app._load_frames_and_names([Path(p) for p in image_paths])
    if not frames:
        raise RuntimeError("Failed to decode project image frames.")
    frames_raw, frames_sub, frames_sub_viz = app._prepare_frame_arrays(frames)

    session_service = getattr(getattr(app, "app_context", None), "project_session_service", app.project_session_service)
    loaded_actions = session_service.apply_loaded_project(
        state=state,
        loaded_event_payloads=loaded.event_payloads,
        frame_count=len(frames_raw),
        frame_shape=frames_raw[0].shape[:2],
        choose_resume_draft=lambda event_id: messagebox.askyesno(
            "Draft Masks Found",
            f"Event '{event_id}' has unfinished draft propagation.\n\nResume draft masks?",
        ),
        decode_rle=app.seg_state._decode_rle,
    )

    global_state = state.get("global", {})
    roi_data = loaded.roi_data or {}
    roi_points = roi_data.get("roi_points", [])
    safe_roi_points = roi_points if isinstance(roi_points, list) else []
    roi_rle = roi_data.get("roi_mask_rle")
    if roi_rle:
        roi_mask = app.seg_state._decode_rle(roi_rle)
    else:
        roi_mask = None

    mismatches = []
    for entry in loaded.images_manifest.get("images", []):
        abs_path = entry.get("absolute_path")
        fp = entry.get("fingerprint", {})
        if abs_path and fp and Path(abs_path).exists() and not fingerprints_match(abs_path, fp):
            mismatches.append(Path(abs_path).name)

    return ProjectLoadPlan(
        project_path=project_path,
        state=state,
        ui_state=ui_state,
        global_state=global_state,
        image_paths=list(image_paths),
        frame_names=list(frame_names),
        frames_raw=frames_raw,
        frames_sub=frames_sub,
        frames_sub_viz=frames_sub_viz,
        event_states=dict(loaded_actions.event_states),
        active_event_id=str(loaded_actions.active_event_id),
        roi_points=safe_roi_points,
        roi_mask=roi_mask,
        fingerprint_mismatches=mismatches,
    )


def apply_loaded_project_plan(app, plan: ProjectLoadPlan) -> None:
    """Apply a previously prepared load plan to app state and widgets."""
    app.current_project_path = str(plan.project_path)
    app._project_created_at = str(plan.state.get("created_at", utc_now_iso()))
    app.active_event_id = str(plan.ui_state.get("active_event_id", "sd_event_001"))
    app.frame_names = list(plan.frame_names)
    app._apply_loaded_stack(
        plan.frames_raw,
        plan.frames_sub,
        plan.frames_sub_viz,
        app.frame_names,
        source_paths=list(plan.image_paths),
    )

    session_service = getattr(getattr(app, "app_context", None), "project_session_service", app.project_session_service)
    app.event_states = dict(plan.event_states)
    session_service.load_event_into_seg_state(
        event_id=str(plan.active_event_id),
        event_states=app.event_states,
        seg_state=app.seg_state,
    )
    app.active_event_id = str(plan.active_event_id)
    app._propagation_committed_snapshot = None
    app.scale_px_per_mm = plan.global_state.get("scale_px_per_mm")
    app.roi_points = list(plan.roi_points)
    app.roi_mask = plan.roi_mask

    try:
        app._set_spinbox_value(app.spin_baseline, int(plan.global_state.get("baseline_frame_count", 30)))
    except Exception:
        pass

    for spin_name, key in (
        ("spin_analysis_start", "analysis_start"),
        ("spin_analysis_end", "analysis_end"),
        ("spin_prop_start", "prop_start"),
        ("spin_prop_end", "prop_end"),
        ("spin_export_start", "export_start"),
        ("spin_export_end", "export_end"),
    ):
        if hasattr(app, spin_name) and key in plan.ui_state:
            app._set_spinbox_value(getattr(app, spin_name), plan.ui_state.get(key))

    app.tool_mode.set(str(plan.ui_state.get("active_tool", "select")))
    try:
        idx = int(plan.ui_state.get("last_frame", 0))
        app.slider.set(max(0, min(len(app.frames_raw) - 1, idx)))
    except Exception:
        pass

    for mismatch_name in plan.fingerprint_mismatches:
        app.log_warn("Project", f"Image fingerprint mismatch: {mismatch_name}")
    if plan.fingerprint_mismatches:
        app.lbl_status.configure(
            text="Status: Project loaded with image mismatch warnings",
            foreground="orange",
        )

    nonempty = app._collect_nonempty_final_mask_frames()
    app._set_propagated_frames(nonempty, mark_dirty=False)
    app.update_display()
    app.project_dirty = False
    app.log_success("Project", f"Opened project: {plan.project_path}")


def open_project(app) -> None:
    path = filedialog.askopenfilename(
        parent=app.root,
        title="Open Project",
        filetypes=[("SD Project", "*.sdproj"), ("All files", "*.*")],
    )
    if not path:
        return
    cleanup_stale_temp_files(Path(path).parent, pattern="*.sdproj.tmp", older_than_sec=86400)
    store = getattr(getattr(app, "app_context", None), "project_store", app.project_store)
    loaded = store.load(path, extract_embedded_to=Path(tempfile.mkdtemp(prefix="sdproj_images_")))
    apply_loaded_project(app, loaded, path)


def recover_autosave(app) -> None:
    autosave_mgr = getattr(getattr(app, "app_context", None), "autosave_manager", app.autosave_manager)
    autosave = autosave_mgr.newest_autosave()
    if autosave is None:
        messagebox.showinfo("Recover Autosave", "No autosave files were found.")
        return
    store = getattr(getattr(app, "app_context", None), "project_store", app.project_store)
    loaded = store.load(autosave, extract_embedded_to=Path(tempfile.mkdtemp(prefix="sdproj_images_")))
    apply_loaded_project(app, loaded, autosave)


def maybe_prompt_autosave_recovery(app) -> None:
    autosave_mgr = getattr(getattr(app, "app_context", None), "autosave_manager", app.autosave_manager)
    newer = autosave_mgr.newest_autosave_if_newer_than(app.current_project_path)
    if newer is None:
        return
    restore = messagebox.askyesno(
        "Autosave Recovery",
        f"Newer autosave found:\n{newer.name}\n\nRestore it now?",
    )
    if restore:
        store = getattr(getattr(app, "app_context", None), "project_store", app.project_store)
        loaded = store.load(newer, extract_embedded_to=Path(tempfile.mkdtemp(prefix="sdproj_images_")))
        apply_loaded_project(app, loaded, newer)


def evaluate_new_project_requirements(app) -> NewProjectRequirements:
    return NewProjectRequirements(
        needs_discard_prompt=bool(app.frames_raw is not None and app.project_dirty),
    )


def new_project(app) -> None:
    requirements = evaluate_new_project_requirements(app)
    if requirements.needs_discard_prompt:
        proceed = messagebox.askyesno("Discard Changes?", "Discard unsaved project changes and start new project?")
        if not proceed:
            return
    app.current_project_path = None
    app.project_dirty = False
    app._project_created_at = utc_now_iso()
    app._project_embed_images = False
    app.active_event_id = "sd_event_001"
    app._reset_for_new_import()


def is_propagation_running(app) -> bool:
    manager = getattr(getattr(app, "app_context", None), "inference_manager", app.inference_manager)
    thread = getattr(manager, "propagate_thread", None)
    return bool(thread is not None and thread.is_alive())


def evaluate_close_requirements(app) -> CloseRequirements:
    has_loaded_stack = app.frames_raw is not None and len(app.frames_raw) > 0
    not_saved_as_project = has_loaded_stack and not bool(app.current_project_path)
    return CloseRequirements(
        has_running_propagation=bool(app._is_propagation_running()),
        not_saved_as_project=bool(not_saved_as_project),
    )


def on_close(app) -> None:
    requirements = evaluate_close_requirements(app)
    if requirements.has_running_propagation:
        proceed = messagebox.askyesno(
            "Propagation Running",
            "Propagation is still running. Closing now will stop it.\n\nClose anyway?",
        )
        if not proceed:
            return

    if requirements.not_saved_as_project:
        proceed = messagebox.askyesno(
            "Project Not Saved",
            "This session has not been saved as a .sdproj project file.\n\nClose anyway?",
        )
        if not proceed:
            return

    app.autosave_manager.stop()
    app.inference_manager.stop()
    if app._ui_alive():
        app.root.destroy()
    app.cleanup_temp_files()
