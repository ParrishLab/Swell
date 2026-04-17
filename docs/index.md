# SDApp

SDApp is a desktop tool for identifying SD events in image stacks and running event-level segmentation analysis in a dedicated analysis workspace.

It is organized as a two-stage workflow:

- **Host window** — load a stack, mark SD events, manage project-level actions.
- **Analysis window** — open one event and run segmentation/mask workflows.

## What it does

- Import an image stack and inspect frames.
- Mark, edit, and manage SD event ranges.
- Open an event in an analysis workspace for segmentation.
- Run propagation and save masks back to the project.
- Export event outputs and metrics.
- Save and reopen work as `.sdproj` project files.

## Where to start

- New users: [Installation](installation.md) → [Quickstart](quickstart.md).
- Looking up a specific button or menu: [GUI reference](gui/host-window.md).
- Reproducing manuscript results or citing the tool: [Citation](citation.md).

## Getting help

- Issues and bug reports: [GitHub Issues](https://github.com/ClayDunford/Combined-tool-test/issues).
- Common problems: [Troubleshooting](troubleshooting.md).
