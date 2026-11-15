"""A gap the cutter's own width, and copper that is one net.

Both were reported as shorts. The first is cut by one pass down its middle
(and without that pass was NOT cut, whatever the check said); the second is
not a short at all.
"""
import pytest
from shapely.geometry import LineString, MultiPolygon, Point, box
from shapely.ops import unary_union

from gerber2rml.config import TraceJob
from gerber2rml.engine import drc
from gerber2rml.engine.traces import isolate

BIT = 0.8


def _bars(gap, length=20.0):
    """Two parallel 0.8 mm tracks, ``gap`` apart."""
    return MultiPolygon([box(0, 0, length, 0.8),
                         box(0, 0.8 + gap, length, 1.6 + gap)])


def _joined_after_milling(copper):
    """Mill the isolation passes out of a full sheet: are the two pieces of
    copper still one?"""
    job = TraceJob(bit_diameter=BIT)
    sheet = copper.envelope.buffer(3)
    paths = isolate(copper, job, outline=sheet)
    cuts = [LineString([(m.x, m.y) for m in p if not m.rapid])
            for p in paths if sum(not m.rapid for m in p) >= 2]
    left = sheet.difference(unary_union(cuts).buffer(BIT / 2 - 0.002))
    parts = list(getattr(left, "geoms", [left]))
    a, b = (g.representative_point() for g in copper.geoms)
    return ([i for i, c in enumerate(parts) if c.contains(a)]
            == [i for i, c in enumerate(parts) if c.contains(b)])


@pytest.mark.parametrize("gap", [0.8, 0.8 - 1e-10, 0.8 + 1e-10, 0.7996])
def test_a_gap_the_cutters_width_is_cut_and_is_not_a_short(gap):
    copper = _bars(gap)
    assert drc.isolation_bridges(copper, BIT) == []
    assert len(drc.exact_fit_pairs(copper, BIT)) == 1
    assert not _joined_after_milling(copper)


def test_a_gap_really_narrower_than_the_cutter_is_still_a_short():
    copper = _bars(0.79)
    assert len(drc.isolation_bridges(copper, BIT)) == 1
    assert drc.exact_fit_pairs(copper, BIT) == []
    assert _joined_after_milling(copper)          # and nothing cuts it


def test_a_wider_gap_is_cut_as_it_always_was():
    copper = _bars(0.9)
    assert drc.isolation_bridges(copper, BIT) == []
    assert drc.exact_fit_pairs(copper, BIT) == []
    assert not _joined_after_milling(copper)


def test_the_exact_fit_pass_takes_no_copper():
    copper = _bars(0.8)
    job = TraceJob(bit_diameter=BIT)
    paths = isolate(copper, job, outline=copper.envelope.buffer(3))
    cuts = [LineString([(m.x, m.y) for m in p if not m.rapid])
            for p in paths if sum(not m.rapid for m in p) >= 2]
    swept = unary_union(cuts).buffer(BIT / 2 - 1e-6)
    assert swept.intersection(copper).area < 1e-3


# -- nets --------------------------------------------------------------------
POUR = box(0, 0, 10, 10)
ISLAND = box(10.3, 4, 12, 6)          # 0.3 mm from the pour
OTHER = box(12.3, 4, 14, 6)           # 0.3 mm from the island


def test_two_pieces_of_one_net_are_not_a_short():
    copper = MultiPolygon([POUR, ISLAND])
    assert len(drc.isolation_bridges(copper, BIT)) == 1            # by shape
    assert drc.isolation_bridges(copper, BIT,
                                 nets=[{"GND"}, {"GND"}]) == []


def test_loose_copper_beside_a_net_is_not_a_short():
    copper = MultiPolygon([POUR, ISLAND])
    assert drc.isolation_bridges(copper, BIT, nets=[{"GND"}, set()]) == []


def test_two_different_nets_are():
    copper = MultiPolygon([POUR, ISLAND])
    assert len(drc.isolation_bridges(copper, BIT,
                                     nets=[{"GND"}, {"5V"}])) == 1


def test_loose_copper_that_bridges_two_nets_is_a_short_on_both_sides():
    copper = MultiPolygon([POUR, ISLAND, OTHER])
    got = drc.isolation_bridges(copper, BIT, nets=[{"GND"}, set(), {"5V"}])
    assert len(got) == 2


def test_nets_that_do_not_line_up_with_the_copper_are_ignored():
    copper = MultiPolygon([POUR, ISLAND])
    assert len(drc.isolation_bridges(copper, BIT, nets=[{"GND"}])) == 1


@pytest.mark.exact_pads
def test_net_names_are_read_from_the_gerber_and_survive_moving():
    from pathlib import Path
    from gerber2rml import loader
    b = loader.load_board(Path(__file__).parent / "fixtures" / "mosfet_test")
    polys = list(b.copper.geoms)
    assert b.copper_nets is not None and len(b.copper_nets) == len(polys)
    assert any(b.copper_nets)
    moved = loader.translate_board(loader.rotate_board(b, 90), 5.0, 7.0)
    assert moved.copper_nets == b.copper_nets
    assert ([round(p.area, 6) for p in moved.copper.geoms]
            == [round(p.area, 6) for p in polys])     # same order, same shapes


# -- corners the cutter cannot reach into ------------------------------------
def test_the_inside_of_an_acute_bend_is_a_corner_not_a_gap():
    """A track joining another at 45 degrees: one piece of copper, and a
    point the round cutter cannot get into. That copper stays on the track
    it is the corner of."""
    from gerber2rml.analysis import find_narrow_gaps, split_narrow_gaps
    bend = unary_union([LineString([(0, 0), (20, 0)]).buffer(0.4),
                        LineString([(10, 0), (16, 6)]).buffer(0.4)])
    other = box(0, 5, 4, 8)                        # a second piece, far away
    copper = MultiPolygon([bend, other])
    between, corners = split_narrow_gaps(
        find_narrow_gaps(copper, None, BIT, min_area=0.01), copper)
    assert between.is_empty
    assert not corners.is_empty


def test_a_slot_between_two_pieces_is_still_a_gap():
    from gerber2rml.analysis import find_narrow_gaps, split_narrow_gaps
    copper = _bars(0.5)
    between, corners = split_narrow_gaps(
        find_narrow_gaps(copper, None, BIT), copper)
    assert not between.is_empty and corners.is_empty


def test_no_gaps_split_into_nothing():
    from shapely.geometry import Polygon
    from gerber2rml.analysis import split_narrow_gaps
    between, corners = split_narrow_gaps(Polygon(), _bars(2.0))
    assert between.is_empty and corners.is_empty
