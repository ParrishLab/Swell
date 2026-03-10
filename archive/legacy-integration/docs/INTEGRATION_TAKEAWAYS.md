# Integration Takeaways: `SD id tool` + `portable_app`

## Summary

Trying to merge the two apps directly into one window exposed a mismatch in workflow ownership.

- `SD id tool` is event-first.
- `portable_app` is segmentation-first.

Those are not just different UIs. They imply different top-level state models, different performance assumptions, and different user intent at launch.

The initial merge was technically possible, but it pushed the user through a segmentation-oriented interface before the core task, which is identifying SD events. That created avoidable complexity and made the app feel structurally wrong even when features were present.

## Main Takeaways

### 1. The real primary workflow is SD identification, not segmentation

The SD browser needs to be the top-level application surface.

Users need to:

- open a stack
- browse the full timeline
- mark/edit/delete SD events
- decide which event to analyze next

Segmentation is a secondary action on one chosen event, not the main shell the user should land in.

### 2. Reusing one app as the host was cheaper, but not cleaner

Using `portable_app` as the host let me reuse:

- project persistence
- segmentation state and mask handling
- propagation
- metrics/export
- autosave/recovery

That was the shortest implementation path, but it preserved the wrong top-level mental model. The result was a browser workflow embedded inside a segmentation app rather than a segmentation workflow launched from an SD browser.

### 3. A single-window merge increases coupling too quickly

Putting both workflows in one window caused several problems:

- too many controls visible at once
- weak separation between event selection and event analysis
- ambiguous ownership of ranges (`event`, `propagation`, `analysis`, `export`)
- higher risk of accidentally editing the wrong event context

The more the two apps were merged into one surface, the more state synchronization logic was needed just to protect the user from the UI.

### 4. Streaming is not optional

The first structural failure was memory.

`portable_app` originally assumed full eager stack loading, which is not viable for large stacks. `SD id tool` already had the better assumption: stream frames from disk, cache lightly, and only materialize what is needed.

Important conclusion:

- stack streaming is foundational infrastructure, not an optimization

Any future architecture should treat lazy frame access as the default for:

- browser preview
- SD popup processing
- project reopen
- analysis-window rendering

### 5. The analysis workspace should be event-scoped

Once a user picks an event, the segmentation UI should open already scoped to:

- that event ID
- that event’s frame start/end
- that event’s saved masks/prompts

This eliminates most accidental cross-event editing and makes the current `portable_app` workspace much more understandable.

### 6. One project model can still support two windows

A second window does not require a second project format.

The existing `.sdproj` model is still workable if:

- the browser owns project lifecycle
- the browser owns the canonical `event_states`
- the analysis window edits one event at a time
- the analysis window syncs back into the browser-owned session state

That is a cleaner separation than giving both windows equal ownership of persistence.

## What Worked Well

- Reusing `portable_app` persistence and per-event state model
- Preserving one `.sdproj` file format
- Reusing the segmentation workspace mostly as-is for event analysis
- Reusing SD popup processing concepts inside the combined codebase
- Moving toward a shared streaming stack layer

## What Caused the Most Friction

- Root-window assumptions baked into `portable_app`
- A large amount of logic living inside one `SDSegmentationApp` class
- UI code and project/state ownership being too interleaved
- Implicit assumption that one active event is also the whole application context
- Model initialization and segmentation lifecycle being tied too closely to import/load

## Architectural Direction That Seems Best

The most defensible structure is:

1. `SDBrowserApp` as the primary window
   - streaming stack viewer
   - event list
   - mark/edit/delete
   - `Analyze SD`
   - project open/save/new/autosave ownership

2. `EventAnalysisWindow` as a reusable child window
   - current `portable_app` workspace
   - scoped to one selected event
   - warns before replacing current context
   - syncs state back to browser-owned project session

3. Shared services underneath both
   - streaming stack access
   - project store
   - session/event state synchronization
   - mask import and metrics/export services

## Codebase Lessons

If this integration is going to keep evolving, the next high-value refactors are:

- extract browser-specific logic out of `app.py`
- extract analysis-window lifecycle into its own module/class
- reduce dependence on one giant app object with many mutable fields
- formalize state sync boundaries between browser and analysis surfaces
- keep disk-backed frame access as the baseline assumption everywhere

## Bottom Line

The integration attempt showed that the apps are compatible at the data/model level, but not at the top-level workflow level.

The correct unification is not "put both tools into one window."

The correct unification is:

- one shared project model
- one shared stack source
- one SD-browser primary surface
- one reusable event-analysis secondary surface
