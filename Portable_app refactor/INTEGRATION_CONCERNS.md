# Integration Concerns and Pain Points

## Context

This document summarizes the main concerns that make integrating the original `SD id tool` and `portable_app` difficult.

It is based on:

- the original repo structures and entrypoints
- the workflow differences between the two apps
- the lessons captured in [INTEGRATION_TAKEAWAYS.md](/Users/claydunford/Development/Combined%20tool%20test/INTEGRATION_TAKEAWAYS.md)

The goal is not to argue against integration. The goal is to identify where integration effort will be spent and where the highest architectural risk lives.

## 1. The apps have different top-level workflow ownership

This is the biggest problem.

### `SD id tool`

The SD tool is organized around:

- loading a stack
- browsing the full timeline
- marking SD event boundaries
- exporting event-oriented outputs

The main window is a browser. The popup is a local marking workspace. That split is already aligned with the user task.

### `portable_app`

The portable app is organized around:

- importing images
- loading the SAM2 model
- editing masks
- propagating masks
- running metrics/export
- saving project state

Its main window is an analysis/editor workspace.

### Why this matters

These are different root assumptions:

- one app assumes the user begins with event discovery
- the other assumes the user begins with mask generation

This means the integration problem is not just moving code between modules. It is deciding which workflow owns the first screen and which workflow becomes secondary.

## 2. The primary data-access strategies are incompatible

### `SD id tool` is built for streaming

The original `SD id tool/stack_reader.py`:

- indexes frame references instead of materializing the full stack
- reuses TIFF handles
- caches a small number of frames
- is explicitly optimized for repeated disk-backed access

That model is compatible with very large stacks.

### `portable_app` is built for eager loading

The original `portable_app/app/core/io.py`:

- reads all frames eagerly
- builds `frames_raw`
- builds denoised frames for the whole stack
- computes a global baseline and display cache across the whole stack
- stores the whole working set in memory

That model is convenient for the current segmentation app, but it is a bad default for large recordings.

### Why this matters

Without unifying this layer first, integration inherits the worst-case behavior:

- SD browsing becomes memory-heavy if it uses `portable_app`’s import model
- segmentation becomes structurally separate from the SD browser if it keeps its own independent image-loading model

This is not a UI concern. It is foundational infrastructure.

## 3. `portable_app` centralizes too much responsibility in one root object

The original `portable_app/app/app.py` puts many unrelated responsibilities into one app class:

- Tk root window setup
- UI composition
- imported frame ownership
- segmentation state
- event state
- autosave and project lifecycle
- model initialization
- metrics/export state
- propagation overlays
- interaction state

The app is composed from mixins and helper modules, but those helpers still depend on the root app object having a large mutable surface area.

### Why this matters

This makes it difficult to:

- reuse the segmentation workspace as a child window
- make project state browser-owned while analysis state is child-window-owned
- cleanly inject only the dependencies a secondary analysis window needs

Integration is harder because the current analysis app is not a narrow component. It is a large host object.

## 4. UI ownership and state ownership are too interleaved in `portable_app`

In the original portable app, project/session logic is not fully separated from UI widgets.

Examples:

- save/load logic depends on widget values for ranges and paths
- analysis/export defaults depend directly on spinbox state
- segmentation lifecycle reads UI entries and writes status labels directly
- inference/model startup is tied to app load/import behavior

### Why this matters

This makes reuse expensive.

If integration wants:

- a browser window that owns project files
- an analysis window that owns event-specific editing

then those concerns need cleaner boundaries than the original app currently provides.

## 5. The SD tool and segmenter use different event models

### `SD id tool`

The original SD app tracks events as lightweight `EventCandidate` objects:

- `event_id`
- `start_idx`
- `end_idx`
- duration metadata

The event is mainly a timeline annotation and export unit.

### `portable_app`

The original portable app treats events as project containers for:

- prompts
- paint layers
- committed masks
- optional draft masks
- propagation state
- analysis output references

The event is mainly a segmentation state bucket.

### Why this matters

The two apps are compatible at the concept level, but they do not use event records for the same purpose.

Integration needs to decide:

- whether the SD event is the canonical event identity
- how SD range metadata maps into segmentation event state
- whether an event can exist meaningfully before any masks/prompts exist

This is solvable, but it is a real modeling problem, not a simple field merge.

## 6. The SD tool’s output contract is file/export oriented, not project-state oriented

The original SD tool exports:

- per-event frame folders
- `event_summary.json`
- `events_manifest.csv`
- `events_manifest.json`

The original portable app saves:

- one `.sdproj` container
- per-event masks/prompts inside project storage
- image manifest and fingerprints

### Why this matters

These are different integration contracts:

- the SD tool expects event export artifacts
- the portable app expects one persistent project/session container

If integration uses export files as the bridge, it keeps the apps loosely coupled but creates friction.
If integration uses one shared project model, it must bypass or replace much of the SD tool’s export-first workflow.

## 7. Model initialization in `portable_app` is tightly coupled to imported stack state

The original `portable_app/app/core/segmentation.py` does more than load the model.

It also:

- writes a temp JPG sequence for the entire stack
- initializes predictor state against that temp sequence
- assumes the full segmentation session is ready once images are imported

### Why this matters

This is awkward for an integrated browser-first workflow.

In a better integrated design, users should be able to:

- load a stack
- browse events
- mark events
- only initialize the heavy segmentation machinery when they choose `Analyze SD`

The original segmenter is optimized for a different user flow, so its model lifecycle is in the wrong place for integration.

## 8. Range semantics are already crowded in `portable_app`

The original portable app already has multiple independent ranges:

- propagation start/end
- analysis start/end
- export start/end
- implicit active event frame span

The SD tool introduces another important range:

- event start/end

### Why this matters

If all of these are shown in one window without clearer ownership, the user can easily lose track of:

- which range defines the event
- which range defines the current analysis scope
- which range defines export

This is one reason a single-window merge tends to feel wrong even when it is technically working.

## 9. The SD tool is conceptually split, but not yet packaged as reusable services

The SD tool has a good conceptual separation:

- browser window
- popup processing engine
- stack reader
- export pipeline

But in practice much of the orchestration is still centered in `sd_gui.py`.

### Why this matters

It is easier to reuse than the portable app’s root object, but it is still not plug-and-play.

Integration still requires extracting:

- event CRUD/state ownership
- popup lifecycle control
- viewer overlay behavior

into cleaner service or controller boundaries.

## 10. Persistence ownership becomes ambiguous very quickly

The original portable app clearly owns:

- autosave
- open/save/new/recover
- the `.sdproj` lifecycle

The original SD tool does not.

### Why this matters

If the apps are integrated without a clear ownership decision, several questions become messy:

- does the SD browser own save/open?
- does the analysis window own save/open?
- when does analysis state sync back to the project?
- what happens if the user marks events while an analysis session is open?

This is less a storage-format problem and more an application-ownership problem.

## 11. Dependency/runtime expectations differ

The SD tool depends mainly on:

- Tkinter
- NumPy
- PIL
- TIFF/image utilities
- matplotlib for trace/export plots

The portable app additionally depends on:

- OpenCV
- PyTorch
- SAM2
- Hydra/config-driven model setup

### Why this matters

Integrating the apps means the lightweight browser workflow inherits the heavier runtime footprint unless care is taken to:

- keep segmentation dependencies lazily activated
- keep browser startup usable when model dependencies are absent or not yet loaded

Otherwise the lighter SD workflow becomes operationally heavier for no user benefit.

## 12. Testing strategy is stronger within each app than across the seam

Both repos have tests, but they validate different local contracts.

### `SD id tool` tests mostly cover

- stack reading
- popup processing cache/job behavior
- export determinism
- timeline/range helpers

### `portable_app` tests mostly cover

- project schema/store/migration
- autosave/recovery
- mask import and analysis helpers
- session state and event payload behavior

### Why this matters

The most fragile part of integration is the seam between:

- event marking
- event selection
- event-scoped analysis
- project sync

That seam is not naturally covered by either original test suite.

Integration will need a new layer of tests specifically around cross-workflow transitions.

## 13. There is no neutral shared core yet

The original repos do not share a common package for:

- stack access
- event definitions
- project/event synchronization
- window-to-window coordination

### Why this matters

Without a neutral core, integration tends to become:

- "make one app host the other"

instead of:

- "make both UIs consume the same services and state model"

That increases the chance of a brittle merge where one app’s assumptions dominate the other’s.

## Highest-Risk Integration Areas

If integration work resumes, the riskiest areas are:

1. Replacing eager stack loading with shared streaming access without breaking segmentation.
2. Reusing the current segmentation workspace as a child window instead of a root-owned app.
3. Defining one canonical event model that supports both SD marking and segmentation payloads.
4. Separating project lifecycle ownership from event-analysis UI ownership.
5. Preventing accidental cross-event edits when analysis is open on one event and the browser selects another.

## Bottom Line

The two original apps are compatible in intent, but difficult to integrate cleanly because they differ in:

- workflow ownership
- stack loading assumptions
- event semantics
- UI/state boundaries
- persistence ownership

The main pain point is not that either repo is "bad." It is that each one is internally coherent around a different center of gravity.

`SD id tool` is coherent around browsing and event marking.

`portable_app` is coherent around analysis and segmentation.

That is why direct integration is difficult: the problem is architectural alignment, not just missing glue code.
