# 9. Saving Masks & Project Portability

1. Click **Save Current Masks** at the bottom of the right dock to commit the active segmentations back to the project service.
2. Close the Analysis Window to return to the Host Window.
3. Save your project by selecting **File → Save Swell Project** or clicking **Save Swell Project**. This writes a compressed `.swell` file containing all events, prompts, regions, and masks.

## Opening a Project (Model Verification)

When reopening a `.swell` file, Swell compares the model information saved in the project metadata with your active local model weights:

* If the models mismatch, a dialog asks whether to:
    * **Switch**: Load the model used to author the project.
    * **Continue**: Keep your active model (may alter future propagation results).
    * **Cancel**: Open in read-only mode (no model-based tools enabled).
