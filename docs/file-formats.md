# File Formats

## Purpose
- **What this document covers**: This document details the internal structure of the `.sdproj` project format, the layout of exported analysis results, and the supported input image types.
- **Intended audience**: Developers extending the platform, researchers needing to script against project data, and users troubleshooting data portability.

## `.sdproj` Project File

### Summary
- **What `.sdproj` stores**: A complete snapshot of a session, including input image references (stack metadata), event definitions (start/end frames, labels), and analysis artifacts (segmentation masks, point prompts, and region-of-interest settings).
- **What it does not store**: The raw source image data (unless specifically configured to embed small subsets). It maintains relative or absolute paths to the original image files.

### Versioning
- **Current schema version**: 2
- **Backward compatibility policy**: The application attempts to gracefully upgrade older project versions. Version 2 introduced a unified persistence owner field and structured analysis sidecars.
- **Migration behavior**: When an older project is opened, it is automatically migrated in-memory. Saving the project will update it to the latest schema version.

### Top-Level Structure
- **File/container format**: A standard ZIP container (deflated compression).
- **Required top-level files**:
  - `manifest.json`: Core metadata and schema versioning.
  - `stack.json`: Dimensions and path information for the source image sequence.
  - `events.json`: List of user-defined temporal events.
  - `analysis_sidecar.json`: Index of analysis artifacts associated with each event.

### Field Reference (`manifest.json`)
| Field | Type | Required | Description | Example |
|---|---|---|---|---|
| `schema_version` | integer | Yes | Version of the file format. | `2` |
| `active_event_id` | string | No | The ID of the event currently selected. | `"event_001"` |
| `metadata` | object | No | Global project settings (e.g., default metrics). | `{}` |
| `persistence` | object | Yes | Internal owner tracking. | `{"owner": "host_sdproj"}` |

### Event Record Structure (`events.json`)
- **Required fields**: `event_id`, `global_start_idx`, `global_end_idx`.
- **Optional fields**: `label`, `flags` (dictionary for custom metadata).
- **Validation rules**: `global_end_idx` must be greater than or equal to `global_start_idx`.

### Analysis Artifact Structure
Artifacts are stored within the zip in subdirectories named by event (e.g., `events/event_1/`).
- **Masks**: Stored as `.npz` (NumPy compressed) files containing binary arrays.
- **Points/prompts**: Stored as `prompts.json`, containing coordinate pairs and point labels (positive/negative).
- **Metrics settings**: Stored within the sidecar JSON, referencing ROI masks (`roi_mask.npz`) and scale calibrations.

### Validation Rules
- **Required invariants**: The stack reference in `stack.json` must match the actual image files on disk for the project to load correctly.
- **Error behavior on invalid data**: If critical JSON files are missing or malformed, a `ProjectLoadError` is raised, and the project will fail to open to prevent data loss.

## Exported Artifacts

### Output Directory Layout
When exporting an event, the following tree is created:
```text
<output_dir>/
└── <event_label>/
    ├── masks/               # Binary segmentation masks (PNG)
    ├── metrics/             # Quantitative results
    │   ├── frame_metrics.csv
    │   ├── summary_metrics.csv
    │   ├── summary_metrics.json
    │   └── metrics_combined.xlsx
    └── plots/               # Visualization of speed and area
        ├── propagation_speed.png
        └── area_mm2.png
```

### Metrics Outputs
- **`frame_metrics.csv` columns**: `frame_idx`, `time_sec`, `area_px`, `area_mm2`, `speed_um_per_sec`, `relative_area_pct`.
- **`metrics_combined.xlsx`**: An Excel workbook containing both per-frame and summary data in separate sheets.
- **Units and formulas**:
  - Area: Calculated via contour integration.
  - Speed: Calculated as the average displacement of the mask boundary between consecutive frames.

### Masks and Image Exports
- **File formats**: Masks are exported as 8-bit single-channel PNGs where `255` represents the segmented object.
- **Coordinate conventions**: (0,0) is the top-left corner of the image.

## Input Image Support
- **Supported formats**: `.tif`, `.tiff`, `.png`, `.jpg`, `.jpeg`, `.bmp`.
- **Multi-page TIFF support**: Fully supported; pages are treated as sequential frames in the stack.
- **RGB Support**: Multi-channel images are automatically detected. Users can choose to average channels (Luma) or use the first channel.
- **Folder requirements**: Images in a folder are sorted "naturally" (e.g., `frame_9.png` comes before `frame_10.png`).

## Examples

### Minimal valid `.sdproj` manifest.json
```json
{
  "schema_version": 2,
  "active_event_id": "event_1",
  "metadata": {},
  "persistence": {
    "owner": "host_sdproj"
  }
}
```

### Example export directory
```text
my_experiment_results/
└── event_A/
    ├── masks/
    │   ├── Mask_frame_001.png
    │   └── Mask_frame_002.png
    ├── metrics/
    │   ├── frame_metrics.csv
    │   └── summary_metrics.json
    └── plots/
        └── area_mm2.png
```
