# Quickstart

This walks through the core workflow end-to-end. It assumes you have a folder of image frames ready to analyze.

## 1. Start the app

```bash
python -m sdapp.main
```

The host window opens.

## 2. Create a project

Click **New Project** and choose your image folder. The stack loads and you can scrub through frames.

## 3. Mark SD events

- Click **Mark SD Event** to define a new event range.
- Use the event table to edit or delete existing events.
- Timeline overlays in the host window show all marked ranges.

## 4. Open analysis for an event

Select an event in the table and click **Open Analysis...**. The analysis window opens with that event's frames loaded.

## 5. Segment the event

In the analysis window:

1. Place positive/negative points on the object of interest, or use the brush tool.
2. Click **Run Propagation** to propagate the mask across the event's frame range.
3. Review the result. Adjust points or brush strokes and re-run as needed.
4. Open **Metrics Settings** to set frames/sec, scale, and ROI for this event.
5. Click **Save Current Masks** when satisfied.

## 6. Export

Return to the host window and use **Export Selected** or **Export All** to write:

- Event images and baselines
- Binary masks
- Metrics outputs (CSV/Excel)

## 7. Save the project

Use **Save SD Project** to persist everything to a `.sdproj` file. Reopening it restores all events and analysis artifacts.

---

Next: see the [GUI reference](gui/host-window.md) for every button and menu, or [File formats](file-formats.md) to understand the export structure.
