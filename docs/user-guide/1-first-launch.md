# 1. First Launch & Model Setup

Upon launching Swell for the first time, you will be prompted to set up the SAM-2 model checkpoint. Follow the onboarding prompt detailed in [Installation](../installation.md#first-run-model-onboarding) to download or link model weights. Once complete, you will see the primary **Host Window**.

> [!TIP]
> **Forced Hardware Selection**: Swell automatically selects the best available device for running segmentation (Apple MPS → NVIDIA CUDA → CPU). If you need to force a specific hardware backend (e.g. to run on CPU if an accelerator misbehaves), set the `SWELL_DEVICE` environment variable to `cpu`, `mps`, or `cuda` before launching the application.
