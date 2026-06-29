# Swell

[![Python](https://img.shields.io/badge/python-%3E%3D3.12-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://github.com/ParrishLab/Swell/actions/workflows/release_phase2_pr.yml/badge.svg)](https://github.com/ParrishLab/Swell/actions/workflows/release_phase2_pr.yml)
[![Docs](https://readthedocs.org/projects/swell/badge/?version=latest)](https://swell.readthedocs.io/)
[![Release](https://img.shields.io/github/v/release/ParrishLab/Swell?sort=semver)](https://github.com/ParrishLab/Swell/releases)
[![License](https://img.shields.io/badge/license-not%20provided-lightgrey.svg)](#license)

Swell is a desktop application for identifying spreading depression events in
image stacks and performing event-level segmentation analysis in a dedicated
workspace.

The app is organized around a two-window workflow:

- **Host window**: load image stacks, mark event ranges, manage project state,
  and export results.
- **Analysis window**: open a single event, refine masks, run propagation, and
  save analysis artifacts back to the project.

## Features

- Import image sequences and multi-page image stacks.
- Mark, edit, review, and delete event frame ranges.
- Open event-scoped analysis workspaces for segmentation.
- Annotate masks with points, brush, eraser, and region tools.
- Run SAM-2-based propagation when model dependencies and checkpoints are
  available.
- Import external masks and save reviewed masks into `.swell` projects.
- Export event images, baseline images, masks, metrics, and spreadsheet reports.
- Save and reopen full project state using the `.swell` project format.

## Installation

### Packaged Releases

Packaged desktop builds are available from
[GitHub Releases](https://github.com/ParrishLab/Swell/releases).

See [docs/installation.md](docs/installation.md) for platform-specific setup,
first-run model onboarding, and troubleshooting notes.

### From Source

Swell requires Python 3.12 or newer.

```bash
git clone https://github.com/ParrishLab/Swell.git
cd Swell
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Install optional model support for SAM-2 propagation:

```bash
pip install -e ".[model]"
```

Install developer and documentation dependencies:

```bash
pip install -e ".[dev,docs,model]"
```

On Windows, create and activate the virtual environment with:

```cmd
python -m venv .venv
.venv\Scripts\activate.bat
```

## Usage

Launch Swell from an editable/source install:

```bash
python -m swell.main
```

Or use the installed console script:

```bash
swell
```

On macOS, the repository also includes a helper script:

```bash
./run_mac.command
```

Run a non-interactive startup smoke check:

```bash
python -m swell.main --smoke-test
```

## Basic Workflow

1. Create a new project and choose an image folder or stack.
2. Mark event ranges in the host window.
3. Open an event in the analysis window.
4. Add prompts or manual mask edits.
5. Run propagation when model support is configured.
6. Review metrics settings, including frame rate, scale, and ROI.
7. Save masks back to the project.
8. Export selected events or the full project.

For the full walkthrough, see [docs/user-guide.md](docs/user-guide.md).

## Documentation

- [Installation](docs/installation.md)
- [User Guide](docs/user-guide.md)
- [Host Window Reference](docs/gui/host-window.md)
- [Analysis Window Reference](docs/gui/analysis-window.md)
- [Developer Guide](docs/developer-guide.md)
- [File Formats](docs/file-formats.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Changelog](CHANGELOG.md)

## Development

Install development dependencies:

```bash
pip install -e ".[dev,docs,model]"
```

Run the test suite:

```bash
pytest
```

Run the startup smoke check:

```bash
python -m swell.main --smoke-test
```

Build the documentation locally:

```bash
mkdocs serve
```

## Project Layout

```text
swell/             Application package
  host/            Host-window project and event management
  analysis/        Event-level segmentation workspace
  shared/          Shared services, metadata, and UI helpers
  resources/       Application resources and model catalogs
tests/             Pytest suite
docs/              User, developer, and release documentation
packaging/         Packaging configuration
scripts/release/   Release and packaging automation
```

## Packaging Status

Current macOS release builds are unsigned and not notarized. Gatekeeper warnings
are expected when opening packaged macOS builds for the first time. See
[docs/installation.md](docs/installation.md) for the recommended launch steps.

## Contributing

Contributions are welcome. Before opening a large change, please open an issue
or discussion describing the problem and proposed direction.

For code changes:

- Keep host, analysis, and shared-module boundaries intact.
- Add or update tests for behavior changes.
- Run `pytest` before submitting a pull request.
- Update user-facing docs when workflows, file formats, or packaging behavior
  changes.

## License

No license file is currently included in this repository. Until a license is
added, reuse rights are not granted by default.
