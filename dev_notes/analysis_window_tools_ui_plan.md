# OSIRA Analysis Window — Tools & UI Phased Plan

Status: Phases 0-6 are implemented and covered by focused/full analysis tests.

This plan tracks the analysis-window transition toward a single-canvas creative
app shell: floating tool rail, contextual options bar, right inspector dock, and
timeline-integrated temporal feedback.

## Guiding principles

- **Treat causes, not symptoms.** Prefer deterministic state and rendering rules
  over UI patches that hide inconsistent behavior.
- **Three-way placement rule:** tools that draw -> floating rail; tool parameters
  -> contextual options bar; temporal feedback -> timeline.
- **Keep workflows stable while moving controls.** Existing point, brush,
  propagation, metrics, mask-save, navigation, pan, and zoom behavior should keep
  working unless explicitly changed.
- **Use composed masks as the source of truth.** Rendering, leverage, propagation
  seeds, fill, and save/export paths should observe final composed mask state, not
  raw `masks_cache` alone.

---

## Completed Work

### Phase 0 — Quick behavior fixes

Implemented:
- Mask-overlay peek with both held-key and sticky toggle.
- Render cache token includes peek state, preventing stale overlay images.
- Leverage recompute now uses composed final masks, not raw mask cache only.
- Leverage recompute is debounced after manual edits and refreshed after
  propagation/import paths.
- Trouble scoring ignores object appearance/disappearance edges by comparing only
  within contiguous nonempty mask spans.

Validation:
- `test_render.py` covers peek/cache behavior.
- `test_leverage.py` covers composed-mask leverage and appearance/disappearance
  edge handling.

### Phase 1 — Shell restructure

Implemented:
- Main analysis UI now uses a large single canvas area with a floating tool rail.
- Right inspector dock contains Reference, Propagation, Event Metrics, and Save
  Current Masks surfaces.
- Reference canvas is docked and supports a synced pop-out reference window.
- Canvas background matches the dark UI instead of default white.
- Metrics are shown directly as Event Metrics instead of hidden behind an
  adjustment button.
- Save Current Masks is a standalone bottom dock action.

Notable refinement:
- The left tool panel floats on top of the canvas rather than occupying a fixed
  layout column.

Validation:
- Viewport tests cover pop-out canvas sizing.
- UI helper and runtime tests cover required attributes and control state.

### Phase 2 — Contextual options bar

Implemented:
- Tool options bar sits below the status row.
- Sensitivity is shown for point and box prompt modes.
- Brush size is shown only for brush/eraser.
- Fill options are shown only for Fill.
- Tool-mode changes avoid unnecessary redraw work when reselecting the active
  tool.

Validation:
- UI helper tests cover option syncing and tool mode behavior.
- Hotkey tests cover tool shortcuts.

### Phase 3 — Box prompts

Implemented:
- Box prompt tool with shortcut `K`.
- Box button is grouped with point tools in the floating rail.
- Rubber-band rectangle drawing on canvas.
- One normalized image-space box per frame.
- Select tool can select, move, and resize boxes using larger grab handles.
- Boxes are rendered with selected/non-selected colors matching point prompt
  conventions.
- Boxes count as user frames, propagation anchors, and prompt markers.
- Single-frame inference and propagation pass `box=` to SAM2-style
  `add_new_points_or_box(...)`, including points+box on the same frame.
- CPU fallback predictor accepts `box`.
- Undo/redo supports `record_action("box", ...)`.
- Prompt JSON persists `box`.
- Project schema bumped to version 4 with additive migration from v3.

Validation:
- `test_interaction_controller.py` covers box drag, tiny-box ignore, selection,
  move/resize, delete, and undo snapshots.
- `test_inference_manager.py` covers box-only and points+box inference and
  propagation injection.
- `test_seg_state.py`, `test_seg_state_prompt_serialization.py`,
  `test_undo_actions.py`, `test_project_schema.py`, and
  `test_project_migration.py` cover state, persistence, undo, and migration.

### Phase 4 — Fill tools

Implemented:
- Fill rail tool with shortcut `G`.
- Fill options include Add/Remove mode and tolerance.
- Fill Holes action is available from the Fill options bar.
- Fill Holes writes only newly filled hole pixels into plus paint while
  respecting existing minus paint.
- Bucket Fill writes to `paint_layers[idx]["plus"]` or `["minus"]`, so fill edits
  reuse paint undo/redo, rendering, propagation anchors, leverage, mask peek, and
  Save Current Masks.
- Bucket Fill now uses deterministic source selection:
  - Add mode first fills a closed empty region bounded by composed mask/paint
    under the click.
  - Add mode falls back to visible-frame intensity flood fill when no bounded
    region exists under the click.
  - Remove mode only erases the composed mask/paint component under the click and
    no-ops on empty background.

Validation:
- `test_interaction_controller.py` covers add/remove fill, bounded paint/mask
  regions, image fallback, outside-image no-op, remove-outside-mask no-op, fill
  undo, and fill holes.
- `test_undo_actions.py`, `test_render.py`, and `test_leverage.py` cover
  downstream paint-layer consumers.

---

## Timeline Progress Refinements — Completed

Implemented after Phase 4:
- Model loading and propagation progress moved out of the status row and into the
  existing `slider_overlay` timeline strip.
- No extra timeline progress row is used; progress is layered on the existing
  timeline bar.
- Green/purple/red timeline markers stay visually above progress.
- Model loading uses an indeterminate moving segment, not a full-width completed
  fill.
- Progress color uses the shared accent blue `#1b75bc`.
- Loading/progress rendering is optimized:
  - static timeline layers are redrawn only when static overlay state changes;
  - progress uses tagged `timeline_progress` canvas items;
  - loading animation updates item coordinates at a 33 ms cadence;
  - propagation updates reuse progress items instead of full overlay redraws.
- Propagation progress carries range, anchor, direction, and retained
  forward/backward phase counts.
- Bidirectional propagation keeps completed forward/backward timeline segments
  visible while the opposite direction runs.

Validation:
- `test_runtime_status_activity.py` covers loading/progress state, scheduling, and
  clearing.
- `test_propagation_progress.py` covers progress payloads and retained
  forward/backward phase state.
- `test_propagation_overlay_state.py` covers timeline geometry, item reuse,
  layering, color, and bidirectional progress visualization.

### Phase 5 — Ghost outlines

Implemented:
- Render ghost outlines for masks within a configurable +/-N frame window (cyan/blue for past, magenta/rose for future).
- Contours computed via `cv2.findContours`, simplified using `cv2.approxPolyDP`, and alpha-blended into the main image array in `render.py` before resizing.
- Contours cached by frame and mask content token (CRC32 checked) to handle dynamic edits, undo/redo, and propagation updates without stale artifacts.
- Right dock View section added with ghost outlines toggle, range control scale, leverage visibility toggle, and Jump to Suggested Correction button.
- Support toggling leverage visibility which conditionally shows/hides timeline leverage heatmap and correction frames.

Validation:
- Unit tests for contour cache invalidation in `test_render.py`.
- Render/styling tests for explicit ghost outline toggling and styling in `test_render.py`.
- UI smoke tests for View dock controls and callbacks in `test_render.py`.

Post-implementation fixes (leverage/heatmap pass):
- The leverage heatmap was computed but never visible: it was drawn first and
  then painted over by coverage/marker bands. Now drawn after coverage/progress
  and below the marker bands (markers raised last), as its own bottom strip.
- Heatmap colouring is now relative to the worst region in view (worst = red,
  calmer = green) instead of an absolute `LEVERAGE_FLOOR`, which real masks
  rarely exceeded and which rendered everything green.
- Leverage scoring no longer under-flags sharp transitions: `compute_trouble`
  scores a frame by its worst neighbour transition (max, not mean), and
  `compute_leverage` floors the length factor (`LENGTH_FLOOR`) so short, sharp
  jumps survive. The `LEVERAGE_FLOOR` gate on the suggested frame was dropped, so
  the worst troubled region is always surfaced (fixes "Jump to Suggested").
- Undo/redo now recompute leverage (`_apply_state` schedules a recompute); it
  previously refreshed markers but left the heatmap stale.
- Removed a redundant leverage recompute on the propagation `complete` status —
  `_set_propagated_frames` already recomputes when ingesting completed masks.
- Box-prompt reset bug (Phase 3): `_reset_interaction_state` now clears
  `boxes` alongside points/paint/masks, so stale box prompts no longer leak into
  a newly imported stack.
- Ghost-outline blend efficiency: contour blending is restricted to each ghost's
  bounding-box ROI via `cv2.addWeighted` (bit-identical output, ~2.8x faster for
  localized ghosts), keeping ghosts live and cheap while painting against them.
  Cache entries now hold `{contours, bbox}` keyed by `(frame, token, shape)`.

---

### Phase 6 — Persistent include/exclude regions

Implemented:
- Added event-local polygon persistent regions with stable IDs, mode
  (`include`/`exclude`), enabled/visible flags, inclusive frame ranges, and
  image-space polygon vertices.
- Project schema bumped to version 5 with additive migration from v4.
- Prompt JSON now persists top-level `persistent_regions`; project/session and
  host workspace sync preserve them per event.
- `compose_final_mask` applies enabled in-range regions after masks and paint:
  includes add pixels, excludes remove pixels, and excludes win on overlap.
- Region rail tool with shortcut `R` creates polygon vertices on the canvas.
- Contextual options bar provides mode, editable start/end frame range, Close
  Polygon, Cancel, Commit Region, and Apply Selected controls.
- Select tool can select visible in-range regions, move polygons, drag vertices,
  and insert a vertex by dragging an edge.
- Right dock Regions section lists regions with select, enabled, visible,
  duplicate, and delete controls.
- Region edits use undo action type `region` with full-list snapshots.
- Region outlines and selected handles render on the main canvas while mask peek
  continues to affect only the mask overlay.

Validation:
- `test_seg_state.py` covers include/exclude composition, exclude precedence,
  visibility-vs-composition, disabled/out-of-range handling, and region-only
  nonempty frame candidates.
- `test_seg_state_prompt_serialization.py`, `test_project_migration.py`, and
  `test_project_session_event_records.py` cover schema, prompt, and event
  persistence.
- `test_interaction_controller.py` covers polygon creation, invalid polygon
  rejection, select-drag movement, and deletion.
- `test_undo_actions.py` covers region undo/redo snapshots.
- `test_render.py` covers visible selected region overlay handles.

---

## Cross-cutting state after Phase 6

- Tool shortcuts in use:
  - Select: `V`
  - Point+: `+` / `=`
  - Point-: `-`
  - Brush: `B`
  - Eraser: `E`
  - Box: `K`
  - Fill: `G`
  - Region: `R`
  - Mask peek: `P`
- Schema version: 5.
- Prompt JSON includes points, boxes, paint layers, and persistent regions.
- Fill edits remain paint-layer edits and do not require schema changes.
- Region constraints are post-composition and are not injected as SAM prompts.

## Current validation baseline

Latest focused/full validation used during implementation:

```bash
python -m pytest tests/analysis
```

Recent result after Phase 6: all analysis tests passing (360).

Note on "complete": phase status below reflects implemented + unit-test-passing,
not full live-app verification. The Phase 5 fixes above were behaviour bugs that
still passed the prior test suite, so treat the checkmarks as "tests green,"
not "verified by clicking through the running app."

## Dependency summary

```text
Phase 0 (peek, leverage fix)              complete
Phase 1 (floating rail + dock + ref)      complete
Phase 2 (options bar)                     complete
Phase 3 (box prompts)                     complete
Phase 4 (fill tools)                      complete
Timeline progress refinements             complete
Phase 5 (ghost outlines + view controls)  complete
Phase 6 (persistent regions)              complete
```
