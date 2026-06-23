from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from swell.host.auto_detect_helpers import grid_bounds_for_layout


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

    minor_alpha = int(round(96 * float(grid_opacity)))
    major_alpha = int(round(150 * float(grid_opacity)))
    layout = (cw, ch, dw, dh, ox, oy)
    grid_bounds = grid_bounds_for_layout(layout, extraction)
    if grid_bounds is not None:
        grid_x, grid_y, grid_w, grid_h = grid_bounds
        n = int(grid_density)
        for i in range(1, n):
            x = grid_x + int(grid_w * i / n)
            alpha = major_alpha if i % 5 == 0 else minor_alpha
            draw.line([(x, grid_y), (x, grid_y + grid_h)], fill=(125, 175, 215, alpha), width=1)
        for i in range(1, n):
            y = grid_y + int(grid_h * i / n)
            alpha = major_alpha if i % 5 == 0 else minor_alpha
            draw.line([(grid_x, y), (grid_x + grid_w, y)], fill=(125, 175, 215, alpha), width=1)

    if roi_mask is not None:
        try:
            roi_small = Image.fromarray(np.asarray(roi_mask, dtype=np.uint8) * 255).resize((dw, dh), Image.NEAREST)
            roi_mask_img = Image.new("L", (cw, ch), 0)
            roi_mask_img.paste(roi_small, (ox, oy))
            empty = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
            grid_overlay = Image.composite(grid_overlay, empty, roi_mask_img)
        except Exception:
            pass

    if active_cells is not None and np.any(active_cells) and border_rects:
        draw = ImageDraw.Draw(grid_overlay)
        for cell_idx in np.flatnonzero(active_cells):
            if int(cell_idx) >= len(border_rects):
                continue
            x0, y0, x1, y1 = border_rects[int(cell_idx)]
            draw.rectangle((x0, y0, x1, y1), outline=(27, 117, 188, 96), width=1)

    return Image.alpha_composite(canvas_pil.convert("RGBA"), grid_overlay).convert("RGB")
