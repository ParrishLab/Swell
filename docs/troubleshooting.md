# Troubleshooting

## Installation

### `pip install` fails on the `sam-2` dependency

The `model` extra installs SAM 2 from a pinned GitHub commit. This requires:

- `git` on your PATH
- A working C/C++ toolchain (Xcode Command Line Tools on macOS, Build Tools for Visual Studio on Windows)

If you do not need automated propagation, install without the `model` extra:

```bash
pip install -e .
```

### `torch` install is slow or fails

`torch` is large and platform-specific. See the [PyTorch install selector](https://pytorch.org/get-started/locally/) for the right command for your OS, Python version, and CUDA setup, then install the `model` extra afterward.

## Launching

### macOS: "SDApp cannot be opened because the developer cannot be verified"

Packaged macOS builds are currently unsigned. Right-click the app and choose **Open**, or allow it in **System Settings → Privacy & Security**.

### The app window doesn't appear / crashes immediately

Run the smoke test to see startup errors:

```bash
python -m sdapp.main --smoke-test
```

Attach the output to any bug report.

## Usage

<!-- TODO: document common analysis-window issues once more user feedback is in -->

### Propagation runs but produces empty masks

- Confirm at least one positive point is placed on the object.
- Check that the event frame range is not empty.
- Verify the `model` extra is installed and `torch` can import.

## Reporting bugs

File issues at [GitHub Issues](https://github.com/ClayDunford/Combined-tool-test/issues) with:

- Your OS and Python version
- How you installed SDApp (packaged build vs. source)
- Steps to reproduce
- The full error message or traceback
