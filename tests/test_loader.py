"""Tests for the Gerber/Excellon loader (Task 4)."""

import math
from pathlib import Path

from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from gerber2rml.loader import load_board, rotate_board

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"


def test_rotate_board_90_moves_geometry():
    b = load_board(FIXT, mirror=False)
    # rotate a hole 90deg CCW about the origin: (x, y) -> (-y, x)
    hx, hy, hd = b.holes[0]
    r = rotate_board(b, 90)
    rx, ry, rd = r.holes[0]
    assert abs(rx - (-hy)) < 1e-6 and abs(ry - hx) < 1e-6 and rd == hd
    # outline area is preserved, copper geometry stays valid
    assert abs(r.outline.area - b.outline.area) < 1e-6
    assert r.copper.is_valid


def test_rotate_board_360_is_identity():
    b = load_board(FIXT, mirror=False)
    assert rotate_board(b, 360) is b           # no-op fast path


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
    assert math.isclose(b.copper.bounds[0], -a.copper.bounds[2], rel_tol=1e-9, abs_tol=1e-9)


def test_outline_is_polygon():
    board = load_board(FIXT, mirror=False)
    assert isinstance(board.outline, Polygon)


def test_holes_are_mirrored():
    a = load_board(FIXT, mirror=False)
    b = load_board(FIXT, mirror=True)
    assert len(a.holes) == len(b.holes)
    for (ax, ay, ad), (bx, by, bd) in zip(a.holes, b.holes):
        assert math.isclose(bx, -ax, abs_tol=1e-9)
        assert math.isclose(by, ay, abs_tol=1e-9)
        assert ad == bd


def test_copper_is_valid():
    board = load_board(FIXT, mirror=False)
    assert board.copper.is_valid


def test_loads_top_copper_field():
    board = load_board(FIXT, mirror=False)
    assert hasattr(board, "copper_top")      # present (may be empty if no F.Cu)


def test_loads_partial_gerber_set(tmp_path):
    import shutil
    src = FIXT
    # only B.Cu, F.Cu, Edge.Cuts, drill -> the set gerbonara's mapper chokes on
    for name in ("buck-B_Cu.gbl", "buck-F_Cu.gtl", "buck-Edge_Cuts.gm1", "buck.drl"):
        shutil.copy(src / name, tmp_path / name)
    board = load_board(tmp_path, mirror=False)
    assert not board.copper.is_empty
    assert board.outline is not None and not board.outline.is_empty
    assert len(board.holes) > 0
