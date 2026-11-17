"""A cut-out that runs into the bracket's bar stops short and leaves a tab."""
from gerber2rml.engine.bracket import path_hit, tabs
from gerber2rml.toolpath import Move

BIT = 0.8
BAR = (150.0, 128.43, 200.0, 138.43)        # the back bar; the stock below it
GROW = BIT / 2.0 + 0.1


def side_cut():
    """The right-hand side of a board spanning the stock in Y: two passes,
    front edge to back edge and back again, at their own depths."""
    return [[Move(179.0, 28.0, 2.0, rapid=True),
             Move(179.0, 28.0, -1.0),
             Move(179.0, 128.43, -1.0),
             Move(179.0, 128.43, -2.0),
             Move(179.0, 28.0, -2.0),
             Move(179.0, 28.0, 2.0, rapid=True)]]


def test_the_untouched_cut_hits_the_bar():
    assert path_hit(side_cut(), BAR, GROW) is not None


def test_tabs_keep_the_bit_off_the_bar_and_both_depths():
    out, n = tabs(side_cut(), [(BAR, GROW)])
    assert n == 1
    assert path_hit(out, BAR, GROW) is None
    cuts = [m for tp in out for m in tp if not m.rapid]
    assert {m.z for m in cuts} == {-1.0, -2.0}
    top = max(m.y for m in cuts)
    assert 128.43 - GROW - 0.1 < top < 128.43 - GROW
    # Both passes still run the rest of the side.
    assert sum(1 for m in cuts if abs(m.y - 28.0) < 1e-6) >= 2


def test_a_cut_clear_of_the_bar_is_left_alone():
    paths = [[Move(179.0, 28.0, 2.0, rapid=True), Move(179.0, 28.0, -1.0),
              Move(179.0, 100.0, -1.0), Move(179.0, 100.0, 2.0, rapid=True)]]
    out, n = tabs(paths, [(BAR, GROW)])
    assert n == 0 and out == paths


def test_travel_goes_high_once_a_cut_is_stopped_short():
    from gerber2rml.engine.bracket import TAB_HOP_LIFT_MM
    from gerber2rml.engine.leadin import FAST_APPROACH, fast_approach
    out, n = tabs(side_cut(), [(BAR, GROW)], inside=(100, 28, 200, 128.43))
    assert n == 1
    rapids = [m for tp in out for m in tp if m.rapid]
    assert rapids and all(m.z >= TAB_HOP_LIFT_MM for m in rapids)
    # The drop to the copper is still a rapid, only the last bit fed.
    fed = fast_approach(out)
    for tp in fed:
        for a, b in zip(tp, tp[1:]):
            if not b.rapid and b.z < 0 and (a.x, a.y) == (b.x, b.y):
                assert a.z <= FAST_APPROACH + 1e-9


def test_no_tab_no_lift():
    paths = [[Move(179.0, 28.0, 2.0, rapid=True), Move(179.0, 28.0, -1.0),
              Move(179.0, 100.0, -1.0), Move(179.0, 100.0, 2.0, rapid=True)]]
    out, n = tabs(paths, [(BAR, GROW)])
    assert n == 0 and max(m.z for tp in out for m in tp) == 2.0
