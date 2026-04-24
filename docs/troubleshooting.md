# Troubleshooting

## Purpose
- **Scope of troubleshooting**: This guide covers common issues related to installation, image loading, project persistence, and analysis errors.
- **Where to report bugs**: Please report issues on the project GitHub repository with a copy of your session logs.

## How To Use This Page
- For each issue: identify the **Symptom** -> verify the **Likely Root Cause** -> apply the **Fix** -> follow **Prevention** steps to avoid it in the future.

## Installation Issues

### Problem: `ModuleNotFoundError: No module named 'torch'`
- **Symptoms**: The application launches but the analysis window shows a "Model Not Loaded" error or crashes when starting propagation.
- **Likely root causes**: PyTorch was not installed in the active Python environment, or the installation is corrupted.
- **How to verify**: Run `python -c "import torch; print(torch.__version__)"` in your terminal.
- **Fix**: Reinstall PyTorch using the instructions in `installation.md`.
- **Prevention**: Use the provided `requirements.txt` or environment setup scripts to ensure all dependencies are met.

## Launch/Startup Issues

### Problem: `Failed to load model checkpoint`
- **Symptoms**: Error dialog on startup or when opening the analysis window.
- **Likely root causes**: Model weights (SAM-2 checkpoints) are missing from the `sdapp/resources/models` directory.
- **How to verify**: Check if the `.pt` files specified in `checkpoints_catalog.json` exist.
- **Fix**: Download the required checkpoints and place them in the correct resources folder.

## Project/Open/Save Issues

### Problem: `ProjectLoadError: Missing required stack reference`
- **Symptoms**: Project fails to open with a "malformed project" error.
- **Likely root causes**: The `.sdproj` file is corrupt or was saved with an incompatible version of the software.
- **How to verify**: Open the `.sdproj` file (it is a ZIP) and check if `stack.json` is present and valid.
- **Fix**: Re-import the source images and recreate the project, or manually repair the `stack.json` file.

## Analysis/Segmentation Issues

### Problem: `Propagation produces empty or incorrect masks`
- **Symptoms**: Propagation runs but no masks appear on subsequent frames.
- **Likely root causes**: Poor initial point prompts, low sensitivity settings, or the object moves too fast/changes appearance too drastically.
- **How to verify**: Check the "Sensitivity" slider in the analysis window; check if the first frame mask correctly covers the object.
- **Fix**: Add more positive/negative prompts to the anchor frame and re-run propagation. Increase the sensitivity slider.
- **Prevention**: Ensure anchor frames have high-quality masks before propagating.

### Problem: `Inference Fallback: GPU Out of Memory`
- **Symptoms**: A warning appears stating the app is switching to "CPU fallback."
- **Likely root causes**: The GPU does not have enough VRAM to handle the image dimensions or model size.
- **How to verify**: Check GPU memory usage using `nvidia-smi` or Activity Monitor (macOS).
- **Fix**: Close other GPU-intensive applications. If the error persists, the app will continue to run on the CPU (though slower).
- **Prevention**: Use smaller image resolutions or higher-tier GPU hardware.

## Export/Metrics Issues

### Problem: `Silent metric export failure`
- **Symptoms**: Export completes but CSV files contain NaNs or empty values.
- **Likely root causes**: The analysis produced invalid masks (e.g., zero area) or the ROI mask was not properly defined.
- **How to verify**: Open the exported masks in an image viewer to see if they are blank.
- **Fix**: Re-run the analysis for the affected event and ensure valid masks are generated before exporting.

## Performance/Memory Issues

### Problem: `Application becomes unresponsive during long propagation`
- **Symptoms**: UI freezes or the progress bar stops moving.
- **Likely root causes**: Large image stacks (thousands of frames) exceeding available system RAM.
- **How to verify**: Monitor system memory (RAM) usage during the operation.
- **Fix**: Break large stacks into smaller sub-directories or process fewer frames at a time.
- **Prevention**: Use the "Memory Management" settings (if available) to limit cache size.

## Environment Collection for Bug Reports
When reporting a bug, please include:
- **OS + version**: (e.g., macOS 14.4, Windows 11)
- **Python version**: (e.g., 3.12.2)
- **Install method**: (e.g., source checkout, packaged installer)
- **Repro steps**: Step-by-step instructions to reproduce the issue.
- **Full traceback/logs**: Copy the text from the terminal or the log window.
- **Sample project/input details**: Image dimensions, bit depth, and number of frames.

## Known Limitations
- **Current constraints**: Multi-channel images must be converted to grayscale for analysis.
- **Planned fixes**: Native multi-channel support and real-time metrics preview in the analysis window.
