# 6. Running Mask Propagation

After placing point, box, or brush prompts on one or more anchor frames:

1. Click **Run Propagation** in the right dock panel.
2. The SAM-2 model propagates the mask from your anchor frames across all frames in the event range.
3. Propagation progress is displayed in real-time as a blue (`#1b75bc`) loading band on the timeline.
4. If you notice inaccuracies on other frames, pause or wait for propagation to complete, add correction prompts on those frames, and re-run propagation. The model will refine its predictions using the new anchor data.

## Propagation Demo

The mask starts on a single anchor frame (the purple marker on the timeline). Press **Run Propagation** to carry it across the range. This simulated run deliberately drifts into white matter on the later frames. Scrub to a drifted frame and click **Add manual correction** — this mimics placing manual point prompts: a green positive point on the cortical tissue the mask should cover and a red negative point in the white matter it should avoid. Re-run to see the downstream frames refine.

<div class="swell-propagation-demo" data-swell-propagation-demo="propagate" data-svg-src="../../assets/demos/slice.svg" data-mask-base="../../assets/demos/region-mask-sequence/">
  <p class="swell-propagation-demo__fallback">Preparing the propagation demo...</p>
</div>

**Simulated propagation preview — no model inference.** This demonstration approximates how an anchor mask propagates and how a correction anchor refines it. It does not run SAM 2.1.
