"""Toolpath playback model: flatten Move lists into a continuous path that a
3D viewer can animate a tool head along.

Pure geometry/maths only (no Qt/OpenGL) so it can be unit tested headless. The
GUI layer (:mod:`gerber2rml.gui.sim3d`) turns these arrays into GL items and a
moving tool marker.

The machine runs the toolpaths in order and the moves within each in order, so
concatenating every move gives the exact continuous path the spindle follows --
rapids ride up at ``travel_z`` and cuts dip to the cut depth, so the flattened
path already encodes the lift/plunge motion in Z.
"""
import math


def _dist(a, b):
    return math.dist(a, b)


def build_path(toolpaths):
    """Flatten ordered moves into ``(points, is_rapid, cum)``.

    ``points``   -- list of ``(x, y, z)`` in machine order.
    ``is_rapid`` -- per point, whether the move *arriving* at it is a rapid
                    (used to colour the segment ending at that point).
    ``cum``      -- cumulative arc length from the start, aligned to ``points``.
    """
    points, is_rapid = [], []
    for tp in toolpaths:
        for m in tp:
            points.append((m.x, m.y, m.z))
            is_rapid.append(m.rapid)
    cum = [0.0]
    for i in range(1, len(points)):
        cum.append(cum[-1] + _dist(points[i - 1], points[i]))
    return points, is_rapid, cum


def split_segments(points, is_rapid):
    """Split into ``(cut_segments, rapid_segments)`` for two-colour drawing.

    Each segment is a ``(p0, p1)`` pair; a segment is a rapid when the move that
    arrives at its end point is a rapid (matching the preview's grouping)."""
    cut, rapid = [], []
    for i in range(1, len(points)):
        (rapid if is_rapid[i] else cut).append((points[i - 1], points[i]))
    return cut, rapid


def index_at(cum, dist):
    """Number of path vertices already reached at arc length ``dist`` (>=1 once
    moving). Binary search over the cumulative-length table."""
    n = len(cum)
    if n == 0:
        return 0
    if dist <= 0:
        return 1
    if dist >= cum[-1]:
        return n
    lo, hi = 0, n - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if cum[mid] <= dist:
            lo = mid + 1
        else:
            hi = mid
    return lo


def position_at(points, cum, dist):
    """Interpolated ``(x, y, z)`` of the tool at arc length ``dist``."""
    if not points:
        return None
    if dist <= 0:
        return points[0]
    if dist >= cum[-1]:
        return points[-1]
    i = index_at(cum, dist)          # cum[i-1] <= dist < cum[i]
    i = max(1, min(i, len(points) - 1))
    seg = cum[i] - cum[i - 1]
    t = 0.0 if seg < 1e-12 else (dist - cum[i - 1]) / seg
    a, b = points[i - 1], points[i]
    return (a[0] + (b[0] - a[0]) * t,
            a[1] + (b[1] - a[1]) * t,
            a[2] + (b[2] - a[2]) * t)


def total_length(toolpaths):
    _p, _r, cum = build_path(toolpaths)
    return cum[-1] if cum else 0.0


def advance_along(points, cum, x, y, prev_dist=0.0, window=400):
    """Forward-only live tracking: project the machine's ``(x, y)`` onto the
    path and return the arc length reached, never less than ``prev_dist``.

    XY-only on purpose: the DRO's Z is in machine coordinates (an arbitrary
    constant away from the job's surface-zero), so matching in XY and reading
    the path's own Z is both frame-proof and what the viewer wants to render.

    ``prev_dist <= 0`` searches the whole path (latch on mid-run); afterwards
    only ``window`` vertices ahead of the last match are scanned, so a rapid
    back over already-cut copper cannot snap the tool marker backwards --
    mirroring :class:`gerber2rml.engine.progress.RunProgress`.
    """
    n = len(points)
    if n < 2:
        return prev_dist
    if prev_dist <= 0.0:
        k0, k1 = 0, n - 1
    else:
        k0 = max(0, index_at(cum, prev_dist) - 1)
        k1 = min(n - 1, k0 + window)
    best_d = None
    best_dist = prev_dist
    for k in range(k0, k1):
        ax, ay = points[k][0], points[k][1]
        bx, by = points[k + 1][0], points[k + 1][1]
        abx, aby = bx - ax, by - ay
        denom = abx * abx + aby * aby
        if denom < 1e-12:
            t = 0.0
        else:
            t = ((x - ax) * abx + (y - ay) * aby) / denom
            t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
        dx, dy = x - (ax + t * abx), y - (ay + t * aby)
        d = dx * dx + dy * dy
        if best_d is None or d < best_d:
            best_d = d
            best_dist = cum[k] + t * (cum[k + 1] - cum[k])
    return max(prev_dist, best_dist)
