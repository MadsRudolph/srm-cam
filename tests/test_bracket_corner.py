"""A board in the bracket's corner: placed there, snapped there, and how
big the stock must be. Pure geometry (engine/bracket.py)."""
import pytest

from gerber2rml.engine import bracket as br

# The lab's bracket: back-right, inside corner (191.79, 128.43), and its
# tongue along the back edge (the keepout below is what Bracket.keepout()
# gives for it).
STOCK = (31.79, 28.43, 160.0, 100.0)          # back-right corner in the L
KEEPOUT = (165.29, 123.93, 189.79, 128.43)


def test_a_small_board_sits_margin_in_from_the_corner_clear_of_the_tongue():
    ext = (0.0, 0.0, 80.0, 60.0)
    x0, y0 = br.corner_place("back-right", STOCK, ext, KEEPOUT, 0.8, 3.0)
    assert x0 + 80.0 == pytest.approx(191.79 - 3.0)       # 3 mm from the right
    top = y0 + 60.0
    assert top + 0.8 < KEEPOUT[1]                          # the bit clears it
    assert top == pytest.approx(KEEPOUT[1] - 1.0)


def test_without_a_tongue_in_the_way_both_edges_are_the_margin():
    ext = (0.0, 0.0, 20.0, 20.0)
    x0, y0 = br.corner_place("front-left", STOCK, ext, KEEPOUT, 0.8, 3.0)
    assert (x0, y0) == pytest.approx((31.79 + 3.0, 28.43 + 3.0))


def test_the_stock_needed_counts_the_tongue():
    ext = (0.0, 0.0, 158.0, 98.1)
    w, h = br.stock_needed("back-right", STOCK, ext, KEEPOUT, 0.8, 3.0)
    assert w == pytest.approx(161.0)
    assert h == pytest.approx(98.1 + 5.5)


def test_a_drag_near_the_corner_snaps_into_it_per_axis():
    ext = (100.0, 50.0, 180.0, 110.0)
    nx, ny = br.corner_place("back-right", STOCK, ext, KEEPOUT, 0.8, 3.0)
    dx, dy = br.snap_offset("back-right", STOCK, ext,
                            nx - ext[0] + 2.0, ny - ext[1] - 30.0,
                            KEEPOUT, 0.8, 3.0)
    assert dx == pytest.approx(nx - ext[0])       # within 3 mm: snapped
    assert dy == pytest.approx(ny - ext[1] - 30.0)  # far: left alone
