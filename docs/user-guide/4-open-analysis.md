# 4. Opening the Analysis Workspace

To segment an event:

1. Select the event in the Host Window's **Event List**.
2. Click the **Open Analysis...** button.
3. Review the **Open Analysis Options** dialog.
4. Optionally click **Show Preview** to inspect the prepared frame with the current settings.
5. Click **Open Analysis** to launch the child workspace for the selected event.

## Open Analysis Options

The options dialog controls how Swell prepares the event frames before they are handed to the Analysis Window:

* **Baseline Frames**: Sets how many pre-event frames are used as preprocessing context.
* **Horizontal Bar Denoise**: Reduces horizontal banding artifacts before analysis.
* **Smoothing**: Applies light smoothing to reduce frame noise.
* **Baseline Subtraction**: Removes pre-event baseline signal from the event frames.
* **Global Normalization**: Normalizes the prepared frame intensity range.
* **Stabilize**: Applies stabilization before the frames open in the Analysis Window.

**Show Preview** computes a preview using the current baseline and preprocessing settings. If you change any setting after previewing, click **Show Preview** again to refresh it. Previewing is optional; clicking **Open Analysis** still opens the workspace using the selected settings.

Swell limits the effective baseline to frames that actually precede the event; it never borrows event frames to satisfy a larger requested count. Changing stabilization after masks, prompts, or ROI geometry exist requires confirmation because stabilization changes their coordinate system. If confirmed, incompatible geometry is cleared before Analysis opens.
