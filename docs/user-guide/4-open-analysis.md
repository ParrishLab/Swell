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

In a fresh session, **Baseline Frames** starts at 30. **Smoothing**, **Baseline Subtraction**, and **Global Normalization** start on; **Horizontal Bar Denoise** and **Stabilize** start off. Swell prefers an event's previously saved values when they exist.

The five preprocessing switches can be changed independently. **Baseline Frames** always controls how far the prepared event scope reaches backward, so it can still affect the stabilization reference and global intensity statistics when **Baseline Subtraction** is off.

**Show Preview** computes a preview using the current baseline and preprocessing settings. If you change any setting after previewing, click **Show Preview** again to refresh it. Previewing is optional; clicking **Open Analysis** still opens the workspace using the selected settings.

Swell limits the effective baseline to frames that actually precede the event; it never borrows event frames to satisfy a larger requested count. Changing stabilization after masks, prompts, or ROI geometry exist requires confirmation because stabilization changes their coordinate system. If confirmed, incompatible geometry is cleared before Analysis opens.

## Preprocessing Preview Demo

This browser-only exercise uses a synthetic event starting at frame 13, so only 12 real pre-event frames exist. Keep the default request of 30 frames and click **Show Preview** to see how Swell caps the baseline without borrowing from the event. Toggle the preprocessing options to inspect their order and effect; as in the desktop dialog, changing a setting makes the current preview stale until you refresh it.

<div class="swell-open-analysis-demo" data-swell-open-analysis-demo>
  <p class="swell-open-analysis-demo__fallback">Preparing the preprocessing preview demo...</p>
</div>

**Simulated preprocessing preview — no project data is loaded and no Analysis Window is opened.** The generated image is designed to make banding, noise, baseline signal, intensity scaling, and motion visible. It illustrates the desktop pipeline but is not a scientific result or a pixel-for-pixel reproduction of Swell's OpenCV processing.
