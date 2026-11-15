"""No-go zones in the automatic run, against the simulated machine.

A clamp the run does not know about is a clamp the bit finds: on 2026-11-15
the surface probe came down on one, and went through another on its way from
touch to touch. A zone is a box drawn round such a thing. These tests are
what "the bit stays out" has to mean: no touch in one, no low move across
one, no job that enters one - and each refusal before anything is cut.
"""
import pytest

from gerber2rml.engine import simmachine as sm
from gerber2rml.engine import spi_probe, stockfind
from gerber2rml.engine.autorun import NOGO_CLEAR_MM, AutoRun, RunFailed
from tests.test_autorun import FAST, Board, Log

CORNER = (41.3, 27.8)                    # the stock's front-left, machine mm
DATUM = CORNER + ("front-left",)


def _run(board=None, **kw):
    """A 100 x 80 stock square in a front-left bracket, the board 3 mm in:
    its outline X 44.3-84.3, Y 30.8-60.8; surface touches at X 46.3, 58.3,
    70.3, 82.3 and Y 32.8, 45.8, 58.8."""
    m = sm.machine(speedup=1e6, corner=(41300, 27800), angle_deg=0.0,
                   size=(100000, 80000))
    ser = spi_probe.open_link("SIM")
    board, log = board or Board(False), Log()
    log.notes = []
    log.note = log.notes.append
    run = AutoRun(ser, sm.printer(), board, log, click_mm=(90, 70),
                  stock_mm=(100, 80), double=False, runner_opts=FAST,
                  datum=DATUM, **kw)
    return m, ser, board, log, run


@pytest.fixture
def moves(monkeypatch):
    """Every surface touch and every over-the-top travel the run makes."""
    seen = {"touch": [], "over": [], "ref": [], "legs": []}
    real_cmd, real_travel, real_ref = (stockfind._cmd, stockfind.travel,
                                       stockfind.reference_at)
    real_lead = AutoRun._lead

    def lead(self, a, way):
        pts = [tuple(a)] + [tuple(p) for p in way]
        seen["legs"] += list(zip(pts, pts[1:]))
        return real_lead(self, a, way)

    monkeypatch.setattr(AutoRun, "_lead", lead)

    def cmd(ser, line, *a, **k):
        if line.startswith("P ") and not line.startswith("P 900"):
            _p, _i, dx, dy = line.split()
            fx, fy = seen["ref"][-1]
            seen["touch"].append((fx + int(dx) / 1000.0,
                                  fy + int(dy) / 1000.0))
        return real_cmd(ser, line, *a, **k)

    def travel(ser, x_um, y_um, should_abort=None, surface_um=None):
        if surface_um is None:
            seen["over"].append((x_um / 1000.0, y_um / 1000.0))
        return real_travel(ser, x_um, y_um, should_abort, surface_um)

    def ref(ser, x_um, y_um, *a, **k):
        seen["ref"].append((x_um / 1000.0, y_um / 1000.0))
        return real_ref(ser, x_um, y_um, *a, **k)

    monkeypatch.setattr(stockfind, "_cmd", cmd)
    monkeypatch.setattr(stockfind, "travel", travel)
    monkeypatch.setattr(stockfind, "reference_at", ref)
    return seen


# A clamp on the board's back edge, over the touch at (58.3, 58.8) and clear
# of every cut: the cut-out runs at Y 60.8, the holes at Y 45.8.
CLAMP = (57.3, 56.5, 59.3, 57.9)


def _grown(rect, bit=0.8):
    g = bit / 2.0 + NOGO_CLEAR_MM
    return rect[0] - g, rect[1] - g, rect[2] + g, rect[3] + g


def _inside(p, rect):
    return rect[0] <= p[0] <= rect[2] and rect[1] <= p[1] <= rect[3]


def test_without_zones_every_surface_point_is_touched(moves):
    m, ser, board, log, run = _run()
    assert run.run() is True
    assert len(set(moves["touch"])) == 12


def test_a_surface_touch_in_a_zone_is_moved_to_a_free_spot(moves):
    """Not dropped: moved. The grid point at (58.3, 58.8) is under the
    clamp; it is touched a few millimetres away instead, off the clamp and
    still on the board, and the map keeps its whole grid."""
    m, ser, board, log, run = _run(nogo=[CLAMP])
    rows = []
    log.level = lambda side, r, nx, ny: rows.extend(r)
    assert run.run() is True
    zone = _grown(CLAMP)
    touched = set(moves["touch"])
    assert len(touched) == 12
    assert not any(_inside(p, zone) for p in touched)
    assert (58.3, 58.8) not in {(round(x, 1), round(y, 1)) for x, y in touched}
    # Inside the grid's own extent: on the board, inside the margin.
    assert all(46.3 - 1e-6 <= x <= 82.3 + 1e-6 and 32.8 - 1e-6 <= y <= 58.8 + 1e-6
               for x, y in touched)
    # The height is entered at the grid point all the same.
    assert len(rows) == 12
    assert (58.3, 58.8) in {(round(x, 1), round(y, 1)) for x, y, _z in rows}
    assert any("moved off a no-go zone" in n for n in log.notes)


def test_a_touch_with_no_free_spot_near_is_not_made(moves):
    """A zone 20 mm wide all round a grid point: nowhere within reach."""
    board = Board(False)
    board.bottom_steps = lambda: []
    big = (58.3 - 20, 45.8 - 20, 58.3 + 20, 45.8 + 20)
    m, ser, board, log, run = _run(board, nogo=[big], level=True)
    # That zone also covers the bracket's own touch at (56.3, 42.8); the
    # stock is found first, so the refusal comes from there.
    with pytest.raises(RunFailed, match="touched to find its height"):
        run.run()


def test_a_move_between_touches_goes_round_a_zone_not_through_it(moves):
    """(46.3, 58.8) to (70.3, 58.8) is a straight line through the clamp.
    The head is led round it at the height it is at - not over the top."""
    m, ser, board, log, run = _run(nogo=[CLAMP])
    assert run.run() is True
    # The one trip at the top is the stock finder's own, to its first
    # touch at (56.3, 42.8), as it has always been.
    assert moves["over"] == [(56.3, 42.8)]
    assert not any("No way round" in n for n in log.notes)
    assert any("Going round" in n for n in log.notes)
    zone = _grown(CLAMP)
    legs = [seg for seg in moves["legs"]]
    assert legs, "no led move was made"
    from shapely.geometry import LineString, box
    for a, b in legs:
        assert not LineString([a, b]).intersects(box(*zone)), (a, b)


def test_zones_that_wall_the_stock_off_are_crossed_at_the_top(moves):
    """A bar from the front of the stock to the back, between two columns
    of touches: there is no way round on the stock, so over it is."""
    board = Board(False)
    board.bottom_steps = lambda: []
    m, ser, board, log, run = _run(board, nogo=[(63.5, 20.0, 65.0, 115.0)])
    assert run.run() is True
    assert len(moves["over"]) > 1
    assert any("No way round" in n for n in log.notes)


def test_the_margin_moves_the_touches_in_from_the_edge(moves):
    m, ser, board, log, run = _run(level_margin=8.0)
    assert run.run() is True
    xs = sorted({round(x, 1) for x, _y in moves["touch"]})
    ys = sorted({round(y, 1) for _x, y in moves["touch"]})
    assert (xs[0], xs[-1]) == (52.3, 76.3)       # 44.3 + 8 and 84.3 - 8
    assert (ys[0], ys[-1]) == (38.8, 52.8)


def test_a_margin_bigger_than_the_board_is_said_not_guessed():
    m, ser, board, log, run = _run(level_margin=16.0)   # the board is 30 deep
    with pytest.raises(RunFailed, match="smaller margin"):
        run.run()


def test_a_job_that_enters_a_zone_is_refused_before_anything_is_cut():
    """The trace runs along Y 40.8 from X 54.3 to 74.3."""
    m, ser, board, log, run = _run(nogo=[(60.0, 39.0, 64.0, 42.0)])
    sent = []
    log.job = lambda key, label, prog: sent.append(key)
    with pytest.raises(RunFailed, match="no-go zone"):
        run.run()
    assert sent == []
    assert ("level", "done") not in log.steps


def test_a_zone_near_a_cut_counts_by_the_clearance_not_the_drawn_box():
    """Drawn 1.5 mm off the trace: inside the 2 mm kept for a box by eye."""
    m, ser, board, log, run = _run(nogo=[(60.0, 42.3 + 0.4, 64.0, 45.0)])
    with pytest.raises(RunFailed, match="no-go zone"):
        run.run()


def test_zones_over_most_of_the_board_leave_no_surface_to_measure(
        monkeypatch):
    """The back row and the right half of the other two are under zones,
    and - with the reach cut to nothing - none of the eight can be moved."""
    from gerber2rml.engine import autorun as ar_mod
    monkeypatch.setattr(ar_mod, "LEVEL_MOVE_MM", 0.5)
    board = Board(False)
    board.bottom_steps = lambda: []          # nothing to cut: only the probe
    m, ser, board, log, run = _run(board, nogo=[(40.0, 50.0, 90.0, 65.0),
                                                (64.0, 28.0, 90.0, 48.0)])
    with pytest.raises(RunFailed, match="too few"):
        run.run()


def test_the_spot_where_the_copper_is_touched_must_be_free():
    """The bracket touch is 15 mm in from its corner: (56.3, 42.8)."""
    m, ser, board, log, run = _run(nogo=[(55.0, 41.0, 58.0, 44.0)])
    with pytest.raises(RunFailed, match="touched to find its height"):
        run.run()
    assert ("stock", "done") not in log.steps


def test_zones_need_the_bracket():
    m = sm.machine(speedup=1e6, corner=(41300, 27800), angle_deg=1.2,
                   size=(100000, 80000))
    ser = spi_probe.open_link("SIM")
    run = AutoRun(ser, sm.printer(), Board(False), Log(), click_mm=(90, 70),
                  stock_mm=(100, 80), double=False, runner_opts=FAST,
                  nogo=[CLAMP])
    with pytest.raises(RunFailed, match="corner bracket"):
        run.run()


# --- a board left in the sheet may hang off it --------------------------------

class Wide(Board):
    """A board whose outline starts ``hang`` mm left of the stock's edge.
    Its work begins 10 mm in from its own edge; nothing is cut out."""

    def __init__(self, hang):
        super().__init__(False)
        self.hang = hang

    def place(self, pose, margin_mm):
        self.off = (pose.x - self.hang, pose.y + 3.0)

    def bottom_steps(self):
        return [("drill", "Drilling"), ("traces", "Traces")]

    def extent(self, side):
        return self.area(side)


def test_left_in_the_sheet_only_the_work_has_to_be_on_the_copper(moves):
    m, ser, board, log, run = _run(Wide(8.0), leave_under=True,
                                   margin_mm=0.0)
    assert run.run() is True
    # Nothing was probed off the sheet either.
    assert moves["touch"] and all(p[0] >= CORNER[0] for p in moves["touch"])


def test_left_in_the_sheet_a_trace_off_the_copper_is_still_refused():
    m, ser, board, log, run = _run(Wide(12.0), leave_under=True,
                                   margin_mm=0.0)
    with pytest.raises(RunFailed, match="hangs off the stock"):
        run.run()


def test_cut_out_the_outline_still_has_to_be_on_the_copper():
    board = Wide(8.0)
    m, ser, board, log, run = _run(board, margin_mm=0.0)
    with pytest.raises(RunFailed, match="hangs off the stock"):
        run.run()


# --- the flip: clamps come off and go back somewhere else ---------------------

def _double(**kw):
    m = sm.machine(speedup=1e6, corner=(41300, 27800), angle_deg=0.0,
                   size=(100000, 80000))
    ser = spi_probe.open_link("SIM")
    board, log = Board(True), Log()
    log.notes = []
    log.note = log.notes.append
    run = AutoRun(ser, sm.printer(), board, log, click_mm=(90, 70),
                  stock_mm=(100, 80), double=True, runner_opts=FAST,
                  datum=DATUM, **kw)
    return m, ser, board, log, run


def test_zones_redrawn_at_the_flip_are_the_ones_the_top_side_obeys():
    """The bottom runs with no zones. At the flip a clamp is put across the
    top side's trace and its zone drawn: the top side is refused, and the
    bottom, already cut, was not."""
    m, ser, board, log, run = _double()
    log.flip = lambda: (m.flip(), True)[1]
    log.nogo = lambda: [(20.0, 20.0, 130.0, 100.0)]     # all over the board
    with pytest.raises(RunFailed, match="no-go zone"):
        run.run()
    assert ("traces", "done") in log.steps              # the bottom was cut
    assert ("top_traces", "done") not in log.steps
    assert any("changed at the flip" in n for n in log.notes)


def test_zones_cleared_at_the_flip_no_longer_stop_the_top_side():
    m, ser, board, log, run = _double(nogo=[(120.0, 90.0, 130.0, 100.0)])
    log.flip = lambda: (m.flip(), True)[1]
    log.nogo = lambda: []
    assert run.run() is True
    assert run.nogo == []


def test_with_nothing_said_at_the_flip_the_zones_stay():
    m, ser, board, log, run = _double(nogo=[(120.0, 90.0, 130.0, 100.0)])
    log.flip = lambda: (m.flip(), True)[1]
    assert run.run() is True
    assert run.nogo == [(120.0, 90.0, 130.0, 100.0)]
    assert not any("changed at the flip" in n for n in log.notes)


# --- where the touches go: plain geometry -------------------------------------

def test_the_grid_follows_the_margin_and_the_stock():
    from gerber2rml.engine.autorun import level_grid
    pts, area = level_grid((0, 0, 100, 60), 5.0)
    assert len(pts) == 12
    assert (pts[0], pts[-1]) == ((5.0, 5.0), (95.0, 55.0))
    # Left in the sheet, hanging 10 mm off its left edge.
    pts, area = level_grid((-10, 0, 90, 60), 5.0, stock=(0, 0, 200, 100))
    assert area[0] == 0 and pts[0] == (5.0, 5.0)
    assert level_grid((0, 0, 20, 60), 12.0)[0] == []


def test_points_clear_of_every_zone_stay_where_they_are():
    from shapely.geometry import box
    from gerber2rml.engine.autorun import level_grid, level_targets
    pts, _a = level_grid((0, 0, 100, 60), 5.0)
    assert level_targets(pts, []) == pts
    assert level_targets(pts, [box(200, 200, 210, 210)]) == pts


def test_a_point_in_a_zone_moves_the_shortest_way_out_towards_the_middle():
    from shapely.geometry import Point, box
    from gerber2rml.engine.autorun import level_grid, level_targets
    pts, _a = level_grid((0, 0, 100, 60), 5.0)       # corner touch at (5, 5)
    zone = box(0, 0, 9, 8)                           # a clamp on that corner
    out = level_targets(pts, [zone])
    assert out[1:] == pts[1:]
    x, y = out[0]
    assert not zone.intersects(Point(x, y))
    assert 5.0 <= x <= 95.0 and 5.0 <= y <= 55.0     # still inside the grid
    assert ((x - 5) ** 2 + (y - 5) ** 2) ** 0.5 <= 6.0


def test_a_point_with_nowhere_to_go_is_given_up():
    from shapely.geometry import box
    from gerber2rml.engine.autorun import level_grid, level_targets
    pts, _a = level_grid((0, 0, 100, 60), 5.0)
    out = level_targets(pts, [box(-20, -20, 40, 40)])
    assert out[0] is None and out[-1] == pts[-1]


# --- travel between cuts goes round a clamp -----------------------------------

def test_a_drill_job_whose_hop_crosses_a_clamp_is_run_not_refused():
    """The two holes are at (59.3, 45.8) and (69.3, 45.8); a clamp stands
    on the line between them. Both are drilled, and no move of the job that
    was sent enters the zone."""
    from gerber2rml.engine.bracket import path_hit
    clamp = (63.8, 44.8, 64.8, 46.8)
    board = Board(False)
    board.bottom_steps = lambda: [("drill", "Drilling")]
    m, ser, board, log, run = _run(board, nogo=[clamp], level=False)
    real = run._nogo_paths
    seen = []

    def spy(paths, label):
        seen.append(paths)
        return real(paths, label)

    run._nogo_paths = spy
    assert run.run() is True
    assert ("drill", "done") in log.steps
    assert seen and all(path_hit(p, clamp, run._nogo_grow()) is None
                        for p in seen)
