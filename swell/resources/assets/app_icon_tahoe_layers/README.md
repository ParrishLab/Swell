# Tahoe Icon Composer Layers

These PNGs are exported from `../app_icon_source.png` for Apple Icon Composer.

- `background.png`: opaque dark rounded-square base with source alpha.
- `waves.png`: blue wave foreground layer with transparency.
- `preview.png`: flattened preview of the two layers.

To create a Tahoe-native icon, import `background.png` and `waves.png` as separate layers in Apple Icon Composer, tune the Liquid Glass appearance, and export the resulting `.icon` file.

The traditional `app_icon.icns`, `app_icon.ico`, and `app_icon_runtime.png` remain generated for current PyInstaller packaging and older OS compatibility.
