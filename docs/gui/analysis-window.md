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

## Keyboard shortcuts

### Tool selection

| Key | Tool |
| --- | --- |
| `B` | Brush |
| `E` | Eraser |
| `V` | Select |
| `+` / `=` | Positive point |
| `-` / `_` | Negative point |

### Frame navigation

| Key | Action |
| --- | --- |
| `←` / `→` | Previous / next frame |
| `Delete` / `Backspace` | Delete selected point |

### Editing

| Key | Action |
| --- | --- |
| `Cmd+Z` / `Ctrl+Z` | Undo |
| `Cmd+Shift+Z` / `Ctrl+Shift+Z` | Redo |

### Zoom and pan

| Key | Action |
| --- | --- |
| `Cmd++` / `Ctrl++` | Zoom in |
| `Cmd+-` / `Ctrl+-` | Zoom out |
| `0` | Reset zoom (fit to frame) |
| `Space` + drag | Pan the viewport |

Use `Cmd` on macOS and `Ctrl` on Windows/Linux. Shortcuts are suppressed when a text field has focus.

## Brush size

The brush size slider in the tools panel sets the radius in pixels (range: 1–50 px, default: 10 px). You can also adjust it with **Shift+Mouse Wheel** while hovering over the canvas.
