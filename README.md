# Swell

Swell is a desktop tool for identifying events in image stacks and running
event-level segmentation analysis in a dedicated analysis workspace.

It is organized as a two-stage workflow:
- Host window: load a stack, mark events, manage project-level actions.
- Analysis window: open one event and run segmentation/mask workflows.

## What The App Does

Swell helps you:
- Import an image stack and inspect frames.
- Mark, edit, and manage event ranges.
- Open an event in an analysis workspace for segmentation.
- Run propagation and save masks back to the project.
- Export event outputs and metrics.
- Save and reopen work as `.swell` project files.

## Core Workflow

1. Start Swell.
2. Click `New Project` and choose an image folder.
3. Mark events in the host window (`Mark Event`, edit/delete, review table).
4. Select an event and click `Open Analysis...`.
5. In analysis:
   - Place points/brush edits.
   - Run propagation.
   - Adjust metrics settings (frames/sec, scale, ROI).
   - Save current masks.
6. Return to host to export selected/all events and save the Swell project.

## Main Functions

### Host Window (Project + Event Management)
- **New Project**: prompts for an image folder and loads a fresh stack.
- **Open/Save Swell Project**: read and write `.swell` files.
- **Event tools**:
  - Mark new events.
  - Edit or delete selected events.
  - View event list and timeline overlays.
- **Open Analysis...**: launches analysis for the active event.
- **Metrics Defaults...**: set global frames/sec, scale, and ROI defaults.
- **Export Selected / Export All**:
  - Export event images and baseline images.
  - Export binary masks.
  - Export metrics outputs.

### Analysis Window (Event Segmentation)
- **Interactive selection tools**: positive/negative points, brush, eraser.
- **Propagation**: run segmentation across a selected frame range.
- **Metrics Settings**: configure event-level frames/sec, scale, ROI.
- **Import External Masks**: map masks from files/folder into current event.
- **Save Current Masks**: persist masks into the active Swell project.

### Project Model
- Swell project files use the `.swell` format.
- A project stores event ranges plus associated analysis artifacts.
- On macOS/Windows packaged builds, `.swell` can be opened directly into Swell.

## Running The App

```bash
python -m swell.main
```

macOS helper:

```bash
./run_mac.command
```

Optional startup smoke check:

```bash
python -m swell.main --smoke-test
```

## Packaged macOS Warning

- Current macOS release builds are intentionally unsigned and not notarized.
- Gatekeeper warnings are expected on macOS packaged builds.
- Sparkle update metadata is still produced, but end users may need manual trust overrides to open or update the app.

## Repository Layout

- `swell/`: application package (`host`, `analysis`, `shared`).
- `tests/`: unit, host, analysis, integration, and migration tests.
- `docs/`: architecture and release planning docs.
- `seam_contract_fixtures/`: seam-contract validation fixtures.
- `archive/legacy-integration/`: historical integration/refactor notes.

## Development Notes

- `pyproject.toml` is the source of truth for dependencies and package metadata.
- Entry point is `swell.main` (`python -m swell.main`).
