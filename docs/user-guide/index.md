# User Guide

This guide walks you through the complete, end-to-end workflow of using Swell, from first launch through segmentation, saving, and exporting analysis results.

## Workflow Overview

The core Swell workflow consists of two main stages: event cataloging in the **Host Window** and pixel-level segmentation in the **Analysis Window**.

```mermaid
sequenceDiagram
    participant User
    participant Host as Host Window
    participant Ana as Analysis Window
    participant Disk as Storage

    User->>Host: 1. Create New Project (Select image folder)
    User->>Host: 2. Scrub frames & click "Mark Event"
    User->>Host: 3. Select event & click "Open Analysis"
    Host->>Ana: 4. Launch workspace with event payload
    User->>Ana: 5. Place points/brush/fill & run propagation
    User->>Ana: 6. Adjust metrics settings & save masks
    Ana->>Host: 7. Sync masks back to active session
    User->>Host: 8. Save Swell Project (.swell)
    User->>Host: 9. Export Selected / Export All results
```

## Tutorial Steps

<span id="1-first-launch-model-setup"></span>
1. [First Launch & Model Setup](1-first-launch.md)

<span id="2-creating-a-project-loading-image-stacks"></span>
2. [Creating a Project & Loading Image Stacks](2-load-images.md)

<span id="3-marking-events"></span>
3. [Marking Events](3-mark-events.md)

<span id="4-opening-the-analysis-workspace"></span>
4. [Opening the Analysis Workspace](4-open-analysis.md)

<span id="5-segmenting-events-interactive-tools"></span>
5. [Segmenting Events](5-segment-events.md)

<span id="6-running-mask-propagation"></span>
6. [Running Mask Propagation](6-propagate-masks.md)

<span id="7-reviewing-with-diagnostic-overlays"></span>
7. [Reviewing Diagnostic Overlays](7-review-overlays.md)

<span id="8-setting-event-metrics"></span>
8. [Setting Event Metrics](8-event-metrics.md)

<span id="9-saving-masks-project-portability"></span>
9. [Saving Masks & Project Portability](9-save-project.md)

<span id="10-exporting-results"></span>
10. [Exporting Results](10-export-results.md)
