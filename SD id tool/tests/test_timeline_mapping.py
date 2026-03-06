from __future__ import annotations

from ui_logic import linear_value_to_x, linear_x_to_value


def test_linear_mapping_round_trip_midpoints() -> None:
    start, end = 0, 2663
    width = 1000.0
    for idx in [0, 1, 250, 999, 1331, 2662, 2663]:
        x = linear_value_to_x(idx, start, end, width)
        back = linear_x_to_value(x, width, start, end)
        assert abs(back - idx) <= 1


def test_linear_mapping_clamps_bounds() -> None:
    x_low = linear_value_to_x(-100, 10, 20, 300)
    x_high = linear_value_to_x(999, 10, 20, 300)
    assert x_low == 0.0
    assert x_high <= 300.0

    assert linear_x_to_value(-50, 300, 10, 20) == 10
    assert linear_x_to_value(9999, 300, 10, 20) == 20
