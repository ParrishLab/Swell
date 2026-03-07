# `portable_app` Parallel Refactor Checklist

## Goal

Create low-risk structural improvements that preserve current behavior while making the segmentation app reusable as an event-scoped analysis workspace in a future integrated system.

## Safest First

### 1. Separate project ownership from root-window ownership

- Introduce a project coordinator/service for:
  - new/open/save/save-as
  - autosave/recovery
  - project load/apply orchestration
- Keep the current menu and user flow unchanged

### 2. Make sync boundaries explicit between workspace state and project event state

- Formalize methods for:
  - loading an event into analysis state
  - syncing active analysis state back into `event_states`
  - preparing project payloads for save
- Preserve `.sdproj` format and existing save behavior

### 3. Introduce a dedicated analysis-workspace controller

- Move root analysis-window orchestration behind a controller/adaptor
- Keep the current UI and root app behavior unchanged
- Make the controller accept injected services rather than assuming full app ownership

### 4. Isolate widget-backed state behind explicit workspace-state objects

- Define internal state for:
  - active event context
  - propagation/export/analysis ranges
  - navigation/display state
  - model readiness and analysis settings
- Keep widgets as views over that state

### 5. Make model startup analysis-scoped instead of import-scoped internally

- Decouple SAM2 lifecycle from stack import assumptions
- Preserve current startup timing in the standalone app
- Make the underlying code capable of deferred model initialization later

## Highest Leverage

### 6. Replace eager frame ownership with a stack-access abstraction

- Introduce an indexable frame source abstraction usable by:
  - render
  - inference setup
  - analysis helpers
  - project reopen
- Preserve current standalone behavior at first, even if initial implementation still wraps eager arrays

### 7. Narrow helper modules away from the giant app surface

- Replace broad `app`-shape expectations with smaller interfaces for:
  - project/session access
  - stack access
  - logging/status
  - analysis workspace state

### 8. Promote project/session/event-state code into the stable core

- Treat `project_session.py`, project schema/store, and event payload logic as reusable infrastructure
- Reduce dependence on root-window specifics in those layers

### 9. Clarify range ownership internally

- Explicitly document and encode the distinctions between:
  - event bounds
  - propagation scope
  - analysis scope
  - export scope
- Preserve current UI semantics while making later event-scoping safer

## Good Stopping Points

### Stop Point A

- Project coordinator extracted
- Event sync methods explicit
- No user-visible workflow changes

### Stop Point B

- Analysis-workspace controller exists
- Stack-access abstraction exists
- Root app is still standalone, but no longer the only possible host

## Validation

- Existing project schema/store/migration tests should still pass
- Existing autosave/recovery tests should still pass
- Existing mask import and session-state tests should still pass
- Manual smoke check:
  - import images
  - segment and propagate
  - save/open project
  - run metrics/export
  - recover autosave
