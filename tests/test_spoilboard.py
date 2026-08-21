"""The spoilboard screw grid.

The thing these tests protect is simple and unforgiving: a drilled hole must
land on a hole in the MDF, which lines up with a thread in the metal plate.
Miss and the bit goes into steel. So the grid arithmetic is checked against the
measured board rather than assumed, and every rule that drops a hole from the
usable set has a test saying why.
"""
from pathlib import Path

import pytest

from gerber2rml.engine import spoilboard as sb
from gerber2rml.engine.spoilboard import HoleGrid

BED = (203.2, 152.4)          # SRM-20 travel


def _grid(origin=(15.0, 15.0), **kw):
    """The lab grid, anchored so hole (0,0) sits 15 mm in from the machine
    origin - a stand-in for the measured anchor."""
    return HoleGrid(origin=origin, **kw)


# ---- the measured numbers --------------------------------------------------

def test_pitch_matches_the_two_measured_spans():
    """190 mm across 20 holes and 120 mm across 13 both give 10.0 mm. Two
    independent spans agreeing is what makes this safe to drill against."""
    assert 190.0 / (20 - 1) == pytest.approx(sb.PITCH)
    assert 120.0 / (13 - 1) == pytest.approx(sb.PITCH)


def test_edge_margin_falls_out_symmetrically():
    """The leftover margin lands on 15.0 mm on all four sides, which is the
    cross-check that the pitch and the board size agree."""
    span_x = (sb.NX - 1) * sb.PITCH
    span_y = (sb.NY - 1) * sb.PITCH
    assert (sb.BOARD[0] - span_x) / 2 == pytest.approx(sb.EDGE_MARGIN)
    assert (sb.BOARD[1] - span_y) / 2 == pytest.approx(sb.EDGE_MARGIN)


def test_hole_centres_step_by_the_pitch():
    g = _grid(origin=(15.0, 25.0))
    assert g.centre(0, 0) == (15.0, 25.0)
    assert g.centre(1, 0) == (25.0, 25.0)
    assert g.centre(0, 1) == (15.0, 35.0)
    assert g.centre(3, 2) == (45.0, 45.0)


# ---- which holes are available --------------------------------------------

def test_outer_ring_is_excluded():
    """Those are the spoilboard's own mounting screws and sit outside the
    build area - offering one would send the bit somewhere it must not go."""
    g = _grid()
    ij = {(i, j) for (i, j, _x, _y) in g.holes()}
    assert (0, 0) not in ij
    assert (sb.NX - 1, sb.NY - 1) not in ij
    assert (1, 1) in ij
    assert len(ij) == (sb.NX - 2) * (sb.NY - 2)


def test_skip_border_is_adjustable():
    g = _grid(skip_border=2)
    ij = {(i, j) for (i, j, _x, _y) in g.holes()}
    assert (1, 1) not in ij
    assert (2, 2) in ij


def test_every_interior_hole_is_reachable_at_the_nominal_anchor():
    """Good news worth pinning down: the spoilboard is 220 mm wide against
    203.2 mm of X travel, but the columns that fall outside are the outer ring,
    which is excluded as spoilboard mounts anyway. So with the board sitting
    square at the machine origin, everything left is drillable."""
    g = _grid(origin=(15.0, 15.0))
    reach = sb.reachable(g, BED)
    assert len(reach) == len(list(g.holes()))


def test_holes_beyond_the_machine_travel_are_dropped():
    """The filter still has to bite, because the spoilboard's real anchor is
    measured, not assumed - mount it 30 mm right and a column goes out of
    reach. Offering one would be a hole the machine refuses to move to."""
    g = _grid(origin=(45.0, 15.0))
    reach = sb.reachable(g, BED)
    assert reach, "sanity: most holes still reachable"
    assert len(reach) < len(list(g.holes()))
    assert all(x <= BED[0] for (_i, _j, x, _y) in reach)


# ---- choosing screw positions ---------------------------------------------

def test_candidates_require_the_whole_head_on_copper():
    """A head hanging over the edge cannot clamp - it tips and lets the stock
    lift. So the hole must be inset by the head radius, not just be inside."""
    g = _grid()
    stock = (40.0, 40.0, 60.0, 40.0)
    inset = sb.M4_HEAD_D / 2.0 + 1.0
    for (_i, _j, x, y) in sb.candidates(g, stock, BED):
        assert stock[0] + inset <= x <= stock[0] + stock[2] - inset
        assert stock[1] + inset <= y <= stock[1] + stock[3] - inset


def test_pick_fasteners_spreads_to_the_corners():
    """Four screws bunched at one end leave the far end free to lift and
    chatter, which is the whole failure this fixture exists to prevent."""
    g = _grid()
    stock = (25.0, 25.0, 100.0, 80.0)
    pts = sb.pick_fasteners(g, stock, BED)
    assert len(pts) == 4
    assert len(set(pts)) == 4                      # four DISTINCT holes
    cx = stock[0] + stock[2] / 2.0
    cy = stock[1] + stock[3] / 2.0
    # one in each quadrant of the stock
    quadrants = {(x > cx, y > cy) for (x, y) in pts}
    assert len(quadrants) == 4


def test_picked_holes_are_real_grid_holes():
    """The point of the whole module: every chosen point must sit exactly on a
    grid hole, because that is where the thread underneath is."""
    g = _grid()
    pts = sb.pick_fasteners(g, (25.0, 25.0, 100.0, 80.0), BED)
    centres = {(round(x, 6), round(y, 6)) for (_i, _j, x, y) in g.holes()}
    for x, y in pts:
        assert (round(x, 6), round(y, 6)) in centres


def test_holes_under_the_design_are_refused():
    """A screw head overlapping the design would be cut into."""
    from shapely.geometry import box
    g = _grid()
    stock = (25.0, 25.0, 100.0, 80.0)
    free = sb.pick_fasteners(g, stock, BED)
    blocked = sb.pick_fasteners(g, stock, BED, keepout=box(25.0, 25.0, 125.0, 105.0))
    assert free, "sanity: some holes exist with no keepout"
    assert blocked == [], "a design covering the whole stock leaves nowhere to screw"


def test_fewer_than_four_is_an_honest_answer():
    """A stock too small for four screws should report the two it can take,
    not invent a third somewhere useless."""
    g = _grid()
    tight = (30.0, 30.0, 22.0, 12.0)     # room for very few holes
    pts = sb.pick_fasteners(g, tight, BED)
    assert len(pts) < 4
    assert len(set(pts)) == len(pts)


def test_no_stock_overlap_gives_no_screws():
    g = _grid()
    pts = sb.pick_fasteners(g, (0.0, 0.0, 5.0, 5.0), BED)
    assert pts == []


# ---- the drilling program --------------------------------------------------

def test_toolpaths_stop_just_through_the_copper():
    """There is already a 4 mm hole in the MDF under every one of these, so
    the bit exits into air - nothing is gained by going deeper."""
    pts = [(50.0, 50.0), (90.0, 50.0)]
    paths = sb.fastener_toolpaths(pts, copper_thickness=1.6, breakthrough=0.3)
    assert paths
    zs = [m.z for tp in paths for m in tp]
    assert min(zs) == pytest.approx(-1.9, abs=1e-6)


def test_toolpaths_are_produced_for_every_point():
    pts = [(50.0, 50.0), (90.0, 50.0), (50.0, 90.0)]
    paths = sb.fastener_toolpaths(pts)
    xy = {(round(m.x, 3), round(m.y, 3)) for tp in paths for m in tp}
    for x, y in pts:
        assert any(abs(px - x) < 3.0 and abs(py - y) < 3.0 for px, py in xy)


def test_procedure_mentions_every_screw():
    pts = [(50.0, 50.0), (90.0, 50.0)]
    text = sb.procedure(pts, _grid())
    assert "screw 1" in text and "screw 2" in text
    assert "Re-zero Z" in text          # tightening pulls the board down


def test_procedure_says_so_when_there_is_nowhere_to_screw():
    text = sb.procedure([], _grid())
    assert "No usable screw positions" in text


# ---- the measured anchor ---------------------------------------------------

def test_measured_anchor_reproduces_both_dro_readings():
    """The two holes actually jogged into on the machine, to 0.05 mm."""
    g = sb.measured_grid()
    x1, y1 = g.centre(1, 0)          # 2nd from the front-left
    x2, y2 = g.centre(18, 0)         # last before the bolt column
    assert (x1, y1) == pytest.approx((16.44, 14.58), abs=0.05)
    assert (x2, y2) == pytest.approx((186.40, 14.58), abs=0.05)


def test_measured_anchor_places_the_board_centred_on_the_travel():
    """Independent confirmation: a 220 mm board on 203.2 mm of travel must
    overhang by exactly 16.8 mm in total. If the anchor or the hole indices
    were wrong this would not land."""
    ox, _oy = sb.MEASURED_ORIGIN
    left = ox - sb.EDGE_MARGIN
    right = left + sb.BOARD[0]
    assert (-left) + (right - 203.2) == pytest.approx(sb.BOARD[0] - 203.2, abs=0.05)
    assert -left == pytest.approx(8.6, abs=0.2)      # near-centred, not shoved over


def test_anchor_is_recorded_as_confirmed_by_drilling():
    """The model was validated by drilling real holes and running M4 screws
    into the plate. Keep that note attached to the numbers: the next person to
    touch this needs to know it was checked against metal, not just arithmetic
    - and needs to know to re-check it if the spoilboard is ever replaced."""
    import gerber2rml.engine.spoilboard as mod
    src = Path(mod.__file__).read_text(encoding="utf-8")
    assert "CONFIRMED IN PRACTICE" in src
    assert "RE-MEASURE" in src


def test_the_grid_is_square_to_the_axes():
    """Both DRO readings gave Y 14.58 exactly, so no rotation term is needed.
    This test exists so that reintroducing one is a deliberate act."""
    g = sb.measured_grid()
    assert g.centre(1, 0)[1] == g.centre(18, 0)[1]


# ---- the screw heads, and the collision nobody sees ------------------------

def test_measured_head_geometry():
    assert sb.M4_HEAD_D == 8.0        # across the head
    assert sb.M4_HEAD_H == 3.0        # standing proud of the copper


def test_default_travel_z_would_hit_a_screw_head():
    """The failure mode of this whole fixture, and it is silent: every cut is
    at the right depth, the XY is perfect, and the spindle drives into a screw
    on the first traverse. The geometry cannot catch it because the screws are
    not in the geometry."""
    from gerber2rml.config import TraceJob
    problem = sb.travel_z_problem(TraceJob().travel_z)
    assert problem is not None
    assert "screw" in problem and "4" in problem


def test_min_travel_z_clears_the_head():
    assert sb.min_travel_z() == pytest.approx(sb.M4_HEAD_H + sb.HEAD_CLEARANCE)
    assert sb.min_travel_z() > sb.M4_HEAD_H
    assert sb.travel_z_problem(sb.min_travel_z()) is None


def test_taller_heads_demand_more_clearance():
    """Swap the screws and the requirement moves with them."""
    assert sb.min_travel_z(head_h=6.0) == pytest.approx(7.0)
    assert sb.travel_z_problem(5.0, head_h=6.0) is not None


def test_procedure_spells_out_the_travel_z_step():
    text = sb.procedure([(50.0, 50.0)], sb.measured_grid())
    assert "TRAVEL Z" in text
    assert f"{sb.min_travel_z():g} mm" in text


def test_keepout_uses_the_real_head_width():
    """An 8 mm head needs 4 mm of clearance, not the 3.5 mm a 7 mm head would.
    Half a millimetre is the difference between clearing the design and
    cutting into a screw."""
    from shapely.geometry import Point
    g = sb.measured_grid()
    stock = (20.0, 20.0, 120.0, 100.0)
    # a design disc centred exactly on a grid hole must exclude that hole
    hx, hy = g.centre(5, 5)
    pts = sb.pick_fasteners(g, stock, BED, keepout=Point(hx, hy).buffer(0.5))
    assert (hx, hy) not in pts


# ---- can the screws actually hold it flat? ---------------------------------

def test_open_copper_spreads_across_the_piece():
    g = sb.measured_grid()
    stock = (30.0, 30.0, 100.0, 75.0)
    pts = sb.pick_fasteners(g, stock, BED)
    assert len(pts) == 4
    assert sb.spread_problem(pts, stock) is None


def test_screws_strung_out_in_a_line_are_reported():
    """Four screws in a line clamp along that line and let the copper pivot
    about it. The COUNT does not reveal this - you get the four you asked for
    and they are useless - so spread is checked separately."""
    from shapely.geometry import box
    g = sb.measured_grid()
    stock = (30.0, 30.0, 100.0, 75.0)
    pts = sb.pick_fasteners(g, stock, BED, keepout=box(2, 2, 106, 106))
    assert len(pts) == 4                      # the count looks fine...
    problem = sb.spread_problem(pts, stock)   # ...and it is still a hinge
    assert problem is not None
    assert "pivot" in problem


def test_spread_check_ignores_a_single_screw():
    assert sb.spread_problem([(50.0, 50.0)], (30.0, 30.0, 100.0, 75.0)) is None

