from __future__ import annotations

import os
import warnings


def env_with_legacy(canonical: str, legacy: str) -> str | None:
    """Read a canonical env var with a deprecated legacy alias."""
    canonical_value = str(os.environ.get(canonical, "")).strip()
    if canonical_value:
        return canonical_value
    legacy_value = str(os.environ.get(legacy, "")).strip()
    if legacy_value:
        warnings.warn(
            f"{legacy} is deprecated; use {canonical} instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return legacy_value
    return None
