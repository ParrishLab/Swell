#!/usr/bin/env python3
"""Headless benchmark for candidate SAM2-family models against saved Swell masks.

Each saved ``.swell`` project (or legacy ``.sdproj`` project) already stores, per
event, the human's *prompts* (clicks / paint) and the *committed masks* that
SAM2.1 produced (and the human accepted / edited). We treat those committed masks
as the **reference** -- i.e. the SAM2.1 result -- and do NOT re-run SAM2.1. The
harness replays the stored prompts through each *candidate* model (e.g. a smaller
SAM2.1 size, or MedSAM2) via the exact same inference path the app uses
(``build_sam2_video_predictor`` -> ``add_new_points_or_box`` / ``add_new_mask`` ->
``propagate_in_video``) and scores the candidate's masks against the reference
with IoU / Dice.

Only the **actual mask range** of each event is evaluated: propagation and scoring
are restricted to the span of frames where the committed mask is non-empty (plus
any prompt frames). The empty baseline pre-roll and tail frames are skipped, which
both removes trivially-perfect empty frames from the score and cuts compute. The
event itself already encodes how long to run -- the operator set that range when
they marked the event.

Example
-------
    .venv/bin/python -m tools.benchmark_models \
        --projects ~/Swell/Data/**/*.swell \
        --models sam2.1_hiera_tiny MedSAM2_hiera_tiny \
        --out bench_results.csv

Pass only the *candidate* models to ``--models``; the SAM2.1 reference comes from
the stored masks and is never run. Each model may be given as:
  * a checkpoint id present in ``swell/resources/checkpoints_catalog.json``
    (resolved to the managed models dir), or
  * a ``managed://<id>`` URI, or
  * a direct path to a ``.pt`` / ``.pth`` file.

Fidelity notes / known limitations
----------------------------------
* The reference is the saved SAM2.1 mask, possibly hand-edited. Heavily edited
  events are a less SAM2.1-biased comparison; use the ``paint_fraction`` column
  (share of prompt frames carrying manual paint) to weight toward those.
* Events whose only prompt is a committed-mask seed (no points and no paint) are
  skipped: seeding a candidate from the committed mask would leak the reference.
* Frames are reconstructed from ``StackRef.input_dir`` using the shared
  visualization pipeline (baseline subtraction / normalization). The baseline is
  computed over the full event scope (so normalization matches the app), but only
  the mask-range frames are exported and propagated. File ordering follows the
  same sorted-glob rule as the importer.
"""

from __future__ import annotations

import argparse
import csv
import glob
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

# Ensure the repo root is importable when run as a plain script.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import cv2  # noqa: E402

from swell.analysis.core.seg_state import SegmentationState  # noqa: E402
from swell.analysis.core.segmentation import _candidate_model_config_names  # noqa: E402
from swell.host.analysis_payload_mapper import EventBounds, scope_metadata  # noqa: E402
from swell.shared.frame_source.preprocessing import build_visualization_stack  # noqa: E402
from swell.shared.persistence import UnifiedProjectStore  # noqa: E402
from swell.shared.services.checkpoint_runtime_service import (  # noqa: E402
    CheckpointRuntimeService,
    managed_uri_to_id,
)

_SUPPORTED_EXTS = {".tif", ".tiff", ".jpg", ".jpeg", ".png", ".bmp"}
_RESOURCE_ROOT = str(_REPO_ROOT / "swell" / "resources")


# --------------------------------------------------------------------------- #
# Frame source: lazily read raw frames from an input directory.
# --------------------------------------------------------------------------- #
class _DirFrameSource:
    """Minimal frame source over a sorted list of image files (raw float32 gray).

    Implements only the contract ``build_visualization_stack`` needs:
    ``frame_count`` and ``get_raw_frame(idx)``.
    """

    def __init__(self, files: list[Path]):
        self._files = list(files)

    @property
    def frame_count(self) -> int:
        return len(self._files)

    def get_raw_frame(self, idx: int) -> np.ndarray:
        path = self._files[int(idx)]
        if path.suffix.lower() in (".tif", ".tiff"):
            import tifffile

            img = tifffile.imread(str(path))
        else:
            img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if img is None:
            raise RuntimeError(f"Failed to read frame: {path}")
        arr = np.asarray(img)
        if arr.ndim == 3 and arr.shape[2] in (3, 4):
            arr = arr[:, :, :3].mean(axis=2)
        return arr.astype(np.float32, copy=False)


def _list_stack_files(input_dir: str) -> list[Path]:
    """Replicate the importer's sorted-glob file ordering for a folder stack."""
    root = Path(input_dir).expanduser()
    if not root.is_dir():
        raise FileNotFoundError(f"Stack input_dir not found or not a directory: {root}")
    found: set[Path] = set()
    for ext in _SUPPORTED_EXTS:
        found.update(root.glob(f"*{ext}"))
        found.update(root.glob(f"*{ext.upper()}"))
    return sorted(found)


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
def _iou(pred: np.ndarray, gt: np.ndarray) -> float:
    p = pred.astype(bool)
    g = gt.astype(bool)
    inter = int(np.logical_and(p, g).sum())
    union = int(np.logical_or(p, g).sum())
    if union == 0:
        return 1.0  # both empty -> perfect agreement
    return inter / union


def _dice(pred: np.ndarray, gt: np.ndarray) -> float:
    p = pred.astype(bool)
    g = gt.astype(bool)
    denom = int(p.sum()) + int(g.sum())
    if denom == 0:
        return 1.0
    return 2.0 * int(np.logical_and(p, g).sum()) / denom


# --------------------------------------------------------------------------- #
# Model resolution + build
# --------------------------------------------------------------------------- #
@dataclass
class ResolvedModel:
    spec: str
    checkpoint_id: str | None
    path: str


def resolve_model(spec: str, svc: CheckpointRuntimeService) -> ResolvedModel:
    raw = spec.strip()
    # Direct file path?
    candidate = Path(raw).expanduser()
    if candidate.is_file():
        return ResolvedModel(spec=raw, checkpoint_id=svc.infer_checkpoint_id_from_path(str(candidate)), path=str(candidate.resolve()))
    # managed:// uri or bare catalog id
    cid = managed_uri_to_id(raw) or raw
    descriptor = svc.find_descriptor(cid)
    if descriptor is None:
        raise ValueError(
            f"Model '{spec}' is not a file and not in the checkpoint catalog. "
            f"Add it to swell/resources/checkpoints_catalog.json or pass a .pt path."
        )
    path = svc.descriptor_path(descriptor)
    if not path.is_file():
        raise FileNotFoundError(
            f"Catalog entry '{cid}' resolves to {path}, which does not exist. "
            f"Download/place the checkpoint there first (the app's model manager does this)."
        )
    return ResolvedModel(spec=raw, checkpoint_id=cid, path=str(path))


def build_predictor(model: ResolvedModel, device: str):
    """Build a SAM2 video predictor, mirroring segmentation.py's hydra/config probe."""
    from sam2.build_sam import build_sam2_video_predictor

    try:
        from hydra import initialize_config_dir
        from hydra.core.global_hydra import GlobalHydra

        GlobalHydra.instance().clear()
        initialize_config_dir(config_dir=_RESOURCE_ROOT, job_name="sam2_bench", version_base=None)
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] hydra init: {exc}", file=sys.stderr)

    candidate_names = _candidate_model_config_names(model.path, model.checkpoint_id)
    errors: list[str] = []
    for config_name in candidate_names:
        family = "sam2.1" if config_name.startswith("sam2.1_") else "sam2"
        local_cname = os.path.join(_RESOURCE_ROOT, "configs", family, config_name)
        if not os.path.exists(local_cname):
            continue
        cname = f"configs/{family}/{config_name}"
        try:
            predictor = build_sam2_video_predictor(cname, model.path, device=device)
            return predictor, cname
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{cname}: {exc}")
    raise RuntimeError(
        f"No compatible config for {model.spec}. Tried: {candidate_names}. Errors: {errors[:3]}"
    )


# --------------------------------------------------------------------------- #
# Per-event evaluation
# --------------------------------------------------------------------------- #
@dataclass
class EventCase:
    project: str
    event_id: str
    label: str
    n_local: int
    frame_dir: str
    prompt_frames: dict[int, dict]  # local_idx -> {"points":..., "paint_plus":..., "paint_minus":...}
    gt_masks: np.ndarray  # (n_local, H, W) bool
    paint_fraction: float
    frame_shape: tuple[int, int]


def export_frames_for_event(
    files: list[Path],
    scope_start: int,
    build_len: int,
    baseline_pre: int,
    sub_lo: int,
    sub_hi: int,
    proc: dict[str, bool],
    cache_root: Path,
    key: str,
) -> tuple[str, tuple[int, int]]:
    """Export the mask-range frames as JPEGs (renumbered from 0).

    Visualization stats (baseline subtraction, p1/p99 normalization, optional
    stabilization) are computed over the full scope window
    ``[scope_start, scope_start + build_len)`` using the event's stored
    ``analysis_processing`` options, so the exported frames match exactly what the
    app fed SAM2.1 when the committed masks were made. Only frames
    ``[sub_lo, sub_hi]`` are written -- the span containing the committed mask.
    """
    n_out = sub_hi - sub_lo + 1
    window_files = files[scope_start : scope_start + build_len]
    if len(window_files) < build_len:
        raise RuntimeError(
            f"Stack has {len(files)} frames; scope window [{scope_start}, {scope_start + build_len}) is out of range."
        )
    out_dir = cache_root / key
    out_dir.mkdir(parents=True, exist_ok=True)
    # Reuse export if complete.
    complete = all((out_dir / f"{j:05d}.jpg").exists() for j in range(n_out))
    if not complete:
        src = _DirFrameSource(window_files)
        _, _, visual = build_visualization_stack(
            src,
            baseline_frames=max(1, int(baseline_pre)),
            apply_horizontal_bar_denoise=bool(proc.get("horizontal_bar_denoise", False)),
            apply_smoothing=bool(proc.get("smoothing", True)),
            apply_baseline_subtraction=bool(proc.get("baseline_subtraction", True)),
            apply_global_normalization=bool(proc.get("global_normalization", True)),
            apply_stabilization=bool(proc.get("stabilization", False)),
        )
        for j, i in enumerate(range(sub_lo, sub_hi + 1)):
            frame_bgr = cv2.cvtColor(np.asarray(visual[i], dtype=np.uint8), cv2.COLOR_GRAY2BGR)
            cv2.imwrite(str(out_dir / f"{j:05d}.jpg"), frame_bgr)
        h, w = int(visual.shape[1]), int(visual.shape[2])
    else:
        first = cv2.imread(str(out_dir / "00000.jpg"))
        h, w = int(first.shape[0]), int(first.shape[1])
    return str(out_dir), (h, w)


def _nonempty_range(masks: np.ndarray) -> tuple[int, int] | None:
    """Return the inclusive [first, last] frame range that contains any mask."""
    nz = [i for i in range(int(masks.shape[0])) if bool(masks[i].any())]
    if not nz:
        return None
    return min(nz), max(nz)


def build_event_case(
    project_path: str,
    event,
    payload: dict[str, Any],
    files: list[Path],
    cache_root: Path,
) -> EventCase | None:
    gt = payload.get("masks_committed")
    if not isinstance(gt, np.ndarray) or gt.ndim != 3 or gt.shape[0] == 0:
        return None
    n_local = int(gt.shape[0])
    h, w = int(gt.shape[1]), int(gt.shape[2])

    prompts = payload.get("prompts") or {}
    seg = SegmentationState()
    try:
        seg.load_prompts_json(prompts, base_shape=(h, w))
    except Exception as exc:  # noqa: BLE001
        print(f"  [skip] {event.event_id}: prompt decode failed: {exc}", file=sys.stderr)
        return None

    prompt_frames: dict[int, dict] = {}
    n_paint = 0
    for f_idx, pts in seg.points.items():
        if 0 <= int(f_idx) < n_local and pts:
            prompt_frames.setdefault(int(f_idx), {})["points"] = pts
    for f_idx, layer in seg.paint_layers.items():
        plus = layer.get("plus")
        minus = layer.get("minus")
        has_plus = plus is not None and np.any(plus)
        has_minus = minus is not None and np.any(minus)
        if 0 <= int(f_idx) < n_local and (has_plus or has_minus):
            entry = prompt_frames.setdefault(int(f_idx), {})
            entry["paint_plus"] = np.asarray(plus, dtype=bool) if plus is not None else None
            entry["paint_minus"] = np.asarray(minus, dtype=bool) if minus is not None else None
            n_paint += 1

    if not prompt_frames:
        # Only a committed-mask seed would be left; skipping avoids reference leakage.
        return None

    paint_fraction = n_paint / len(prompt_frames) if prompt_frames else 0.0

    gt_bool = gt.astype(bool)
    rng = _nonempty_range(gt_bool)
    if rng is None:
        # No committed mask to compare against.
        return None
    # Restrict to the actual mask span, expanded to include every prompt frame
    # (prompts are the propagation seeds and must be inside the exported window).
    lo = max(0, min(rng[0], min(prompt_frames)))
    hi = min(n_local - 1, max(rng[1], max(prompt_frames)))

    flags = dict(event.flags or {})
    scope = scope_metadata(EventBounds(int(event.start_idx), int(event.end_idx), flags))
    scope_start = int(scope.scope_start)
    baseline_pre = int(flags.get("baseline_pre_frames", max(0, int(event.start_idx) - scope_start)))

    # Use the event's stored processing options so the exported frames match what
    # SAM2.1 actually saw (notably stabilization, which shifts pixels AND the frame
    # that the stored prompt coordinates were placed on).
    proc = flags.get("analysis_processing") if isinstance(flags.get("analysis_processing"), dict) else {}

    # Build visualization over [scope_start, scope_start+hi] (keeps the baseline
    # pre-roll for correct normalization); export only the [lo, hi] mask range.
    build_len = hi + 1
    proc_tag = "".join("1" if bool(proc.get(k)) else "0" for k in
                       ("horizontal_bar_denoise", "smoothing", "baseline_subtraction",
                        "global_normalization", "stabilization"))
    key = f"{Path(project_path).stem}__{event.event_id}__{scope_start}_{lo}_{hi}__p{proc_tag}"
    frame_dir, (fh, fw) = export_frames_for_event(
        files, scope_start, build_len, baseline_pre, lo, hi, proc, cache_root, key
    )
    if (fh, fw) != (h, w):
        print(
            f"  [warn] {event.event_id}: frame shape {(fh, fw)} != mask shape {(h, w)}; skipping.",
            file=sys.stderr,
        )
        return None

    # Re-base prompts and ground truth to the exported window (index 0 == frame lo).
    windowed_prompts = {int(f - lo): entry for f, entry in prompt_frames.items() if lo <= f <= hi}
    return EventCase(
        project=project_path,
        event_id=str(event.event_id),
        label=str(event.label),
        n_local=hi - lo + 1,
        frame_dir=frame_dir,
        prompt_frames=windowed_prompts,
        gt_masks=gt_bool[lo : hi + 1],
        paint_fraction=paint_fraction,
        frame_shape=(h, w),
    )


def run_model_on_case(predictor, case: EventCase, device: str, threshold: float) -> dict[int, np.ndarray]:
    """Init state on the event's frames, inject stored prompts, propagate both ways."""
    import gc

    import torch

    inference_state = predictor.init_state(video_path=case.frame_dir)
    predictor.reset_state(inference_state)

    prompt_idxs = sorted(case.prompt_frames.keys())
    anchor = prompt_idxs[0]
    h, w = case.frame_shape

    for f_idx in prompt_idxs:
        entry = case.prompt_frames[f_idx]
        if "paint_plus" in entry or "paint_minus" in entry:
            base = np.zeros((h, w), dtype=bool)
            plus = entry.get("paint_plus")
            minus = entry.get("paint_minus")
            mask = base.copy()
            if plus is not None:
                mask |= plus
            if minus is not None:
                mask &= ~minus
            predictor.add_new_mask(
                inference_state=inference_state,
                frame_idx=int(f_idx),
                obj_id=1,
                mask=mask.astype(np.float32),
            )
        if "points" in entry:
            pts = entry["points"]
            points = np.array([[p["x"], p["y"]] for p in pts], dtype=np.float32)
            labels = np.array([p.get("label", 1) for p in pts], dtype=np.int32)
            predictor.add_new_points_or_box(
                inference_state=inference_state,
                frame_idx=int(f_idx),
                obj_id=1,
                points=points,
                labels=labels,
            )

    out: dict[int, np.ndarray] = {}

    def _collect(reverse: bool):
        for out_frame_idx, out_obj_ids, out_mask_logits in predictor.propagate_in_video(
            inference_state, start_frame_idx=anchor, reverse=reverse
        ):
            if len(out_obj_ids) > 0:
                out[int(out_frame_idx)] = (out_mask_logits[0] > threshold).cpu().numpy().squeeze().astype(bool)

    try:
        with torch.inference_mode():
            _collect(reverse=False)
            _collect(reverse=True)
    finally:
        # Reusing one predictor across many events leaks device memory: each
        # init_state loads a fresh frame set onto the GPU. Drop this event's state
        # and reclaim the cache so long sweeps don't OOM (matches the app's cleanup).
        predictor.reset_state(inference_state)
        del inference_state
        gc.collect()
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
        elif torch.cuda.is_available():
            torch.cuda.empty_cache()
    return out


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
@dataclass
class Row:
    project: str
    event_id: str
    label: str
    model: str
    frame: int
    iou: float
    dice: float
    gt_nonempty: int
    pred_nonempty: int
    paint_fraction: float


def expand_projects(patterns: list[str]) -> list[str]:
    out: list[str] = []
    for pat in patterns:
        matches = glob.glob(os.path.expanduser(pat), recursive=True)
        if matches:
            out.extend(sorted(matches))
        elif os.path.isfile(os.path.expanduser(pat)):
            out.append(os.path.expanduser(pat))
    # de-dup, keep order
    seen: set[str] = set()
    uniq: list[str] = []
    for p in out:
        rp = str(Path(p).resolve())
        if rp not in seen and Path(rp).suffix.lower() in {".swell", ".sdproj"}:
            seen.add(rp)
            uniq.append(rp)
    return uniq


def pick_device(requested: str) -> str:
    import torch

    if requested != "auto":
        return requested
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--projects", nargs="+", required=True, help="`.swell` or legacy `.sdproj` paths/globs (recursive ** supported).")
    ap.add_argument("--models", nargs="+", required=True,
                    help="Candidate models to run (catalog ids, managed:// uris, or .pt paths). "
                         "Do not list SAM2.1 -- its result is the stored committed mask.")
    ap.add_argument("--out", default="bench_results.csv", help="Per-frame CSV output path.")
    ap.add_argument("--device", default="auto", choices=["auto", "mps", "cuda", "cpu"])
    ap.add_argument("--threshold", type=float, default=0.0, help="Logit threshold (app sensitivity default = 0.0).")
    ap.add_argument("--cache-dir", default=None, help="Where to write exported frame JPEGs (default: temp dir).")
    ap.add_argument("--max-events", type=int, default=0, help="Cap events per project (0 = all).")
    args = ap.parse_args(argv)

    device = pick_device(args.device)
    print(f"Device: {device}")

    svc = CheckpointRuntimeService()
    try:
        models = [resolve_model(m, svc) for m in args.models]
    except (ValueError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    for m in models:
        print(f"Model: {m.spec} -> {m.path}")

    projects = expand_projects(args.projects)
    if not projects:
        print("ERROR: no .swell files matched.", file=sys.stderr)
        return 2
    print(f"Projects: {len(projects)}")

    cache_root = Path(args.cache_dir).expanduser() if args.cache_dir else Path(tempfile.mkdtemp(prefix="osira_bench_"))
    cache_root.mkdir(parents=True, exist_ok=True)
    print(f"Frame cache: {cache_root}")

    store = UnifiedProjectStore()

    # Build each candidate predictor once; init_state is called per event.
    # SAM2.1 is NOT built here -- its result is the stored committed mask.
    built: dict[str, Any] = {}
    for m in models:
        print(f"Loading candidate {m.spec} ...")
        t0 = time.perf_counter()
        predictor, cname = build_predictor(m, device)
        built[m.spec] = predictor
        print(f"  ready via {cname} ({(time.perf_counter() - t0):.1f}s)")

    rows: list[Row] = []
    for proj in projects:
        print(f"\n=== {proj} ===")
        try:
            state = store.load(proj)
        except Exception as exc:  # noqa: BLE001
            print(f"  [skip project] load failed: {exc}", file=sys.stderr)
            continue
        if state.stack_ref is None:
            print("  [skip project] no stack_ref.", file=sys.stderr)
            continue
        try:
            files = _list_stack_files(state.stack_ref.input_dir)
        except FileNotFoundError as exc:
            print(f"  [skip project] {exc}", file=sys.stderr)
            continue

        n_events = 0
        for event in state.events:
            if args.max_events and n_events >= args.max_events:
                break
            payload = state.analysis_sidecar.get(str(event.event_id))
            if not isinstance(payload, dict):
                continue
            case = build_event_case(proj, event, payload, files, cache_root)
            if case is None:
                continue
            n_events += 1
            print(f"  event {case.event_id} ({case.label}): {case.n_local} mask-range frame(s), "
                  f"{len(case.prompt_frames)} prompt frame(s), paint_frac={case.paint_fraction:.2f}")

            for m in models:
                try:
                    preds = run_model_on_case(built[m.spec], case, device, args.threshold)
                except Exception as exc:  # noqa: BLE001
                    print(f"    [{m.spec}] inference failed: {exc}", file=sys.stderr)
                    continue
                dices = []
                for local_idx in range(case.n_local):
                    gt = case.gt_masks[local_idx]
                    pred = preds.get(local_idx, np.zeros(case.frame_shape, dtype=bool))
                    iou = _iou(pred, gt)
                    dice = _dice(pred, gt)
                    dices.append(dice)
                    rows.append(Row(
                        project=proj, event_id=case.event_id, label=case.label, model=m.spec,
                        frame=local_idx, iou=iou, dice=dice,
                        gt_nonempty=int(np.any(gt)), pred_nonempty=int(np.any(pred)),
                        paint_fraction=case.paint_fraction,
                    ))
                print(f"    [{m.spec}] mean Dice={np.mean(dices):.3f}")

    # Write per-frame CSV.
    out_path = Path(args.out).expanduser().resolve()
    with out_path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["project", "event_id", "label", "model", "frame", "iou", "dice",
                         "gt_nonempty", "pred_nonempty", "paint_fraction"])
        for r in rows:
            writer.writerow([r.project, r.event_id, r.label, r.model, r.frame,
                             f"{r.iou:.4f}", f"{r.dice:.4f}", r.gt_nonempty, r.pred_nonempty,
                             f"{r.paint_fraction:.3f}"])
    print(f"\nWrote {len(rows)} rows -> {out_path}")

    # Summary table: mean Dice/IoU per model.
    # "all" frames include empties (GT absent) which trivially score 1.0 and dilute
    # the signal; "GT+" restricts to frames that actually contain a committed mask,
    # which is the discriminative comparison between models.
    print("\n=== Summary ===")
    print(f"{'model':<32} {'frames':>8} {'Dice(all)':>10} {'IoU(all)':>9} "
          f"{'GT+frames':>10} {'Dice(GT+)':>10} {'IoU(GT+)':>9}")
    by_model: dict[str, list[Row]] = {}
    for r in rows:
        by_model.setdefault(r.model, []).append(r)
    for model, rs in by_model.items():
        md = float(np.mean([r.dice for r in rs])) if rs else 0.0
        mi = float(np.mean([r.iou for r in rs])) if rs else 0.0
        gt = [r for r in rs if r.gt_nonempty]
        gmd = float(np.mean([r.dice for r in gt])) if gt else 0.0
        gmi = float(np.mean([r.iou for r in gt])) if gt else 0.0
        print(f"{model:<32} {len(rs):>8} {md:>10.3f} {mi:>9.3f} "
              f"{len(gt):>10} {gmd:>10.3f} {gmi:>9.3f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
