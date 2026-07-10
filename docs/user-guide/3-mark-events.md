# 3. Marking Events

Once the stack is loaded, you can browse frames using the slider at the bottom of the canvas or keyboard arrow keys.

1. Scrub to the first frame where the Spreading Depression (SD) wave appears.
2. Click **Mark Event** in the toolbar.
3. In the popup dialog, move through the preview with its frame slider or the **Prev** and **Next** buttons.
4. When the preview shows the first event frame, click **Set Start**. Move to the final event frame and click **Set End**. You can also refine the **Start** and **End** frame numbers directly.
5. Adjust the **Contrast** slider when needed to make the event boundary easier to judge.
6. Click **Confirm**.
7. The event is added to the **Event List** on the left, and a colored timeline band is rendered overlaying the frame scrubber at the bottom of the window.

## Mark Event Controls

* **Baseline Count**: The number of pre-event frames to retain as baseline context. This value is saved with the event and is used when Swell prepares frames for analysis.
* **Baseline End**: The final frame in the baseline used by the dialog preview. It defaults to the frame immediately before the event start and updates when the start frame changes.

Choose baseline frames that represent the pre-event signal. The default is appropriate when those frames are free of the event; otherwise, adjust the baseline controls before confirming the event.

## Auto-detect Events

Auto-detection is an alternate way to propose event ranges. It does not require the SAM-2 model checkpoint, and each proposed range should still be reviewed before it becomes an event.

1. With a recording loaded, click **Autodetect** in the Host Window sidebar.
2. In the workbench, optionally click **Draw ROI** to limit detection to a region, then click **Run Detection**.
3. Review the entries in **Detected Candidates**, including their **Start**, **End**, duration, and coherence values.
4. Select a candidate to inspect its frame and activity timeline. Refine its **Start** and **End** values as needed.
5. Click **Accept Event** to add a reviewed candidate to the project, or click **Delete Event** to remove a false positive. Use **Commit & Proceed** to add every remaining reviewed candidate and close the workbench.
6. Back in the Host Window, select an event and click **Edit Event** when you need to refine its bounds or saved baseline count.

The workbench controls change which candidates are proposed:

* **Sensitivity**, **Min. participation**, and **Coherence filter** adjust the detection criteria.
* **Signal polarity** defaults to brightening waves; choose negative or both when reviewing dark-going recordings.
* **Split compound events** can separate a broad candidate window into distinct events.

Changing these settings reruns detection in the background. Accepted events receive Swell's default baseline count; set a different saved baseline count later through **Edit Event** when needed.

## Editing or Deleting Events

* To modify an event's bounds, select the event in the table and click **Edit Event**.
* To remove an event, select it and click **Delete Event**.
* **Safety Lock**: Arrow-key scrubbing and deleting shortcuts are automatically suppressed while your cursor is inside any text-entry fields (like the frame range inputs), preventing accidental timeline jumping.
