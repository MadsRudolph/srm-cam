import math
import pytest
from gerber2rml.toolpath import Move
from gerber2rml.engine.fiducial import (
    Transform, fit_transform, residuals, rms, apply_to_toolpaths,
)

P = [(0.0, 0.0), (10.0, 0.0), (10.0, 8.0), (0.0, 8.0)]   # nominal corners


def test_pure_translation():
    meas = [(x + 2.0, y - 3.0) for (x, y) in P]
    t = fit_transform(P, meas)
    assert abs(t.tx - 2.0) < 1e-9 and abs(t.ty + 3.0) < 1e-9
    assert abs(t.theta) < 1e-9 and abs(t.scale - 1.0) < 1e-9
    assert rms(t, P, meas) < 1e-9


def test_rotation_plus_translation():
    a = math.radians(1.5)                       # small flip skew
    c, s = math.cos(a), math.sin(a)
    meas = [(c * x - s * y + 4.0, s * x + c * y + 1.0) for (x, y) in P]
    t = fit_transform(P, meas)
    assert abs(t.theta - a) < 1e-6
    assert abs(t.scale - 1.0) < 1e-6
    assert rms(t, P, meas) < 1e-6


def test_uniform_scale_only_when_allowed():
    meas = [(1.01 * x, 1.01 * y) for (x, y) in P]
    rigid = fit_transform(P, meas, allow_scale=False)
    assert abs(rigid.scale - 1.0) < 1e-12        # locked
    scaled = fit_transform(P, meas, allow_scale=True)
    assert abs(scaled.scale - 1.01) < 1e-6


def test_two_points_exact_similarity():
    nom = [(0.0, 0.0), (10.0, 0.0)]
    meas = [(5.0, 5.0), (5.0, 15.0)]             # nominal->measured, 90deg + move
    t = fit_transform(nom, meas, allow_scale=True)
    assert rms(t, nom, meas) < 1e-9


def test_residuals_flag_a_bad_point():
    meas = [(x + 1.0, y + 1.0) for (x, y) in P]
    meas[2] = (meas[2][0] + 0.3, meas[2][1])     # one hole mis-measured
    t = fit_transform(P, meas)
    res = residuals(t, P, meas)
    assert max(res) > 0.1 and rms(t, P, meas) > 0.0


def test_apply_to_toolpaths_moves_xy_not_z():
    t = Transform(theta=0.0, scale=1.0, tx=2.0, ty=-3.0)
    tp = [[Move(1.0, 1.0, -0.15), Move(2.0, 1.0, -0.15, rapid=True)]]
    out = apply_to_toolpaths(tp, t)
    assert out[0][0].x == 3.0 and out[0][0].y == -2.0 and out[0][0].z == -0.15
    assert out[0][1].rapid is True


def test_too_few_points_raises():
    with pytest.raises(ValueError):
        fit_transform([(0.0, 0.0)], [(1.0, 1.0)])


def test_length_mismatch_raises():
    with pytest.raises(ValueError):
        fit_transform(P, P[:3])


def test_degenerate_nominal_raises():
    with pytest.raises(ValueError):
        fit_transform([(1.0, 1.0), (1.0, 1.0)], [(0.0, 0.0), (2.0, 2.0)])
