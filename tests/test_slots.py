"""Oval holes: KiCad writes them as Excellon slots (G85), which were dropped
("the oval holes don't get cut", Tilstandsmaskine v2, 2026-11-19)."""
import math

from shapely.geometry import LineString, Point
from shapely.ops import unary_union

from gerber2rml.config import DrillJob
from gerber2rml.engine import mountfid
from gerber2rml.engine.drill import drill_single_bit
from gerber2rml.loader import select_drill_holes, slot_hits

DRL = """M48
; #@! TF.FileFunction,Plated,1,2,PTH
FMAT,2
METRIC
T1C0.800
T2C0.900
%
G90
G05
T1
X10.0Y-10.0
X40.0Y-30.0
T2
X20.65Y-20.5G85X21.75Y-20.5
G05
M30
"""


def test_a_slot_in_the_drill_file_becomes_hits_along_its_line(tmp_path):
    (tmp_path / "b-PTH.drl").write_text(DRL)
    holes = select_drill_holes(tmp_path)
    slot = [h for h in holes if abs(h[2] - 0.9) < 1e-6]
    assert len([h for h in holes if abs(h[2] - 0.8) < 1e-6]) == 2
    assert len(slot) >= 2
    xs = sorted(h[0] for h in slot)
    assert xs[0] == 20.65 and xs[-1] == 21.75
    assert all(abs(h[1] + 20.5) < 1e-9 for h in slot)


def test_the_hits_cut_the_oval_and_nothing_else():
    hits = slot_hits(0.0, 0.0, 1.1, 0.0, 0.9)
    cut = []
    for p in drill_single_bit(hits, DrillJob()):
        pts = [(m.x, m.y) for m in p if m.z < 0]
        cut.append(LineString(pts).buffer(0.4) if len(pts) > 1
                   else Point(pts[0]).buffer(0.4))
    cut = unary_union(cut)
    want = LineString([(0, 0), (1.1, 0)]).buffer(0.45)
    assert want.difference(cut).area < 0.02 * want.area
    assert cut.difference(want).area < 0.001


def test_a_zero_length_slot_is_one_hole():
    assert slot_hits(1.0, 2.0, 1.0, 2.0, 1.0) == [(1.0, 2.0, 1.0)]


def test_slot_pieces_are_never_reference_holes():
    box = (0.0, 0.0, 100.0, 60.0)
    slot = slot_hits(4.0, 4.0, 6.0, 4.0, 1.6)
    assert mountfid.pick_any(slot + [(95, 55, 1.0)], box) == []
    assert mountfid.pick(slot + slot_hits(94, 55, 96, 55, 1.6), box) == []
    got = mountfid.pick_any(slot + [(5, 55, 1.0), (95, 55, 1.0)], box)
    assert sorted(got) == [(5, 55, 1.0), (95, 55, 1.0)]
