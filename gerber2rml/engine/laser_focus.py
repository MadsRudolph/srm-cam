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
# How far off focus still etches cleanly, mm either way; a band is at most
# twice it deep. The field test (2026-11-19) cleared the same at -0.3 and
# +0.3 mm as at focus, so a sheet is banded only past that.
DEFAULT_TOLERANCE_MM = 0.3
MIN_POINTS = 3            # a map from fewer is not a map: say so instead
# Where the blue dot may land. In a hole it does not fail: it reads the hole's
# depth as the surface, and the whole map goes off (seen on a student's PC,
# 2026-11-19, a point in a mounting hole). So a point keeps this far from any
# hole's edge, and this far inside the board's outline - clear of the mill's
# cut-out channel and its tabs.
HOLE_CLEAR_MM = 1.5
EDGE_CLEAR_MM = 2.0


def _snap(v, step=GRID_MM, lo=0.0, hi=220.0):
    return min(max(round(v / step) * step, lo), hi)


def safe_area(outlines, holes, hole_clear=HOLE_CLEAR_MM,
              edge_clear=EDGE_CLEAR_MM):
    """Where on the bed the blue dot may measure: inside the board outlines
    (bed rings), ``edge_clear`` in from them, and ``hole_clear`` from every
    hole (bed rings). A shapely geometry; empty when nothing is left."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    inside = unary_union([Polygon(r).buffer(0) for r in outlines if len(r) >= 3])
    area = inside.buffer(-edge_clear)
    holes = [Polygon(r).buffer(0) for r in holes if len(r) >= 3]
    if holes:
        area = area.difference(unary_union(holes).buffer(hole_clear))
    return area


def keep_out(outlines, holes, hole_clear=HOLE_CLEAR_MM,
             edge_clear=EDGE_CLEAR_MM):
    """Where the blue dot must never measure, anywhere on the bed: in or by a
    hole, and on the board's cut-out line (the mill's channel and tabs)."""
    from shapely.geometry import LinearRing, Polygon
    from shapely.ops import unary_union
    parts = [LinearRing(r).buffer(edge_clear) for r in outlines if len(r) >= 3]
    parts += [Polygon(r).buffer(0).buffer(hole_clear)
              for r in holes if len(r) >= 3]
    return unary_union(parts)


def clear_point(x, y, safe, search=None, extent=220.0):
    """The factory grid point nearest (x, y) that lies in ``safe``, or None
    when there is none within ``search`` mm (any distance by default)."""
    from shapely.geometry import Point
    if safe is None:
        return (_snap(x, hi=extent), _snap(y, hi=extent))
    if safe.is_empty:
        return None
    reach = search if search is not None else extent
    best = None
    n = int(math.ceil(reach / GRID_MM)) + 1
    cx, cy = _snap(x, hi=extent), _snap(y, hi=extent)
    for i in range(-n, n + 1):
        for j in range(-n, n + 1):
            gx, gy = cx + i * GRID_MM, cy + j * GRID_MM
            if not (0.0 <= gx <= extent and 0.0 <= gy <= extent):
                continue
            d = math.hypot(gx - x, gy - y)
            if d > reach + 1e-9 or (best is not None and d >= best[0]):
                continue
            if safe.contains(Point(gx, gy)):
                best = (d, (gx, gy))
    return None if best is None else best[1]


def grid_points(bounds, spacing=DEFAULT_SPACING_MM, inset=DEFAULT_INSET_MM,
                extent=220.0, safe=None, moved=None):
    """Where to measure over a job whose bed bounds are ``bounds`` (x0, y0,
    x1, y1, mm): a grid at most ``spacing`` apart, ``inset`` in from the
    edges, every point on the factory's 10 mm grid and inside the job. The
    four corners and the middle at least; a point is never measured twice.

    With ``safe`` (:func:`safe_area`) a point that would land outside it - in
    a hole, on the cut-out - goes to the nearest grid point inside it within
    half a spacing, or is left out; ``moved`` (a list) gets ``(was, now)``
    for each, ``now`` None for one left out."""
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
        if safe is not None:
            from shapely.geometry import Point
            if not safe.contains(Point(*p)):
                now = clear_point(p[0], p[1], safe,
                                  search=max(spacing / 2.0, GRID_MM),
                                  extent=extent)
                if moved is not None:
                    moved.append((p, now))
                if now is None:
                    continue
                p = now
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
    skipped: list = field(default_factory=list)   # (x, y) the dot was not read at

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


# ---------------------------------------------------------------------------
# The machine's own error, and taking it out
# ---------------------------------------------------------------------------
#
# The dot reads true at the middle of the bed, where single autofocus works,
# but away from it the lab's F1 Ultra reads a slope that is not there: on a
# flat copper sheet the map said 1.4 mm per 100 mm up the bed, and focus
# ladders etched at the front and back were sharpest within ~0.2 mm of the
# middle's height. One mm of height moves the dot only ~3.8 px in the photo,
# one mm of the dot's own place on the bed ~10 px the same way, so a tenth of
# a millimetre of galvo-against-camera error reads as a quarter of a
# millimetre of height. A single photo cannot tell the two apart; the error
# is the machine's, the same on every surface, so it is measured once on a
# flat sheet and taken off every map after.

REFERENCE_CENTRE = (110.0, 110.0)   # where the dot is trusted: bias 0 here


def reference_from(fmap, centre=REFERENCE_CENTRE):
    """A map measured on a flat sheet -> the machine's bias, as a
    :class:`FocusMap` that is 0 at ``centre``. Every reading there was the
    same flat surface, so whatever varies is the machine's."""
    if fmap is None or len(fmap.points) < MIN_POINTS:
        raise ValueError("Measure at least three points on the flat sheet.")
    c = fmap.at(*centre)
    return FocusMap([(x, y, dz - c) for x, y, dz in fmap.points], fmap.z)


def corrected(fmap, reference):
    """``fmap`` with the machine's bias taken off each point."""
    if reference is None or not reference.points or fmap is None:
        return fmap
    return FocusMap([(x, y, dz - reference.at(x, y)) for x, y, dz in fmap.points],
                    fmap.z, list(fmap.skipped))


def reference_covers(reference, bounds, margin=GRID_MM):
    """Whether the reference was measured over all of ``bounds``: beyond
    it the nearest edge value is used, which is only a guess."""
    if reference is None or not reference.points:
        return False
    xs = [p[0] for p in reference.points]
    ys = [p[1] for p in reference.points]
    x0, y0, x1, y1 = bounds
    return (x0 >= min(xs) - margin and x1 <= max(xs) + margin
            and y0 >= min(ys) - margin and y1 <= max(ys) + margin)


BAND_CELL_MM = 2.0        # how finely the bed is split into height bands


def band_boxes(fmap, bounds, tolerance=DEFAULT_TOLERANCE_MM, cell=BAND_CELL_MM):
    """``[(dz, [box])]``: the job's area ``bounds`` (x0, y0, x1, y1, bed mm)
    split by the height under it into bands no deeper than ``2 * tolerance``,
    each band a list of boxes (x0, y0, x1, y1) covering where it lies, from
    the lowest surface up.

    :func:`plan_zones` puts a whole path in the band of its middle. A traces
    job's isolation round the board's edge is one region whose middle is the
    board's middle, so it never left the middle's height: on a tilted board
    the edges, the very thing the map is for, were not refocused. Here the
    paths are cut where the bands meet instead (the rework boxes' clipping,
    ``xtool.traces_job(boxes=...)``), each piece run at the height under it."""
    x0, y0, x1, y1 = bounds
    x0, y0, x1, y1 = x0 - 1.0, y0 - 1.0, x1 + 1.0, y1 + 1.0
    if fmap is None or not fmap.points:
        return [(0.0, [(x0, y0, x1, y1)])]
    nx = max(1, int(math.ceil((x1 - x0) / cell)))
    ny = max(1, int(math.ceil((y1 - y0) / cell)))
    sx, sy = (x1 - x0) / nx, (y1 - y0) / ny
    dz = [[fmap.at(x0 + (i + 0.5) * sx, y0 + (j + 0.5) * sy) for i in range(nx)]
          for j in range(ny)]
    flat = [v for row in dz for v in row]
    lo, hi = min(flat), max(flat)
    if hi - lo <= 2 * tolerance + 1e-9:
        return [(round((lo + hi) / 2.0, 3), [(x0, y0, x1, y1)])]
    width = 2 * tolerance
    n = int(math.ceil((hi - lo) / width - 1e-9))
    band = [[min(int((v - lo) / width), n - 1) for v in row] for row in dz]
    out = []
    for k in range(n):
        boxes, vals = [], []
        for j in range(ny):
            i = 0
            while i < nx:
                if band[j][i] != k:
                    i += 1
                    continue
                start = i
                while i < nx and band[j][i] == k:
                    vals.append(dz[j][i])
                    i += 1
                boxes.append((x0 + start * sx, y0 + j * sy,
                              x0 + i * sx, y0 + (j + 1) * sy))
        if boxes:
            out.append((round((min(vals) + max(vals)) / 2.0, 3), boxes))
    return out


def describe(fmap, zones, tolerance=DEFAULT_TOLERANCE_MM):
    """One line for the operator about what was measured and what the run
    will do with it."""
    if fmap is None or not fmap.points:
        return "Not measured: the whole job runs at the autofocus height."
    tx, ty = fmap.tilt()
    words = (f"{len(fmap.points)} points, {fmap.spread:.2f} mm from the "
             f"lowest to the highest")
    if fmap.skipped:
        where = ", ".join(f"({x:g}, {y:g})" for x, y in fmap.skipped[:3])
        more = "…" if len(fmap.skipped) > 3 else ""
        words += (f"; {len(fmap.skipped)} left out, the dot not seen at "
                  f"{where}{more}")
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
    ends it early (the map then has what was measured).

    A point where the dot cannot be read (it fell on a cut line, a hole, off
    the material) is left out and listed in ``skipped``; the map is made from
    the rest. Only when fewer than ``MIN_POINTS`` were read does it fail."""
    from gerber2rml.engine.xtool_camera import CameraError
    laser._json("POST", "/device/modeSwitch", {"state": "P_AUTOFOCUS"})
    out, skipped, last = [], [], None
    try:
        z = laser.z()
        for i, (x, y) in enumerate(points):
            if should_stop is not None and should_stop():
                break
            try:
                dz = laser.measure(cal, (x, y))
            except CameraError as e:
                skipped.append((float(x), float(y)))
                last = e
            else:
                out.append((float(x), float(y), float(dz)))
            if progress is not None:
                progress(i + 1, len(points))
    finally:
        laser._json("POST", "/device/modeSwitch", {"state": "P_IDLE"})
    if skipped and len(out) < min(MIN_POINTS, len(points)):
        raise CameraError(f"Only {len(out)} of {len(points)} points could be "
                          f"read. {last}")
    return FocusMap(out, z, skipped)


def zone_indices(centres, fmap, tolerance=DEFAULT_TOLERANCE_MM):
    """``[(dz, [index])]``: shapes whose middles on the bed are ``centres``
    (in their order), grouped as :func:`plan_zones` groups paths. The laser
    page runs each group by itself (its jobs take a set of shape indices)."""
    paths = [[c] for c in centres]
    index = {id(p): i for i, p in enumerate(paths)}
    return [(z.dz, [index[id(p)] for p in z.paths])
            for z in plan_zones(paths, fmap, tolerance)]
