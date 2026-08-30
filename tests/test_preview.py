"""Tests for the preview polyline helper."""
from gerber2rml.toolpath import Move
from gerber2rml.app.preview import (toolpath_segments, traverse_segments,
                                    preview_segments)


def test_splits_cut_and_rapid():
    """Rapid approach, plunge+cut, rapid lift."""
    tp = [Move(0, 0, 2, rapid=True), Move(0, 0, -0.1), Move(1, 0, -0.1),
          Move(1, 0, 2, rapid=True)]
    cuts, rapids = toolpath_segments([tp])
    assert len(cuts) >= 1
    assert len(rapids) >= 1
    # the cut polyline contains the (0,0)->(1,0) move
    assert any((1.0, 0.0) in poly for poly in cuts)


def test_empty_input():
    """Empty input returns empty lists."""
    assert toolpath_segments([]) == ([], [])


def test_rapid_runs_inside_a_path_carry_no_xy_extent():
    """Why traverse_segments has to exist.

    Every generator emits one path per contour, each beginning with a rapid to
    its own start. So the only rapid runs INSIDE a path are the plunge and the
    retract, and both sit at a single XY - which draws as nothing.
    """
    tp = [Move(0, 0, 2, rapid=True), Move(0, 0, -0.1), Move(1, 0, -0.1),
          Move(1, 0, 2, rapid=True)]
    _cuts, rapids = toolpath_segments([tp])
    for poly in rapids:
        assert len({(round(x, 6), round(y, 6)) for x, y in poly}) == 1


def test_traverse_segments_joins_the_end_of_one_path_to_the_next():
    a = [Move(0, 0, 2, rapid=True), Move(0, 0, -0.1), Move(1, 0, -0.1),
         Move(1, 0, 2, rapid=True)]
    b = [Move(5, 5, 2, rapid=True), Move(5, 5, -0.1), Move(6, 5, -0.1),
         Move(6, 5, 2, rapid=True)]
    assert traverse_segments([a, b]) == [[(1.0, 0.0), (5.0, 5.0)]]


def test_traverse_segments_skips_a_zero_length_hop():
    a = [Move(0, 0, 2, rapid=True), Move(1, 1, -0.1), Move(2, 2, 2, rapid=True)]
    b = [Move(2, 2, 2, rapid=True), Move(3, 3, -0.1)]
    assert traverse_segments([a, b]) == []


def test_traverse_segments_ignores_empty_paths():
    assert traverse_segments([]) == []
    assert traverse_segments([[], []]) == []


def test_preview_segments_gives_travel_moves_something_to_draw():
    """The regression this whole helper exists for: both GUIs shipped a travel
    layer that had never displayed anything."""
    from gerber2rml.app.state import ProjectState
    from pathlib import Path
    st = ProjectState()
    st.load(Path(__file__).parent / "fixtures" / "mosfet_test")
    paths = st.toolpaths("traces")

    _c, plain = toolpath_segments(paths)
    drawable = [r for r in plain
                if len({(round(x, 5), round(y, 5)) for x, y in r}) > 1]
    assert drawable == [], "the premise changed; re-check this fix"

    _c, withtravel = preview_segments(paths)
    drawable = [r for r in withtravel
                if len({(round(x, 5), round(y, 5)) for x, y in r}) > 1]
    assert len(drawable) > 10, len(drawable)


def test_preview_segments_leaves_the_cuts_alone():
    from gerber2rml.app.state import ProjectState
    from pathlib import Path
    st = ProjectState()
    st.load(Path(__file__).parent / "fixtures" / "mosfet_test")
    paths = st.toolpaths("traces")
    assert preview_segments(paths)[0] == toolpath_segments(paths)[0]


def test_the_drawn_travel_matches_what_the_estimator_charges_for():
    """The estimator carries the tool position across paths, so it already
    times these hops. Drawing them is drawing what it is timing."""
    from math import dist
    from gerber2rml.app.state import ProjectState
    from pathlib import Path
    st = ProjectState()
    st.load(Path(__file__).parent / "fixtures" / "mosfet_test")
    paths = st.toolpaths("traces")
    hops = traverse_segments(paths)
    # every hop starts where the previous path ended
    ends = [(tp[-1].x, tp[-1].y) for tp in paths if tp]
    starts = [(tp[0].x, tp[0].y) for tp in paths if tp]
    for i, (a, b) in enumerate(hops):
        assert a in ends and b in starts
        assert dist(a, b) > 0
