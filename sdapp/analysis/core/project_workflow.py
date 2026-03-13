from __future__ import annotations

"""Project lifecycle workflow helpers for SDSegmentationApp."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import filedialog, messagebox

from sdapp.analysis.core.frame_source import EagerFrameSource
from sdapp.analysis.core.project_fingerprint import fingerprints_match
from sdapp.analysis.core.project_migration import migrate_project_state
from sdapp.analysis.core.project_schema import validate_project_state, utc_now_iso


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
    frame_source: Any
    event_records: dict[str, Any]
    active_event_id: str
    roi_points: list
    roi_mask: Any
    fingerprint_mismatches: list[str]


@dataclass
class CloseRequirements:
    has_running_propagation: bool


def _standalone_removed(action: str) -> None:
    message = (
        f"{action} is not available in host-bound analysis windows.\n"
        "Use the SD ID main window for project lifecycle actions."
    )
    raise RuntimeError(message)


def setup_project_menu(app) -> None:
    """Configure the top-level File menu."""
    from sdapp.shared.menu.factory import build_shared_menu

    app._menu_bar = build_shared_menu(app.root, app, mode="analysis", host_mode=bool(getattr(app, "_host_mode", False)))


def save_project_to_path(app, target_path: str | Path, is_autosave: bool = False) -> None:
    target_path = Path(target_path).expanduser().resolve()
    if bool(getattr(app, "_host_mode", False)) and callable(getattr(app, "_host_project_saver", None)) and not is_autosave:
        if hasattr(app, "_emit_host_sync"):
            app._emit_host_sync(reason="save")
        state = app._host_project_saver(str(target_path))
        if isinstance(state, dict):
            path_from_state = state.get("project_path")
            if isinstance(path_from_state, str) and path_from_state:
                target_path = Path(path_from_state).expanduser().resolve()
        app.current_project_path = str(target_path)
        notifier = getattr(app, "_host_project_saved_notifier", None)
        if callable(notifier):
            try:
                notifier(str(target_path))
            except Exception:
                pass
        app.project_dirty = False
        app.log_success("Project", f"Saved project: {target_path}")
        return
    if bool(is_autosave):
        return
    _standalone_removed("Save Project")


def save_project(app) -> None:
    if app.current_project_path is None:
        return app.save_project_as()
    save_project_to_path(app, app.current_project_path, is_autosave=False)


def save_project_as(app) -> None:
    initial_dir = None
    initial_name = "analysis.sdproj"
    if app.current_project_path:
        current = Path(app.current_project_path)
        initial_dir = str(current.parent)
        initial_name = current.name
    else:
        initial_dir = str(Path(getattr(app, "app_root", ".")).resolve())
    target = filedialog.asksaveasfilename(
        parent=app.root,
        title="Save Project As",
        defaultextension=".sdproj",
        filetypes=[("SD Project", "*.sdproj"), ("All files", "*.*")],
        initialdir=initial_dir,
        initialfile=initial_name,
    )
    if not target:
        return
    save_project_to_path(app, target, is_autosave=False)


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
        frame_source=EagerFrameSource(
            raw_frames=frames_raw,
            subtracted_frames=frames_sub,
            visual_frames=frames_sub_viz,
            frame_names=list(frame_names),
            source_paths=list(image_paths),
        ),
        event_records=dict(loaded_actions.event_records),
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
    app.frame_source = plan.frame_source
    app.analysis_workspace.bind_frame_source(plan.frame_source)
    if getattr(app, "app_context", None) is not None:
        app.app_context.frame_source = plan.frame_source
    app.event_records = dict(plan.event_records)
    app.analysis_workspace.open_event(str(plan.active_event_id))
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
        frame_count = app._get_frame_count() if hasattr(app, "_get_frame_count") else len(app.frames_raw)
        app.slider.set(max(0, min(frame_count - 1, idx)))
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


def is_propagation_running(app) -> bool:
    manager = getattr(getattr(app, "app_context", None), "inference_manager", app.inference_manager)
    thread = getattr(manager, "propagate_thread", None)
    return bool(thread is not None and thread.is_alive())


def evaluate_close_requirements(app) -> CloseRequirements:
    return CloseRequirements(
        has_running_propagation=bool(app._is_propagation_running()),
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

    has_unsaved_masks = bool(getattr(app, "project_dirty", False))
    if has_unsaved_masks and hasattr(app, "_collect_nonempty_final_mask_frames"):
        try:
            has_unsaved_masks = bool(app._collect_nonempty_final_mask_frames())
        except Exception:
            has_unsaved_masks = bool(getattr(app, "project_dirty", False))
    if has_unsaved_masks and callable(getattr(app, "save_current_masks", None)):
        response = messagebox.askyesnocancel(
            "Unsaved Masks",
            "Current masks have unsaved changes.\n\nSave masks before closing?",
        )
        if response is None:
            return
        if response is True:
            app.save_current_masks()
            if bool(getattr(app, "project_dirty", False)):
                # Save was canceled or failed; keep window open.
                return

    if hasattr(app, "_shutdown_model_resources"):
        app._shutdown_model_resources()
    if hasattr(app, "_emit_host_sync"):
        app._emit_host_sync(reason="close")
    autosave_mgr = getattr(app, "autosave_manager", None)
    if autosave_mgr is not None and hasattr(autosave_mgr, "stop"):
        autosave_mgr.stop()
    app.inference_manager.stop()
    if app._ui_alive():
        app.root.destroy()
    app.cleanup_temp_files()
