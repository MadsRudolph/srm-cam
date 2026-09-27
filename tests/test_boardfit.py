"""Drilling a board made elsewhere: pad choice, the mirror check, and the
fitted drill file landing on the measured board."""
import math

from gerber2rml.config import DrillJob
from gerber2rml.engine import boardfit as bf
from gerber2rml.engine.fiducial import Transform, fit_transform, rms
from gerber2rml.engine.gcode_parse import parse_nc

HOLES = [(10.0, 10.0, 0.8), (40.0, 12.0, 0.8), (38.0, 30.0, 1.0),
         (12.0, 28.0, 0.8), (25.0, 20.0, 0.8), (26.0, 11.0, 1.0)]


def _moved(t):
    return [t.apply(x, y) for x, y, _d in HOLES]


def test_nearest_hole():
    assert bf.nearest_hole(HOLES, 39.5, 29.0) == 2
    assert bf.nearest_hole([], 0, 0) is None


def test_suggested_pads_are_spread_and_out_of_line():
    idx = bf.suggest_pads(HOLES)
    assert len(idx) == 3 and len(set(idx)) == 3
    pts = [HOLES[i][:2] for i in idx]
    # The farthest pair is in it: that is what pins the rotation.
    far = max(math.dist(a[:2], b[:2]) for a in HOLES for b in HOLES)
    assert max(math.dist(a, b) for a in pts for b in pts) == far
    assert not bf.mirror_ambiguous(pts)


def test_suggest_with_few_holes_returns_them_all():
    assert sorted(bf.suggest_pads(HOLES[:2])) == [0, 1]


def test_pads_in_a_line_are_flagged():
    assert bf.mirror_ambiguous([(0.0, 0.0), (20.0, 0.0), (10.0, 0.05)])
    assert bf.mirror_ambiguous([(0.0, 0.0), (20.0, 0.0)])     # two always are
    # A triangle has a handedness, symmetric or not: pad for pad, a mirror
    # image cannot be turned back onto it.
    assert not bf.mirror_ambiguous([(0.0, 0.0), (20.0, 0.0), (10.0, 15.0)])


def test_a_mirrored_board_does_not_fit_lopsided_pads():
    idx = bf.suggest_pads(HOLES)
    nom = [HOLES[i][:2] for i in idx]
    mirrored = [(60.0 - x, y) for x, y in nom]
    t = fit_transform(nom, mirrored)
    assert rms(t, nom, mirrored) > 1.0


def test_fitted_drill_file_lands_on_the_measured_board(tmp_path):
    t = Transform(math.radians(2.0), 1.0, 15.0, 7.5)
    idx = bf.suggest_pads(HOLES)
    fit = fit_transform([HOLES[i][:2] for i in idx],
                        [t.apply(*HOLES[i][:2]) for i in idx])
    job = DrillJob(bit_diameter=0.8, single_bit=True)
    written = bf.write_fitted_drill(HOLES, job, fit, tmp_path, "lab",
                                    "Roland SRM-20 (G-code)")
    assert [p.name for p in written] == ["lab_drill_fitted.nc"]
    moves = [m for path in parse_nc(written[0].read_text()) for m in path]
    cuts = [(m.x, m.y) for m in moves if m.z < 0]
    for x, y, d in HOLES:
        mx, my = t.apply(x, y)
        # Plunged holes are cut dead on the moved centre; interpolated ones
        # circle it at (hole - bit) / 2.
        reach = (d - 0.8) / 2 + 1e-3
        assert any(math.dist(c, (mx, my)) <= reach + 1e-3 for c in cuts), (x, y)
    # Nothing is cut at the design position of a hole the move carried away.
    assert not any(math.dist(c, HOLES[0][:2]) < 1.0 for c in cuts)


def test_warp_keeps_diameters():
    t = Transform(0.0, 1.0, 1.0, 2.0)
    assert bf.warp_holes([(0.0, 0.0, 0.8)], t) == [(1.0, 2.0, 0.8)]
