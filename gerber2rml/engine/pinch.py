"""Cut the gaps the bit cannot fit into, on purpose.

Isolation mills along the copper grown by half the cut width, so two islands
closer than one FULL cut width have their grown outlines merge: the path runs
around the pair and the gap between them is never cut (the mechanism is
spelled out in :mod:`gerber2rml.engine.drc`). Nothing forbids the move — the
toolpath for it simply does not exist, and the board comes off the machine
with a permanent short.

Between IC pads that is the normal case, not the exception: 0.45 mm between
0.8 mm pads against a 0.8 mm cutter. The only way through with that bit in
the spindle is to accept the damage — drive the cutter down the MIDDLE of the
gap, taking the gap plus a bite out of both neighbours. At 0.45 mm and 0.80 mm
that bite is 0.175 mm per side: it costs solderable pad and buys a board with
no shorts.

So this is deliberately not clever. It does not try to keep the pads whole,
because with a cutter wider than the gap nothing can. What it does do is
confine the damage to the pinches: every gap the bit fits in is still cut by
the ordinary passes at full trace width, and only the channels that would
otherwise stay bridged get a pass through them.

Opt in per job with ``TraceJob.cut_pinches``. :func:`pinch_losses` reports
which pads paid for it and by how much.
"""
import math

from shapely.geometry import LineString, Point
from shapely.ops import nearest_points, unary_union

from gerber2rml.engine.drc import isolation_pairs
from gerber2rml.toolpath import Move

RUN_OUT_MAX = 8.0   # how far a run-out may travel, in bit radii, before it
                    # gives up. Bounded on purpose: a cut that cannot find its
                    # way out must stop, not keep going across the board.
FACING_COS = 0.5    # how square-on a crossing must be to count as a gap: the
                    # cosine between it and the local tangent, so 0.5 is within
                    # 60 degrees of the normal
WALK_STEP = 0.05    # mm between samples when walking an island's outline to
                    # trace a channel. Finer than the cut is wide, so a gap
                    # that narrows in and out is not stepped over.
SMOOTH_WIN = 7      # samples averaged to take the stair-step out of a channel.
                    # Each midpoint is worked out on its own from the nearest
                    # point on the far island, and on copper that curves - a
                    # polygonised arc - consecutive ones jitter by a few
                    # microns each way. The cut is one continuous motion, so it
                    # should read as one: the tool has no business chattering
                    # along a straight gap.
SIMPLIFY_MM = 0.01  # mm of deviation allowed when dropping redundant points.
                    # Well inside the margin the centred cut leaves (half the
                    # bit past the far edge), and it turns 300 samples of a
                    # straight channel into the two points it really is.


def _polygons(geom):
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    return [g for g in getattr(geom, "geoms", []) if g.geom_type == "Polygon"]


def _run_out(near, far, cleared, blocked, d_max, step=0.05, overlap=0.15):
    """A point out beyond ``near``, away from ``far``, far enough to matter.

    The centreline itself only spans the closest approach — between two round
    pads that is a 0.06 mm arc, and a cut that short leaves the pair joined by
    the copper standing either side of it. The cut has to carry on until it
    breaks into metal the ordinary isolation pass has already taken
    (``cleared``), which is where it can stop: past that point there is
    nothing left to cut.

    It stops early if it would reach a THIRD island (``blocked``). Eating the
    two pads that own the gap is the deal; slicing an unrelated trace on the
    way past is not, so the run-out gives up rather than cross one.
    """
    dx, dy = near[0] - far[0], near[1] - far[1]
    n = math.hypot(dx, dy)
    if n <= 1e-12 or d_max <= 0:
        return None
    ux, uy = dx / n, dy / n
    t = 0.0
    while t < d_max:
        t += step
        pt = Point(near[0] + ux * t, near[1] + uy * t)
        if blocked is not None and blocked.intersects(pt):
            t -= step                       # back off: don't enter that island
            break
        if cleared is not None and cleared.contains(pt):
            t = min(t + overlap, d_max)     # overlap so no whisker survives
            break
    if t <= 0:
        return None
    return (near[0] + ux * t, near[1] + uy * t)


def _smooth(cs):
    """The channel with the sampling jitter averaged out of it.

    The ends are put back exactly where they were: they set the run-out
    directions and the reach of the cut, and a moving average pulls the ends
    of a line inward."""
    if len(cs) < SMOOTH_WIN:
        return cs
    half = SMOOTH_WIN // 2
    out = []
    for i in range(len(cs)):
        lo, hi = max(0, i - half), min(len(cs), i + half + 1)
        window = cs[lo:hi]
        out.append((sum(p[0] for p in window) / len(window),
                    sum(p[1] for p in window) / len(window)))
    out[0], out[-1] = cs[0], cs[-1]
    return out


def _faces(p, q, before, after):
    """Whether the crossing ``p``->``q`` leaves the outline sideways-on.

    ``before``/``after`` are the outline a sample either side of ``p``, so
    their difference is the local tangent. A gap crossed square-on is along
    the normal (dot product near zero); a stub off the end of a pad runs down
    the tangent (near one)."""
    tx, ty = after.x - before.x, after.y - before.y
    ux, uy = q.x - p.x, q.y - p.y
    tn, un = math.hypot(tx, ty), math.hypot(ux, uy)
    if tn <= 1e-12 or un <= 1e-12:
        return False
    return abs((ux * tx + uy * ty) / (un * tn)) <= FACING_COS


def _back(cs, end, look=0.3):
    """The point ``look`` mm back down the channel from the end at ``end``.

    The run-out direction comes from this, not from the neighbouring sample:
    a channel can finish on a short stub across the pad's end, and a direction
    taken from the last two points would then send the cut into the pad
    instead of out along the gap."""
    order = range(len(cs)) if end == -1 else range(len(cs) - 1, -1, -1)
    here = cs[end]
    far = cs[1] if end == 0 else cs[-2]
    for i in order:
        if math.dist(cs[i], here) >= look:
            return cs[i]
    return far


def _channel(a, b, width):
    """Points equidistant from ``a`` and ``b`` along every stretch where they
    run closer than ``width``, in order.

    A pair is reported by :func:`isolation_pairs` once, at its closest
    approach, but two pours can run alongside each other for 20 mm and two
    round pads can pinch over 0.06 mm. Cutting only the closest approach
    leaves the rest of the channel bridged, so the channel has to be walked.

    Walking one island's own outline is what puts the points in order, and it
    follows a gap that changes width or bends around a corner without any
    stitching: for each sample on ``a`` that has ``b`` within the cut width,
    the midpoint to the nearest point on ``b`` is on the centreline by
    construction. The cut has to stay in the MIDDLE like that — at ``g/2``
    from each side the cutter spans ``g/2 + r``, which reaches the far copper
    for every gap it is called on, while hugging one side does not.

    A stretch ends where the gap opens past the cut width: past there the
    ordinary isolation pass does the work, and carrying on would run the
    cutter across copper that is nobody's business.
    """
    def flush(run, runs):
        """Close off a stretch. A pinch can be a single sample wide — two
        curves touching at a point — and that still has to be cut, so a
        one-sample stretch is seeded as a short segment along the local
        tangent, which is the direction the channel runs in."""
        if len(run) >= 2:
            runs.append([mid for mid, _t in run])
        elif len(run) == 1:
            (mx, my), (tx, ty) = run[0]
            n = math.hypot(tx, ty)
            if n > 1e-12:
                ux, uy = tx / n * WALK_STEP / 2.0, ty / n * WALK_STEP / 2.0
                runs.append([(mx - ux, my - uy), (mx + ux, my + uy)])

    runs = []
    for ring in [a.exterior] + list(a.interiors):
        if ring.length <= 0:
            continue
        length = ring.length
        n = max(2, int(math.ceil(length / WALK_STEP)))
        run = []
        for i in range(n + 1):
            s = i * length / n
            p = ring.interpolate(s)
            keep = p.distance(b) < width
            if keep:
                q = nearest_points(p, b)[1]
                # Only where the two genuinely FACE each other. Past the end of
                # a channel a stretch of this outline still has the far island
                # within a cut width - off the pad's end, say - and midpoints
                # taken there fan the cut around the corner or drive it down
                # the pad, eating copper for nothing. What tells them apart is
                # direction: across a real gap the crossing runs along this
                # outline's normal, and along a stub it runs down the tangent.
                before = ring.interpolate((s - WALK_STEP) % length)
                after = ring.interpolate((s + WALK_STEP) % length)
                keep = _faces(p, q, before, after)
            if not keep:
                flush(run, runs)
                run = []
                continue
            run.append((((p.x + q.x) / 2.0, (p.y + q.y) / 2.0),
                        (after.x - before.x, after.y - before.y)))
        flush(run, runs)
    return runs


def pinch_centrelines(copper, job, width=None):
    """Lines down the middle of every gap too narrow for the cutter to enter.

    Each is run on past both ends until it breaks into metal the ordinary
    pass already took (see :func:`_run_out`). ``width`` overrides the job's
    effective cut width, which is what the checks use to ask "what would a
    different bit do".
    """
    if width is None:
        width = job.effective_diameter()
    r = width / 2.0
    pairs = isolation_pairs(copper, width)
    if not pairs:
        return []
    # What the ordinary first isolation pass already takes out. The run-outs
    # aim for this: once the cut reaches it, the channel is open at that end.
    cleared = copper.buffer(r).boundary.buffer(r)
    islands = _polygons(copper)
    lines = []
    for a, b, gap in pairs:
        others = [p for p in islands if p is not a and p is not b]
        blocked = unary_union(others) if others else None
        # Longest first: a channel's end is often found a second time off the
        # neighbouring edge as a stub a few samples long, pointing into the pad
        # rather than along the gap. Cutting that again buys nothing and its
        # run-out drives straight into copper, so a stub that merely retraces
        # a channel already taken is dropped.
        taken = None
        for cs in sorted(_channel(a, b, width),
                         key=lambda c: LineString(c).length, reverse=True):
            ls = LineString(cs)
            if taken is not None:
                near = ls.intersection(taken.buffer(2 * WALK_STEP))
                if near.length >= 0.8 * ls.length:
                    continue
            taken = ls if taken is None else unary_union([taken, ls])
            cs = _smooth(cs)
            head = _run_out(cs[0], _back(cs, 0), cleared, blocked, RUN_OUT_MAX * r)
            tail = _run_out(cs[-1], _back(cs, -1), cleared, blocked,
                            RUN_OUT_MAX * r)
            if head is not None:
                cs.insert(0, head)
            if tail is not None:
                cs.append(tail)
            lines.append(LineString(cs).simplify(SIMPLIFY_MM))
    return lines


def pinch_cuts(copper, job, width=None):
    """Toolpaths that sever every gap too narrow for the cutter to enter."""
    cut_z, travel_z = -job.effective_cut_depth(), job.travel_z
    paths = []
    for line in pinch_centrelines(copper, job, width=width):
        cs = list(line.coords)
        sx, sy = cs[0]
        tp = [Move(sx, sy, travel_z, rapid=True), Move(sx, sy, cut_z)]
        for (x, y) in cs[1:]:
            tp.append(Move(x, y, cut_z))
        tp.append(Move(cs[-1][0], cs[-1][1], travel_z, rapid=True))
        paths.append(tp)
    return paths


def pinch_losses(copper, job, width=None, threshold=0.35):
    """Which copper islands the pinch passes eat into, worst first.

    ``[{"x", "y", "area", "lost"}]`` for islands losing at least ``threshold``
    of their area, where ``lost`` is the fraction removed. A pad at 0.9 has
    essentially gone and there is nothing left to solder to: that is the
    warning the operator has to see BEFORE the spindle starts, because the
    cut itself cannot be undone."""
    lines = pinch_centrelines(copper, job, width=width)
    if not lines:
        return []
    r = (width if width is not None else job.effective_diameter()) / 2.0
    swept = unary_union([ln.buffer(r) for ln in lines])
    out = []
    for poly in _polygons(copper):
        if poly.area <= 0:
            continue
        eaten = poly.intersection(swept)
        if eaten.is_empty:
            continue
        lost = eaten.area / poly.area
        if lost >= threshold:
            c = poly.centroid
            out.append({"x": c.x, "y": c.y, "area": poly.area, "lost": lost})
    out.sort(key=lambda d: -d["lost"])
    return out
