# `SD id tool` Parallel Refactor Checklist

## Goal

Create low-risk structural improvements that preserve current behavior while making the SD tool easier to integrate into a future shared system.

## Safest First

### 1. Introduce an explicit event-state service

- Move event add/edit/delete/select/ID-allocation logic out of `sd_gui.py`
- Keep the existing `Treeview` and popup behavior unchanged
- Make the GUI call the service instead of mutating `self.events` directly

### 2. Separate durable event data from transient UI state

- Keep `EventCandidate` for durable event metadata
- Create separate state for:
  - current selected event
  - current preview frame
  - popup-local temporary edits
- Avoid changing displayed behavior

### 3. Extract popup session orchestration

- Create a popup controller that owns:
  - popup open/close
  - popup range state
  - baseline control normalization
  - confirm/cancel result handling
- Leave popup layout and visuals intact

### 4. Extract browser-view state from widget callbacks

- Introduce a browser state object for:
  - current frame index
  - selected event ID
  - overlay span data
  - visible range metadata
- Make UI widgets reflect state rather than own it

### 5. Standardize subsystem status/progress callbacks

- Give reader, popup processing, and export paths a shared callback shape
- Keep the current log widget rendering unchanged
- Reduce direct subsystem dependence on the GUI text widget

## Highest Leverage

### 6. Generalize `stack_reader.py` input contract

- Support opening a resolved file list as well as a folder
- Preserve natural sorting and TIFF handle reuse
- Avoid changing current standalone load behavior

### 7. Define a serializable SD event/session payload separate from export

- Add a lightweight event serialization layer not tied to `events_manifest.*`
- Keep exporter outputs unchanged
- Make SD event data portable into a shared project/session model later

### 8. Promote the main browser into an explicit top-level controller

- Create a browser controller/service boundary around:
  - stack lifecycle
  - event service
  - popup controller
  - export triggers
- Keep `sd_gui.py` as the standalone Tk host for now

### 9. Narrow `sd_gui.py` to view composition and user interaction wiring

- Reduce direct business logic in widget handlers
- Route event/popup/export operations through extracted services
- Preserve current logs, controls, and workflows

## Good Stopping Points

### Stop Point A

- Event service extracted
- Popup controller extracted
- No visible behavior changes

### Stop Point B

- Stack reader supports file lists
- SD event/session serialization exists
- Browser controller boundary is explicit

## Validation

- Existing SD popup tests should still pass
- Existing stack reader tests should still pass
- Existing exporter tests should still pass
- Manual smoke check:
  - load stack
  - mark event
  - edit/delete event
  - export selected/all
