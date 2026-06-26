"""Fiducial registration: fit a 2D transform from measured reference holes.

Double-sided alternative to dowel pins. The mill drills 2-4 corner fiducial
holes registered to the bottom copper. After the flip the operator measures
where those holes actually landed; we fit the best-fit similarity transform
(rotation + translation, optionally uniform scale) from the NOMINAL hole
positions (where a perfect flip would put them) to the MEASURED positions, and
warp the top-trace toolpaths by it.

Rigid by default (scale locked to 1) to match a physically rigid board; uniform
scale is offered to absorb genuine thermal/measurement scale. Shear is never
modelled -- it would silently absorb real misregistration. The RMS of the fit
residuals is the numeric "how good was this flip?" readout.

Math: closed-form 2D similarity least squares (Umeyama). Centre both point sets,
then theta = atan2(sum cross, sum dot), scale = |.|/sum|p|^2 (or 1 if locked),
translation = q_bar - scale*R(theta)*p_bar.
"""
from dataclasses import dataclass
from math import atan2, cos, sin, sqrt

from gerber2rml.toolpath import Move


@dataclass(frozen=True)
class Transform:
    """2D similarity: scale * R(theta) * (x, y) + (tx, ty)."""
    theta: float
    scale: float
    tx: float
    ty: float

    def apply(self, x, y):
        c, s = cos(self.theta), sin(self.theta)
        return (self.scale * (c * x - s * y) + self.tx,
                self.scale * (s * x + c * y) + self.ty)


def _check(nominal, measured):
    if len(nominal) != len(measured):
        raise ValueError("nominal and measured must have equal length")
    if len(nominal) < 2:
        raise ValueError("need at least 2 fiducial points to fit a transform")


def fit_transform(nominal, measured, allow_scale=False):
    """Best-fit similarity mapping ``nominal`` -> ``measured`` (each list[(x, y)],
    length 2-4). Rigid (scale=1) unless ``allow_scale``. Raises ValueError on
    too-few/mismatched points or a degenerate (zero-spread) nominal set."""
    _check(nominal, measured)
    n = len(nominal)
    pxb = sum(p[0] for p in nominal) / n
    pyb = sum(p[1] for p in nominal) / n
    qxb = sum(q[0] for q in measured) / n
    qyb = sum(q[1] for q in measured) / n
    dot = cross = denom = 0.0
    for (px, py), (qx, qy) in zip(nominal, measured):
        ax, ay = px - pxb, py - pyb
        bx, by = qx - qxb, qy - qyb
        dot += ax * bx + ay * by
        cross += ax * by - ay * bx
        denom += ax * ax + ay * ay
    if denom < 1e-12:
        raise ValueError("degenerate nominal points (no spread to fit)")
    theta = atan2(cross, dot)
    scale = sqrt(dot * dot + cross * cross) / denom if allow_scale else 1.0
    c, s = cos(theta), sin(theta)
    tx = qxb - scale * (c * pxb - s * pyb)
    ty = qyb - scale * (s * pxb + c * pyb)
    return Transform(theta, scale, tx, ty)


def residuals(t, nominal, measured):
    """Per-point Euclidean distance (mm) between ``t(nominal)`` and ``measured``."""
    _check(nominal, measured)
    out = []
    for (px, py), (qx, qy) in zip(nominal, measured):
        mx, my = t.apply(px, py)
        out.append(sqrt((mx - qx) ** 2 + (my - qy) ** 2))
    return out


def rms(t, nominal, measured):
    """Root-mean-square of :func:`residuals` -- the flip-quality number (mm)."""
    res = residuals(t, nominal, measured)
    return sqrt(sum(r * r for r in res) / len(res))


def apply_to_toolpaths(toolpaths, t):
    """Warp X/Y of every ``Move`` by ``t``; Z and rapid are untouched."""
    out = []
    for path in toolpaths:
        new = []
        for m in path:
            nx, ny = t.apply(m.x, m.y)
            new.append(Move(nx, ny, m.z, m.rapid))
        out.append(new)
    return out
