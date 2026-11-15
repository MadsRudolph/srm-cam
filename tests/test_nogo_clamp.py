"""No-go zones shaped as the lab's real cam clamp (engine/nogo.py)."""
import math

import pytest

from gerber2rml.engine import nogo
from gerber2rml.engine.bracket import path_hit
from gerber2rml.toolpath import Move

STOCK = (30.0, 20.0, 190.0, 120.0)        # 160 x 100
LIP, CAM = nogo.CLAMP_LIP_MM, nogo.CLAMP_CAM_MM
BOSS = nogo.CLAMP_D_MM / 2 - LIP


def _one(zones):
    assert len(zones) == 1, zones
    return zones[0]


def test_a_click_near_an_edge_with_no_holes_sets_the_clamp_on_that_edge():
    cx, cy, d = _one(nogo.clamp_at(80.0, 23.0, STOCK))   # just inside the front
    assert d == nogo.CLAMP_D_MM and cx == 80.0
    assert cy + d / 2 == pytest.approx(STOCK[1] + LIP)


def test_a_click_far_from_the_stock_is_centred_on_the_click():
    assert nogo.clamp_at(100.0, 70.0, STOCK) == [(100.0, 70.0, 26.0)]
    assert nogo.clamp_at(5.0, 5.0, None) == [(5.0, 5.0, 26.0)]


def test_a_clamp_is_tighter_than_the_box_drawn_round_it():
    grow = 0.4 + nogo.NOGO_CLEAR_MM
    disc = nogo.zone_shape((100.0, 50.0, 26.0), grow)
    box = nogo.zone_shape((87.0, 37.0, 113.0, 63.0), grow)
    assert disc.area < box.area
    x0, _y0, x1, _y1 = disc.bounds
    assert (x1 - x0) / 2 == pytest.approx(
        13.0 + 0.4 + nogo.CLAMP_CLEAR_MM, abs=0.01)


def test_a_cut_past_the_lip_is_clear_and_one_on_it_is_not():
    clamp = _one(nogo.clamp_at(80.0, 20.0, STOCK))       # lip reaches y = 22
    grow = 0.4 + nogo.NOGO_CLEAR_MM
    clear_y = STOCK[1] + LIP + 0.4 + nogo.CLAMP_CLEAR_MM + 0.05
    ok = [[Move(70.0, clear_y, -0.1), Move(90.0, clear_y, -0.1)]]
    bad = [[Move(70.0, 22.5, -0.1), Move(90.0, 22.5, -0.1)]]
    assert path_hit(ok, clamp, grow) is None
    assert path_hit(bad, clamp, grow) is not None
    corner = [[Move(95.5, 23.0, -0.1), Move(96.0, 23.0, -0.1)]]
    assert path_hit(corner, clamp, grow) is None


def test_a_way_round_a_clamp_misses_its_disc():
    disc = nogo.zone_shape((100.0, 60.0, 26.0), 0.4 + nogo.NOGO_CLEAR_MM)
    way = nogo.route((70.0, 60.0), (130.0, 60.0), [disc], STOCK)
    assert way
    from shapely.geometry import LineString
    assert not LineString([(70.0, 60.0)] + way
                          + [(130.0, 60.0)]).intersects(disc)
    far = max(abs(y - 60.0) for _x, y in way)
    assert far < 13 + 1.4 + 3


def test_zones_round_trip_through_the_settings_text():
    from gerber2rml.gui2.autorun import nogo_from_text, nogo_to_text
    zones = [(10.0, 10.0, 20.0, 25.0), (80.0, 9.0, 26.0),
             (80.0, 9.0, 26.0, 84.0, 5.0)]
    assert nogo_from_text(nogo_to_text(zones)) == zones
    assert nogo_from_text("1,2,0;x;1,2,3,4") == [(1.0, 2.0, 3.0, 4.0)]


def test_picking_a_clamp_uses_its_disc():
    z = (100.0, 60.0, 26.0, 104.0, 57.0)
    assert nogo.zone_contains(z, 100.0, 72.0)
    assert not nogo.zone_contains(z, 112.0, 72.0)     # the square's corner
    assert math.isclose(nogo.zone_bounds(z)[2], 113.0)


# --- screwed into a bed hole --------------------------------------------------

def _boss_meets_left(z, edge_x):
    return z[0] + BOSS == pytest.approx(edge_x, abs=0.01)


def test_a_clamp_screwed_in_a_hole_is_turned_against_the_edge():
    screw = (STOCK[0] - 8.0, 60.0)              # a hole 8 mm left of the sheet
    z = _one(nogo.clamp_on_screw(screw, STOCK, click=(screw[0], 64.0)))
    assert z[2] == nogo.CLAMP_D_MM and z[3:] == screw
    assert _boss_meets_left(z, STOCK[0])
    assert math.hypot(z[0] - screw[0], z[1] - screw[1]) == pytest.approx(
        CAM, abs=0.01)


def _cw_presses_harder(z, screw, edge_dist):
    """Turn the clamp a little further clockwise (seen from above, Y to the
    back) about its screw: its boss must go further onto the sheet."""
    a = math.atan2(z[1] - screw[1], z[0] - screw[0]) - 0.05
    return edge_dist((screw[0] + CAM * math.cos(a),
                      screw[1] + CAM * math.sin(a))) > edge_dist(z[:2])


def test_tightening_clockwise_presses_the_clamp_onto_the_sheet():
    """Each edge: the clamp sits at the first touch going clockwise, so the
    thumbscrew's clockwise drag adds pressure instead of taking it off."""
    x0, y0, x1, y1 = STOCK
    cases = [((x0 - 8.0, 60.0), lambda c: c[0]),          # left: +x is in
             ((x1 + 8.0, 60.0), lambda c: -c[0]),         # right
             ((80.0, y0 - 8.0), lambda c: c[1]),          # front
             ((80.0, y1 + 8.0), lambda c: -c[1])]         # back
    for screw, inward in cases:
        z = _one(nogo.clamp_on_screw(screw, STOCK))
        assert _cw_presses_harder(z, screw, inward), screw


def test_the_click_picks_the_hole_not_the_turn():
    screw = (80.0, STOCK[1] - 8.0)
    a = nogo.clamp_on_screw(screw, STOCK, click=(84.0, screw[1]))
    b = nogo.clamp_on_screw(screw, STOCK, click=(76.0, screw[1]))
    assert a == b
    # In front of the sheet, clockwise first touch has the clamp to the
    # left of its screw.
    assert a[0][0] < 80.0


def test_its_lip_is_the_only_part_over_the_copper():
    screw = (80.0, STOCK[1] - 12.0)             # in front of the sheet
    z = _one(nogo.clamp_on_screw(screw, STOCK, click=(84.0, screw[1])))
    assert z[1] + z[2] / 2 == pytest.approx(STOCK[1] + LIP, abs=0.01)
    # The thumbscrew's 14.4 mm head is inside the disc.
    assert math.hypot(z[0] - 80.0, z[1] - screw[1]) + 7.2 <= z[2] / 2


def test_a_hole_close_to_the_edge_turns_the_clamp_fully_away():
    """3.9 mm from the edge: the boss cannot clear it, so the clamp is
    turned as far from the sheet as the cam goes - not a catch-all disc."""
    screw = (80.0, STOCK[1] - 3.9)
    z = _one(nogo.clamp_on_screw(screw, STOCK, click=(84.0, screw[1])))
    assert z[2] == nogo.CLAMP_D_MM
    assert z[:2] == pytest.approx((80.0, screw[1] - CAM))
    # Over the copper: 13 - 5.5 - 3.9 = 3.6 mm, not 14.6.
    assert z[1] + z[2] / 2 - STOCK[1] == pytest.approx(3.6, abs=0.01)


def test_a_hole_far_from_the_edge_turns_the_clamp_fully_towards_it():
    screw = (STOCK[0] - 20.0, 60.0)
    z = _one(nogo.clamp_on_screw(screw, STOCK, click=(screw[0], 64.0)))
    assert z[:2] == pytest.approx((screw[0] + CAM, 60.0))
    assert z[0] + z[2] / 2 < STOCK[0]           # it holds nothing: off the sheet


def test_with_no_stock_the_clamp_is_every_way_it_could_turn():
    (z,) = nogo.clamp_on_screw((50.0, 50.0), None)
    assert z == (50.0, 50.0, nogo.CLAMP_D_MM + 2 * CAM, 50.0, 50.0)


def test_a_click_picks_the_nearest_bed_hole():
    holes = [(STOCK[0] - 8.0, 60.0), (STOCK[0] - 8.0, 70.0)]
    z = _one(nogo.clamp_at(STOCK[0] - 6.0, 68.0, STOCK, holes))
    assert _boss_meets_left(z, STOCK[0]) and z[3:] == holes[1]
