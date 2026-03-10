# SD Tool Seam Preparation (Host-Side Changes)

## Purpose
Prepare **SD id tool** to host `portable_app` as an event-scoped analysis workspace, without integrating UI windows yet.

This document defines the concrete refactor steps needed in SD id tool so both apps can meet at a stable seam.

## Target Seam Contract
The host app (SD tool) must provide the analysis app with:
- `event_id: str` (canonical identity)
- `start_idx: int`
- `end_idx: int`
- `label: str`
- stack handle (`FrameSource`-compatible adapter)
- persistent project/session service for event read/write

The host keeps ownership of:
- project lifecycle (`new/open/save/autosave/recovery`)
- stack loading and event catalog
- active event selection

The analysis workspace keeps ownership of:
- segmentation prompts/masks/drafts for one event
- event-scoped editing and propagation state

## Required SD Tool Refactors

### 1. Extract a non-UI `EventCatalogService`
Current issue:
- Event creation/edit/delete/selection is largely embedded in GUI flow.

Needed change:
- Add a service layer (`core/event_catalog.py` or equivalent) with no Tk dependencies.
- Public methods:
  - `list_events() -> list[EventMeta]`
  - `create_event(start_idx, end_idx, label=None) -> event_id`
  - `update_event(event_id, start_idx=None, end_idx=None, label=None)`
  - `delete_event(event_id)`
  - `get_event(event_id) -> EventMeta | None`
  - `set_active_event(event_id)`
  - `get_active_event_id() -> str | None`

Constraints:
- Event IDs must be stable and persisted.
- Bounds normalization (`start <= end`) must be enforced in service, not UI.

### 2. Introduce a project/session persistence layer
Current issue:
- SD tool is export-first (`events_manifest.*`) rather than project-session-first.

Needed change:
- Add project session abstraction (`core/project_session.py`) that persists:
  - stack identity/reference
  - event catalog
  - global analysis metadata needed by host
- Keep existing export outputs for backward compatibility, but make them derived artifacts.

Minimum methods:
- `new_project(stack_ref)`
- `open_project(path)`
- `save_project(path=None)`
- `upsert_event_meta(...)`
- `load_event_meta(event_id)`

### 3. Add a stack adapter that matches seam expectations
Current issue:
- SD tool has stack reader internals, but no stable interface shaped for cross-app hosting.

Needed change:
- Wrap current `stack_reader` in an adapter with this interface:
  - `frame_count`
  - `frame_shape`
  - `frame_names`
  - `source_paths` or stable stack reference
  - `get_raw_frame(idx)`
  - optional preprocessed getters if already available

Notes:
- Keep current streaming/caching behavior; do not regress memory profile.
- Adapter should be UI-agnostic and safe for background read access patterns already used by SD tool.

### 4. Separate table/timeline UI from event mutations
Current issue:
- UI handlers directly mutate event state.

Needed change:
- Table, timeline, and popup actions call `EventCatalogService` methods.
- UI becomes a projection of service state.
- Add explicit refresh/update methods:
  - `refresh_event_table(events)`
  - `refresh_timeline_overlays(events, active_event_id)`

### 5. Add host-side analysis handoff API (no window integration yet)
Needed change:
- Add a host adapter object (`AnalysisHandoffAdapter`) that returns:
  - selected event metadata
  - frame source adapter
  - project/session handle for event payload sync

This is the object `portable_app` will consume later.

### 6. Lock event identity and metadata compatibility
Required compatibility rules:
- `event_id` is canonical and never regenerated on relabel.
- `start_idx`/`end_idx` are integer frame indices in stack coordinate space.
- Labels are mutable presentation fields.

## Data Model Recommendations
Use explicit dataclasses/types in SD tool:
- `EventMeta(event_id, start_idx, end_idx, label, flags)`
- `HostSessionState(active_event_id, events, stack_ref, project_path, dirty)`

Avoid passing raw dicts between UI and persistence layers.

## Incremental Delivery Order
1. Add `EventMeta` + `EventCatalogService` and route existing UI through it.
2. Add project/session persistence abstraction and map existing manifest behavior into it.
3. Add frame source adapter around `stack_reader`.
4. Add analysis handoff adapter API.
5. Add host-level tests and only then start cross-app wiring.

## Test Requirements (SD Tool Side)
Add tests before integration wiring:
- event catalog CRUD + active selection
- bounds normalization and validation
- event ID stability across relabel/save/load
- project roundtrip with event metadata preserved
- frame source adapter index/shape correctness
- host handoff returns consistent `(event, frame_source, session)` tuple

## Acceptance Criteria Before Integration
- SD tool can load a large stack and manage events entirely via service APIs.
- Event table/timeline are projections of service state, not state owners.
- Project open/save restores event catalog and active event deterministically.
- Frame source adapter is stable and independent from GUI code.
- Host handoff API exists and is consumed in at least one non-UI integration test.

## Non-Goals in This Pass
- No merge of UI windows yet.
- No schema redesign beyond what is needed for host event/session ownership.
- No replacement of SD tool’s existing processing algorithms.
