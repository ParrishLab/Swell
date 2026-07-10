# 10. Exporting Results

In the Host Window:

1. Select one or more events from the table.
2. Click **Export Selected** or **Export All** to generate outputs on disk.
3. Depending on the options you select, each event's export folder can contain:
    * `baseline`: Event-preceding baseline images.
    * `event_extent`: Raw event-frame images.
    * `analysis_images`: Grayscale-normalized or processed analysis frames.
    * `analysis_mask_overlays`: Masks overlaid on processed analysis frames.
    * `binary_masks`: Single-channel 8-bit binary TIFF masks, where `255` is wavefront and `0` is background.
    * `binary_masks_roi_cropped`: Optional ROI-constrained binary masks cropped to the ROI bounding box.
    * `mask_overlays`: Masks overlaid on raw input frames.
    * `contour_map`: Contour outline visualizations.
    * `metrics`: Frame-by-frame and summary spreadsheets, including:
        * `propagation_speed.csv`: Wavefront speed ($\mu m/sec$).
        * `area_recruited.csv`: Mask area recruitment ($mm^2$).
        * `intensity.csv`: Mean ROI pixel intensity and relative intensity change ($\Delta I / I_0$) over time.
        * `metrics_combined.xlsx`: A consolidated Excel workbook with summary, frame metrics, and intensity sheets when combined spreadsheet export is selected.
    * `plots`: Diagnostic charts showing propagation speed, area over time, and relative intensity changes (`intensity_delta_i_over_baseline_i.png`).
    * `event_summary.json` and `event_summary.md`: Machine-readable and human-readable event summaries.

For the complete export tree, see [Export Directory Layout](../file-formats.md#3-export-directory-layout).

> [!IMPORTANT]
> **Intensity Metric Prerequisites**
> The **Intensity** metric tracks mean pixel intensity over time within a Region of Interest (ROI). It is only available for export if the following conditions are met:
> 1. A valid Region of Interest (ROI) is defined.
> 2. Event-level frames per second (FPS) is configured.
> 3. The event has preceding baseline frames (meaning the event start frame is greater than 1, and the global baseline pre-frame count is greater than 0) so a baseline intensity ($I_0$) can be computed.
