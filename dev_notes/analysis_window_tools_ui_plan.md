# OSIRA Analysis Window — Tools & UI Phased Plan

Status: proposal / workshop output. No code changed yet.

Covers five new analysis tools plus a UI/UX restructure toward a single-canvas
creative-app shell (left tool rail, contextual options bar, right inspector dock,
bottom timeline).

## Guiding principles

- **Fix-and-cheap-wins before restructure.** Don't gate a broken feature or a
  one-line toggle behind a layout rewrite.
- **Scaffolding before tools.** The rail, options bar, and dock are prerequisites
  for cleanly placing box/fill/region tools.
- **Three-way placement rule:** tools that *draw* -> left rail; things that
  *toggle/manage* -> right dock; things that are *temporal* -> timeline.
- **Heaviest/schema-touching work last** (persistent regions), when the UI slots
  already exist.

---

## Phase 0 — Decoupled quick wins (no layout dependency)

**0a. Mask-overlay peek**
- Gate `apply_mask_overlay` at `render.py:232` on a `self._mask_peek` flag.
- **Add the peek bool to the cache token** at `render.py:241` — otherwise the
  cached overlaid image is returned and the toggle looks broken (the one gotcha).
- Held-key + sticky toggle, cloning the space-pan `KeyPress/KeyRelease` pattern at
  `layout.py:622`. Watch X11 key auto-repeat flicker; reuse the space-pan
  debouncing.

**0b. Mask leverage fix (#5)** — logic only, independent of UI:
- Recompute on mask edits (debounced), not only post-propagation — today
  `_recompute_leverage_map` fires only in `_set_propagated_frames` (`app.py:1737`).
- Stop the false max-trouble spike at object appearance/disappearance
  (`leverage.py:45`) — restrict scoring to the contiguous object span.
- Score *composed* final masks, not raw `masks_cache`.
- Recalibrate `TROUBLE_FLOOR`/weights on real events.

**Files:** `render.py`, `layout.py`, `leverage.py`, `app.py`
**Validation:** peek toggles cleanly with no stale cache; leverage strip no longer
reds-out the event ends and updates after a manual edit.

---

## Phase 1 — Shell restructure (the big layout change)

Rebuild the `content` grid from two `uniform="viewer"` columns (`layout.py:56`)
into **rail | canvas | dock** with weights `(0, 1, 0)` and a fixed dock width.

- **Left rail:** move the *existing* tool buttons (Select / Point+/- / Brush+/-)
  out of the bottom strip into a vertical rail. No new tools yet — just
  relocation. Reuse `tool_mode` + `_sync_tool_mode_buttons`.
- **Right dock (accordion/collapsible sections,** reusing the
  `_set_analysis_panel` pattern**):**
  - **Reference** (pinned top): small docked version of the no-overlay view + an
    **expand** pop-out (`Toplevel`) with **synced panning** via shared viewport
    state; keep the `if not self.is_dragging` skip (`render.py:270`) for the
    pop-out too.
  - **Propagation** controls (range stays mirrored onto the timeline overlay so
    the spatial link survives).
  - **Metrics / Masks.**
- Main area becomes a **single large interactive canvas**.

**Files:** `layout.py` (largest diff), `render.py` (pop-out render target),
`viewport.py` (confirm shared vs per-canvas pan state — decides if "synced" is
free).
**Risk:** highest of all phases (re-parenting `canvas_right`, grid rewrite). Do it
as one focused change after Phase 0.
**De-risk option:** split the dock-only move (propagation + metrics) from the
canvas/rail restructure.
**Validation:** propagation/metrics work from the dock; progress still shows in the
top status row; reference pop-out pans in lockstep.

---

## Phase 2 — Contextual tool-options bar

Add a thin options bar under the status row. New infra: a `dict` mapping
`tool_mode -> [option frames]` and a `_sync_tool_options()` hooked into the
existing `tool_mode.trace_add`. Migrate brush-size and sensitivity out of
always-visible into it.

**Files:** `layout.py`
**Why now:** every new tool (box/fill/region) drops its options into this bar;
building it once here keeps Phases 3–6 small.

---

## Phase 3 — Box prompts (#4)

Cheapest *model* feature — `add_new_points_or_box` already takes `box=` and is the
call used today (`inference_manager.py:550`).
- New `box` rail tool; rubber-band rectangle on drag; store `boxes[idx]` in
  `seg_state`.
- Add `box=` at the two injection sites (single-frame infer + propagation injector
  ~`inference_manager.py:771`); support box+points together.
- Thread box-only frames into `get_user_frames`/`user_seed_frames` so they count as
  anchors.
- New `record_action("box", ...)` undo type; `box` field in
  `to_prompts_json`/`load_prompts_json` + schema/migration.
- **Out of scope / research spike:** box-local renormalization fights SAM2's
  precomputed embeddings — track separately, likely as a global "boost contrast
  over range" preprocessing toggle, not box-local.

**Files:** `interaction_controller.py`, `inference_manager.py`, `seg_state.py`,
`undo.py`, `project_schema.py`, `project_migration.py`, `layout.py`

---

## Phase 4 — Fill (#3)

- **Fill-holes button** (`binary_fill_holes` on current mask) — highest
  value/effort ratio.
- **Bucket flood-fill** rail tool (`cv2.floodFill` -> write to
  `paint_layers[idx]["plus"]`/`["minus"]`).
- Both reuse the paint path: `record_action("paint", ...)`, undo,
  propagation-seeding, rendering — **no schema change**.

**Files:** `interaction_controller.py`, `layout.py`

---

## Phase 5 — Ghost outlines (#2)

View-only, no schema.
- For frames within +/-N, `cv2.findContours` -> draw **into the image array** with
  `cv2.polylines` + `addWeighted` (true alpha; avoids Tk canvas-item bloat and the
  no-alpha problem).
- **Cache contours** keyed by frame + the existing `_array_content_token`;
  `approxPolyDP`-simplify.
- Encode direction (dashed past / solid future or two hues); color user-defined
  frames differently via `get_user_frames`.
- Right-dock **View** panel: toggle + range slider + "auto-show while a drawing
  tool is active."
- Fold in the leverage **visibility toggle + "Jump to suggested" button** here (the
  `suggested` frame already exists from Phase 0).

**Files:** `render.py`, `overlay_renderer.py`, `layout.py`

---

## Phase 6 — Persistent never/always regions (#1)

Heaviest; done last when rail + dock + options bar exist.
- `persistent_regions` in `seg_state` (region mask + mode include/exclude + frame
  range).
- **Post-hoc override** as the spine: composite in `compose_final_mask`, in
  `update_display`, and at the `res_mask = (logits > thresh)` lines in propagation.
  **Optionally also** seed regions as a mask hint on the anchor frame (hybrid:
  guaranteed output + reduced downstream drift).
- Rail tool + red/blue mode in options bar (start as *painted* sticky region
  reusing brush raster; vertex-polygon editing is a v2).
- Right-dock **Regions** list: per-region delete / visibility / include-exclude
  toggle (the "layer-like" management surface).
- New undo type + new prompt-JSON fields + schema/migration.
- Default scope **global** (static artifacts), optional range.

**Files:** `seg_state.py`, `inference_manager.py`, `render.py`,
`interaction_controller.py`, `undo.py`, `project_schema.py`,
`project_migration.py`, `layout.py`

---

## Cross-cutting (touched across phases)

- **Tool plumbing:** `tool_mode` StringVar, `_sync_tool_mode_buttons`, dispatch in
  `on_mouse_down`/`_handle_tool`, modifier-inversion — extend, don't rewrite.
- **Undo:** currently only `paint`/`point`/`clear_frame`; add `box`, `region`.
- **Persistence + migration:** Phases 3 and 6 add prompt-JSON fields -> bump
  `project_schema.py` + `project_migration.py`.
- **Keybindings polish:** single-key tool shortcuts (Box->`K`, Fill->`G`,
  Region->`R`) in `_bind_shortcuts` — near-free pro-tool ergonomics.

## Dependency summary

```
Phase 0 (peek, leverage fix)        -- independent, do first
Phase 1 (shell: rail+dock+ref)      -- enables everything UI-placed
Phase 2 (options bar)               -- needs Phase 1
Phase 3 (box)   |
Phase 4 (fill)  |-- need Phases 1+2 for clean placement
Phase 5 (ghosts)|   (5 also closes out leverage UI from Phase 0)
Phase 6 (regions)   -- last; needs rail+dock+options bar
```
