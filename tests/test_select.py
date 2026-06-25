"""Tests for rework box-selection clipping of toolpaths."""
from gerber2rml.toolpath import Move
from gerber2rml.engine.select import clip_toolpaths_to_bbox


def _ring(pts, cut_z=-0.15, travel_z=2.0):
    """Build a traces-style toolpath: rapid -> plunge -> cuts -> retract."""
    sx, sy = pts[0]
    tp = [Move(sx, sy, travel_z, rapid=True), Move(sx, sy, cut_z)]
    for (x, y) in pts[1:]:
        tp.append(Move(x, y, cut_z))
    tp.append(Move(pts[-1][0], pts[-1][1], travel_z, rapid=True))
    return tp


def _cut_points(toolpaths):
    return [(m.x, m.y) for tp in toolpaths for m in tp if not m.rapid]


def test_keeps_segments_inside_box():
    tp = _ring([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)])
    # box covers only the bottom edge (y near 0)
    out = clip_toolpaths_to_bbox([tp], (-1, -1, 11, 1))
    pts = _cut_points(out)
    assert (0, 0) in pts and (10, 0) in pts          # bottom edge kept
    assert (10, 10) not in pts and (0, 10) not in pts  # top edge dropped


def test_drops_paths_fully_outside():
    tp = _ring([(0, 0), (1, 0), (1, 1), (0, 0)])
    out = clip_toolpaths_to_bbox([tp], (50, 50, 60, 60))
    assert out == []


def test_clipped_path_has_rapid_and_plunge():
    tp = _ring([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)])
    out = clip_toolpaths_to_bbox([tp], (-1, -1, 11, 1))
    assert out, "expected at least one rework path"
    first = out[0]
    assert first[0].rapid and abs(first[0].z - 2.0) < 1e-9   # approach at travel_z
    assert not first[1].rapid and abs(first[1].z + 0.15) < 1e-9  # plunge to cut z
    assert first[-1].rapid                                    # retract at the end


def test_straddling_segment_is_trimmed_to_edge():
    # a single segment crossing the box edge is kept but trimmed at x=5
    tp = _ring([(0, 0), (10, 0)])
    out = clip_toolpaths_to_bbox([tp], (-1, -1, 5, 1))
    pts = _cut_points(out)
    assert (0, 0) in pts                      # inside endpoint kept
    assert (10, 0) not in pts                 # outside endpoint dropped
    assert any(abs(x - 5) < 1e-9 and abs(y) < 1e-9 for (x, y) in pts)  # trimmed at edge


def test_segment_crossing_box_with_no_vertex_inside():
    # long edge passes through the box; neither endpoint is inside it
    tp = _ring([(-10, 0), (10, 0)])
    out = clip_toolpaths_to_bbox([tp], (-2, -1, 2, 1))
    pts = _cut_points(out)
    assert any(abs(x + 2) < 1e-9 for (x, y) in pts)   # entered at x=-2
    assert any(abs(x - 2) < 1e-9 for (x, y) in pts)   # exited at x=2


def test_bbox_corner_order_agnostic():
    tp = _ring([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)])
    a = clip_toolpaths_to_bbox([tp], (-1, -1, 11, 1))
    b = clip_toolpaths_to_bbox([tp], (11, 1, -1, -1))   # reversed corners
    assert _cut_points(a) == _cut_points(b)


def test_cut_z_override_sets_rework_depth():
    # default keeps the source depth; an override re-cuts at the new depth, and
    # the rapid travel height is left untouched.
    tp = _ring([(0, 0), (10, 0)], cut_z=-0.15, travel_z=2.0)
    default = clip_toolpaths_to_bbox([tp], (-1, -1, 11, 1))
    assert all(abs(m.z + 0.15) < 1e-9 for m in default[0] if not m.rapid)
    deeper = clip_toolpaths_to_bbox([tp], (-1, -1, 11, 1), cut_z=-0.30)
    assert all(abs(m.z + 0.30) < 1e-9 for m in deeper[0] if not m.rapid)  # cuts deeper
    assert any(m.rapid and abs(m.z - 2.0) < 1e-9 for m in deeper[0])      # travel kept


def test_disjoint_runs_split_into_separate_paths():
    # square with a box over two opposite edges -> two separate rework runs
    tp = _ring([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)])
    out = clip_toolpaths_to_bbox([tp], (-1, 4, 11, 6))   # horizontal mid-band
    # the band crosses the two vertical edges -> at least two runs
    assert len(out) >= 2
