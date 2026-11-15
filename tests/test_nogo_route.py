"""The way round a no-go zone (engine/nogo.py): plain geometry."""
import math

from shapely.geometry import LineString, box
from shapely.ops import unary_union

from gerber2rml.engine.nogo import route

STOCK = (0.0, 0.0, 100.0, 80.0)


def _ok(a, b, way, zones):
    line = LineString([a] + way + [b])
    assert not line.intersects(unary_union(zones)), way
    return line.length


def test_a_clear_line_needs_no_turns():
    assert route((10, 10), (90, 10), [box(40, 30, 60, 50)], STOCK) == []
    assert route((10, 10), (90, 10), [], STOCK) == []


def test_one_zone_is_passed_round_its_nearer_side():
    zones = [box(40, 30, 60, 50)]
    way = route((10, 35), (90, 35), zones, STOCK)
    assert way and len(way) == 2
    assert all(y < 30 for _x, y in way)          # under it: 5 mm, not 15
    assert _ok((10, 35), (90, 35), way, zones) < 80 + 2 * 8


def test_two_zones_in_a_row_are_both_passed():
    zones = [box(30, 20, 40, 60), box(60, 20, 70, 60)]
    way = route((10, 40), (90, 40), zones, STOCK)
    assert way
    _ok((10, 40), (90, 40), way, zones)


def test_it_does_not_leave_the_stock_to_get_round():
    """The zone reaches the stock's front edge: the only way is behind it."""
    zones = [box(40, -5, 60, 50)]
    way = route((10, 10), (90, 10), zones, STOCK)
    assert way and all(y > 50 for _x, y in way)
    assert all(STOCK[0] <= x <= STOCK[2] and STOCK[1] <= y <= STOCK[3]
               for x, y in way)


def test_a_wall_across_the_stock_has_no_way_round():
    assert route((10, 40), (90, 40), [box(40, -5, 60, 85)], STOCK) is None


def test_an_end_inside_a_zone_has_no_way():
    assert route((50, 40), (90, 40), [box(40, 30, 60, 50)], STOCK) is None
    assert route((10, 40), (50, 40), [box(40, 30, 60, 50)], STOCK) is None


def test_the_ends_may_be_off_the_stock():
    zones = [box(40, 30, 60, 50)]
    way = route((-20, 40), (90, 40), zones, STOCK)
    assert way
    _ok((-20, 40), (90, 40), way, zones)


def test_the_shortest_way_is_taken_not_just_any():
    zones = [box(40, 10, 60, 70)]
    a, b = (10, 20), (90, 20)
    way = route(a, b, zones, STOCK)
    under = math.dist(a, (39.7, 9.7)) + 20.6 + math.dist((60.3, 9.7), b)
    assert _ok(a, b, way, zones) <= under + 0.01


# --- a job's travel is led round; its cuts are not ----------------------------

def _hole(x, y):
    from gerber2rml.toolpath import Move
    return [Move(x, y, 2.0, rapid=True), Move(x, y, -1.9),
            Move(x, y, 2.0, rapid=True)]


def test_the_hop_between_two_holes_goes_round_a_clamp():
    """The lab case, 2026-11-15: two corner holes, a clamp between them,
    and a run that refused to drill because the straight line from one to
    the other clipped the clamp's corner."""
    from gerber2rml.engine.bracket import path_hit
    from gerber2rml.engine.nogo import detour
    clamp = (40.0, 30.0, 60.0, 50.0)
    paths = [_hole(10, 40), _hole(90, 40)]
    assert path_hit(paths, clamp, 0.0)
    out, led = detour(paths, [box(*clamp)], STOCK)
    assert led == 1
    assert path_hit(out, clamp, 0.0) is None
    # The holes are where they were, and there are still two of them.
    cuts = [(m.x, m.y) for tp in out for m in tp if not m.rapid]
    assert cuts == [(10, 40), (90, 40)]
    # The way round is travelled at travel height, not dragged at depth.
    extra = [m for m in out[1] if m.rapid and (m.x, m.y) not in ((90, 40),)]
    assert extra and all(m.z == 2.0 for m in extra)


def test_a_cut_through_a_zone_is_left_for_the_check_to_refuse():
    from gerber2rml.engine.bracket import path_hit
    from gerber2rml.engine.nogo import detour
    from gerber2rml.toolpath import Move
    clamp = (40.0, 30.0, 60.0, 50.0)
    trace = [[Move(10, 40, 2.0, rapid=True), Move(10, 40, -0.1),
              Move(90, 40, -0.1), Move(90, 40, 2.0, rapid=True)]]
    out, led = detour(trace, [box(*clamp)], STOCK)
    assert led == 0 and out == trace
    assert path_hit(out, clamp, 0.0)


def test_a_hole_in_a_zone_is_not_moved():
    from gerber2rml.engine.bracket import path_hit
    from gerber2rml.engine.nogo import detour
    clamp = (40.0, 30.0, 60.0, 50.0)
    paths = [_hole(10, 40), _hole(50, 40)]
    out, led = detour(paths, [box(*clamp)], STOCK)
    assert led == 0
    assert path_hit(out, clamp, 0.0)


def test_paths_with_no_zone_near_come_back_as_they_went_in():
    from gerber2rml.engine.nogo import detour
    paths = [_hole(10, 10), _hole(20, 10)]
    assert detour(paths, [box(40, 30, 60, 50)], STOCK) == (paths, 0)
    assert detour(paths, [], STOCK) == (paths, 0)
