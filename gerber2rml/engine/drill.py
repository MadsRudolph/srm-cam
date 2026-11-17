"""Drilling: Excellon holes -> peck-drill toolpaths."""
import math
from functools import lru_cache
from gerber2rml.toolpath import Move


def group_holes_by_diameter(holes, ndigits: int = 3):
    """Group holes by diameter, returned as ``[(diameter, [holes...]), ...]``
    sorted ascending by diameter. The SRM-20 carries one bit at a time, so each
    diameter is drilled in its own job (smallest first) with a manual bit change
    between them."""
    groups: dict = {}
    for h in holes:
        key = round(h[2], ndigits)
        groups.setdefault(key, []).append(h)
    return [(d, groups[d]) for d in sorted(groups)]


def format_diameter(d: float) -> str:
    """Format a diameter for a filename: 0.8 -> '0.8', 1.0 -> '1.0', 1.52 -> '1.52'."""
    s = f"{d:.3f}".rstrip("0")
    if s.endswith("."):
        s += "0"
    return s


ORDER_TIME_BUDGET = 1.0  # s: the 2-opt pass stops improving after this long


def order_holes(holes, start=(0.0, 0.0), budget=ORDER_TIME_BUDGET):
    """The holes in a short drilling order: nearest neighbour from ``start``,
    then 2-opt until no swap helps (or ``budget`` seconds pass).

    Excellon files list holes by tool and footprint, not by position, so in
    file order the bit criss-crosses the board: 3-4x the travel on the synth
    boards. Only the order changes; the holes themselves are returned as given.
    """
    holes = list(holes)
    if len(holes) < 3:
        return holes
    return list(_order_cached(tuple(map(tuple, holes)), tuple(start), budget))


@lru_cache(maxsize=32)
def _order_cached(holes, start, budget):
    import time
    rest = list(holes)
    route = [start]
    p = start
    while rest:                                   # nearest neighbour
        i = min(range(len(rest)),
                key=lambda k: (rest[k][0] - p[0]) ** 2 + (rest[k][1] - p[1]) ** 2)
        p = rest.pop(i)
        route.append(p)

    def d(a, b):
        return math.hypot(a[0] - b[0], a[1] - b[1])

    # 2-opt on an open route with a fixed start: reverse route[i+1..j] when
    # that shortens it. The end is free (no edge after the last hole).
    n = len(route)
    stop = time.monotonic() + budget
    improved = True
    while improved and time.monotonic() < stop:
        improved = False
        for i in range(n - 2):
            a, b = route[i], route[i + 1]
            ab = d(a, b)
            for j in range(i + 2, n):
                c = route[j]
                if j + 1 < n:
                    e = route[j + 1]
                    gain = ab + d(c, e) - d(a, c) - d(b, e)
                else:
                    gain = ab - d(a, c)
                if gain > 1e-9:
                    route[i + 1:j + 1] = route[i + 1:j + 1][::-1]
                    b = route[i + 1]
                    ab = d(a, b)
                    improved = True
            if time.monotonic() >= stop:
                break
    return tuple(route[1:])


PECK_REENTRY = 0.2  # mm: rapid back to this clearance above the previous peck
                    # depth before feeding, so plunge-feed motion only cuts fresh
                    # material instead of crawling down through the open hole.


def drill_holes(holes, job):
    """Generate peck-drill toolpaths (one per hole).

    holes: list of (x, y, diameter) tuples in mm. diameter is unused in v1
    (the operator loads one bit). Each hole: rapid over the hole, then peck
    cycles until total_depth, ending lifted to the full travel height.

    Between pecks of the *same* hole the bit lifts only ``job.peck_retract`` (a
    small clearance above the surface, enough to shed chips) and then rapids back
    down to just above the previous depth -- it does NOT return to the full
    ``travel_z``. The full retract happens once, after the last peck, so the
    rapid to the next hole clears the board. This keeps slow plunge-feed motion
    confined to fresh material and avoids the wasteful full-height bob on every
    peck.
    """
    pecks = max(1, math.ceil(job.total_depth / job.cut_depth))
    paths = []
    for (x, y, _dia) in order_holes(holes):
        tp = [Move(x, y, job.travel_z, rapid=True)]      # rapid over the hole
        prev = 0.0                                       # last depth reached (+ve mm)
        for k in range(1, pecks + 1):
            depth = job.total_depth if k == pecks else k * job.cut_depth
            # rapid to where cutting resumes: just above the surface on the first
            # peck, just above the previous depth thereafter.
            entry = job.peck_retract if k == 1 else -max(prev - PECK_REENTRY, 0.0)
            tp.append(Move(x, y, entry, rapid=True))
            tp.append(Move(x, y, -depth))                # peck down (plunge feed)
            # small chip-clearing lift between pecks; full retract after the last.
            tp.append(Move(x, y, job.travel_z if k == pecks else job.peck_retract,
                           rapid=True))
            prev = depth
        paths.append(tp)
    return paths


INTERP_MAX_STEP = 0.6  # mm: deepest step of a circled hole. A plain hole may
                       # be one plunge, but a circle side-cuts its full step
                       # depth, which a 0.8 mm bit should not do 1.8 mm deep.


def _interpolate_hole(x, y, hole_d, job, segments: int = 48):
    """Mill a hole that is larger than the bit by circular interpolation: peck
    down and trace a full circle at each depth. The path radius is
    ``(hole_d - bit)/2`` so the cutter edge reaches the hole wall. Each step is
    at most ``INTERP_MAX_STEP`` deep, whatever the plain holes' peck."""
    r = (hole_d - job.bit_diameter) / 2.0
    step = min(job.cut_depth, INTERP_MAX_STEP)
    pecks = max(1, math.ceil(job.total_depth / step))
    sx = x + r
    tp = [Move(sx, y, job.travel_z, rapid=True)]
    for k in range(1, pecks + 1):
        depth = job.total_depth if k == pecks else k * step
        tp.append(Move(sx, y, -depth))                       # plunge at circle start
        for i in range(1, segments + 1):
            ang = 2 * math.pi * i / segments
            tp.append(Move(x + r * math.cos(ang), y + r * math.sin(ang), -depth))
    tp.append(Move(sx, y, job.travel_z, rapid=True))         # retract
    return tp


def drill_single_bit(holes, job, tol: float = 1e-3):
    """One-bit toolpath: plunge holes that fit the bit, interpolate larger ones.

    Holes smaller than the bit cannot be made smaller, so they are plunged at the
    bit size (oversized) — the GUI/run plan flags this."""
    paths = []
    for (x, y, d) in order_holes(holes):
        if d > job.bit_diameter + tol:
            paths.append(_interpolate_hole(x, y, d, job))
        else:
            paths.extend(drill_holes([(x, y, d)], job))
    return paths


def drill_jobs(holes, job, prefix, ext=".rml"):
    """Plan the drill file(s) for *holes*, honoring ``job.single_bit``.

    Returns ``[(filename, toolpaths), ...]`` (filenames are bare, no directory):
    - ``single_bit``  -> one ``'{prefix}{ext}'`` (plunge + interpolate, one bit).
    - otherwise        -> one ``'{prefix}_{dia}mm{ext}'`` per diameter, smallest
      first, each plunged with its matching bit.

    ``ext`` is the output extension (``.rml`` for RML, ``.nc`` for G-code).
    """
    if job.single_bit:
        return [(f"{prefix}{ext}", drill_single_bit(holes, job))]
    return [
        (f"{prefix}_{format_diameter(d)}mm{ext}", drill_holes(hs, job))
        for d, hs in group_holes_by_diameter(holes)
    ]
