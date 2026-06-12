# Analysis Window Reference

The **Analysis Window** is a dedicated creative workspace designed for pixel-level event segmentation, automated mask propagation, and spatial metrics calibration.

---

## 1. Floating Tool Rail

The toolbar floats on the left side of the main canvas. You can select tools by clicking their icons or pressing their keyboard shortcuts:

| Icon | Tool | Shortcut | Description |
|---|---|---|---|
| 🔍 | **Select** | `V` | Selects, moves, or resizes bounding boxes and persistent region polygon vertices. |
| 🟢 | **Positive Point** | `+` / `=` | Places green positive prompts marking target object structures. |
| 🔴 | **Negative Point** | `-` | Places red negative prompts marking background or artifacts to exclude. |
| 📦 | **Box** | `K` | Draws a bounding box prompt enclosing the target object (limit one per frame). |
| 🖌️ | **Brush** | `B` | Manually paints mask pixels. |
| 🧽 | **Eraser** | `E` | Manually removes mask pixels. |
| 🪣 | **Fill** | `G` | Flood-fills closed regions or pixel intensities. |
| ⬡ | **Region** | `R` | Draws persistent include/exclude polygon regions across a frame range. |

---

## 2. Contextual Options Bar

Located below the status bar, the options bar dynamically displays parameters based on the active tool:

* **Sensitivity Slider** (Point & Box modes): Controls model prompt sensitivity during inference.
* **Brush Size Slider** (Brush & Eraser modes): Sets the brush radius in pixels (1–50 px, defaults to 10 px). Can also be adjusted using **Shift + Mouse Wheel**.
* **Fill Mode Controls** (Fill mode):
    * **Add/Remove toggle**: Set whether click flood-fills or flood-erases.
    * **Tolerance Slider**: Set the intensity boundary threshold for flood-filling.
    * **Fill Holes button**: Fills all enclosed negative areas (holes) within the active mask.
* **Region Options** (Region mode):
    * **Include/Exclude mode toggle**: Include or exclude pixels.
    * **Frame Range inputs**: Define the start and end frame bounds where the region is active.
    * **Close Polygon / Cancel / Commit Region**: Vertex editing operations.

---

## 3. Right Inspector Dock

The inspector on the right is divided into collapsible sections to manage secondary settings and workflows:

### A. Reference Window
* Displays a baseline frame or reference channel.
* **Pop-Out Canvas**: Opens a synced, secondary reference window that can be dragged to another monitor.

### B. Propagation settings
* **Run Propagation**: Runs bidirectional mask propagation across the event's frame range.
* **Propagation Direction**: Choose to propagate forward, backward, or bidirectionally from your anchor frames.

### C. Event Metrics {: #metrics-settings}
Configure parameters that override project-level defaults:
* **Frames Per Second (FPS)**: Time calibration.
* **Physical Scale**: Custom calibration. Click the ruler icon to calibrate against a reference line.
* **ROI Selector**: Enables editing or drawing an event-specific Region of Interest.

### D. View settings (Overlays)
* **Ghost Outlines Toggle**: Superimposes mask outlines from neighboring frames.
* **Ghost Frame Range Slider**: Configure the sliding window range ($\pm N$ frames) for showing ghosts.
* **Leverage Visibility Toggle**: Shows or hides the timeline leverage heatmap and correction indicators.
* **Jump to Suggested Correction**: Seeks the playhead to the worst-scoring troubled frame.

### E. Regions List
* Displays committed persistent regions.
* Toggle individual region visibility or enable/disable them.
* Actions to duplicate or delete selected regions.

### F. Save Actions (Bottom Dock)
* **Save Current Masks**: Commits all drafted and propagated masks into the active `.sdproj` session.

---

## 4. Timeline Strip & Visual Indicators

The timeline at the bottom of the canvas combines a frame scrubber with three distinct indicator layers:

1. **Scrubber Playhead**: Click or drag to change the active frame.
2. **Model Loading & Propagation Progress**: Uses the blue accent color (`#1b75bc`) to indicate background model actions. It updates smoothly at 33 ms intervals for indeterminate loading states.
3. **Heatmap & Markers**:
    * **Leverage Heatmap**: Shows the intensity of temporal trouble scores (red is troubled, green is stable).
    * **Timeline Markers**: Green markers show positive prompt anchors; red markers show negative prompts; purple dots indicate committed persistent regions.

---

## 5. Keyboard Shortcuts & Gestures

### Tool Selection
* `V`: Select Tool
* `+` / `=`: Positive Point Tool
* `-`: Negative Point Tool
* `K`: Box Tool
* `B`: Brush Tool
* `E`: Eraser Tool
* `G`: Fill Tool
* `R`: Region Tool
* `P` (Held or Toggled): Peek Mask Overlay

### Viewport Control
* `Ctrl + +` / `Cmd + +`: Zoom In
* `Ctrl + -` / `Cmd + -`: Zoom Out
* `0`: Reset Zoom (Fit to Screen)
* `Space + Drag`: Pan Viewport

### Editing Actions
* `Ctrl + Z` / `Cmd + Z`: Undo Action
* `Ctrl + Shift + Z` / `Cmd + Shift + Z`: Redo Action
* `Delete` / `Backspace`: Delete Selected Point Prompt or Bounding Box

---

## 6. Known Limitations

* **SAM2 CPU Fallback**: If PyTorch or CUDA/MPS libraries are missing, or if you run out of VRAM, the app falls back to a deterministic CPU predictor. While functional, propagation speed will be significantly slower. You can force a specific device (e.g. `cpu`, `mps`, or `cuda`) using the `SDAPP_DEVICE` environment variable.
* **Native C Extensions Warning**: A warning log about missing native `_C` extension libraries may appear on start. This is normal in environments without fully compiled C++ bindings and does not block segmentation.
* **Timeline Redraw Optimization**: The timeline is cached to avoid rendering lag. Under heavy editing, manually scrubbing the timeline will refresh all visual overlays.
