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

An event's entry in `analysis_sidecar.json` points to its prompt file through
`prompts_ref`. The prompt payload itself has no `schema_version` field.

```json
{
  "event_id": "event_001",
  "frames": {
    "7": {
      "points": [{"x": 14.0, "y": 20.0, "label": 1}],
      "box": [10.0, 16.0, 28.0, 36.0]
    }
  },
  "ground_truth_frames": [7],
  "persistent_regions": [
    {
      "id": "region_1",
      "mode": "exclude",
      "enabled": true,
      "visible": true,
      "frame_start": 7,
      "frame_end": 12,
      "polygon": [[32.0, 20.0], [38.0, 20.0], [38.0, 30.0]]
    }
  ]
}
```

* **Frame indices:** The keys in `frames` are strings representing zero-based
  frame indices. Read `prompts_frame_origin` from the event's sidecar entry
  before mapping indices to the source stack. Current Analysis saves use
  `analysis_scope_local`: index 0 is the first frame of the analysis scope,
  which can include baseline frames before the event.
* **Point and box prompts:** Points use image-space `x` and `y` coordinates.
  A point's `label` is 1 for positive and 0 for negative. A frame can contain
  one `box` in `[xmin, ymin, xmax, ymax]` order.
* **Paint edits:** Optional `paint_plus_rle` and `paint_minus_rle` fields in
  each frame store add and erase masks as `{"shape": [height, width], "runs": [[start, length], ...]}`.
  Each run uses a zero-based offset into the row-major flattened mask.
* **Ground truth:** `ground_truth_frames` lists frames locked as ground-truth
  masks.
* **Persistent regions:** Each region has an `id`, a `mode` of `include` or
  `exclude`, and separate `enabled` and `visible` flags. The inclusive
  `frame_start` and `frame_end` use the prompt payload's frame origin.
  `polygon` is a list of `[x, y]` vertices in image coordinates.

### E. Embedded Source Images (`images_embedded.json` + `images/`) — *Optional, schema 3*
Present only when the project was saved with `metadata.embed_source_images = true`. Lets a `.swell` carry its own source frames so it remains usable after the original stack folder is moved or deleted.
* `images/` (directory): Original source frame files copied in **verbatim** (lossless — preserves `uint16`/`float` and multi-page TIFFs). Each unique source file is stored once, keyed by its filename.
* `images_embedded.json`: Index mapping each embedded frame name to its archive path.
    * `embedded` (object): `{ <frame_filename>: <arcname> }`, e.g. `{"000090.tiff": "images/000090.tiff"}`.

**Load behavior.** The on-disk `stack.json` `input_dir` is preferred when it exists and matches the recorded count, oriented dimensions, dtype, and any available fingerprints. If it is missing or mismatched, embedded frames are extracted to a temporary directory and used when they match; otherwise Swell asks for a matching replacement folder. Fingerprint fields are additive within schema 3, and older projects that do not contain them remain loadable.

---

## 3. Export Directory Layout

The Host Window creates one folder per exported event, using the sanitized
event label (or the event ID if the label is empty). Outputs depend on your
export selections. This example uses the label `event_A`:

```text
my_export_output/
├── events_manifest.csv
├── trace_data.csv                           # When a DC trace is loaded
└── event_A/
    ├── baseline/                            # Pre-event source frames
    ├── event_extent/                        # Source frames within the event
    ├── analysis_images/                     # Processed analysis frames
    ├── analysis_mask_overlays/               # Masks over processed frames
    ├── binary_masks/                        # TIFF masks: 255 foreground, 0 background
    ├── binary_masks_roi_cropped/
    │   └── roi_crop_metadata.json            # Full-frame shape and crop bounds
    ├── mask_overlays/                       # Masks over source frames
    ├── contour_map/                         # Contour overview image
    ├── event_summary.json
    ├── event_summary.md
    └── metrics/
        ├── propagation_speed_event_A.csv
        ├── propagation_speed.png
        ├── area_recruited_event_A.csv
        ├── area_recruited.png
        ├── relative_area_recruited_event_A.csv
        ├── relative_area_recruited.png
        ├── intensity_event_A.csv
        ├── intensity_delta_i_over_baseline_i.png
        ├── metrics_combined_event_A.xlsx     # When combined export is enabled
        ├── metrics_summary.json
        └── metrics_summary.md
```

Optional object-lineage outputs also go in `metrics/`:

* `track_propagation_speed_<event>.csv`, `track_area_recruited_<event>.csv`,
  `track_relative_area_recruited_<event>.csv`, and
  `lineage_weighted_propagation_speed_<event>.csv`
* `object_lineage_summary.json` for tracking settings and aggregate counts
* `object_tracks_<event>.csv` and `object_lineage_<event>.csv` for optional
  per-frame object and split/merge tables
* `object_lineage_frames/` and `object_lineage_overview.png` for optional
  visualizations

---

## 4. Metrics & Calculations Reference

### Per-event metric CSVs

The speed, recruited area, and relative recruited area CSVs each contain
one value column plus these frame columns:

| Column | Meaning |
|---|---|
| `frame_index` | Zero-based frame index in the source stack. |
| `frame_display` | One-based frame number shown in the app: `frame_index + 1`. |
| `time_sec` | Seconds from the event start: `(frame_index − event_start_index) / FPS`. The first event frame is at zero. |

The values below describe the **event-level** metrics. Per-object tables
report separate tracked objects.

| Value column | Calculation | Requirements |
|---|---|---|
| `speed_um_per_sec` | `mean_outward_displacement_px × 1000 × FPS / scale_px_per_mm` | Frame rate and scale; uses the full mask if no ROI is set. |
| `area_mm2` | `contour_area_sq_px / scale_px_per_mm²` | Frame rate, scale, and a valid ROI. |
| `relative_area_pct` | `100 × contour_area_sq_px / ROI_pixel_count` | Frame rate and a valid ROI. No full-frame denominator is substituted. |

Swell clips the final mask to the ROI when one is available. It uses the
largest external contour in each frame and smooths it when there are enough
contour points. Recruited area is the area enclosed by that contour in square
pixels. It is not a count of foreground pixels: holes are not subtracted and
disconnected components outside the largest contour are not summed.

Speed averages the outward displacement of the current contour relative to
the previous contour, using only displacements greater than 0.015 mm after
conversion to pixels at the configured scale. When a value is unavailable,
the CSV cell is empty.

### Object-Lineage Thresholds

Object-lineage metrics use physical defaults that are converted to pixels for
each calibrated dataset: minimum component area 0.00025 mm², maximum centroid
distance 0.10 mm, and maximum boundary distance 0.05 mm. Tracks must persist
for at least two frames. The tracking summary records the physical settings
and their pixel equivalents.

### Intensity CSV

`intensity_<event>.csv` includes the same frame columns. Baseline frames have
negative `time_sec` values because time is relative to event onset.

| Additional column | Meaning |
|---|---|
| `phase` | `baseline` for selected pre-event frames or `event` for frames inside the event. |
| `intensity` | Mean source-image intensity within the ROI on that frame. |
| `baseline_intensity` | Mean of the ROI intensity values from the selected baseline frames. |
| `delta_i_over_baseline_i` | Fractional change: `(intensity − baseline_intensity) / baseline_intensity`. |

Intensity export requires a valid ROI, a positive frame rate, and at least one
pre-event baseline frame with a finite, nonzero mean baseline intensity.

---

## 5. Supported Input Image Formats

* **Image Formats**: `.tif`, `.tiff`, `.png`, `.jpg`, `.jpeg`, `.bmp`.
* **Multi-Page TIFF**: Multi-page tiff sequences are unpacked automatically into frame sequences.
* **Orientation & Axes**: EXIF/TIFF orientation is applied before dimensions are compared. TIFF `Y`, `X`, sample/channel, and frame axes are used when available to distinguish planar color from frame sequences.
* **RGB Conversion**: RGB channels are flattened to grayscale. The app default calculates weighted luma (`Y = 0.299R + 0.587G + 0.114B`) or extracts the first channel (configurable).
* **Dimension Policy**: All decoded frames must have one common oriented size. A mismatch rejects the entire open operation and preserves the previously loaded stack.
* **Floating-Point Policy**: Non-finite pixels are ignored when calculating percentile bounds and replaced with a finite median (or zero when no finite pixels exist) before filtering and analysis.
* **Sorting Policy**: Naturally sorted by filename sequence to ensure frame coherence.
* **Event Path Directory Security**: On-disk event folder paths are automatically sanitized on save to prevent filesystem collisions and invalid character faults on Windows/macOS.
