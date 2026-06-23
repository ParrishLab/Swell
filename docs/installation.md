# Installation & Onboarding

This page covers system requirements, installation steps for both packaged binaries and source setups, and first-time segmentation model configuration.

---

## System Requirements

* **Operating System**: macOS 13+ (Apple Silicon or Intel), Windows 10/11 (x64).
* **Python (Source Install)**: Python 3.12 or newer.
* **Hardware Acceleration**:
    * **CPU**: Always supported and serves as the guaranteed fallback.
    * **Apple Silicon (macOS)**: Uses Metal Performance Shaders (MPS) automatically when available.
    * **NVIDIA GPU (Windows/Linux source only)**: Can run on CUDA if PyTorch is installed with CUDA support. Packaged Windows binaries default to CPU execution.
* **Disk Space**: ~1.5 GB for dependencies and model checkpoints.

---

## Packaged Desktop Release (Recommended)

Packaged builds allow you to run Swell without setting up Python locally.

1. Download the latest release zip for your platform from the [GitHub Releases](https://github.com/ClayDunford/Swell/releases) page.
2. Extract the archive contents:
    * **macOS**: Extract `swell-macos-arm64.zip` (Apple Silicon) or `swell-macos-x86_64.zip` (Intel). Move `Swell.app` to your `/Applications` directory.
    * **Windows**: Extract `swell-windows-x64.zip` to a folder of your choice.
3. Launch the application:
    * **macOS**: Double-click `Swell.app`.
    * **Windows**: Double-click `Swell.exe`.

> [!WARNING]
> **macOS Gatekeeper Warning**
> Packaged macOS builds are unsigned and not notarized. Upon first launch, macOS will block execution. To bypass:
> 1. Right-click (or Control-click) `Swell.app` and choose **Open**.
> 2. In the warning dialog that appears, click **Open** again.
> 3. Alternatively, navigate to **System Settings → Privacy & Security**, scroll down, and select **Open Anyway** under the security section.

---

## Installing from Source

If you prefer to run or modify the code directly, set up a local Python environment.

### 1. Clone the Repository
```bash
git clone https://github.com/ClayDunford/Swell.git
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

> [!NOTE]
> The `sam-2` package is compiled from a specific commit. If compilation fails, ensure you have a working C compiler toolchain installed (`clang` or Xcode Command Line Tools on macOS, MSVC Build Tools on Windows).

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

On your very first launch (or when opening the Analysis Window without a resolved checkpoint), you will be prompted with the **Model Onboarding Dialog**:

```text
No local SAM2 model file is available.

Yes = Download approved default model file
No = Select a local model file
Cancel = Keep model-based tools disabled
```

### Option A: Automatic Download (Recommended)
Click **Yes**. Swell will automatically fetch the default model (`sam2.1_hiera_base_plus.pt`) from Hugging Face and verify its SHA-256 integrity hash (`1620c3a8...`).
* **Download Directory**:
    * macOS: `~/Library/Application Support/swell/models/`
    * Windows: `%APPDATA%\swell\models\`
* **Custom Models Directory**: You can override the download path by setting the `SWELL_MODELS_DIR` environment variable before starting the application.

### Option B: Local File Association
If you are working offline, click **No** and select a pre-downloaded `.pt` file on your filesystem. 

### Option C: Review-Only Mode
Click **Cancel** to keep the model disabled. You will still be able to open projects, view frames, draw manual masks, and export existing data, but automated propagation will be unavailable.

---

## Verifying the Installation

To run a non-interactive startup check that verifies all modules load correctly:

```bash
python -m swell.main --smoke-test
```

If the environment is fully working, it will print:
```text
SMOKE_TEST:PASS
```
If a dependency is missing or corrupt, it will print a traceback and exit with code `1`.
