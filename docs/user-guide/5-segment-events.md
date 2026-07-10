# 5. Segmenting Events

The Analysis Window provides a specialized floating tool rail on the canvas and context-specific option bars below the status row.

## SAM 2.1 Prompt Tools

Positive points, negative points, and boxes are the tools that provide prompts to SAM 2.1. Select and Clear Frame help manage those prompts, but do not create model prompts themselves.

* **Select (`V`)**: Select, move, or delete a point. Drag a box or one of its handles to reposition or resize it.
* **Positive Point (`+` / `=`)**: Left-click on tissue that belongs in the target SD wave structure.
* **Negative Point (`-`)**: Left-click on unwanted tissue, noise, or artifacts to steer the model away from them.
* **Box (`K`)**: Click and drag to draw one bounding box around the target.
* **Clear Frame**: Remove every prompt and the current mask from the frame.

## Prompt Tools Demo

Try placing a positive point in the light-gray cortical tissue above the white matter, where the SD is located. The simulated result may include too much or too little tissue; add positive and negative points or draw a box to refine it. Selecting a tool updates the short explanation below the viewer.

<div class="swell-prompt-demo" data-swell-prompt-demo data-svg-src="../../assets/demos/slice.svg" data-icon-base="../../assets/analysis-toolbar/">
  <p class="swell-prompt-demo__fallback">Preparing the prompt-tools demo...</p>
</div>

**Simulated mask preview — no model inference.** This demonstration approximates how prompts refine a prediction. It does not run SAM 2.1.

## Manual Mask Editing & Persistent Regions

Brush, eraser, and fill edits directly change the mask. They do not send prompts to SAM 2.1.

* **Brush (`B`) & Eraser (`E`)**: Manually draw or erase masks. Adjust the radius in pixels (1–50 px) using the options bar slider or **Shift + Mouse Wheel**.
* **Fill + (`G`)**: Fill an empty region enclosed by mask or paint strokes, falling back to pixel-intensity flood fill on open background.
* **Fill - (`Shift+G`)**: Erase the contiguous mask component under the cursor.
* **Fill Holes**: Fill enclosed negative pockets inside the active mask.
* **Include Region (`R`) & Exclude Region (`Shift+R`)**: Draw polygon constraints that apply to one or more frames. Regions affect the final masks and exports; they do not seed mask propagation.
    * The **Viewing frame** slider changes the frame currently shown. The **Region frames (start-end)** fields set the one-based, inclusive range where that saved region applies. A new region starts on the current viewing frame by default.
    * Left-click to place visible vertices and connecting lines; place at least three vertices, then click **Close Shape** to finish the outline or **Discard** to abandon the draft. Double-click does not close a region.
    * Click **Add Region** to save it. Select a saved region from the **Regions** panel to adjust its frame range, toggle it on or off, duplicate or delete it, or use **Convert to Include/Exclude** to change its mode.
    * *Exclude regions* always take precedence where they overlap include regions or other mask edits.

## Manual Mask Editing Demo

This exercise starts with an intentionally incomplete mask of the light-gray cortical tissue above the white matter, where the SD is located. Paint to restore an edge, erase unwanted area, or use Fill + on a tissue region. These are direct mask edits, not model inference.

<div class="swell-mask-edit-demo" data-swell-mask-edit-demo data-svg-src="../../assets/demos/slice.svg" data-icon-base="../../assets/analysis-toolbar/">
  <p class="swell-mask-edit-demo__fallback">Preparing the manual mask-editing demo...</p>
</div>

**Manual mask preview — no model inference.** Brush, eraser, and fill changes apply directly to the displayed mask.

## Persistent Regions Demo

This exercise uses a short simulated SD mask sequence derived from exported binary masks. Each frame misses a small cortical area and has a small white-matter spill. Add an **Include Region** over the missed area and an **Exclude Region** over the spill, then move between frames to see the selected ranges take effect. This is a simulated final-mask preview; it does not run SAM 2.1 or mask propagation.

<div class="swell-region-demo" data-swell-region-demo data-svg-src="../../assets/demos/slice.svg" data-icon-base="../../assets/analysis-toolbar/" data-mask-base="../../assets/demos/region-mask-sequence/">
  <p class="swell-region-demo__fallback">Preparing the persistent-regions demo...</p>
</div>

**Simulated final-mask preview — no model inference or propagation.** The exercise supports one Include region and one Exclude region at a time. It focuses on drawing regions, setting frame ranges, enabling or disabling, and deletion; duplicating a region and **Convert to Include/Exclude**, described above, are desktop-application features left out of this focused demo.
