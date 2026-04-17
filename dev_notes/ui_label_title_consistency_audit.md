# UI Label/Title Consistency Audit

This document records user-facing label/title inconsistencies found across host + analysis UI code and suggests a single preferred wording for each case.

No UI strings were changed in this pass.

## Suggested Style Baseline

- Use **Title Case** for button labels, menu items, panel headers, and checkbox labels.
- Use `...` only for actions that open another dialog/workflow.
- Use stable domain terms consistently:
  - **SD Project** for `.sdproj` lifecycle actions.
  - **Open Analysis** (or **Analyze SD**) as one canonical term, not both.
  - **Frames/sec** (or **Frames per second (fps)**) as one canonical frame-rate label.

## Inconsistencies and Suggested Fixes

| ID | Current Label(s) | Location(s) | Inconsistency | Suggested Fix |
|---|---|---|---|---|
| 1 | `Analyze SD`, `Analyze SD Options - ...`, `Open Analysis` | `sdapp/host/sd_gui.py:239`, `sdapp/host/controllers/analysis_launch_controller.py:23`, `sdapp/host/controllers/analysis_launch_controller.py:119` | Same workflow uses two action names (`Analyze` vs `Open`). | Standardize on **Open Analysis** everywhere in this flow (button, dialog title, warning titles, window title). |
| 2 | `Generate Metrics` vs `Generate Metrics Defaults` vs `Adjust Metrics` | `sdapp/host/sd_gui.py:242`, `sdapp/host/sd_gui.py:716`, `sdapp/analysis/ui/layout.py:177`, `sdapp/analysis/ui/layout.py:181` | Metrics UI is named differently across windows. | Use **Metrics Defaults** (host/global) and **Metrics Settings** (analysis/event-level), or choose one canonical pair and apply consistently. |
| 3 | `Frames/Sec`, `Frames/Sec:` | `sdapp/host/sd_gui.py:725`, `sdapp/host/sd_gui.py:730`, `sdapp/analysis/ui/layout.py:192` | Abbreviation/casing style is non-standard and repeated inconsistently. | Replace with **Frames/sec** or **Frames per second (fps)** everywhere. |
| 4 | `Export Folder...` (menu) | `sdapp/shared/menu/factory.py:34` | Menu item sounds like “export now” but actually picks output directory. | Rename to **Set Output Folder...** (or **Choose Output Folder...**). |
| 5 | `Config` (menu heading) with model-only actions | `sdapp/shared/menu/factory.py:80` | Heading is generic while submenu is model-specific (`Set Model Path...`, `Load Model`, `Validate Assets`). | Rename menu heading to **Model** (or broaden submenu to match a real **Settings** menu). |
| 6 | `Output folder`, `Event images`, `Baseline images`, `Binary masks`, `Propagation speed`, `Area recruited`, `Relative area recruited` | `sdapp/host/controllers/host_window_controller.py:102`, `:116`, `:117`, `:118`, `:127`, `:129`, `:132` | Mixed sentence case while most UI controls use Title Case. | Convert to Title Case: **Output Folder**, **Event Images**, **Baseline Images**, **Binary Masks**, **Propagation Speed**, **Area Recruited**, **Relative Area Recruited**. |
| 7 | Dialog actions without ellipsis for dialog-opening buttons (`Analyze SD`, `Generate Metrics`) | `sdapp/host/sd_gui.py:239`, `sdapp/host/sd_gui.py:242` | Menu uses ellipsis semantics but equivalent dialog-opening buttons do not. | Rename to **Open Analysis...** and **Metrics Defaults...** if retaining ellipsis convention for secondary dialogs. |
| 8 | `Open SD Project` / `Save SD Project` vs `Open Project` / `Save Project` / `Save Project As...` | `sdapp/host/controllers/project_lifecycle_controller.py:78`, `:108`, `sdapp/shared/menu/factory.py:37-39` | Project lifecycle wording alternates between “Project” and “SD Project”. | Use **SD Project** consistently in menus/dialog titles: **Open SD Project...**, **Save SD Project**, **Save SD Project As...**. |
| 9 | `Save Project As...` (menu) vs `Save Project As` (dialog title) | `sdapp/shared/menu/factory.py:26`, `:39`, `sdapp/analysis/core/project_workflow.py:99` | Same action appears with different title text conventions. | Keep menu item **Save SD Project As...** and dialog title **Save SD Project As** (same wording, no ellipsis in title). |
| 10 | `No Data` vs `No Images` for same prerequisite | `sdapp/analysis/core/mask_import_workflow.py:19`, `sdapp/analysis/core/analysis_controller.py:284`, `:351` | Same “import required” condition uses different warning titles. | Standardize on **No Images** (or **No Image Data**) for all image-not-loaded warnings. |
| 11 | Warning titles `Event`, `Edit`, `Mark SD` in SD event editing popup flow | `sdapp/host/mark_popup_controller.py:20`, `:24`, `:42`, `:305`, `:350` | Same area uses multiple generic titles. | Use one title family, e.g. **SD Event** for selection/edit errors and **Mark SD Event** for popup-specific warnings. |
| 12 | `Run` (propagation button) | `sdapp/analysis/ui/layout.py:170` | Action label is too generic vs nearby explicit labels. | Rename to **Run Propagation**. |
| 13 | `Refresh Current Sequence` | `sdapp/host/mark_popup_controller.py:82` | Uses “Sequence” while rest of host UI uses “Frames/Range/Event”. | Rename to **Refresh Selected Range** (or **Refresh Current Range**) for terminology alignment. |
| 14 | Mask import source buttons `Folder` / `Files` | `sdapp/analysis/core/mask_import_dialog.py:47`, `:48` | Button labels are terse and inconsistent with surrounding verb-driven actions. | Rename to **From Folder...** and **From Files...**. |

## Recommended Rollout Order

1. Standardize high-visibility workflow verbs (`Open Analysis`, metrics naming, SD project naming).
2. Normalize Title Case and frame-rate terminology.
3. Clean up dialog/messagebox title consistency (`No Images`, `SD Event` family).
4. Apply ellipsis convention to dialog-opening actions.

