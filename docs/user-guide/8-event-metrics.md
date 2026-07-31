# 8. Setting Event Metrics

Before saving, configure quantitative parameters in the right dock's **Event Metrics** panel:

* **Frames Per Second**: Frame capture rate used to convert boundary movement per frame into movement per second.
* **Physical Scale**: Pixel-to-physical size calibration, stored as pixels per millimeter. Click the ruler icon to draw a two-point line across a known physical distance, or enter pixels/mm manually.
* **Region of Interest (ROI)**: Restrict measurements to one or more closed polygon regions. Multiple regions are combined into one ROI mask.

## Calibration and ROI Exercise

Drag the purple scale-line endpoints across a known distance, then enter that
distance in millimeters. Adjust FPS to see that it changes propagation speed but
not area. Drag the blue ROI vertices—or redraw the polygon—to see which example
mask pixels remain in the measurement.

<div class="swell-metrics-demo" data-swell-metrics-calibration-demo data-svg-src="../../assets/demos/slice.svg">
  <p class="swell-metrics-demo__fallback">Preparing the calibration exercise...</p>
</div>

**Simulated measurement preview — no project data is changed.** Swell computes
pixels/mm as the drawn line length divided by its known length. Physical area
therefore changes with the square of the scale, while propagation speed uses
both scale and FPS. The example boundary shift and mask geometry above are fixed
teaching data, not measurements from SAM 2.1.

## Choosing Global or Local Settings

Use **Set Global Scale** and **Save Global ROI** when events share the same
acquisition geometry. Use **Set Local Scale** or **Save Local ROI** for an event
that genuinely needs an override. A local override remains in effect until you
choose **Use Global Scale** or **Use Global ROI**.

Before exporting physical-unit metrics, confirm that FPS is positive, the scale
is expressed in pixels/mm, and the intended ROI is closed. Intensity metrics
also require preceding baseline frames; see [Exporting Results](10-export-results.md).
