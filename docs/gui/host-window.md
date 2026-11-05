# Host Window Reference

The **Host Window** is the primary hub of Swell, controlling project lifecycle, event cataloging, and data export.

The frame viewer is on the left; **Marked Events**, **Event Actions**, and
the log are on the right. Use the **File** menu to create, open, or save projects.

---

## 1. Menu Bar Commands

### File Menu
* **New Project**: Prompts for a directory containing an image sequence and initializes a new stack session.
* **Open Swell Project...**: Opens a file browser to load an existing `.swell` project package.
* **Save Swell Project**: Persists the active session state, marked events, and analysis masks back into the active `.swell` file.
* **Save Swell Project As...**: Saves the active project package under a new filename or directory.
* **Embed Source Images In Project File**: Includes the source images the next time you save.
* **Import DC Trace...**: Imports an external electrophysiological DC trace (e.g., from an iOS DC recording) and maps it to the timeline.
* **Remove DC Trace**: Discards the mapped DC trace from the active project.
* **Exit**: Terminates the application.

### Model Menu
* **Manage Models...**: Launches the Model Manager window to inspect, download, or select SAM-2 model checkpoints in your managed app-data directory.
* **Set Model Path...**: Browses for a local model weights file (`.pt`) to use as a manual override.
* **Load Model**: Manually forces the application to load the selected model weights file into VRAM or system RAM.
* **Update Project Model**: Updates the project's metadata to record the active model's path and SHA-256 hash.
* **Validate Assets**: Validates the local resources directory to ensure icons, catalog JSONs, and updater binaries are present.

---

## 2. Panels & UI Elements

### Right sidebar
* **Marked Events**: Lists the cataloged events.
* **Edit Selected / Delete Selected**: Edits the selected event bounds or removes selected events.
* **Open Analysis...**: Launches the child event segmentation workspace for the selected event.
* **Open Metrics...**: Configures global default frames per second, pixel-to-physical scale calibration, and Region of Interest (ROI) settings used by events without local overrides.
* **Export Buttons**:
    * **Export Selected**: Writes images, masks, and metrics for highlighted events.
    * **Export All**: Exports all cataloged events in the project.

### Main Stack Viewer
* **Canvas Viewport**: Displays the image frame at the active timeline scrubber position.
* **Timeline Scrubber**: A slider bar to scrub through the stack frames. Underneath the slider, horizontal colored bars represent the start and end ranges of marked events.

---

## 3. Important Dialogs

### Scale Calibration Dialog
Opened via **Open Metrics... → Set Scale**:
* Click and drag a line on the reference image over a known physical distance.
* Enter the physical length (e.g., in millimeters) to compute the pixels-per-unit ratio.
* **Axis-Lock**: Toggle this option to snap the drawn line to strict horizontal or vertical axes, ensuring clean calibration.

### ROI Defaults Dialog
Opened via **Open Metrics... → Draw ROI**:
* Draw one or more polygons to define the default region of interest (ROI). Recruited-area metrics use the mask clipped to this ROI.

### Auto-Detect Event Window
Opened via the **Autodetect** button below the frame viewer:
* Launches an automated temporal grid coherence pipeline that analyzes frame intensity changes.
* **Dual-Pane Timeline**: Renders a high-level overview timeline and a detail timeline showing grid subsection activity.
* **Opacity & Border Controls**: Adjust the visibility of subsection overlays.
* **Signal Polarity**: Defaults to positive-going intensity changes. Switch to negative-going or both polarities when reviewing dark-going recordings.
* **Incremental Rerun**: Parameter modifications (coherence gates, quiet Median Absolute Deviation tolerance sliders) trigger a debounced rerun of the algorithm in the background without locking the user interface.

### Export Dialog
Opened via **Export Selected** or **Export All**:
* Provides checkboxes to select which outputs to include (Event Extent Images, Baseline Images, Binary Masks, Propagation Speed, Area Recruited, Relative Area Recruited, and **Intensity**).
* **Prerequisite Validation Tooltips**: If any metric is unavailable for the selected events (e.g. scale or ROI is missing), its checkbox is disabled, and hovering over it displays a tooltip explaining the missing requirement (e.g. "Some selected events are missing pre-event baseline frames" for the **Intensity** metric).

---

## 4. Keyboard Shortcuts

Timeline scrubbing shortcuts are globally active, except when a text input box (such as the event label field) has focus:

| Key Binding | Action |
|---|---|
| `←` / `→` | Step 1 frame backward / forward |
| `Shift + ←` / `Shift + →` | Jump 10 frames backward / forward |
| `↑` / `↓` | Jump 10 frames forward / backward |

---

## 5. Known Limitations

* **Gatekeeper/SmartScreen**: Since packaged releases are unsigned, macOS Gatekeeper and Windows Defender SmartScreen warnings are expected. See the [Installation](../installation.md#packaged-desktop-release-recommended) page for trust overrides.
* **Single-Channel Grayscale**: RGB stacks are converted to grayscale on import. High-bit-depth images are normalized down to 8-bit depth for canvas rendering.
* **Hardware Accelerator Override**: By default, Swell auto-detects MPS or CUDA for running segmentations. If an accelerator misbehaves, you can force a CPU execution fallback by setting the `SWELL_DEVICE=cpu` environment variable in your terminal before launching the application.
* **Background Model Downloads**: The model manager download process requires a stable internet connection. If the download fails with a `403 Forbidden` error, check your network proxy settings or download the weights manually and use **Model → Set Model Path...** to associate.
