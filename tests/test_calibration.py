"""TDD tests for the calibration coupon generator (Task C1)."""

from gerber2rml.examples.calibration import write_coupon
from gerber2rml.loader import load_board


def test_coupon_round_trips_through_loader(tmp_path):
    folder = write_coupon(tmp_path)
    board = load_board(folder, mirror=False)
    minx, miny, maxx, maxy = board.outline.bounds
    assert abs((maxx - minx) - 40.0) < 0.5
    assert abs((maxy - miny) - 30.0) < 0.5
    assert not board.copper.is_empty
    assert len(board.holes) == 8
    dias = sorted({round(d, 1) for (_x, _y, d) in board.holes})
    assert dias == [0.8, 1.0]


def test_write_coupon_creates_three_files(tmp_path):
    folder = write_coupon(tmp_path)
    names = sorted(p.name for p in folder.iterdir())
    assert any(n.endswith("B_Cu.gbr") for n in names)
    assert any("Edge_Cuts" in n for n in names)
    assert any(n.endswith(".drl") for n in names)
