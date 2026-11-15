"""A board left in the sheet, right up to the bracket.

Nothing is cut round it, so it needs no room for that and may lie under the
bracket's probe tongue - where the bit must not go. What would be cut there
is left out, the bit is led round, and the run goes ahead only once the
passes, milled out of the sheet on paper, are seen to join no nets.
"""
import pytest
from shapely.geometry import MultiPolygon, box

from gerber2rml.config import TraceJob
from gerber2rml.engine import autorun as ar
from gerber2rml.engine import bracket as br
from gerber2rml.engine.traces import isolate
from gerber2rml.toolpath import Move

B = br.DEFAULT                                   # back-right, the lab's
TONGUE, ARMS = B.keepout(), B.arms()
STOCK = (31.79, 28.43, 191.79, 128.43)           # 160 x 100 in the bracket
ZONES = [(TONGUE, 0.45)] + [(a, 0.5) for a in ARMS]
JOB = TraceJob(bit_diameter=0.8)


def _cut(*pts, z=-0.15, up=2.0):
    return ([Move(pts[0][0], pts[0][1], up, rapid=True)]
            + [Move(x, y, z) for x, y in pts]
            + [Move(pts[-1][0], pts[-1][1], up, rapid=True)])


# -- the geometry -------------------------------------------------------------
def test_a_cut_under_the_tongue_is_found_and_one_beside_it_is_not():
    assert br.path_hit([_cut((170, 126), (180, 126))], TONGUE, 0.45)
    assert br.path_hit([_cut((150, 120), (160, 120))], TONGUE, 0.45) is None


def test_a_hop_over_the_tongue_counts_as_being_there():
    """Over the bracket the question is not how deep the bit is."""
    hop = [_cut((150, 126), (160, 126)), _cut((191, 126), (191.2, 126))]
    assert br.path_hit(hop, TONGUE, 0.45) is not None


def test_the_bars_stand_beside_the_stock():
    (ax0, ay0, ax1, ay1), (bx0, by0, bx1, by1) = ARMS
    assert ay0 == pytest.approx(STOCK[3])         # the X bar starts at its back
    assert bx0 == pytest.approx(STOCK[2])         # the Y bar at its right


def test_a_board_not_cut_out_goes_to_the_far_edges():
    x, y = br.far_place("back-right", (31.79, 28.43, 160, 100),
                        (0, 0, 155.5, 97.0))
    assert (x, y) == pytest.approx((31.79, 28.43))
    x, y = br.far_place("front-left", (31.79, 28.43, 160, 100),
                        (0, 0, 155.5, 97.0))
    assert (x + 155.5, y + 97.0) == pytest.approx((191.79, 128.43))


def test_the_surface_is_not_touched_under_the_tongue():
    area = br.level_area_clear(STOCK, TONGUE, 2.3, 2.0)
    assert area[3] - 2.0 < TONGUE[1] - 2.3 + 1e-3   # the top row is clear
    assert area[:3] == STOCK[:3]
    far = (31.79, 28.43, 150.0, 128.43)             # no touch in its X span
    assert br.level_area_clear(far, TONGUE, 2.3, 2.0) == far


# -- leaving work out ---------------------------------------------------------
def _pour_board(extra=None):
    track = box(100, 60, 130, 70)
    pour = box(32.29, 28.93, 186.79, 124.93).difference(track.buffer(1.0))
    polys, nets = [pour, track], [{"GND"}, {"5V"}]
    if extra is not None:
        polys[0] = pour.difference(extra.buffer(1.0))
        polys.append(extra)
        nets.append({"RESET"})
    copper = MultiPolygon(polys)
    return copper, nets, isolate(copper, JOB, outline=box(*STOCK))


def test_what_is_under_the_bracket_is_left_out_and_gone_round():
    copper, nets, paths = _pour_board()
    assert br.path_hit(paths, TONGUE, 0.45)           # the pour's own edge
    new, uncut = br.avoid(paths, ZONES, STOCK)
    assert uncut > 10
    assert br.path_hit(new, TONGUE, 0.45) is None     # cuts AND hops
    assert all(br.path_hit(new, a, 0.5) is None for a in ARMS)
    for tp in new:                                    # the ways round stay on it
        for m in tp:
            assert STOCK[0] - 1 <= m.x <= STOCK[2] + 1
            assert STOCK[1] - 1 <= m.y <= STOCK[3] + 1


def test_a_pour_edge_left_uncut_joins_no_nets():
    copper, nets, paths = _pour_board()
    new, _uncut = br.avoid(paths, ZONES, STOCK)
    assert br.joined_nets(copper, nets, new, STOCK, 0.4) == []


def test_another_nets_track_left_uncut_is_found_joined():
    copper, nets, paths = _pour_board(extra=box(170, 122.9, 180, 123.7))
    assert br.joined_nets(copper, nets, paths, STOCK, 0.4) == []   # whole: fine
    new, _uncut = br.avoid(paths, ZONES, STOCK)
    assert br.joined_nets(copper, nets, new, STOCK, 0.4) == [["GND", "RESET"]]


def test_without_net_names_every_piece_of_copper_counts_as_its_own():
    copper, _nets, paths = _pour_board(extra=box(170, 122.9, 180, 123.7))
    new, _uncut = br.avoid(paths, ZONES, STOCK)
    assert br.joined_nets(copper, None, new, STOCK, 0.4)


def test_paths_nowhere_near_are_returned_untouched():
    paths = [_cut((60, 60), (80, 60))]
    new, uncut = br.avoid(paths, ZONES, STOCK)
    assert new == paths and uncut == 0.0


# -- the run's own check ------------------------------------------------------
class _Pose:
    x, y, w, h = STOCK[0], STOCK[1], 160.0, 100.0


class _Src:
    def __init__(self, jobs, copper, nets, extent):
        self.jobs, self.copper, self.nets, self._extent = \
            jobs, copper, nets, extent

    def extent(self, side):
        return self._extent

    def bottom_steps(self):
        return [(k, k.replace("_", " ").title()) for k in self.jobs]

    def toolpaths(self, key):
        return self.jobs[key], 100, 50

    def copper_nets(self, side="bottom", fitted=True):
        return self.copper, self.nets


class _Ev:
    def __init__(self):
        self.notes = []

    def note(self, text):
        self.notes.append(text)


def _run(src, leave_under):
    run = ar.AutoRun(None, None, src, _Ev(), click_mm=None,
                     stock_mm=(160, 100), double=False, bit_mm=0.8,
                     keepout=TONGUE, arms=ARMS, leave_under=leave_under,
                     margin_mm=0.0)
    run.pose = _Pose()
    return run


FULL = (32.29, 28.93, 186.79, 124.93)             # reaches under the tongue


def test_cut_out_as_usual_a_job_under_the_tongue_stops_the_run():
    copper, nets, paths = _pour_board()
    run = _run(_Src({"traces_run": paths}, copper, nets, FULL), False)
    with pytest.raises(ar.RunFailed, match="probe tongue"):
        run._check_keepout("bottom")


def test_left_in_the_sheet_a_pour_edge_under_the_tongue_is_let_through():
    copper, nets, paths = _pour_board()
    run = _run(_Src({"traces_run": paths}, copper, nets, FULL), True)
    run._check_keepout("bottom")                  # does not raise
    assert any("left uncut" in n and "joins no nets" in n
               for n in run.ev.notes)


def test_left_in_the_sheet_two_nets_joined_stops_the_run():
    copper, nets, paths = _pour_board(extra=box(170, 122.9, 180, 123.7))
    run = _run(_Src({"traces_run": paths}, copper, nets, FULL), True)
    with pytest.raises(ar.RunFailed, match="GND \\+ RESET"):
        run._check_keepout("bottom")


def test_a_hole_under_the_tongue_stops_the_run_either_way():
    copper, nets, paths = _pour_board()
    hole = [[Move(175, 126, 2, rapid=True), Move(175, 126, -1.9),
             Move(175, 126, 2, rapid=True)]]
    for leave in (False, True):
        src = _Src({"traces_run": paths if leave else [], "drill_run": hole},
                   copper, nets, FULL)
        with pytest.raises(ar.RunFailed, match="probe tongue"):
            _run(src, leave)._check_keepout("bottom")


def test_a_cut_off_the_stock_into_a_bar_stops_the_run():
    off = [_cut((191.6, 60), (191.6, 80))]        # 0.19 mm from the bar
    src = _Src({"drill_run": off}, MultiPolygon([box(0, 0, 1, 1),
                                                 box(3, 3, 4, 4)]),
               None, FULL)
    with pytest.raises(ar.RunFailed, match="into the bracket"):
        _run(src, True)._check_keepout("bottom")


def test_shorts_the_design_already_has_are_not_blamed_on_leaving_out():
    """Two nets closer than the bit are joined whatever is left out: that
    is the checks' finding, not a reason to refuse this."""
    a, b2 = box(60, 60, 70, 61), box(60, 61.5, 70, 62.5)      # 0.5 mm apart
    track = box(100, 60, 130, 70)
    pour = (box(32.29, 28.93, 186.79, 124.93)
            .difference(track.buffer(1.0))
            .difference(box(58, 58, 72, 64.5)))
    copper = MultiPolygon([pour, track, a, b2])
    nets = [{"GND"}, {"5V"}, {"A"}, {"B"}]
    paths = isolate(copper, JOB, outline=box(*STOCK))
    assert br.joined_nets(copper, nets, paths, STOCK, 0.4) == [["A", "B"]]
    run = _run(_Src({"traces_run": paths}, copper, nets, FULL), True)
    run._check_keepout("bottom")                  # the pour's edge: let through
    assert any("joins no nets" in n for n in run.ev.notes)


# -- both faces ---------------------------------------------------------------
def test_a_way_round_misses_every_part_of_the_bracket_not_just_one():
    """From beside the tongue to below the end of a bar: the dog-leg that
    clears the tongue must not then cross the bar."""
    paths = [_cut((100, 127.3), (140.2, 127.3)), _cut((191.69, 76.8),
                                                      (191.69, 40))]
    new, _uncut = br.avoid(paths, ZONES, STOCK)
    assert br.path_hit(new, TONGUE, 0.45) is None
    assert all(br.path_hit(new, a, 0.5) is None for a in ARMS)


def test_a_double_sided_board_is_centred_across_the_sheet():
    """Turned over left to right it lands mirrored: room on one side this
    way up is room on the other side then."""
    x, y = br.far_place("back-right", (31.79, 28.43, 160, 100),
                        (0, 0, 150, 90), flipped=True)
    assert x == pytest.approx(31.79 + 5.0) and y == pytest.approx(28.43)


class _Src2(_Src):
    """Two faces: reference holes, and a top side with its own job."""

    def __init__(self, bottom_fids, top_paths, top_copper, top_nets, **kw):
        super().__init__(**kw)
        self.bottom_fids, self.top_paths = bottom_fids, top_paths
        self.top_copper, self.top_nets = top_copper, top_nets

    def fiducials(self):
        # The layout's top frame: reflected about the board's own middle,
        # which for a board that fills the stock is the stock's.
        mid = STOCK[0] + STOCK[2]
        return self.bottom_fids, [(mid - x, y) for x, y in self.bottom_fids]

    def top_steps(self):
        return [("top_traces_run", "Top traces")]

    def nominal_top(self, key):
        return self.top_paths

    def copper_nets(self, side="bottom", fitted=True):
        if side == "top":
            return self.top_copper, self.top_nets
        return self.copper, self.nets


def _run2(src):
    run = ar.AutoRun(None, None, src, _Ev(), click_mm=None,
                     stock_mm=(160, 100), double=True, bit_mm=0.8,
                     keepout=TONGUE, arms=ARMS, leave_under=True,
                     margin_mm=0.0)
    run.pose = _Pose()
    return run


CORNER_HOLES = [(36.79, 33.43), (186.79, 33.43), (36.79, 123.43),
                (150.0, 110.0)]        # the back-right one moved in


def _two_faced(top_paths, top_copper=None, top_nets=None, holes=CORNER_HOLES):
    copper, nets, paths = _pour_board()
    return _Src2(holes, top_paths,
                 top_copper or MultiPolygon([box(40, 40, 41, 41),
                                             box(50, 50, 51, 51)]),
                 top_nets, jobs={"traces_run": paths}, copper=copper,
                 nets=nets, extent=FULL)


def test_a_top_with_nothing_near_the_bracket_is_let_through():
    run = _run2(_two_faced([_cut((60, 60), (90, 60))]))
    run._check_flipped()


def test_a_hole_that_lands_under_the_bracket_is_left_out_of_the_fit():
    """The back-left hole comes round to the back-right, under the tongue.
    Three others can still be reached, and three is what a fit takes."""
    run = _run2(_two_faced([_cut((60, 60), (90, 60))]))
    run._check_flipped()
    assert any("will not be used" in n for n in run.ev.notes)
    assert run._hole_blocked(186.79, 123.43)           # where it lands
    assert not run._hole_blocked(100.0, 60.0)


def test_too_few_holes_left_to_reach_stops_it_before_anything_is_cut():
    holes = [(36.79, 123.43), (60.0, 123.43), (186.79, 33.43)]
    run = _run2(_two_faced([_cut((60, 60), (90, 60))], holes=holes))
    with pytest.raises(ar.RunFailed, match="reference holes"):
        run._check_flipped()


def test_top_isolation_under_the_tongue_once_flipped_is_proved_or_refused():
    # This board fills the stock, so its top frame is already where the
    # flip puts it: the tongue is at the back-right there too.
    a = box(170, 121.0, 180, 121.8)                    # its ring goes under
    b2 = box(100, 60, 120, 70)
    for nets, ok in (([{"A"}, {"B"}], True), (None, True)):
        copper = MultiPolygon([a, b2])
        paths = isolate(copper, JOB, outline=box(*STOCK))
        run = _run2(_two_faced(paths, copper, nets))
        run._check_flipped()                           # one net there: fine
        assert any("Once flipped" in n and "joins no nets" in n
                   for n in run.ev.notes)
    # ...but two nets right under it, both their rings cut open there, are
    # joined through the sheet's own copper:
    a2 = box(168, 124.0, 172, 124.8)
    c = box(176, 124.0, 180, 124.8)
    copper = MultiPolygon([a2, b2, c])
    paths = isolate(copper, JOB, outline=box(*STOCK))
    run = _run2(_two_faced(paths, copper, [{"A"}, {"B"}, {"C"}]))
    with pytest.raises(ar.RunFailed, match="once the board is flipped"):
        run._check_flipped()


# -- a clamp is treated as the tongue is ---------------------------------------
#
# A board left in the sheet runs to the sheet's edge, and so do the clamps
# that hold it. A poured board has an isolation pass all the way round, a
# tenth of a millimetre inside its edge (a poured 160 x 100 board on the lab mill,
# 2026-11-15: three clamps, three "work lies in a no-go zone").

CLAMP = (100.0, 26.0, 112.0, 33.0)            # on the pour's front edge
TRACK_CLAMP = (110.0, 68.0, 120.0, 74.0)      # across the 5V track's edge


def _run_clamped(src, leave_under, nogo):
    run = ar.AutoRun(None, None, src, _Ev(), click_mm=None,
                     stock_mm=(160, 100), double=False, bit_mm=0.8,
                     keepout=TONGUE, arms=ARMS, leave_under=leave_under,
                     margin_mm=0.0, nogo=nogo)
    run.pose = _Pose()
    return run


def test_left_in_the_sheet_a_pour_edge_under_a_clamp_is_left_uncut():
    copper, nets, paths = _pour_board()
    run = _run_clamped(_Src({"traces_run": paths}, copper, nets, FULL), True,
                       [CLAMP])
    run._check_keepout("bottom")                  # proves it, does not raise
    run._check_nogo("bottom")                     # and what is left is clear
    assert any("left uncut" in n and "no-go zone" in n for n in run.ev.notes)
    kept, uncut = run._leave_out("traces_run", paths)
    assert uncut > 10.0                           # the clamp is 12 mm wide
    assert br.path_hit(kept, CLAMP, run._nogo_grow()) is None


def test_cut_out_as_usual_a_pour_edge_under_a_clamp_stops_the_run():
    """Nothing is left out of a board that is cut out: it is refused."""
    copper, nets, paths = _pour_board()
    run = _run_clamped(_Src({"traces_run": paths}, copper, nets, FULL), False,
                       [CLAMP])
    with pytest.raises(ar.RunFailed, match="no-go zone"):
        run._check_nogo("bottom")


def test_left_in_the_sheet_a_clamp_that_would_join_two_nets_stops_the_run():
    """The clamp sits on the gap between the 5V track and the pour: left
    uncut there, they are one piece of copper."""
    copper, nets, paths = _pour_board()
    run = _run_clamped(_Src({"traces_run": paths}, copper, nets, FULL), True,
                       [TRACK_CLAMP])
    with pytest.raises(ar.RunFailed, match="5V"):
        run._check_keepout("bottom")


def test_a_hole_under_a_clamp_stops_the_run_even_left_in_the_sheet():
    copper, nets, paths = _pour_board()
    hole = [_cut((105.0, 30.0), (105.2, 30.0), z=-1.9)]
    run = _run_clamped(_Src({"traces_run": paths, "drill_run": hole},
                            copper, nets, FULL), True, [CLAMP])
    run._check_keepout("bottom")
    with pytest.raises(ar.RunFailed, match="Drill Run would take the bit"):
        run._check_nogo("bottom")
