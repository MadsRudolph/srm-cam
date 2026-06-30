"""Ramped lead-in: ease the bit into copper instead of plunging straight down.

A vertical plunge engages the full cut depth instantly -- a torque spike when the
bit hits the copper (and, for a sharp V-bit tip, a chipping risk). This transform
replaces the entry plunge of a cut path with a shallow *ramp*: the tool descends
from just above the surface to full depth over the first few mm of the cut path,
so the depth of engagement grows gradually.

It is a pure transform on :class:`~gerber2rml.toolpath.Move` lists, applied (like
:func:`gerber2rml.engine.leveling.apply_leveling`) AFTER toolpath generation but
BEFORE placement/leveling, so the ramp Z (nominal, surface = 0) later warps with
the height map. It only touches paths that have a lateral cut to ramp along:

  * trace isolation rings and the cut-out outline  -> ramped
  * drill plunges / pecks (no lateral cut)          -> returned unchanged

The ramp is resampled by arc length, so a single long first edge is still entered
gradually. Closed paths (isolation rings, the outline) are re-cut over the ramped
lead-in at full depth at the end, so the gentle entry doesn't leave it shallow.
"""
import math
from gerber2rml.toolpath import Move

DEFAULT_RAMP_LEN = 1.0   # mm of lateral travel to spread the plunge over
RAMP_CLEARANCE = 0.2     # mm above the surface (Z0) where the ramp begins
RAMP_STEP = 0.25         # mm: resample the ramp this finely so Z descends smoothly
EPS = 1e-9


def apply_lead_in(paths, ramp_len=DEFAULT_RAMP_LEN, clearance=RAMP_CLEARANCE):
    """Return new toolpaths with each cut path's entry plunge replaced by a ramp.
    Paths with no lateral cut after the plunge (drills) are returned unchanged."""
    return [_ramp_one(tp, ramp_len, clearance) for tp in paths]


def _ramp_one(tp, ramp_len, clearance):
    # locate the entry plunge: first cut move straight down from the approach
    i = None
    for k in range(1, len(tp)):
        m, prev = tp[k], tp[k - 1]
        if (not m.rapid and abs(m.x - prev.x) < EPS and abs(m.y - prev.y) < EPS
                and m.z < prev.z - EPS):
            i = k
            break
    if i is None:
        return tp                                  # no recognisable plunge

    cut_z = tp[i].z
    x0, y0 = tp[i].x, tp[i].y

    # the cut body: contiguous non-rapid moves after the plunge
    j = i + 1
    while j < len(tp) and not tp[j].rapid:
        j += 1
    body = tp[i + 1:j]
    if not body:
        return tp                                  # nothing lateral to ramp on (drill)

    pts = [(x0, y0)] + [(m.x, m.y) for m in body]
    seglen = [math.hypot(pts[k][0] - pts[k - 1][0], pts[k][1] - pts[k - 1][1])
              for k in range(1, len(pts))]
    cum = [0.0]
    for s in seglen:
        cum.append(cum[-1] + s)
    total = cum[-1]
    if total < EPS:
        return tp                                  # pecks at one point -> leave alone

    ramp_d = min(ramp_len, total)
    closed = math.hypot(pts[-1][0] - x0, pts[-1][1] - y0) < EPS

    def point_at(s):
        """(x, y) at arc length ``s`` along the body polyline."""
        for k in range(1, len(cum)):
            if s <= cum[k] + EPS:
                seg = seglen[k - 1]
                t = (s - cum[k - 1]) / seg if seg > EPS else 0.0
                return (pts[k - 1][0] + (pts[k][0] - pts[k - 1][0]) * t,
                        pts[k - 1][1] + (pts[k][1] - pts[k - 1][1]) * t)
        return pts[-1]

    n = max(1, math.ceil(ramp_d / RAMP_STEP))

    out = list(tp[:i])                             # keep approach up to (not incl.) plunge
    out.append(Move(x0, y0, clearance, rapid=True))  # rapid down to just above surface

    # 1) ramp: descend clearance -> cut_z over the first ramp_d of travel
    for s_i in range(1, n + 1):
        f = s_i / n
        px, py = point_at(ramp_d * f)
        out.append(Move(px, py, clearance + (cut_z - clearance) * f))

    # 2) continue along the rest of the body at full depth (vertices past ramp_d)
    for k in range(1, len(pts)):
        if cum[k] > ramp_d + EPS:
            out.append(Move(pts[k][0], pts[k][1], cut_z))

    # 3) re-cut the ramped lead-in at full depth (closed paths return to the start)
    if closed:
        for s_i in range(1, n + 1):
            px, py = point_at(ramp_d * s_i / n)
            out.append(Move(px, py, cut_z))

    out.extend(tp[j:])                             # original retract / trailing rapids
    return out
