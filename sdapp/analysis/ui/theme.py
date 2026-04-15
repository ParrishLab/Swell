# Compatibility shim — theme definitions live in sdapp.shared.ui.theme.
from sdapp.shared.ui.theme import (  # noqa: F401
    CANVAS_BACKGROUND,
    LayoutSpacing,
    SLIDER_OVERLAY_BACKGROUND,
    SPACING,
    apply_theme,
    _configure_scrollbar_style,
    _theme_palette,
)
