# 7. Reviewing Diagnostic Overlays

* **Ghost Outlines**: Enable ghost outlines in the right dock's *View* section. This displays contours of masks from neighboring frames (cyan/blue for past, magenta/rose for future) so you can track propagation velocity and shape consistency.
* **Leverage Heatmap**: The bottom timeline strip acts as a leverage heatmap. Red sections indicate high frame-to-frame mask transition differences (potential errors). Click **Jump to Suggested Correction** to immediately seek to the frame with the worst trouble score.

## Ghost Outlines Demo

Scrub through this simulated propagated sequence, then enable **Ghost Outlines**. Neighboring-frame contours appear over the current mask — cyan for past frames, magenta for future frames — so you can follow how the mask shifts and grows from frame to frame. Adjust **Ghost range** to compare against more neighbors.

<div class="swell-propagation-demo" data-swell-propagation-demo="ghosts" data-svg-src="../../assets/demos/slice.svg" data-mask-base="../../assets/demos/region-mask-sequence/">
  <p class="swell-propagation-demo__fallback">Preparing the ghost-outlines demo...</p>
</div>

**Simulated overlay preview — no model inference.** Ghost outlines are drawn from the fixed demo masks, not from live SAM 2.1 propagation.

## Leverage Heatmap Demo

The timeline strip below grades each frame by how much its mask changes from the previous frame — red is high leverage ("edit here"), green is settled. The white tick marks the suggested correction. Click **Jump to Suggested Correction** to seek straight to the worst frame, or toggle the heatmap off to compare.

<div class="swell-propagation-demo" data-swell-propagation-demo="leverage" data-svg-src="../../assets/demos/slice.svg" data-mask-base="../../assets/demos/region-mask-sequence/">
  <p class="swell-propagation-demo__fallback">Preparing the leverage-heatmap demo...</p>
</div>

**Simulated diagnostic preview — no model inference.** The leverage scores are computed from the fixed demo masks; this exercise does not run SAM 2.1 or mask propagation.
