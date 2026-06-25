"""Tests for the dowel-pin fit-test drill gerber (examples/hole_test)."""

from gerber2rml.examples.hole_test import write_hole_test, CLEAR_N
from gerber2rml.loader import load_board
from gerber2rml.doublesided import PIN_LARGE, PIN_SMALL


def test_round_trips_through_loader_with_swept_holes(tmp_path):
    folder = write_hole_test(tmp_path, name="ht")
    board = load_board(folder, mirror=False)
    assert len(board.holes) == 2 * CLEAR_N          # both rows, one hole per clearance
    dias = {round(d, 2) for _x, _y, d in board.holes}
    assert len(dias) == 2 * CLEAR_N                 # every hole a distinct diameter


def test_writes_legend(tmp_path):
    write_hole_test(tmp_path, name="ht")
    text = (tmp_path / "ht_legend.txt").read_text(encoding="utf-8")
    assert "SMALL" in text and "BIG" in text
    assert text.count("BIG") >= CLEAR_N and text.count("SMALL") >= CLEAR_N


def test_top_row_small_pin_bottom_row_big(tmp_path):
    """Top (higher-Y) row holes bracket the SMALL pin; bottom row the BIG pin."""
    folder = write_hole_test(tmp_path, name="ht")
    board = load_board(folder, mirror=False)
    rows = {}
    for _x, y, d in board.holes:
        rows.setdefault(round(y), []).append(d)
    ys = sorted(rows)
    bottom, top = rows[ys[0]], rows[ys[-1]]
    # top row sits around the small pin, bottom row around the big pin
    assert all(PIN_SMALL <= d <= PIN_SMALL + 0.65 for d in top)
    assert all(PIN_LARGE <= d <= PIN_LARGE + 0.65 for d in bottom)
