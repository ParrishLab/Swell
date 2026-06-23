# Troubleshooting & Diagnostic Guide

Use this guide to identify and resolve common issues with installation, startup, project loading, segmentation models, and performance.

---

## 1. Structured Troubleshooting Reference

For each issue, map the **Symptom** to its **Root Cause**, apply the **Fix**, and follow the **Prevention** steps to avoid it in the future.

### Installation & Launch

| Symptom | Likely Root Cause | Fix | Prevention |
|---|---|---|---|
| **`ModuleNotFoundError: No module named 'torch'`** | PyTorch was not installed in the active virtual environment, or the installation is corrupt. | Run `pip install -e ".[model]"` inside your active virtual environment. | Always use `.[model]` or `.[dev,docs,model]` when installing from source if you need automated propagation. |
| **C compiler errors during `sam-2` install** | A working C++ compilation toolchain is missing on your system. | Install compiler tools: Xcode Command Line Tools on macOS (`xcode-select --install`) or MSVC Build Tools on Windows. | Verify compilation tools are installed before running `pip install`. |
| **`Failed to load model checkpoint`** | The SAM-2 weight files are missing or have mismatched SHA-256 hashes. | Open the Model Manager under **Model → Manage Models...** and click **Yes** to re-download. | Do not manually rename or tamper with files inside the managed models folder. |
| **macOS blocks application launch** | The packaged application is unsigned and not notarized (Gatekeeper security block). | Right-click `Swell.app`, choose **Open**, and click **Open Anyway**. | Refer to the [Installation](installation.md#packaged-desktop-release-recommended) guide for Gatekeeper overrides. |

### Project & State Sync

| Symptom | Likely Root Cause | Fix | Prevention |
|---|---|---|---|
| **`ProjectLoadError: Missing required stack reference`** | The original image folder referenced in `stack.json` was deleted, renamed, or moved. | Edit the project's `stack.json` file inside the zip container to correct the path, or re-import the images as a new project. | Maintain relative path layout if moving project files and image stacks across machines. |
| **`ValueError: Unsupported persistence owner`** | The `.swell` package was saved by an incompatible external program, or is corrupt. | Verify you are loading a file created by Swell. Restore the file from an autosave. | Avoid editing JSON files inside the ZIP archive manually without validating schemas. |
| **`STACK_MISMATCH` or `SESSION_MISMATCH` on save** | The active image stack was changed in the host window while an analysis session was still open. | Close the analysis window, reload the correct stack, and open analysis again. Syncs from mismatched stacks are rejected. | Avoid changing stack context in the Host Window while you have an active event segmentation workspace open. |

### Segmentation & Propagation

| Symptom | Likely Root Cause | Fix | Prevention |
|---|---|---|---|
| **Propagation outputs blank or incorrect masks** | Low model sensitivity settings or poor initial anchor frame prompt guidance. | Increase the sensitivity slider in the options bar. Add more positive/negative point prompts on problem frames. | Ensure first-frame masks are high quality before running propagation. |
| **`Inference Fallback: GPU Out of Memory`** | The active GPU does not have enough VRAM to handle the image dimensions or sequence length. | The app will automatically fall back to CPU mode. Close other GPU-intensive apps to free up VRAM. | Downsample large image dimensions or process shorter event ranges. |
| **Accelerator crashes or rendering artifacts** | Hardware accelerator (MPS/CUDA) driver conflict or hardware instability. | Force CPU execution by setting the `SWELL_DEVICE=cpu` environment variable in your terminal before launching. | Set environment variable defaults in your shell config if your machine has unstable GPU drivers. |
| **UI freezes during long propagation runs** | Large image stacks exceeding available system RAM cache limits. | Break massive image sequences into smaller folders and process as separate projects. | Monitor system RAM usage in Task Manager / Activity Monitor during propagation. |

---

## 2. Environment Diagnostics for Bug Reports

If you encounter an issue not covered in this guide, please file a bug report on the [GitHub Repository](https://github.com/ClayDunford/Swell/issues) and include the following diagnostic information:

1. **System Metadata**:
    * Operating System and version (e.g., macOS 14.5, Windows 11 x64).
    * Python version (e.g., Python 3.12.3) if running from source.
    * Installation method (packaged ZIP vs source checkout).
2. **Replication Steps**:
    * Detailed, step-by-step description of actions taken leading to the error.
3. **Application Logs**:
    * Copy the traceback or error dialog text.
    * Check console output or logs printed in the terminal.
4. **Stack Parameters**:
    * Image dimensions (width, height), number of frames, and file format (e.g., `.tif`, `.png`).
