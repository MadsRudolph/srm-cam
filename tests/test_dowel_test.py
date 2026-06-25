"""Tests for the minimal dowel-registration test coupon (examples/dowel_test).

The coupon's whole job is to exercise the double-sided dowel flow on the
smallest board that still proves registration: 2 traces + 4 holes, plus the
dowel/align holes the builder adds in the waste.
"""

from gerber2rml.examples.dowel_test import write_coupon
from gerber2rml.loader import load_board
from gerber2rml.doublesided import build_double_sided, build_align_only, DowelSpec


def test_coupon_round_trips_through_loader(tmp_path):
    folder = write_coupon(tmp_path)
    board = load_board(folder, mirror=False)
    minx, miny, maxx, maxy = board.outline.bounds
    assert abs((maxx - minx) - 24.0) < 0.5
    assert abs((maxy - miny) - 18.0) < 0.5
    assert not board.copper.is_empty           # 2 traces + pads
    assert not board.copper_top.is_empty       # F.Cu pads + witness mark
    assert len(board.holes) == 4               # the four witness holes
    assert sorted({round(d, 1) for (_x, _y, d) in board.holes}) == [0.8]


def test_double_sided_build_adds_two_dowels_on_the_flip_axis(tmp_path):
    folder = write_coupon(tmp_path)
    files = build_double_sided(folder, tmp_path / "out", "dowel",
                               dowels=DowelSpec(), board_thickness=1.6)
    names = {p.name for p in files}
    assert "dowel_align.nc" in names           # the dowel/align holes
    assert "dowel_top_traces.nc" in names and "dowel_bottom_traces.nc" in names


def test_dowel_hole_offset_widens_hole_but_keeps_centre(tmp_path):
    """The slip-fit loop: bumping a clearance must grow that hole while the dowel
    centre stays put, so a re-cut lands back on the existing hole."""
    folder = write_coupon(tmp_path)
    from gerber2rml.doublesided import layout_double_sided

    nominal = layout_double_sided(
        folder, dowels=DowelSpec(clearance_large=0.0, clearance_small=0.0))
    wider = layout_double_sided(
        folder, dowels=DowelSpec(clearance_large=0.2, clearance_small=0.2))

    for (nx, ny, nd), (wx, wy, wd) in zip(nominal.align_holes, wider.align_holes):
        assert abs(nx - wx) < 1e-6 and abs(ny - wy) < 1e-6   # centre invariant
        assert abs((wd - nd) - 0.2) < 1e-6                   # hole 0.2 mm bigger


def test_fresh_align_depth_bites_fixed_distance_into_bed(tmp_path):
    """Fresh dowel holes must reach DOWEL_BED_DEPTH below the stock regardless
    of stock thickness, so the pin always gets enough bite into the bed."""
    from gerber2rml.doublesided import _align_drill, DOWEL_BED_DEPTH
    from gerber2rml.config import DrillJob

    for thickness in (1.6, 4.5):
        _spec, depth = _align_drill(DrillJob(), DowelSpec(), None, thickness)
        assert abs(depth - (thickness + DOWEL_BED_DEPTH)) < 1e-6


def test_align_only_recut_matches_full_build_centres(tmp_path):
    folder = write_coupon(tmp_path)
    p = build_align_only(folder, tmp_path / "out", "dowel",
                         dowels=DowelSpec(), board_thickness=1.6)
    assert p.exists() and p.name == "dowel_align.nc"
