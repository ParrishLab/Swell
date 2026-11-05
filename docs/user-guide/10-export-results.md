# 10. Exporting Results

1. In the Host Window, select events in **Marked Events**.
2. Choose **Export Selected** or **Export All**, then choose the outputs to
   include. Hover over a disabled metric to see which requirement is missing.
3. Choose the destination folder. Swell creates a subfolder for each event.

Depending on your selection, event folders can include baseline and event
images, processed analysis frames, binary TIFF masks, ROI-cropped masks,
overlays, contour maps, and event summaries. CSV tables, plots, optional
object-lineage outputs, and the combined Excel workbook are written to
`metrics/` within the event folder. Metric CSV and workbook filenames include
the event label, for example `propagation_speed_event_A.csv` and
`metrics_combined_event_A.xlsx`.

| Metric | Unit | Settings needed |
|---|---|---|
| Propagation speed | µm/s | Frame rate and physical scale |
| Recruited area | mm² | Frame rate, physical scale, and ROI |
| Relative recruited area | % of ROI | Frame rate and ROI |
| Intensity change | ΔI/I₀ | Frame rate, ROI, and preceding baseline frames |

!!! important "Intensity baseline"
    Set a positive baseline pre-frame count and mark an event that starts after
    the first frame. Swell averages ROI intensity over the available baseline
    frames. The baseline mean must be finite and nonzero to calculate ΔI/I₀.

See [the export directory layout](../file-formats.md#3-export-directory-layout)
for filenames and [the metrics reference](../file-formats.md#4-metrics-calculations-reference)
for formulas and the event-relative time convention.
