#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
ASSET_DIR = ROOT / "sdapp" / "resources" / "assets"
SOURCE_DEFAULT = ASSET_DIR / "app_icon_source.png"
LAYER_DIR = ASSET_DIR / "app_icon_tahoe_layers"

BLUE = (18, 119, 189)
DARK = (26, 32, 40)


def _distance_sq(pixel: tuple[int, int, int], target: tuple[int, int, int]) -> int:
    return sum((int(pixel[idx]) - int(target[idx])) ** 2 for idx in range(3))


def _write_layer_sources(img: Image.Image) -> None:
    LAYER_DIR.mkdir(parents=True, exist_ok=True)
    rgba = img.convert("RGBA")
    width, height = rgba.size
    background = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    waves = Image.new("RGBA", rgba.size, (0, 0, 0, 0))

    src_pixels = rgba.load()
    bg_pixels = background.load()
    wave_pixels = waves.load()
    for y in range(height):
        for x in range(width):
            r, g, b, a = src_pixels[x, y]
            if a <= 0:
                continue
            bg_pixels[x, y] = (*DARK, a)
            pixel = (r, g, b)
            if _distance_sq(pixel, BLUE) <= _distance_sq(pixel, DARK):
                wave_pixels[x, y] = (r, g, b, a)

    background.save(LAYER_DIR / "background.png", format="PNG")
    waves.save(LAYER_DIR / "waves.png", format="PNG")
    composite = Image.alpha_composite(background, waves)
    composite.save(LAYER_DIR / "preview.png", format="PNG")
    _write_layer_readme()


def _write_layer_readme() -> None:
    (LAYER_DIR / "README.md").write_text(
        "\n".join(
            [
                "# Tahoe Icon Composer Layers",
                "",
                "These PNGs are exported from `../app_icon_source.png` for Apple Icon Composer.",
                "",
                "- `background.png`: opaque dark rounded-square base with source alpha.",
                "- `waves.png`: blue wave foreground layer with transparency.",
                "- `preview.png`: flattened preview of the two layers.",
                "",
                "To create a Tahoe-native icon, import `background.png` and `waves.png` as separate layers in Apple Icon Composer, tune the Liquid Glass appearance, and export the resulting `.icon` file.",
                "",
                "The traditional `app_icon.icns`, `app_icon.ico`, and `app_icon_runtime.png` remain generated for current PyInstaller packaging and older OS compatibility.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def generate(source: Path) -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    source = source.expanduser().resolve()
    if source != SOURCE_DEFAULT.resolve():
        shutil.copyfile(source, SOURCE_DEFAULT)
    img = Image.open(source).convert("RGBA")

    img.resize((512, 512), Image.Resampling.LANCZOS).save(ASSET_DIR / "app_icon_runtime.png", format="PNG")
    img.save(
        ASSET_DIR / "app_icon.ico",
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    img.save(
        ASSET_DIR / "app_icon.icns",
        format="ICNS",
        sizes=[(16, 16), (32, 32), (64, 64), (128, 128), (256, 256), (512, 512), (1024, 1024)],
    )
    _write_layer_sources(img)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate SDApp app icons and Tahoe Icon Composer layer sources.")
    parser.add_argument("source", nargs="?", default=str(SOURCE_DEFAULT), help="RGBA source PNG for the app icon.")
    args = parser.parse_args()
    source = Path(args.source)
    if not source.exists():
        raise FileNotFoundError(f"Missing app icon source: {source}")
    generate(source)
    print("Generated:")
    for path in [
        SOURCE_DEFAULT,
        ASSET_DIR / "app_icon_runtime.png",
        ASSET_DIR / "app_icon.ico",
        ASSET_DIR / "app_icon.icns",
        LAYER_DIR / "background.png",
        LAYER_DIR / "waves.png",
        LAYER_DIR / "preview.png",
    ]:
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
