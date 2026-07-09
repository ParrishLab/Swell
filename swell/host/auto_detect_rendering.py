from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from swell.host.auto_detect_helpers import grid_bounds_for_layout

_GRID_FOREGROUND = (125, 175, 215)
_GRID_HALO = (0, 0, 0)
_ACTIVE_FILL = (77, 179, 255)
_ACTIVE_FILL_ALPHA = 190
_GRID_FOREGROUND_ALPHA = 170
_GRID_HALO_ALPHA = 125
_GRID_FOREGROUND_WIDTH = 2
_GRID_HALO_WIDTH = 4


def _alpha(value: float, opacity: float) -> int:
    return max(0, min(255, int(round(float(value) * max(0.0, min(1.0, float(opacity)))))))


def _draw_contrast_line(
    draw: ImageDraw.ImageDraw,
    points: list[tuple[int, int]],
    *,
    color: tuple[int, int, int],
    opacity: float,
    foreground_alpha: float,
    halo_alpha: float,
    foreground_width: int,
    halo_width: int,
) -> None:
    draw.line(points, fill=(*_GRID_HALO, _alpha(halo_alpha, opacity)), width=int(halo_width))
    draw.line(points, fill=(*color, _alpha(foreground_alpha, opacity)), width=int(foreground_width))


def active_rects_for_overlay(
    active_cells: np.ndarray | None,
    border_rects: list[tuple[int, int, int, int]],
) -> list[tuple[int, int, int, int]]:
    if active_cells is None or not np.any(active_cells) or not border_rects:
        return []
    rects: list[tuple[int, int, int, int]] = []
    for cell_idx in np.flatnonzero(active_cells):
        if int(cell_idx) < len(border_rects):
            rects.append(tuple(int(v) for v in border_rects[int(cell_idx)]))
    return rects


def fill_active_regions_on_overlay(
    overlay: Image.Image,
    rects: list[tuple[int, int, int, int]],
) -> None:
    pad = max(1, int(_GRID_HALO_WIDTH))
    width, height = overlay.size
    for x0, y0, x1, y1 in rects:
        overlay.paste(
            (0, 0, 0, 0),
            (
                max(0, int(x0) - pad),
                max(0, int(y0) - pad),
                min(width, int(x1) + pad + 1),
                min(height, int(y1) + pad + 1),
            ),
        )
    draw = ImageDraw.Draw(overlay)
    for x0, y0, x1, y1 in rects:
        draw.rectangle((int(x0), int(y0), int(x1), int(y1)), fill=(*_ACTIVE_FILL, _ACTIVE_FILL_ALPHA))


def build_grid_overlay_image(
    img_u8: np.ndarray,
    *,
    canvas_size: tuple[int, int],
    grid_density: int,
    grid_opacity: float,
    roi_mask: np.ndarray | None,
    extraction,
    active_cells: np.ndarray | None,
    border_rects: list[tuple[int, int, int, int]],
) -> Image.Image:
    cw, ch = max(1, int(canvas_size[0])), max(1, int(canvas_size[1]))
    h, w = img_u8.shape[:2]
    scale = min(cw / max(w, 1), ch / max(h, 1))
    dw, dh = max(1, int(w * scale)), max(1, int(h * scale))

    pil = Image.fromarray(img_u8).convert("RGB").resize((dw, dh), Image.LANCZOS)
    canvas_pil = Image.new("RGB", (cw, ch), (26, 26, 26))
    ox, oy = (cw - dw) // 2, (ch - dh) // 2
    canvas_pil.paste(pil, (ox, oy))

    grid_overlay = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    draw = ImageDraw.Draw(grid_overlay)

    layout = (cw, ch, dw, dh, ox, oy)
    grid_bounds = grid_bounds_for_layout(layout, extraction)
    if grid_bounds is not None:
        grid_x, grid_y, grid_w, grid_h = grid_bounds
        n = int(grid_density)
        for i in range(1, n):
            x = grid_x + int(grid_w * i / n)
            _draw_contrast_line(
                draw,
                [(x, grid_y), (x, grid_y + grid_h)],
                color=_GRID_FOREGROUND,
                opacity=grid_opacity,
                foreground_alpha=_GRID_FOREGROUND_ALPHA,
                halo_alpha=_GRID_HALO_ALPHA,
                foreground_width=_GRID_FOREGROUND_WIDTH,
                halo_width=_GRID_HALO_WIDTH,
            )
        for i in range(1, n):
            y = grid_y + int(grid_h * i / n)
            _draw_contrast_line(
                draw,
                [(grid_x, y), (grid_x + grid_w, y)],
                color=_GRID_FOREGROUND,
                opacity=grid_opacity,
                foreground_alpha=_GRID_FOREGROUND_ALPHA,
                halo_alpha=_GRID_HALO_ALPHA,
                foreground_width=_GRID_FOREGROUND_WIDTH,
                halo_width=_GRID_HALO_WIDTH,
            )

    active_rects = active_rects_for_overlay(active_cells, border_rects)
    if active_rects:
        fill_active_regions_on_overlay(grid_overlay, active_rects)

    if roi_mask is not None:
        try:
            roi_small = Image.fromarray(np.asarray(roi_mask, dtype=np.uint8) * 255).resize((dw, dh), Image.NEAREST)
            roi_mask_img = Image.new("L", (cw, ch), 0)
            roi_mask_img.paste(roi_small, (ox, oy))
            empty = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
            grid_overlay = Image.composite(grid_overlay, empty, roi_mask_img)
        except Exception:
            pass

    return Image.alpha_composite(canvas_pil.convert("RGBA"), grid_overlay).convert("RGB")
