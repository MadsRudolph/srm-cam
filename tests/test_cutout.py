"""Cutout engine tests (TDD — Task 7)."""
import pytest
from shapely.geometry import box
from gerber2rml.config import CutoutJob
from gerber2rml.engine.cutout import cut_outline


def test_cutout_passes_reach_total_depth():
    outline = box(0, 0, 20, 20)
    job = CutoutJob(cut_depth=0.6, total_depth=1.8, tabs=0)
    paths = cut_outline(outline, job)
    deepest = min(m.z for tp in paths for m in tp if not m.rapid)
    assert deepest <= -1.8


def test_outline_is_offset_outward():
    outline = box(0, 0, 20, 20)
    job = CutoutJob(bit_diameter=0.8, tabs=0, cut_depth=0.6, total_depth=0.6)
    paths = cut_outline(outline, job)
    xs = [m.x for tp in paths for m in tp if not m.rapid]
    assert min(xs) < 0          # cut path rides outside the board edge


def test_tabs_create_gaps():
    outline = box(0, 0, 20, 20)
    job = CutoutJob(tabs=4, tab_width=1.5, cut_depth=0.6, total_depth=0.6)
    paths_with = cut_outline(outline, job)
    paths_without = cut_outline(outline, CutoutJob(tabs=0, cut_depth=0.6, total_depth=0.6))
    n_with = sum(len(tp) for tp in paths_with)
    n_without = sum(len(tp) for tp in paths_without)
    assert n_with > n_without   # tabs split the ring into more, shorter paths


def test_overlapping_tabs_raises():
    outline = box(0, 0, 20, 20)
    # 4 tabs of 30mm each on an ~82mm ring => tabs*width > ring length
    job = CutoutJob(tabs=4, tab_width=30.0, cut_depth=0.6, total_depth=0.6)
    with pytest.raises(ValueError):
        cut_outline(outline, job)

def test_tabs_zero_gives_single_path_per_pass():
    outline = box(0, 0, 20, 20)
    job = CutoutJob(tabs=0, cut_depth=0.6, total_depth=0.6)
    assert len(cut_outline(outline, job)) == 1


def _tabs(outline, job, stock=None):
    """The uncut gaps along the cut ring, as (x, y) centres."""
    from shapely.geometry import LineString
    from shapely.ops import unary_union
    deepest = -job.cut_depth
    cuts = []
    for tp in cut_outline(outline, job, stock):
        pts = [(m.x, m.y) for m in tp if not m.rapid and m.z == deepest]
        if len(pts) > 1:
            cuts.append(LineString(pts))
    ring = LineString(outline.buffer(job.bit_diameter / 2).exterior.coords)
    # A cut follows the ring in short chords, so it strays a little off it.
    gaps = ring.difference(unary_union(cuts).buffer(0.03))
    pieces = list(getattr(gaps, "geoms", [gaps]))
    return [g.centroid.coords[0] for g in pieces if g.length > 1.0]


JOB = dict(bit_diameter=0.8, tab_width=1.5, cut_depth=0.6, total_depth=0.6)


def test_tabs_go_on_the_long_sides_of_a_long_board():
    outline = box(0, 0, 40, 20)
    tabs = _tabs(outline, CutoutJob(tabs=4, **JOB))
    assert len(tabs) == 4
    for x, y in tabs:
        assert y < 0 or y > 20              # on a long side, front or back
        assert 3.0 < x < 37.0               # and well away from the corners
    assert sum(y < 0 for _x, y in tabs) == 2


def test_a_square_board_has_a_tab_on_each_side_and_none_in_a_corner():
    outline = box(0, 0, 30, 30)
    tabs = _tabs(outline, CutoutJob(tabs=4, **JOB))
    assert len(tabs) == 4
    for x, y in tabs:
        assert sum(3.0 < v < 27.0 for v in (x, y)) == 1  # mid-side, not a corner


def test_any_number_of_tabs_stays_off_the_corners():
    outline = box(10, 5, 90, 35)
    for n in (1, 2, 3, 5, 6, 8):
        tabs = _tabs(outline, CutoutJob(tabs=n, **JOB))
        assert len(tabs) == n
        for x, y in tabs:
            assert 13.0 < x < 87.0 and (y < 5 or y > 35)


def test_a_short_side_on_the_sheet_edge_leaves_the_tabs_on_the_long_sides():
    outline = box(0, 0, 60, 20)
    tabs = _tabs(outline, CutoutJob(tabs=4, **JOB), stock=(0, -10, 80, 30))
    assert len(tabs) >= 4
    for x, y in tabs:
        if x > 0:                           # the left end is on the sheet's edge
            assert 3.0 < x < 57.0 and (y < 0 or y > 20)


def test_a_round_board_still_gets_its_tabs():
    from shapely.geometry import Point
    tabs = _tabs(Point(0, 0).buffer(15, quad_segs=16),
                 CutoutJob(tabs=4, **JOB))
    assert len(tabs) >= 3      # a tab on the ring's start point reads as two halves


def _carrier():
    """60 x 40 board with two 7 x 7 windows, like the stencil carrier."""
    from shapely.geometry import Polygon
    w = lambda cx, cy: [(cx - 3.5, cy - 3.5), (cx + 3.5, cy - 3.5),
                        (cx + 3.5, cy + 3.5), (cx - 3.5, cy + 3.5)]
    return Polygon([(0, 0), (60, 0), (60, 40), (0, 40)],
                   [w(12, 11), w(48, 29)])


def test_windows_inside_the_board_are_cut_with_the_tool_inside_them():
    job = CutoutJob(bit_diameter=0.8, tabs=0, cut_depth=0.6, total_depth=0.6)
    paths = cut_outline(_carrier(), job)
    assert len(paths) == 3                  # two windows + the outer ring
    for tp, (cx, cy) in zip(paths[:2], [(12, 11), (48, 29)]):
        xs = [m.x for m in tp if not m.rapid]
        ys = [m.y for m in tp if not m.rapid]
        # tool centre 0.4 mm inside each edge, so the window comes out 7 x 7
        assert min(xs) == pytest.approx(cx - 3.1) and max(xs) == pytest.approx(cx + 3.1)
        assert min(ys) == pytest.approx(cy - 3.1) and max(ys) == pytest.approx(cy + 3.1)
        assert (xs[0], ys[0]) == (xs[-1], ys[-1])   # a closed loop


def test_windows_are_cut_to_full_depth_before_the_board_is_freed():
    job = CutoutJob(bit_diameter=0.8, tabs=4, cut_depth=0.6, total_depth=1.8)
    paths = cut_outline(_carrier(), job)
    inside = lambda tp: all(0 < m.x < 60 and 0 < m.y < 40 for m in tp)
    kinds = [inside(tp) for tp in paths]
    assert kinds[:6] == [True] * 6          # 2 windows x 3 passes, first
    assert not any(kinds[6:])               # then the outer ring with its tabs
    assert min(m.z for tp in paths[:6] for m in tp) == pytest.approx(-1.8)


def test_a_window_narrower_than_the_bit_is_skipped_with_a_warning():
    from shapely.geometry import Polygon
    board = Polygon([(0, 0), (20, 0), (20, 20), (0, 20)],
                    [[(10, 10), (10.5, 10), (10.5, 10.5), (10, 10.5)]])
    job = CutoutJob(bit_diameter=0.8, tabs=0, cut_depth=0.6, total_depth=0.6)
    with pytest.warns(UserWarning, match="narrower than"):
        paths = cut_outline(board, job)
    assert len(paths) == 1                  # just the outer ring


def test_a_tiny_board_still_keeps_its_tabs_off_the_corners():
    outline = box(0, 0, 4, 4)
    tabs = _tabs(outline, CutoutJob(tabs=4, **JOB))
    assert len(tabs) == 4
    for x, y in tabs:
        assert sum(0.7 < v < 3.3 for v in (x, y)) == 1

