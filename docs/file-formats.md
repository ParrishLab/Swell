# Data & File Format Reference

This reference documents the internal structure of the `.swell` project package, the directory layout of exported results, the metrics output variables, and the supported input image types.

---

## 1. `.swell` Project File Structure

An `.swell` file is the primary save container for Swell. It is a standard **compressed ZIP file** containing structured JSON metadata files and binary mask data.

### Top-Level Files in the ZIP

```text
my_project.swell (ZIP)
├── manifest.json            # Core project settings and schema versions
├── stack.json               # Path and dimension info for source stack
├── events.json              # List of cataloged event bounds and labels
├── analysis_sidecar.json    # Manifest index mapping events to analysis files
├── images_embedded.json     # (Optional) Index of embedded source frames
├── images/                  # (Optional) Embedded source frame files
│   ├── 000090.tiff          # Original frame files, stored verbatim
│   └── ...
└── events/                  # Event-specific directories
    ├── event_001/           # Deterministic sanitized directory name
    │   ├── prompts.json     # Point, box, paint, and persistent region data
    │   ├── masks.npz        # Compressed NumPy 3D array of committed masks
    │   └── masks_draft.npz  # (Optional) Working draft masks
    └── event_002/
        └── ...
```

---

## 2. Schema Schematics & Field Reference

Swell uses versioned schemas to maintain compatibility across releases. 

### A. Container Manifest (`manifest.json`)
* **Metadata Schema Version**: `3` (defined as `HOST_PROJECT_SCHEMA_VERSION = 3`).
* **Field Reference**:
    * `schema_version` (int): Active container schema version. Current writers emit `3`; `2` is still accepted on load (schema 3 is additive). Version `3` adds the optional embedded-source-images layer described in section E.
    * `active_event_id` (str or null): ID of the event highlighted during the last save.
    * `metadata` (object): Global configuration parameters, including:
        * `global_metrics_defaults` (object): Default scale calibrations and ROI.
        * `dc_trace_attachment` (object or null): Mapped DC electrophysiology trace path references.
        * `embed_source_images` (bool, optional): When `true`, the save writes the source frames into the container (section E). Persists with the project so re-saves keep embedding.
    * `persistence` (object): Ownership details. Contains:
        * `owner` (str): Current writers emit `"swell_project"`; legacy `"host_sdproj"` is still accepted on load.

### B. Image Stack Reference (`stack.json`)
Describes the original image directory:
* `input_dir` (str): Absolute or relative filesystem path to the frame folder.
* `frame_count` (int): Total number of frames in the stack.
* `frame_height` (int): Height of stack frames in pixels.
* `frame_width` (int): Width of stack frames in pixels.
* `dtype` (str): Pixel data type (typically `"uint8"`).
* `frame_names_digest` (str or null): Optional SHA-256 identity of the ordered decoded frame names.
* `source_fingerprint` (str or null): Optional SHA-256 identity derived from source-file boundaries and sampled decoded frame content. Used to reject a different recording that happens to share dimensions and dtype.

> **Note:** `stack.json` always records the source folder by reference. Embedded frames (section E) are an *additional* resilience copy, not a replacement. On load, the on-disk `input_dir` is preferred only when its stack identity matches; otherwise Swell tries the embedded copy and then asks for a matching replacement folder.

### C. Event List Catalog (`events.json`)
Stores event catalog bounds:
* `event_id` (str): Logical UUID/string for the event.
* `label` (str): User-assigned event label.
* `global_start_idx` (int): Absolute inclusive start frame index (0-indexed).
* `global_end_idx` (int): Absolute inclusive end frame index (0-indexed).
* `flags` (object): Dictionary for custom plugin/analysis tags.

### D. Event Prompts & Regions (`events/<event_dir>/prompts.json`)
Stores all interactive labels and annotations for a single event.
* **Logical Schema Version**: `6` (defined as `SCHEMA_VERSION = 6` in `project_schema.py`). Supports additive migration from v1–v5.
* **Structure**:
    * `schema_version` (int): Must be `6`.
    * `points` (list of objects): Coordinate prompts.
        * `frame` (int): Event-relative frame index.
        * `x`, `y` (float): Image-space canvas coordinates.
        * `label` (int): `1` for positive prompt, `0` for negative prompt.
    * `boxes` (list of objects): Bounding boxes.
        * `frame` (int): Event-relative frame index.
        * `box` (list of float): Bounding rectangle `[ymin, xmin, ymax, xmax]`.
    * `paint_layers` (list of objects): Brush and eraser edits.
    * `persistent_regions` (list of objects): Include/exclude polygons.
        * `id` (str): Unique region ID.
        * `mode` (str): `"include"` or `"exclude"`.
        * `enabled` (bool): Active state toggle.
        * `visible` (bool): Canvas rendering toggle.
        * `start_frame`, `end_frame` (int): Frame ranges where the polygon applies.
        * `vertices` (list of lists): Vertex coordinate pairs `[[x1, y1], [x2, y2], ...]`.
    * `ground_truth_frames` (list of int): Optional list of frames marked as manual ground-truth baseline references.

### E. Embedded Source Images (`images_embedded.json` + `images/`) — *Optional, schema 3*
Present only when the project was saved with `metadata.embed_source_images = true`. Lets a `.swell` carry its own source frames so it remains usable after the original stack folder is moved or deleted.
* `images/` (directory): Original source frame files copied in **verbatim** (lossless — preserves `uint16`/`float` and multi-page TIFFs). Each unique source file is stored once, keyed by its filename.
* `images_embedded.json`: Index mapping each embedded frame name to its archive path.
    * `embedded` (object): `{ <frame_filename>: <arcname> }`, e.g. `{"000090.tiff": "images/000090.tiff"}`.

**Load behavior.** The on-disk `stack.json` `input_dir` is preferred when it exists and matches the recorded count, oriented dimensions, dtype, and any available fingerprints. If it is missing or mismatched, embedded frames are extracted to a temporary directory and used when they match; otherwise Swell asks for a matching replacement folder. Fingerprint fields are additive within schema 3, and older projects that do not contain them remain loadable.

---

## 3. Export Directory Layout

When exporting results in the Host Window, Swell creates a structured directory using the event's user-assigned label:

```text
my_export_output/
├── event_A/                     # Named after event label
│   ├── baseline/                # Event-preceding baseline PNG images
│   │   ├── 000089_baseline.png
│   │   └── ...
│   ├── event_extent/            # Raw event extent PNG images
│   │   ├── 000090_event.png
│   │   └── ...
│   ├── analysis_images/         # Grayscale-normalized/processed frames (PNG)
│   ├── analysis_mask_overlays/  # Masks overlaid on normalized frames (PNG)
│   ├── binary_masks/            # Single-channel 8-bit binary TIFF masks
│   │   ├── 000090_event_mask.tiff  # 255 = wavefront, 0 = background
│   │   └── ...
│   ├── binary_masks_roi_cropped/ # Optional ROI-constrained masks cropped to the ROI bounding box
│   │   ├── roi_crop_metadata.json # Full-frame shape and crop bounds
│   │   └── 000090_event_mask_roi_cropped.tiff
│   ├── mask_overlays/           # Masks overlaid on raw input frames (PNG)
│   ├── contour_map/             # Visual contour outlines superimposed on canvas (PNG)
│   ├── metrics/                 # Quantitative spreadsheets
│   │   ├── propagation_speed.csv
│   │   ├── propagation_speed.png
│   │   ├── area_recruited.csv
│   │   ├── area_recruited.png
│   │   ├── intensity.csv         # Mean ROI pixel intensity over time
│   │   ├── intensity_delta_i_over_baseline_i.png # Relative intensity changes plot
│   │   ├── track_propagation_speed.csv # Per-object propagation speed
│   │   ├── track_area_recruited.csv     # Per-object recruited area
│   │   ├── track_relative_area_recruited.csv
│   │   ├── lineage_weighted_propagation_speed.csv
│   │   ├── object_lineage_summary.json  # Tracking configuration and aggregate counts
│   │   ├── object_tracks.csv            # Optional per-frame object table
│   │   ├── object_lineage.csv           # Optional split/merge lineage table
│   │   ├── object_lineage_overview.png  # Optional overview montage
│   │   ├── object_lineage_frames/       # Optional per-frame overlays
│   │   ├── frame_metrics.csv
│   │   ├── summary_metrics.csv
│   │   ├── summary_metrics.json
│   │   └── metrics_combined.xlsx # Consolidated multi-sheet Excel file
│   ├── plots/                   # Diagnostic matplotlib charts
│   │   ├── propagation_speed.png
│   │   ├── area_mm2.png
│   │   └── intensity_delta_i_over_baseline_i.png # Relative intensity change graph
│   ├── event_summary.json       # Raw metrics parameters metadata
│   └── event_summary.md         # Readable event markdown report
└── trace_data.csv               # electrophysiological DC trace (if loaded)
```

---

## 4. Metrics & Calculations Reference

### Column Dictionary (`frame_metrics.csv`)
* `frame_idx` (int): 0-indexed absolute frame position in the source stack.
* `time_sec` (float): Time position, calculated as:
  $$time\_sec = \frac{frame\_idx}{FPS}$$
* `area_px` (int): Number of positive pixels in the final composed mask.
* `area_mm2` (float): Area of the segmented mask in square millimeters:
  $$area\_mm2 = area\_px \times \left(\frac{1.0}{scale\_px\_per\_mm}\right)^2$$
* `speed_um_per_sec` (float): Wavefront propagation speed in micrometers per second. Calculated as the average distance shift ($avg\_dist\_px$) of the primary mask boundary contour between consecutive frames:
  $$speed\_um\_per\_sec = \frac{avg\_dist\_px \times \left(\frac{1000.0}{scale\_px\_per\_mm}\right)}{sec\_per\_frame}$$
  Boundary displacements smaller than `0.015 mm` are filtered after converting that physical threshold to pixels with the dataset calibration. When no valid pixels-per-millimeter calibration is available, Swell retains the legacy `2 px` threshold.
* `relative_area_pct` (float): Composed mask area divided by total ROI area (or total frame area if no ROI is specified).

### Object-Lineage Thresholds

Object-lineage metrics use physical defaults that are converted to pixels for each calibrated dataset: minimum component area `0.00025 mm²`, maximum centroid distance `0.10 mm`, and maximum boundary distance `0.05 mm`. Tracks must persist for at least two frames. `object_lineage_summary.json`, `event_summary.json`, `event_summary.md`, and the combined workbook record the physical settings and their pixel equivalents so an export can be audited independently of image resolution.

### Column Dictionary & Formulas (`intensity.csv`)
* `frame_index` (int): 0-indexed absolute frame position in the source stack.
* `frame_display` (int): 1-indexed display frame position (`frame_index + 1`).
* `time_sec` (float): Event-relative time in seconds. Calculated relative to the start of the event ($start\_idx$):
  $$time\_sec = (frame\_index - start\_idx) \times sec\_per\_frame$$
* `phase` (str): `"baseline"` (for event-preceding frames) or `"event"` (for frames within the active event range).
* `intensity` (float): Mean pixel intensity value within the ROI mask area for the active frame.
* `baseline_intensity` ($I_0$) (float): Mean pixel intensity within the ROI mask area averaged across all event-preceding baseline frames:
  $$I_0 = \frac{1}{N_{baseline}} \sum_{t \in \text{baseline}} I(t)$$
* `delta_i_over_baseline_i` ($\Delta I / I_0$) (float): Relative change in mean pixel intensity compared to the baseline intensity:
  $$\Delta I / I_0 = \frac{I - I_0}{I_0}$$

---

## 5. Supported Input Image Formats

* **Image Formats**: `.tif`, `.tiff`, `.png`, `.jpg`, `.jpeg`, `.bmp`.
* **Multi-Page TIFF**: Multi-page tiff sequences are unpacked automatically into frame sequences.
* **Orientation & Axes**: EXIF/TIFF orientation is applied before dimensions are compared. TIFF `Y`, `X`, sample/channel, and frame axes are used when available to distinguish planar color from frame sequences.
* **RGB Conversion**: RGB channels are flattened to grayscale. The app default calculates luma averages ($Y = 0.299R + 0.587G + 0.114B$) or extracts the first channel (configurable).
* **Dimension Policy**: All decoded frames must have one common oriented size. A mismatch rejects the entire open operation and preserves the previously loaded stack.
* **Floating-Point Policy**: Non-finite pixels are ignored when calculating percentile bounds and replaced with a finite median (or zero when no finite pixels exist) before filtering and analysis.
* **Sorting Policy**: Naturally sorted by filename sequence to ensure frame coherence.
* **Event Path Directory Security**: On-disk event folder paths are automatically sanitized on save to prevent filesystem collisions and invalid character faults on Windows/macOS.
