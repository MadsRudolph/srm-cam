"""Focus over the whole board, not only its middle: the laser's bed levelling.

Autofocus measures one point (the middle) and sets the head's Z there. A
board that is tilted on the bed, bowed, or simply wide is then out of focus
towards its edges, and the copper there comes out ragged: the beam is wider
and weaker off its focus.

The laser can measure the height anywhere on its field without moving: the
galvo points the blue dot at a spot, the camera photographs it, and the
factory calibration (one entry per 10 mm grid point) turns where the dot
landed into how far that surface is from focus (``xtool.XTool.measure``).
So, as on the mill:

1. **Measure** a grid of points over the job (:func:`grid_points`) - the
   corners, the edges and the middle, on the factory's 10 mm grid.
2. **Map**: the heights, as mm above focus at the head's current Z
   (:class:`FocusMap`), interpolated between the points.
3. **Zones**: the job's paths, grouped by the height under them into bands no
   deeper than the depth of focus (:func:`plan_zones`). Each band runs on its
   own, with the head moved to that band's focus first. A path is never cut
   in two: it goes, whole, to the band its middle is in. A job whose whole
   spread is within the depth of focus stays one run, at the middle height.

Nothing moves in X or Y between zones: the galvo field is fixed to the bed,
so the alignment on the drilled holes holds for every zone.
"""
import math
from dataclasses import dataclass, field

GRID_MM = 10.0            # the factory calibration's grid
DEFAULT_SPACING_MM = 30.0
DEFAULT_INSET_MM = 3.0
# How far off focus still etches cleanly, mm either way. The F1 Ultra's
# field lens holds about this; a band is at most twice it deep.
DEFAULT_TOLERANCE_MM = 0.15


def _snap(v, step=GRID_MM, lo=0.0, hi=220.0):
    return min(max(round(v / step) * step, lo), hi)


def grid_points(bounds, spacing=DEFAULT_SPACING_MM, inset=DEFAULT_INSET_MM,
                extent=220.0):
    """Where to measure over a job whose bed bounds are ``bounds`` (x0, y0,
    x1, y1, mm): a grid at most ``spacing`` apart, ``inset`` in from the
    edges, every point on the factory's 10 mm grid and inside the job. The
    four corners and the middle at least; a point is never measured twice."""
    x0, y0, x1, y1 = bounds
    ax0, ay0 = x0 + inset, y0 + inset
    ax1, ay1 = max(x1 - inset, ax0), max(y1 - inset, ay0)
    nx = max(2, int(math.ceil((ax1 - ax0) / spacing)) + 1)
    ny = max(2, int(math.ceil((ay1 - ay0) / spacing)) + 1)
    pts = []
    for j in range(ny):
        for i in range(nx):
            x = ax0 + (ax1 - ax0) * i / (nx - 1)
            y = ay0 + (ay1 - ay0) * j / (ny - 1)
            # The nearest grid point that is still on the job.
            sx = _snap(x, hi=extent)
            sy = _snap(y, hi=extent)
            if sx < x0 or sx > x1:
                sx = _snap(x + (GRID_MM / 2 if sx < x0 else -GRID_MM / 2),
                           hi=extent)
            if sy < y0 or sy > y1:
                sy = _snap(y + (GRID_MM / 2 if sy < y0 else -GRID_MM / 2),
                           hi=extent)
            pts.append((sx, sy))
    mid = (_snap((x0 + x1) / 2, hi=extent), _snap((y0 + y1) / 2, hi=extent))
    pts.append(mid)
    out = []
    for p in pts:
        if p not in out:
            out.append(p)
    return out


@dataclass
class FocusMap:
    """Heights measured over the bed: ``points`` are (x, y, dz), with dz the
    mm the surface there is above focus at the head's Z when measured
    (``z``)."""
    points: list
    z: float = 0.0

    @property
    def spread(self):
        if not self.points:
            return 0.0
        dz = [p[2] for p in self.points]
        return max(dz) - min(dz)

    def at(self, x, y):
        """dz at (x, y): inverse-distance weighted from the nearest points,
        exact at a measured point."""
        if not self.points:
            return 0.0
        near = sorted(self.points,
                      key=lambda p: (p[0] - x) ** 2 + (p[1] - y) ** 2)[:4]
        num = den = 0.0
        for px, py, dz in near:
            d2 = (px - x) ** 2 + (py - y) ** 2
            if d2 < 1e-9:
                return dz
            w = 1.0 / d2
            num += w * dz
            den += w
        return num / den

    def tilt(self):
        """The best plane's slope, mm per 100 mm, across X and across Y: a
        board that is simply not lying flat shows as a tilt."""
        pts = self.points
        if len(pts) < 3:
            return 0.0, 0.0
        n = len(pts)
        mx = sum(p[0] for p in pts) / n
        my = sum(p[1] for p in pts) / n
        mz = sum(p[2] for p in pts) / n
        sxx = sum((p[0] - mx) ** 2 for p in pts)
        syy = sum((p[1] - my) ** 2 for p in pts)
        sxy = sum((p[0] - mx) * (p[1] - my) for p in pts)
        sxz = sum((p[0] - mx) * (p[2] - mz) for p in pts)
        syz = sum((p[1] - my) * (p[2] - mz) for p in pts)
        det = sxx * syy - sxy * sxy
        if abs(det) < 1e-9:
            return 0.0, 0.0
        a = (sxz * syy - syz * sxy) / det
        b = (syz * sxx - sxz * sxy) / det
        return a * 100.0, b * 100.0

    def to_dict(self):
        return {"z": self.z, "points": [list(p) for p in self.points]}

    @classmethod
    def from_dict(cls, data):
        try:
            return cls([tuple(float(v) for v in p) for p in data["points"]],
                       float(data.get("z", 0.0)))
        except (KeyError, TypeError, ValueError):
            return None


@dataclass
class Zone:
    """Paths run at one head height: ``dz`` mm above the measured Z."""
    dz: float
    paths: list = field(default_factory=list)


def _middle(path):
    xs = [p[0] for p in path]
    ys = [p[1] for p in path]
    return (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0


def plan_zones(paths, fmap, tolerance=DEFAULT_TOLERANCE_MM):
    """``[Zone]``: ``paths`` (lists of (x, y), bed mm) grouped into bands of
    the height under them, each band no deeper than ``2 * tolerance``, in
    order from the lowest surface up. A job within the depth of focus all
    over is one zone at the middle of its range. Within a zone the paths
    keep the order they came in."""
    if not paths:
        return []
    if fmap is None or not fmap.points:
        return [Zone(0.0, list(paths))]
    under = [fmap.at(*_middle(p)) if p else 0.0 for p in paths]
    lo, hi = min(under), max(under)
    if hi - lo <= 2 * tolerance + 1e-9:
        return [Zone(round((lo + hi) / 2.0, 3), list(paths))]
    width = 2 * tolerance
    n = int(math.ceil((hi - lo) / width - 1e-9))
    bands = [[] for _ in range(n)]
    for p, dz in zip(paths, under):
        k = min(int((dz - lo) / width), n - 1)
        bands[k].append((p, dz))
    zones = []
    for band in bands:
        if not band:
            continue
        dzs = [dz for _p, dz in band]
        zones.append(Zone(round((min(dzs) + max(dzs)) / 2.0, 3),
                          [p for p, _dz in band]))
    return zones


def describe(fmap, zones, tolerance=DEFAULT_TOLERANCE_MM):
    """One line for the operator about what was measured and what the run
    will do with it."""
    if fmap is None or not fmap.points:
        return "Not measured: the whole job runs at the autofocus height."
    tx, ty = fmap.tilt()
    words = (f"{len(fmap.points)} points, {fmap.spread:.2f} mm from the "
             f"lowest to the highest")
    if abs(tx) > 0.05 or abs(ty) > 0.05:
        words += f" (tilted {tx:+.2f} mm across, {ty:+.2f} mm up the bed per 100 mm)"
    if len(zones) <= 1:
        return words + f". Within ±{tolerance:.2f} mm: one run, in focus all over."
    return words + (f". Run in {len(zones)} bands, the head refocused for "
                    f"each.")


def measure_map(laser, cal, points, *, progress=None, should_stop=None):
    """Measure ``points`` with the blue dot (``laser`` an ``xtool.XTool``,
    ``cal`` its calibration). Returns a :class:`FocusMap` at the head's
    present Z. ``progress(i, n)`` after each point; ``should_stop()`` True
    ends it early (the map then has what was measured)."""
    laser._json("POST", "/device/modeSwitch", {"state": "P_AUTOFOCUS"})
    out = []
    try:
        z = laser.z()
        for i, (x, y) in enumerate(points):
            if should_stop is not None and should_stop():
                break
            dz = laser.measure(cal, (x, y))
            out.append((float(x), float(y), float(dz)))
            if progress is not None:
                progress(i + 1, len(points))
    finally:
        laser._json("POST", "/device/modeSwitch", {"state": "P_IDLE"})
    return FocusMap(out, z)


def zone_indices(centres, fmap, tolerance=DEFAULT_TOLERANCE_MM):
    """``[(dz, [index])]``: shapes whose middles on the bed are ``centres``
    (in their order), grouped as :func:`plan_zones` groups paths. The laser
    page runs each group by itself (its jobs take a set of shape indices)."""
    paths = [[c] for c in centres]
    index = {id(p): i for i, p in enumerate(paths)}
    return [(z.dz, [index[id(p)] for p in z.paths])
            for z in plan_zones(paths, fmap, tolerance)]
