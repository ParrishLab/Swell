# Host window

The host window is the entry point for project and event management.

<!-- TODO: add screenshot of the host window with annotated regions -->

## Project actions

| Action | Description |
| --- | --- |
| **New Project** | Prompts for an image folder and loads a fresh stack. |
| **Open SD Project** | Opens a `.sdproj` file. |
| **Save SD Project** | Writes the current project to disk. |

## Event tools

| Action | Description |
| --- | --- |
| **Mark SD Event** | Define a new event range on the current stack. |
| **Edit Event** | Modify the frame range of the selected event. |
| **Delete Event** | Remove the selected event. |
| Event table | Lists all events with frame ranges and status. |
| Timeline overlay | Visual marker of all event ranges across the stack. |

## Analysis launch

- **Open Analysis...** — opens the analysis window for the currently selected event.

## Defaults and export

| Action | Description |
| --- | --- |
| **Metrics Defaults...** | Set global frames/sec, scale, and ROI defaults applied to new events. |
| **Export Selected** | Export artifacts for the selected event(s). |
| **Export All** | Export artifacts for every event in the project. |

Exports include event images, baseline images, binary masks, and metrics files. See [File formats](../file-formats.md) for the output layout.

<!-- TODO: document keyboard shortcuts -->
