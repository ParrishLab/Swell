# File formats

## `.sdproj` project files

An `.sdproj` file stores:

- Event ranges (start/end frame for each marked SD event)
- Per-event analysis artifacts (masks, points, metrics settings)
- Project-level defaults (frames/sec, scale, ROI)
- References to the source image folder

On macOS and Windows packaged builds, double-clicking an `.sdproj` file opens it directly in SDApp.

<!-- TODO: document internal schema (keys, versions) once stabilized for the v1 release -->

## Exported artifacts

Export actions write to the output directory you choose. The typical layout:

```
<export_root>/
  <event_id>/
    event_frames/        # raw frames for the event range
    baseline/            # baseline reference images
    masks/               # binary mask per frame (TIFF)
    metrics.csv          # per-frame metrics
    metrics.xlsx         # same data, Excel-formatted
```

<!-- TODO: document exact metrics columns and units -->

## Image input

SDApp accepts a folder of image frames. Supported formats:

- TIFF (single-page)
- PNG
- JPEG

<!-- TODO: confirm multi-page TIFF / HDF5 stack support -->
