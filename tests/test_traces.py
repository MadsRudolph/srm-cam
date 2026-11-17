import pytest
from shapely.geometry import Point
from gerber2rml.config import TraceJob
from gerber2rml.engine.traces import isolate
from gerber2rml.toolpath import Move


def test_one_pad_makes_one_ring_per_offset():
    copper = Point(0, 0).buffer(1.0)        # 1 mm radius pad
    job = TraceJob(bit_diameter=0.4, offsets=2, stepover=0.5)
    paths = isolate(copper, job)
    assert len(paths) == 2                   # two offset passes
    for tp in paths:
        assert all(isinstance(m, Move) for m in tp)
        assert tp[0].rapid is True           # starts with a rapid approach
        assert any(m.z < 0 for m in tp)      # cuts below zero
        assert tp[-1].rapid is True          # ends lifted


def test_ring_radius_grows_by_stepover():
    copper = Point(0, 0).buffer(1.0)
    job = TraceJob(bit_diameter=0.4, offsets=2, stepover=0.5)
    paths = isolate(copper, job)
    r0 = max(abs(m.x) for m in paths[0] if not m.rapid)
    r1 = max(abs(m.x) for m in paths[1] if not m.rapid)
    assert r1 > r0                           # second pass is further out


def test_empty_copper_returns_empty():
    from shapely.geometry import Polygon
    assert isolate(Polygon(), TraceJob()) == []


def test_two_separate_pads_each_get_isolated():
    from shapely.geometry import MultiPolygon
    pad_a = Point(0, 0).buffer(1.0)
    pad_b = Point(10, 0).buffer(1.0)          # far apart -> stay separate after buffer
    copper = MultiPolygon([pad_a, pad_b])
    job = TraceJob(bit_diameter=0.4, offsets=1, stepover=0.5)
    paths = isolate(copper, job)
    assert len(paths) == 2                     # one isolation ring per pad


def test_vbit_cuts_at_the_derived_depth():
    # width-first vbit: Z is the depth back-solved from target_width, not cut_depth
    copper = Point(0, 0).buffer(1.0)
    job = TraceJob(tool_type="vbit", tip_diameter=0.1, included_angle=30.0,
                   target_width=0.2, offsets=1)
    paths = isolate(copper, job)
    cut_z = min(m.z for tp in paths for m in tp if not m.rapid)
    assert abs(cut_z - (-job.effective_cut_depth())) < 1e-9
    assert cut_z != -job.cut_depth          # NOT the flat-endmill depth


def test_vbit_offset_matches_equivalent_flat_bit():
    # isolating with a vbit of effective width W == isolating with a flat bit of
    # diameter W: the first ring lands at the same radius.
    copper = Point(0, 0).buffer(1.0)
    flat = TraceJob(bit_diameter=0.4, offsets=1, stepover=0.5)
    # bit_diameter is deliberately NOT 0.4 here: a vbit must ignore it and isolate
    # by its effective (target) width, so this only matches if the engine switched.
    vbit = TraceJob(bit_diameter=0.8, tool_type="vbit", tip_diameter=0.1,
                    included_angle=30.0, target_width=0.4, offsets=1, stepover=0.5)
    rf = max(abs(m.x) for m in isolate(copper, flat)[0] if not m.rapid)
    rv = max(abs(m.x) for m in isolate(copper, vbit)[0] if not m.rapid)
    assert abs(rf - rv) < 1e-6


def test_clear_all_terminates_and_stays_in_outline():
    from shapely.geometry import box, Point
    outline = box(0, 0, 20, 20)
    copper = Point(10, 10).buffer(2.0)        # one pad in the middle
    job = TraceJob(bit_diameter=0.8, offsets=-1, stepover=0.5)
    paths = isolate(copper, job, outline=outline)
    assert 0 < len(paths) < 200               # terminates, not the 1000+ cap
    xs = [m.x for tp in paths for m in tp if not m.rapid]
    assert min(xs) >= -1 and max(xs) <= 21     # clipped to the board, no huge rings


# -- the board outline is never lasered --------------------------------------

def test_an_outline_plotted_into_the_copper_file_is_left_out():
    """KiCad's "Plot Edge.Cuts on all layers" draws the outline in the copper
    Gerber; read as copper the laser would isolate it all the way round."""
    from pathlib import Path
    from gerbonara import GerberFile
    from gerber2rml.engine import soldermask, xtool
    from gerber2rml.loader import _find_layer
    folder = Path(__file__).parent / "fixtures" / "mosfet_test"
    edge_path = _find_layer(folder, "*-Edge_Cuts.*", "*.gm1")
    outline = soldermask._read_outline(edge_path)
    clean = GerberFile.open(str(xtool.copper_layer_path(folder, "bottom")))
    plain, left_out = xtool.copper_without_outline(clean, outline)
    assert left_out == 0.0
    dirty = GerberFile.open(str(xtool.copper_layer_path(folder, "bottom")))
    dirty.objects.extend(GerberFile.open(str(edge_path)).objects)
    as_read = soldermask._layer_to_shapely(dirty)
    assert as_read.intersection(outline.boundary).length > 0.9 * outline.boundary.length
    fixed, left_out = xtool.copper_without_outline(dirty, outline)
    assert left_out == pytest.approx(outline.boundary.length, rel=0.02)
    assert fixed.symmetric_difference(plain).area < 1e-6


def test_one_stroke_on_the_edge_is_still_copper():
    from pathlib import Path
    from gerbonara import GerberFile
    from gerber2rml.engine import soldermask, xtool
    from gerber2rml.loader import _find_layer
    folder = Path(__file__).parent / "fixtures" / "mosfet_test"
    edge_path = _find_layer(folder, "*-Edge_Cuts.*", "*.gm1")
    outline = soldermask._read_outline(edge_path)
    layer = GerberFile.open(str(xtool.copper_layer_path(folder, "bottom")))
    layer.objects.append(GerberFile.open(str(edge_path)).objects[0])
    geom, left_out = xtool.copper_without_outline(layer, outline)
    assert left_out == 0.0
    assert geom.symmetric_difference(soldermask._layer_to_shapely(layer)).area < 1e-9


def test_isolation_never_runs_along_the_boards_edge():
    """Copper that reaches the edge has nothing past it to be isolated from."""
    from shapely.geometry import LineString, Point, box
    from gerber2rml.engine import xtool
    outline = box(0, 0, 40, 30)
    copper = box(0, 5, 20, 10).union(Point(30, 20).buffer(2))   # one to the edge
    art = xtool.LaserArt(kind="traces", outline=outline, copper=copper, drills=[],
                         apertures=xtool.traces_apertures(copper, outline))
    groups, _ = xtool.traces_rings(art, (0.0, 0.0))
    _, h = art.size
    edge = box(0, 0, 40, h).exterior
    rings = [LineString(r) for g in groups for r in g]
    assert rings
    assert all(r.intersection(edge.buffer(0.01)).length < 0.05 for r in rings)
    # The rest of the track's isolation, and the pad's, are all still there.
    total = sum(r.length for r in rings)
    per_ring = [2 * 20 + 5, 2 * 3.14159 * 2]
    assert total > 6 * sum(per_ring) * 0.95
