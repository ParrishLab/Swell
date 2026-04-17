# Analysis window

The analysis window is where a single event is segmented and its masks are produced.

<!-- TODO: add screenshot of the analysis window with annotated regions -->

## Selection tools

| Tool | Description |
| --- | --- |
| **Positive point** | Mark a pixel that belongs to the object. |
| **Negative point** | Mark a pixel that does **not** belong to the object. |
| **Brush** | Paint mask regions directly. |
| **Eraser** | Remove mask regions. |

## Propagation

- **Run Propagation** — propagate the current mask across the event's frame range using the segmentation model.
- Adjust points or brush strokes and re-run as needed; the model refines from the new inputs.

## Metrics settings

Open **Metrics Settings** to configure, for the active event:

- Frames per second
- Physical scale (pixels → units)
- ROI (region of interest)

These override the project-level defaults set in the host window.

## Mask I/O

| Action | Description |
| --- | --- |
| **Import External Masks** | Map masks from a file or folder into the current event. |
| **Save Current Masks** | Persist the current mask set into the active `.sdproj` project. |

<!-- TODO: document keyboard shortcuts and brush-size controls -->
