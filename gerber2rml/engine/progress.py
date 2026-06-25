"""Live run-progress tracking from the DRO position.

The mill is driven externally (VPanel), but we read its live position over the
SPI link. Given a job's toolpaths and feeds we precompute a cumulative-time
profile of the path, then project each live ``(x, y, z)`` onto it to estimate
how far the run has got and how much time is left.

Frame: the toolpaths and the live position must be in the SAME coordinates (bed
mm). The GUI plots the DRO marker in exactly that frame (it lands on the board),
so they line up without any extra calibration.

Progress is forward-only: each update searches a window *ahead* of the last
matched spot and the elapsed time only ever increases, so a revisited XY (a
rapid back over already-cut copper) can't snap the bar backwards. The first
update searches the whole path, so arming mid-run still latches on.

Timing mirrors :mod:`gerber2rml.engine.estimate` exactly, so a finished run lands
on the same total the planner showed.
"""
from math import sqrt

from gerber2rml.engine.estimate import DEFAULT_RAPID


def _seg_speed(m, dx, dy, dz, xy_feed, plunge_feed, rapid_feed):
    if m.rapid:
        return rapid_feed
    if abs(dx) < 1e-6 and abs(dy) < 1e-6 and dz < 0:
        return plunge_feed                  # straight down = plunge
    return xy_feed


def _project(p, a, b):
    """Closest point on segment a->b to p (all 3D); return (t in [0,1], distance)."""
    ax, ay, az = a
    abx, aby, abz = b[0] - ax, b[1] - ay, b[2] - az
    denom = abx * abx + aby * aby + abz * abz
    if denom < 1e-12:                       # degenerate segment
        dx, dy, dz = p[0] - ax, p[1] - ay, p[2] - az
        return 0.0, sqrt(dx * dx + dy * dy + dz * dz)
    t = ((p[0] - ax) * abx + (p[1] - ay) * aby + (p[2] - az) * abz) / denom
    t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
    cx, cy, cz = ax + t * abx, ay + t * aby, az + t * abz
    dx, dy, dz = p[0] - cx, p[1] - cy, p[2] - cz
    return t, sqrt(dx * dx + dy * dy + dz * dz)


class RunProgress:
    """Track how far a live tool position has advanced along a job's toolpaths.

    ``toolpaths``: ``Move`` lists in bed mm. ``xy_feed``/``plunge_feed``: mm/s.
    Call :meth:`update` with each live ``(x, y, z)``; it returns
    ``(fraction, elapsed_s, remaining_s)``.
    """

    def __init__(self, toolpaths, xy_feed, plunge_feed, rapid_feed=DEFAULT_RAPID,
                 window=400):
        self.pts = []                       # path vertices (x, y, z) in order
        self.cum = []                       # cumulative seconds reaching each vertex
        cx = cy = cz = None
        t = 0.0
        for path in toolpaths:
            for m in path:
                if cx is None:              # first vertex = run start, t=0
                    self.pts.append((m.x, m.y, m.z)); self.cum.append(0.0)
                    cx, cy, cz = m.x, m.y, m.z
                    continue
                dx, dy, dz = m.x - cx, m.y - cy, m.z - cz
                d = sqrt(dx * dx + dy * dy + dz * dz)
                if d <= 1e-9:
                    continue                # no move (e.g. repeated point)
                sp = _seg_speed(m, dx, dy, dz, xy_feed, plunge_feed, rapid_feed)
                if sp > 0:
                    t += d / sp
                self.pts.append((m.x, m.y, m.z)); self.cum.append(t)
                cx, cy, cz = m.x, m.y, m.z
        self.total = self.cum[-1] if self.cum else 0.0
        self._i = 0                         # forward cursor (last matched segment)
        self._elapsed = 0.0                 # monotonic time reached so far
        self._latched = False               # have we found the start point yet?
        self._window = window

    def update(self, x, y, z):
        """Advance to the live point; return (fraction, elapsed_s, remaining_s)."""
        n = len(self.pts)
        if self.total <= 0.0 or n < 2:
            return (1.0, self.total, 0.0)
        p = (x, y, z)
        if not self._latched:               # first read: search the whole path
            lo, hi = 0, n - 1
        else:
            lo = self._i
            hi = min(n - 1, self._i + self._window)
        best_d = None
        best_i = self._i
        best_t = self._elapsed
        for k in range(lo, hi):
            tt, d = _project(p, self.pts[k], self.pts[k + 1])
            if best_d is None or d < best_d:
                best_d = d
                best_i = k
                best_t = self.cum[k] + tt * (self.cum[k + 1] - self.cum[k])
        if best_d is not None:
            self._latched = True
            if best_t > self._elapsed:      # forward-only: never rewind the bar
                self._elapsed = best_t
                self._i = best_i
        frac = self._elapsed / self.total
        if frac > 1.0:
            frac = 1.0
        return (frac, self._elapsed, max(0.0, self.total - self._elapsed))
