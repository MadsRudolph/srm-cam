"""Tests for the Gerber/Excellon loader (Task 4)."""

from pathlib import Path

from shapely.geometry.base import BaseGeometry

from gerber2rml.loader import load_board

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"


def test_loads_copper_outline_and_holes():
    board = load_board(FIXT, mirror=False)
    assert isinstance(board.copper, BaseGeometry)
    assert not board.copper.is_empty
    assert board.outline is not None and not board.outline.is_empty
    assert len(board.holes) > 0
    for x, y, dia in board.holes:
        assert dia > 0


def test_mirror_flips_x():
    a = load_board(FIXT, mirror=False)
    b = load_board(FIXT, mirror=True)
    assert b.copper.bounds[0] == -a.copper.bounds[2]  # minx_mirrored == -maxx
