from __future__ import annotations

from collections import OrderedDict

from ui_logic import clamp_popup_range


def test_clamp_popup_range_swaps_and_clamps_current() -> None:
    cache: OrderedDict[int, object] = OrderedDict((k, object()) for k in range(20))
    s, e, cur, removed = clamp_popup_range(15, 5, 30, 29, cache)
    assert (s, e) == (5, 15)
    assert cur == 15
    assert set(removed) == set(range(0, 5)) | set(range(16, 20))


def test_clamp_popup_range_shrink_invalidates_out_of_range_cache() -> None:
    cache: OrderedDict[int, object] = OrderedDict((k, object()) for k in [90, 95, 100, 105, 110])
    s, e, cur, removed = clamp_popup_range(95, 105, 300, 100, cache)
    assert (s, e) == (95, 105)
    assert cur == 100
    assert removed == [90, 110]
    assert list(cache.keys()) == [95, 100, 105]


def test_clamp_popup_range_empty_frame_count() -> None:
    s, e, cur, removed = clamp_popup_range(0, 10, 0, 5)
    assert (s, e, cur) == (0, 0, 0)
    assert removed == []
