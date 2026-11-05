# 9. Saving Masks & Project Portability

1. Click **Save Current Masks** at the bottom of the Analysis dock to send your masks back to the Host Window.
2. Return to the Host Window and choose **File → Save Swell Project** to write the project to disk. The compressed `.swell` file stores the events, prompts, regions, and masks.

## Making a project portable

By default, the project references the source images in their original folder.
Keep that folder with the project if you plan to move it.

To create a self-contained copy, enable **File → Embed Source Images In
Project File** in the Host Window, then save the project. This includes the
original image files and can make the project substantially larger.

## Opening a Project (Model Verification)

When you open Analysis for a project with a recorded checkpoint, Swell
checks it against the active checkpoint. If they differ, you can:

* **Yes** to switch to the project checkpoint, locating the file if necessary.
* **No** to continue with the active checkpoint. Future segmentation may differ.
* **Cancel** to stay in the Host Window. You can review and export existing
  data there, but Analysis remains unavailable until model setup is complete.
