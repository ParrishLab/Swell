# Installation

SDApp runs on macOS and Windows. Python 3.12 or newer is required.

## Packaged release (recommended for end users)

Download the latest release from the [Releases page](https://github.com/ClayDunford/Combined-tool-test/releases).

!!! warning "macOS Gatekeeper"
    Current macOS release builds are intentionally unsigned and not notarized. You may need to right-click the app and choose **Open** the first time, or grant permission in **System Settings → Privacy & Security**.

## From source

```bash
git clone https://github.com/ClayDunford/Combined-tool-test.git
cd Combined-tool-test
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
```

Launch:

```bash
python -m sdapp.main
```

Or on macOS:

```bash
./run_mac.command
```

## Segmentation model (optional)

The automated propagation feature uses SAM 2. It is an optional extra because `torch` is a large dependency.

```bash
pip install -e ".[model]"
```

!!! note
    The `sam-2` dependency is pinned to a specific commit. If installation fails, check that you have git and a working C compiler toolchain.

## Smoke test

To verify the install launches cleanly without opening a full window:

```bash
python -m sdapp.main --smoke-test
```

## Development install

For contributors:

```bash
pip install -e ".[dev,docs,model]"
```

This adds `pytest` and the documentation toolchain.
