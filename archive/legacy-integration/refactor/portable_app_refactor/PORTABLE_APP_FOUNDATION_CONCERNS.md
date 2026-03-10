# `portable_app` Foundation Concerns for Easier Integration

## Purpose

This document lists low-risk structural concerns in `portable_app` that do not need to change current user-visible behavior, but would make future integration much easier.

The emphasis is on foundation work:

- decomposing ownership
- reducing root-app coupling
- making the segmentation workspace reusable

Not on changing the current segmentation workflow.

## 1. The root app object owns too many unrelated concerns

The current `app.py`-centered design combines:

- Tk root/window ownership
- imported frame ownership
- segmentation state
- event state
- autosave/project lifecycle
- model lifecycle
- render/interaction wiring
- metrics/export state

### Why this matters for integration

A future integrated design will likely need the segmentation workspace as a secondary surface, not the root application shell.

That is hard if the analysis UI assumes it owns everything.

### Foundation improvement

Split the current app responsibilities into clearer layers:

- project/session owner
- stack access owner
- analysis workspace controller
- root window host

The existing standalone app can still instantiate them together.

## 2. Project lifecycle is too closely tied to the root analysis window

`portable_app` clearly owns:

- `New/Open/Save/Save As`
- autosave/recovery
- project migration/load

But those flows assume the root app window is also the analysis workspace.

### Why this matters for integration

In a browser-first integrated app, project lifecycle should be owned by the browser window, while the segmentation workspace should act more like an editor over shared project state.

### Foundation improvement

Move project ownership behind a project coordinator/service so the existing window can call it, but a future browser window can also own it without rewriting persistence logic.

## 3. The segmentation workspace is reusable in concept, but not yet in structure

The existing segmentation UI is valuable and should likely be reused.

However, it currently assumes:

- it owns stack import
- it owns model startup timing
- it owns project lifecycle context
- it is the primary user surface

### Why this matters for integration

That makes it difficult to open the current workspace as an event-scoped secondary window.

### Foundation improvement

Extract an analysis-workspace adapter that accepts injected dependencies:

- current event ID
- stack source
- event state
- project/session services

This can be done while preserving the current standalone window behavior.

## 4. UI widget state and business state are too tightly coupled

The current code relies heavily on widget values for application behavior:

- range spinboxes
- input/output entries
- scale/ROI controls
- current tool mode

### Why this matters for integration

In a multi-surface app, UI widgets should reflect analysis state, not define the only source of truth for it.

### Foundation improvement

Introduce explicit workspace-state objects for:

- active range values
- display/navigation state
- analysis/export settings
- current event context

The existing widgets can bind to those values without changing current functionality.

## 5. Event state exists, but the app still behaves like one event is the whole app

`portable_app` already has an `event_states` concept in the project/session model.

That is good.

But many flows still assume the currently loaded event is effectively the full active app context.

### Why this matters for integration

An integrated browser-first design needs one event to be editable without the app implicitly forgetting that other events exist.

### Foundation improvement

Clarify the distinction between:

- canonical project event data
- currently loaded analysis event
- transient workspace state for the loaded event

That separation can be introduced without changing the current visible workflow.

## 6. Import and model lifecycle are too closely coupled

In the original design, importing a stack leads quickly into model-oriented behavior.

The model setup path also depends on:

- full working image state
- temp-frame preparation
- app-wide readiness state

### Why this matters for integration

A browser-first integrated system should be able to:

- open a stack
- manage events
- delay heavy analysis initialization until needed

### Foundation improvement

Make model startup explicitly analysis-session-scoped rather than import-scoped.

The current standalone app can still start it at the same time if desired, but the code should no longer require that assumption.

## 7. Eager stack loading is convenient for the current app, but a bad shared foundation

The original `portable_app` import path eagerly materializes:

- raw frames
- denoised frames
- baseline-subtracted frames
- display caches

### Why this matters for integration

That approach is incompatible with the SD browser’s streaming assumptions and makes large stacks harder to support.

### Foundation improvement

Replace the import layer with a stack-access abstraction that can later support:

- lazy reads
- cached processed views
- event-scoped access

The segmentation UI can still consume an indexable frame source, but it should not require a full in-memory stack.

## 8. The current module split is better than the root class, but helpers still depend on the root app shape

There are already focused modules such as:

- `io.py`
- `project_workflow.py`
- `project_session.py`
- `segmentation.py`
- `analysis_controller.py`

That is good progress.

### Why this matters for integration

Many of these helpers still assume a large `app` object with many mutable fields and widgets.

### Foundation improvement

Reduce helper dependence on the concrete root app surface by introducing narrower interfaces for:

- project/session access
- stack access
- status/logging
- analysis workspace state

## 9. Persistence is strong, but synchronization boundaries are implicit

The `.sdproj` model is one of the strongest assets in `portable_app`.

However, the exact sync boundaries between:

- UI edits
- `seg_state`
- `event_states`
- saved project payloads

are still mostly orchestrated procedurally.

### Why this matters for integration

A reusable analysis window will need explicit rules for:

- when working state is synced into canonical event state
- when canonical event state is written to disk
- what happens on close/switch/save

### Foundation improvement

Define explicit sync methods and transitions without changing the existing save format.

## 10. Analysis/export/propagation range semantics need clearer ownership

The current app has multiple overlapping ranges:

- propagation
- analysis
- export
- implicit event bounds

### Why this matters for integration

If the segmentation workspace is later launched from a selected SD event, those ranges need a clear hierarchy.

### Foundation improvement

Define range semantics explicitly:

- event bounds
- current analysis window scope
- propagation scope
- export scope

That can remain internal documentation/code cleanup at first, without changing visible UI behavior.

## 11. Runtime dependency weight should be kept behind analysis-specific boundaries

The portable app depends on heavier runtime layers:

- OpenCV
- PyTorch
- SAM2
- Hydra/config-based model init

### Why this matters for integration

If these dependencies leak into a future primary SD browser surface, the lighter browsing workflow becomes harder to run and reason about.

### Foundation improvement

Keep heavy dependencies behind analysis-only initialization boundaries so the segmentation workspace is modular and lazily activated.

## 12. The best reusable asset is the per-event project model, but it needs clearer ownership around it

The strongest part of `portable_app` for integration is the event-oriented project/session persistence.

### Why this matters for integration

That model should become shared infrastructure, not remain tightly identified with one root UI shell.

### Foundation improvement

Promote the project/session/event-state layer as the stable core, and treat the current segmentation window as one client of that core.

## Best Foundation Work to Do First

If only a few low-risk steps are taken, the highest-value ones are:

1. Separate project ownership from root-window ownership.
2. Introduce an analysis-workspace controller that can be hosted by a child window.
3. Replace eager frame ownership with a stack-access abstraction.
4. Make event/workspace sync points explicit instead of procedural.

## Bottom Line

`portable_app` already has the strongest persistence and per-event analysis infrastructure.

Its main integration difficulty is not missing features. It is that the current app structure assumes the segmentation workspace is the entire application.

The most useful foundational improvements are the ones that make the existing analysis workspace reusable as a component without changing what the standalone app does today.
