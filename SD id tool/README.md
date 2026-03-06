# IOS SD Manual Event Marker

This app is a desktop Tkinter tool for manually identifying SD events in an image stack.

It is built around a simple workflow:

1. Load a folder of image frames.
2. Browse the full stack in the main viewer.
3. Open a popup around the current frame with `Mark SD`.
4. Use the popup to baseline-subtract, inspect, and mark the event start/end.
5. Save the marked event back to the main event list.
6. Export selected or all marked events.

The app is no longer centered on automated event detection. The main purpose is to let a user inspect image sequences directly and create a clean manual record of SD event boundaries.

## What the App Does

The main window is the global browser for the full image stack:

- large frame viewer for the loaded sequence
- slider and overlay bar for navigating the entire stack
- event table showing saved SD events
- actions for editing, deleting, and exporting events
- logs for load, processing, and export status

The popup window is the SD marking workspace:

- opens around the current frame with a local range
- shows a processed main viewer for baseline-subtracted inspection
- shows a mini raw-image viewer for reference
- lets the user set `start` and `end`
- supports local range changes, baseline controls, and temporary contrast adjustment
- writes the event back to the main table on confirm

## Processing Model

The popup viewer applies a local processing pipeline to help the user see SD structure more clearly. That processing is for display and marking; it does not rewrite the source images.

Current popup processing flow:

1. Read the selected stack range from disk.
2. Smooth frames with Gaussian filtering (`sigma=0.5`).
3. Build a baseline image from a median of baseline-window frames.
4. Subtract that baseline from the working range.
5. Normalize the processed range using percentile scaling (`p1` / `p99`).
6. Convert the display output to `uint8` for viewing.

Important baseline behavior:

- baseline defaults to the frames before the mark point
- baseline controls are editable in the popup
- if the SD start moves into the baseline region, baseline end is moved to just before the start
- recomputation is debounced to avoid recalculating on every keystroke

## Performance Design

The app has been refactored so popup responsiveness is the priority.

Key performance choices:

- popup processing runs in a background worker
- stale popup jobs are ignored if a newer request is submitted
- smoothed frames, baselines, normalization stats, and processed frames are cached
- stack reads use natural sorting and TIFF handle reuse
- runtime caches are trimmed periodically and on lifecycle events

This matters because the expensive operations are smoothing, baseline median creation, normalization, and repeated disk reads across large image sequences.

## Export Behavior

Exports are event-based.

For each saved event, the exporter writes:

- baseline frames preceding the event
- event frames spanning `start_idx` through `end_idx`
- one `event_summary.json`

At the output root, the exporter also writes:

- `events_manifest.csv`
- `events_manifest.json`
- optional trace outputs if a trace exists:
  - `trace_data.csv`
  - `trace_plot.png`

Export preserves original frame precision where possible. Display normalization in the GUI is separate from export.

## Code Structure

### Entry Point

- [main.py](/Users/claydunford/Development/IOS-Analysis-Code/Python/SD id tool/main.py)
  - starts the Tkinter app and creates `SDAnalyzerApp`

### Main GUI

- [sd_gui.py](/Users/claydunford/Development/IOS-Analysis-Code/Python/SD id tool/sd_gui.py)
  - main window layout
  - popup marking workflow
  - viewer navigation and overlays
  - event CRUD operations
  - popup baseline / contrast controls
  - background processing integration
  - cache trimming and UI status/logging

### Image Stack Loading

- [stack_reader.py](/Users/claydunford/Development/IOS-Analysis-Code/Python/SD id tool/stack_reader.py)
  - scans supported image files
  - applies natural filename sorting
  - loads TIFF pages and standard image files
  - normalizes non-grayscale inputs to grayscale
  - caches frames and manages TIFF handle reuse

### Popup Processing Engine

- [processing_engine.py](/Users/claydunford/Development/IOS-Analysis-Code/Python/SD id tool/processing_engine.py)
  - background popup computation
  - job cancellation / stale-result protection
  - smoothed-frame cache
  - baseline cache
  - normalization cache
  - processed-frame warmup near the current frame

### Data Models and Constants

- [config.py](/Users/claydunford/Development/IOS-Analysis-Code/Python/SD id tool/config.py)
  - app constants
  - frame metadata types
  - `EventCandidate`
  - trace/export dataclasses

### Shared UI Logic

- [ui_logic.py](/Users/claydunford/Development/IOS-Analysis-Code/Python/SD id tool/ui_logic.py)
  - popup range clamping
  - overlay normalization helpers
  - slider / marker-bar mapping helpers
  - baseline alignment helper logic

### Signal / Trace Utilities

- [signal_analysis.py](/Users/claydunford/Development/IOS-Analysis-Code/Python/SD id tool/signal_analysis.py)
  - computes a simple whole-stack trace
  - converts event objects to serializable dictionaries

### Export Pipeline

- [exporter.py](/Users/claydunford/Development/IOS-Analysis-Code/Python/SD id tool/exporter.py)
  - writes event exports
  - writes manifests
  - optionally writes trace outputs
  - uses bounded parallelism for frame export

### Tests

- [tests/test_stack_reader.py](/Users/claydunford/Development/IOS-Analysis-Code/Python/SD id tool/tests/test_stack_reader.py)
- [tests/test_exporter.py](/Users/claydunford/Development/IOS-Analysis-Code/Python/SD id tool/tests/test_exporter.py)
- [tests/test_popup_processing_cache.py](/Users/claydunford/Development/IOS-Analysis-Code/Python/SD id tool/tests/test_popup_processing_cache.py)
- [tests/test_popup_processing_jobs.py](/Users/claydunford/Development/IOS-Analysis-Code/Python/SD id tool/tests/test_popup_processing_jobs.py)
- [tests/test_popup_processing_equivalence.py](/Users/claydunford/Development/IOS-Analysis-Code/Python/SD id tool/tests/test_popup_processing_equivalence.py)
- [tests/test_popup_range_state.py](/Users/claydunford/Development/IOS-Analysis-Code/Python/SD id tool/tests/test_popup_range_state.py)
- [tests/test_popup_bounds_normalization.py](/Users/claydunford/Development/IOS-Analysis-Code/Python/SD id tool/tests/test_popup_bounds_normalization.py)
- [tests/test_timeline_mapping.py](/Users/claydunford/Development/IOS-Analysis-Code/Python/SD id tool/tests/test_timeline_mapping.py)
- [tests/test_signal_analysis.py](/Users/claydunford/Development/IOS-Analysis-Code/Python/SD id tool/tests/test_signal_analysis.py)

## Running the App

Install dependencies from [requirements.txt](/Users/claydunford/Development/IOS-Analysis-Code/Python/SD id tool/requirements.txt), then run:

```bash
python main.py
```

On macOS, [run_mac.command](/Users/claydunford/Development/IOS-Analysis-Code/Python/SD id tool/run_mac.command) can also be used as a launcher.

## Running Tests

```bash
python -m pytest -q
```

## Current Design Intent

The current structure is intentionally split into:

- a lightweight global browsing window
- a focused popup workspace for local SD marking
- a separate processing engine for expensive popup computation

That separation keeps the marking workflow clear and keeps the UI responsive while the popup processing pipeline updates.
