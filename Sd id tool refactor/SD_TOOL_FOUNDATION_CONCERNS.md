# `SD id tool` Foundation Concerns for Easier Integration

## Purpose

This document lists low-risk structural concerns in `SD id tool` that do not need to change the app's current behavior, but would make future integration much easier.

The emphasis is on foundation work:

- cleaner module boundaries
- clearer ownership of data and UI state
- more reusable interfaces

Not on feature changes.

## 1. Too much orchestration lives in `sd_gui.py`

The app already has good conceptual pieces:

- `stack_reader.py`
- `processing_engine.py`
- `exporter.py`
- `ui_logic.py`

But a large amount of application orchestration still lives in `sd_gui.py`, including:

- event CRUD
- popup lifecycle
- preview rendering
- overlay management
- export triggers
- load-state management

### Why this matters for integration

This makes the SD browser hard to reuse as a clean top-level module in a larger integrated app.

### Foundation improvement

Extract thin controller/service layers for:

- event list management
- popup session management
- viewer/timeline state

This should preserve behavior while reducing direct UI-to-business-logic coupling.

## 2. Event state is lightweight, but not yet centralized behind one service

`EventCandidate` is a good start, but event operations are spread through GUI code.

Examples:

- next ID allocation
- add/edit/delete logic
- treeview synchronization
- current selected event tracking

### Why this matters for integration

An integrated app will want to reuse SD event state without also reusing the exact Tk widget behavior.

### Foundation improvement

Create one event-state manager that owns:

- event creation
- event updates
- deletion
- selection
- event ID generation

The existing UI can call it without changing visible behavior.

## 3. The main browser and popup are conceptually separate, but not packaged that way

The current SD tool already behaves like two surfaces:

- main browser window
- local popup marking workspace

That is a strength.

### Why this matters for integration

This separation is the right basis for a future browser-first architecture, but currently the popup depends heavily on shared mutable app state in the root GUI object.

### Foundation improvement

Formalize popup input/output boundaries:

- popup input: selected event or anchor frame, local range, baseline config, current frame
- popup output: confirmed event bounds and any updated popup-local settings

That makes the popup reusable without changing what the user sees.

## 4. Viewer/timeline state is mixed with widget state

The tool has a useful full-stack preview and overlay bar, but much of the state is directly tied to widgets and widget callbacks.

### Why this matters for integration

If this browser is reused inside a larger app or paired with a secondary analysis window, its navigation state should not depend on direct widget mutation patterns alone.

### Foundation improvement

Introduce a browser-view state object that owns:

- current frame index
- selected event ID
- visible overlay spans
- slider/range state

The widgets should reflect this state rather than own it.

## 5. Export is file-oriented and isolated from any long-lived project model

The exporter is internally clean, but its contract is entirely export-driven:

- manifests
- per-event folders
- summaries

### Why this matters for integration

That is useful, but a future integrated system will likely want to preserve SD events inside a project/session model before export.

### Foundation improvement

Keep the current exporter behavior, but add a separate serialization layer for SD event data that is not tied to export folder generation.

This should be additive, not a replacement.

## 6. Stack access is reusable, but tied to folder-oriented assumptions

`stack_reader.py` is one of the strongest parts of the codebase, especially:

- frame refs
- TIFF handle reuse
- bounded caching

### Why this matters for integration

An integrated app may want broader stack-source support:

- files selected individually
- project-restored image manifests
- already-resolved path lists

### Foundation improvement

Generalize the stack reader API so it can open a list of source files in addition to a folder.

That expands reuse without changing user-facing SD tool behavior.

## 7. Logging/status behavior is app-local rather than service-level

The current logging is useful for the standalone tool, but most subsystems report through the GUI layer.

### Why this matters for integration

When the SD browser becomes part of a larger system, browser logic, popup processing, and export should be able to report status without depending on one concrete text widget.

### Foundation improvement

Normalize internal status/progress callbacks so subsystems can emit structured updates while the current GUI still renders them exactly the same way.

## 8. The data model is good for SD marking, but not clearly separated from UI display needs

Current event data mixes:

- actual event boundaries and duration
- display-oriented concerns such as tree/table representation and current selection

### Why this matters for integration

Future integration will need to treat SD event data as durable application state, not just something shown in the table.

### Foundation improvement

Keep `EventCandidate`, but define:

- durable event data
- transient UI selection/display state

as separate concepts.

## 9. The app is reusable conceptually as a browser shell, but not exposed that way

The original SD tool is already the closest thing to the correct primary surface.

### Why this matters for integration

Integration gets easier if the SD tool can be thought of as:

- browser shell
- stack service
- event service
- popup service

instead of one Tk app file with helpers.

### Foundation improvement

Refactor toward a top-level browser controller that the current standalone app can instantiate directly.

That creates a reusable shell without altering current functionality.

## Best Foundation Work to Do First

If only a few low-risk steps are taken, the highest-value ones are:

1. Extract event CRUD/selection into a dedicated service.
2. Extract popup session input/output into a dedicated controller.
3. Generalize `stack_reader.py` to accept resolved file lists as well as folders.
4. Introduce a browser-view state object independent of Tk widgets.

## Bottom Line

`SD id tool` already has the right workflow shape for an integrated system.

Its biggest integration challenge is not incorrect behavior. It is that the right concepts already exist, but are still orchestrated mostly inside one GUI module.

The easiest foundational improvements are the ones that make those concepts explicit and reusable without changing what the standalone SD tool does today.
