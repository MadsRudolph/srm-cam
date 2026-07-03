"""Isolation DRC: copper gaps narrower than the bit are unfixable shorts."""
from shapely.geometry import box
from shapely.ops import unary_union

from gerber2rml.engine.drc import isolation_bridges


def test_narrow_gap_is_flagged_with_location():
    # two pads 0.5 mm apart: a 0.8 mm bit cannot pass between them
    copper = unary_union([box(0, 0, 10, 10), box(10.5, 0, 20, 10)])
    hits = isolation_bridges(copper, bit_d=0.8)
    assert len(hits) == 1
    h = hits[0]
    assert abs(h["gap"] - 0.5) < 1e-6
    assert abs(h["x"] - 10.25) < 1e-6           # midpoint of the pinch
    assert 0 <= h["y"] <= 10


def test_wide_gap_is_fine():
    copper = unary_union([box(0, 0, 10, 10), box(11, 0, 20, 10)])
    assert isolation_bridges(copper, bit_d=0.8) == []


def test_touching_polygons_are_one_net_not_a_short():
    copper = unary_union([box(0, 0, 10, 10), box(10, 0, 20, 10)])  # merged
    assert isolation_bridges(copper, bit_d=0.8) == []


def test_multiple_pinches_sorted_worst_first():
    copper = unary_union([box(0, 0, 10, 10),
                          box(10.7, 0, 20, 10),      # 0.7 gap in x
                          box(0, 10.2, 10, 20)])     # 0.2 gap in y
    hits = isolation_bridges(copper, bit_d=0.8)
    # three real pinches: 0.2, 0.7, and the 0.728 DIAGONAL between the two far
    # boxes' corners — also genuinely impassable for a 0.8 bit
    assert len(hits) == 3
    assert hits[0]["gap"] < hits[1]["gap"] < hits[2]["gap"]
    assert abs(hits[0]["gap"] - 0.2) < 1e-6


def test_empty_and_single_polygon():
    from shapely.geometry import Polygon
    assert isolation_bridges(None, 0.8) == []
    assert isolation_bridges(box(0, 0, 5, 5), 0.8) == []
    assert isolation_bridges(Polygon(), 0.8) == []
