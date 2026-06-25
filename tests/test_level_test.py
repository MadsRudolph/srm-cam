"""Smoke test for the bed-leveling test coupon (examples/level_test)."""
from gerber2rml.examples.level_test import write_coupon
from gerber2rml.loader import load_board


def test_coupon_round_trips_with_spread_copper(tmp_path):
    folder = write_coupon(tmp_path)
    b = load_board(folder, mirror=False)
    x0, y0, x1, y1 = b.outline.bounds
    assert abs((x1 - x0) - 80.0) < 0.5 and abs((y1 - y0) - 60.0) < 0.5
    assert len(b.holes) == 6
    # copper reaches close to all four edges (so leveling has something to correct)
    cx0, cy0, cx1, cy1 = b.copper.bounds
    assert cx0 < 6 and cy0 < 6 and cx1 > 74 and cy1 > 54
