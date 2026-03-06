# IOS SD Segmenter (Portable App)

Current status: this app supports segmentation, propagation, metrics analysis, and full project persistence using `.sdproj` files with autosave/recovery.

## 1) Quick Setup

From repo root, go to `portable_app`.

### macOS
1. Run `bootstrap_mac.command` once.
2. Run `run_mac.command`.

### Windows
1. Run `bootstrap_win.bat` once.
2. Run `run_win.bat`.

Bootstrap creates `.venv` and installs dependencies.

## 2) Core Workflow

1. Set input via folder or files.
2. Set output folder.
3. Verify SAM2 model path and click `Load Model`.
4. Set baseline frame count.
5. Click `Import Images`.
6. Segment with points/brush/eraser and run propagation.
7. Optionally set scale + ROI and run metrics.
8. Save as a `.sdproj` project.

## 3) Project Save Format (`.sdproj`)

Projects are stored as ZIP-based `.sdproj` containers and include:
- project state metadata
- image manifest and fingerprints
- global ROI/scale state
- per-event committed masks (`masks.npz`)
- optional per-event draft masks (`masks_draft.npz`)
- prompts/clicks/paint data

Saving uses atomic temp-write + replace to reduce corruption risk.

## 4) Autosave + Recovery (Current Behavior)

- Autosave is triggered from dirty-state updates and debounced.
- Autosaves rotate in a 3-slot ring.
- Autosave filenames are tag-aware (derived from current input when available).
- Recovery is available from:
1. Startup prompt when a newer autosave exists.
2. `File -> Recover Autosave...`.
- Closing warns when:
1. Propagation is still running.
2. Session has not been saved as a `.sdproj`.

## 5) External Mask Import

`File -> Import External Masks...` supports importing masks from:
- folder selection
- multiple files

Import flow includes:
- automatic mapping guess
- alignment preview with offset adjustment
- apply into active event as committed masks

## 6) Analysis + Export

### Analysis
1. `Set Scale`
2. `Draw ROI`
3. `Run Metrics`

Metrics outputs:
- `output/metrics_analysis/frame_metrics.csv`
- `output/metrics_analysis/summary_metrics.csv`
- `output/metrics_analysis/summary_metrics.json`

### Export
- `EXPORT` writes binary masks for selected range.
- Export range auto-follows generated mask bounds until manually edited.

## 7) Shortcuts

- Frame navigation: `Left` / `Right`
- Undo: `Cmd+Z` (macOS) or `Ctrl+Z` (Windows)
- Redo: `Cmd+Shift+Z` (macOS) or `Ctrl+Shift+Z` (Windows)
- Delete selected point: `Delete` / `Backspace`

## 8) Release Branch Auto-Update

`run_mac.command` and `run_win.bat` run startup update logic:
- only on `release` branch
- skipped when worktree is dirty
- app still launches on update failure
- dependency install runs when `requirements.txt` changed

Updater script: `tools/startup_update.py`

## 9) Developer Notes

Run tests:

```bash
./.venv/bin/python -m unittest discover -s tests -q
```

Current suite includes coverage for project schema/store/migration, autosave ring/recovery, close warnings, and external mask alignment/import behavior.
