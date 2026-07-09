from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

_RENDER_LOCK = threading.RLock()


def render_lock() -> threading.RLock:
    return _RENDER_LOCK


def create_agg_figure(*args: Any, **kwargs: Any):
    from matplotlib.figure import Figure

    return Figure(*args, **kwargs)


def save_agg_figure(fig, path: str | Path, *, dpi: int = 150) -> None:
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    canvas = FigureCanvasAgg(fig)
    canvas.draw()
    fig.savefig(path, dpi=dpi)


def get_colormap(name: str, fallback: str = "viridis"):
    try:
        from matplotlib import colormaps

        return colormaps[str(name)]
    except Exception:
        from matplotlib import colormaps

        return colormaps[str(fallback)]
