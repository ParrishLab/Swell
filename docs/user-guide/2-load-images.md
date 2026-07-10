# 2. Creating a Project & Loading Image Stacks

All work in Swell begins by importing an image sequence.

1. Click **New Project** in the Host Window's left panel or choose **File → New Project** from the menu.
2. In the folder browser, select the directory containing your image sequence.

## Image Folder Requirements

To ensure the stack loads successfully, verify your images meet these criteria:

* **Supported Formats**: `.png`, `.jpg`, `.jpeg`, `.bmp`, `.tif`, `.tiff`.
* **Multi-Page TIFF**: You can import a single multi-page `.tiff` file or a directory containing a series of single-page TIFFs.
* **Natural Sorting**: File names are sorted using natural alphanumeric ordering. For example, `frame_9.png` correctly precedes `frame_10.png` (instead of sorting alphabetically where `frame_10.png` would precede `frame_2.png`).
* **RGB Channel Conversion**: If multi-channel RGB images are detected, the app converts them to single-channel grayscale (Luma averaged or first-channel selection) to run the analysis.
