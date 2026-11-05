# Installation & Onboarding

This page covers system requirements, installation steps for both packaged binaries and source setups, and first-time segmentation model configuration.

---

## System Requirements

* **Operating System**: macOS 13+ (Apple Silicon or Intel), Windows 10/11 (x64).
* **Python (Source Install)**: Python 3.12 or newer.
* **Hardware Acceleration**:
    * **CPU**: Can run SAM-2 when PyTorch, SAM-2, and a compatible checkpoint are installed.
    * **Apple Silicon (macOS)**: Uses Metal Performance Shaders (MPS) automatically when available.
    * **NVIDIA GPU (Windows/Linux source only)**: Can run on CUDA if PyTorch is installed with CUDA support. Packaged Windows binaries default to CPU execution.
* **Disk Space**: ~1.5 GB for dependencies and model checkpoints.

---

## Packaged Desktop Release (Recommended)

Packaged builds allow you to run Swell without setting up Python locally.

1. Download the latest release zip for your platform from the [GitHub Releases](https://github.com/ParrishLab/Swell/releases) page.
2. Extract the archive contents:
    * **macOS (Apple Silicon)**: Extract the archive ending in `-macos-arm64.zip`. Move `Swell.app` to your `/Applications` directory.
    * **Windows**: Extract the archive ending in `-windows-x64.zip` to a folder of your choice.
3. Launch the application:
    * **macOS**: Double-click `Swell.app`.
    * **Windows**: Double-click `Swell.exe`.

The current release does not include an Intel Mac package. On Intel, follow
[Installing from Source](#installing-from-source).

!!! warning "macOS Gatekeeper"
    The macOS package is unsigned and not notarized. If macOS blocks it,
    confirm that you downloaded it from the official Swell release, then
    follow [Apple's instructions for opening an app from an unidentified
    developer](https://support.apple.com/en-us/102445).

---

## Installing from Source

If you prefer to run or modify the code directly, set up a local Python environment.

### 1. Clone the Repository
```bash
git clone https://github.com/ParrishLab/Swell.git
cd Swell
```

### 2. Set Up Virtual Environment
On macOS/Linux:
```bash
python3 -m venv .venv
source .venv/bin/activate
```
On Windows (Command Prompt):
```cmd
python -m venv .venv
.venv\Scripts\activate.bat
```

### 3. Install Dependencies
Install the package in editable mode:
```bash
pip install -e .
```

To include the SAM-2 automated segmentation engine (which installs PyTorch):
```bash
pip install -e ".[model]"
```

!!! note "Building SAM-2 from source"
    The `sam-2` dependency is pinned to a specific source commit. If compilation fails, ensure you have a working C compiler toolchain installed (`clang` or Xcode Command Line Tools on macOS, MSVC Build Tools on Windows).

For developers wanting to run tests and build documentation:
```bash
pip install -e ".[dev,docs,model]"
```

### 4. Launch from Terminal
```bash
python -m swell.main
```

---

## First-Run Model Onboarding

Swell requires weights (checkpoints) for the SAM-2 model to propagate segmentations. To prevent bloated downloads, these weights are **not** bundled with the application.

If Swell cannot resolve a local checkpoint at startup, it shows the **Model Onboarding Dialog**:

```text
No local SAM2 model file is available.

Yes = Download approved default model file
No = Select a local model file
Cancel = Keep model-based tools disabled
```

### Option A: Automatic Download (Recommended)
Click **Yes** to download the default model, `sam2.1_hiera_base_plus.pt`, from the configured checkpoint catalog.
* **Download Directory**:
    * macOS: `~/Library/Application Support/Swell/models/`
    * Windows: `%APPDATA%\swell\models\`
* **Custom Models Directory**: You can override the download path by setting the `SWELL_MODELS_DIR` environment variable before starting the application.

### Option B: Local File Association
If you are working offline, click **No** and select a pre-downloaded `.pt` file on your filesystem.

### Option C: Review-Only Mode
Click **Cancel** to keep the model disabled. You can still open projects, view frames, and export existing data in the Host Window. Opening Analysis, including for manual mask editing, requires a configured checkpoint. To set one up later, choose **Model → Manage Models...**.

---

## Verifying the Installation

Run the startup smoke check to verify that key application modules import:

```bash
python -m swell.main --smoke-test
```

If the selected imports succeed, it prints:
```text
SMOKE_TEST:PASS
```
On failure it prints `SMOKE_TEST:FAIL:...` and exits with code `1`. To include the PyTorch and SAM-2 imports, run `python -m swell.main --smoke-test --smoke-model-runtime`.
