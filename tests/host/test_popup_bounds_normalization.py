from __future__ import annotations

from swell.host.ui_geometry import adjust_baseline_end_for_start, normalize_overlay_bounds


def test_normalize_overlay_bounds_swaps_and_clamps() -> None:
    s, e = normalize_overlay_bounds(120, 50, 200)
    assert (s, e) == (50, 120)

    s, e = normalize_overlay_bounds(-10, 300, 100)
    assert (s, e) == (0, 99)


def test_normalize_overlay_bounds_handles_missing_values() -> None:
    s, e = normalize_overlay_bounds(None, 20, 100)
    assert s is None and e == 20

    s, e = normalize_overlay_bounds(20, None, 100)
    assert s == 20 and e is None

    s, e = normalize_overlay_bounds(None, None, 100)
    assert s is None and e is None


def test_normalize_overlay_bounds_empty_stack() -> None:
    s, e = normalize_overlay_bounds(2, 1, 0)
    assert s is None and e is None


def test_adjust_baseline_end_for_start_forced_match() -> None:
    end, changed = adjust_baseline_end_for_start(120, 500, 80, force_match_start=True)
    assert end == 119
    assert changed is True


def test_adjust_baseline_end_for_start_only_corrects_invalid_overlap() -> None:
    end, changed = adjust_baseline_end_for_start(75, 500, 90, force_match_start=False)
    assert end == 74
    assert changed is True

    end, changed = adjust_baseline_end_for_start(120, 500, 90, force_match_start=False)
    assert end == 90
    assert changed is False
