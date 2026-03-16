# SDApp

SDApp is a desktop tool for identifying SD events in image stacks and running
event-level segmentation analysis in a dedicated analysis workspace.

It is organized as a two-stage workflow:
- Host window: load a stack, mark SD events, manage project-level actions.
- Analysis window: open one event and run segmentation/mask workflows.

## What The App Does

SDApp helps you:
- Import an image stack and inspect frames.
- Mark, edit, and manage SD event ranges.
- Open an event in an analysis workspace for segmentation.
- Run propagation and save masks back to the project.
- Export event outputs and metrics.
- Save and reopen work as `.sdproj` project files.

## Core Workflow

1. Start SDApp.
2. Click `New Project` and choose an image folder.
3. Mark SD events in the host window (`Mark SD Event`, edit/delete, review table).
4. Select an event and click `Open Analysis...`.
5. In analysis:
   - Place points/brush edits.
   - Run propagation.
   - Adjust metrics settings (frames/sec, scale, ROI).
   - Save current masks.
6. Return to host to export selected/all events and save the SD project.

## Main Functions

### Host Window (Project + Event Management)
- **New Project**: prompts for an image folder and loads a fresh stack.
- **Open/Save SD Project**: read and write `.sdproj` files.
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
- **Save Current Masks**: persist masks into the active SD project.

### Project Model
- SDApp project files use the `.sdproj` format.
- A project stores event ranges plus associated analysis artifacts.
- On macOS/Windows packaged builds, `.sdproj` can be opened directly into SDApp.

## Running The App

```bash
python -m sdapp.main
```

macOS helper:

```bash
./run_mac.command
```

Optional startup smoke check:

```bash
python -m sdapp.main --smoke-test
```

## Repository Layout

- `sdapp/`: application package (`host`, `analysis`, `shared`).
- `tests/`: unit, host, analysis, integration, and migration tests.
- `docs/`: architecture and release planning docs.
- `seam_contract_fixtures/`: seam-contract validation fixtures.
- `archive/legacy-integration/`: historical integration/refactor notes.

## Development Notes

- `pyproject.toml` is the source of truth for dependencies and package metadata.
- Entry point is `sdapp.main` (`python -m sdapp.main`).
