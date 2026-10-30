"""Automatic fiducial finding: locate a drilled hole's center electrically.

The touch probe senses copper (tool touching copper pulls D7 low). Over the
drilled fiducial hole there is nothing to touch, so a shallow descend
distinguishes hole from copper — the firmware's ``H x y`` test (v2). Center
finding is classic edge bisection: from a start point inside the hole, walk
outward until copper, bisect the edge to ~50 um, do the same on the other
side, midpoint = center; repeat in Y at the found X, and a second X pass at
the found Y only when the first chord ran far from the middle.

Every touch test is a physical descent, so the count is the run time. Edges
after the first are bracketed where the earlier ones say they are, instead of
marched out to from the start point.

A board made elsewhere often has holes whose copper is not on the clipped net
all the way round: an isolated mounting pad inside a GND pour, a broken
thermal, other nets' traces on one side. The probe only sees copper on the
clip's net, so one direction can find nothing at all, or find copper further
out than the rest. Then the four-edge pass gives way to rays every 45 degrees
and a circle fitted to the edges that agree - the pour's clearance edge is
concentric with the hole, so it centres just as well as the hole's own rim.
"""
import itertools
import math
import time

from gerber2rml.engine.spi_probe import ProbeError, _read_line, send_abort


class NoEdge(ProbeError):
    """A direction ran out of range without touching copper on the net."""


def hole_test(ser, x_um, y_um, timeout=30.0, should_abort=None):
    """``H x y`` -> True (copper contact) / False (hole). Raises on errors."""
    ser.write(f"H {int(x_um)} {int(y_um)}\n".encode())
    line = _read_line(ser, time.monotonic() + timeout, should_abort)
    if should_abort is not None and should_abort():
        send_abort(ser)
        raise ProbeError("aborted")
    if line == "H 1":
        return True
    if line == "H 0":
        return False
    raise ProbeError(f"hole test failed (got {line!r}) — firmware v2 with "
                     f"'holetest' required, and a known surface (probe copper "
                     f"once first)")


def _find_edge(ser, x0, y0, dx, dy, coarse_um=400, span_um=4000, tol_um=50,
               should_abort=None, guess_um=None, bracket_um=150):
    """From (x0, y0) (inside the hole), march along (dx, dy) until copper,
    then bisect the hole->copper edge to ``tol_um``. Returns distance (um).

    ``guess_um`` is where an earlier edge says this one should be: two tests
    either side of it replace the march when they bracket the edge."""
    def test(d):
        return hole_test(ser, x0 + dx * d, y0 + dy * d,
                         should_abort=should_abort)

    lo = 0
    hi = None
    d = coarse_um
    if guess_um is not None and guess_um - bracket_um > 0:
        g_lo, g_hi = int(guess_um - bracket_um), int(guess_um + bracket_um)
        if not test(g_lo):
            lo = g_lo
            if test(g_hi):
                hi = g_hi
            else:
                lo = g_hi
                d = g_hi + coarse_um
        else:
            hi = g_lo
    while hi is None and d <= span_um:
        if test(d):
            hi = d
            break
        lo = d
        d += coarse_um
    if hi is None:
        raise NoEdge("no copper edge within range — is the tool actually "
                     "over the fiducial hole?")
    while hi - lo > tol_um:
        mid = (lo + hi) // 2
        if hole_test(ser, x0 + dx * mid, y0 + dy * mid,
                     should_abort=should_abort):
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2.0


def find_hole_center(ser, x_mm, y_mm, should_abort=None, near_um=400):
    """Locate the hole center starting from (x_mm, y_mm), which must be over
    the hole (jog roughly over it first). Returns (cx_mm, cy_mm).

    Requires: datum latched (``D``), a surface reference (one successful
    probe/``B`` on copper), and the start point actually in the hole.
    """
    x0, y0 = round(x_mm * 1000), round(y_mm * 1000)
    if hole_test(ser, x0, y0, should_abort=should_abort):
        raise ProbeError("copper contact at the start point — jog the tool "
                         "over the fiducial HOLE first")
    edges = []                           # every edge found, absolute um
    tried = set()                        # directions already walked

    def ray(ox, oy, dx, dy, guess_um=None):
        tried.add((dx, dy))
        try:
            d = _find_edge(ser, ox, oy, dx, dy, should_abort=should_abort,
                           guess_um=guess_um)
        except NoEdge:
            return None
        edges.append((ox + dx * d, oy + dy * d))
        return d

    centre = _four_edges(ray, x0, y0, near_um)
    if centre is not None:
        return centre[0] / 1000.0, centre[1] / 1000.0
    # Something did not add up: walk the directions not yet tried, and fit.
    s = math.sqrt(0.5)
    for dx, dy in ((1, 0), (s, s), (0, 1), (-s, s),
                   (-1, 0), (-s, -s), (0, -1), (s, -s)):
        if (dx, dy) not in tried:
            ray(x0, y0, dx, dy)
    cx, cy = _fit_edges(edges)
    return cx / 1000.0, cy / 1000.0


def _four_edges(ray, x0, y0, near_um, agree_um=150):
    """The fast pass: a chord in X, one in Y through its middle, and a second
    X chord only when the first ran far from the centre. Returns the centre
    (um), or None when an edge is missing or the radii disagree - the sign
    that some of the copper round this hole is not on the probed net."""
    right = ray(x0, y0, 1, 0)
    left = ray(x0, y0, -1, 0)
    if right is None or left is None:
        return None
    cx = x0 + (right - left) / 2.0
    half = (right + left) / 2.0          # the radius, if y0 is near the centre
    up = ray(round(cx), y0, 0, 1, guess_um=half)
    if up is None:
        return None
    down = ray(round(cx), y0, 0, -1, guess_um=2 * half - up)
    if down is None:
        return None
    cy = y0 + (up - down) / 2.0
    r_y = (up + down) / 2.0
    # A chord's midpoint is the centre whatever its height, but a chord far
    # from the middle crosses the rim at a slant and blurs both edges. Only
    # then is a second X pass at the true Y worth its touches.
    if abs(cy - y0) > near_um:
        right = ray(round(cx), round(cy), 1, 0, guess_um=r_y)
        left = ray(round(cx), round(cy), -1, 0, guess_um=r_y)
        if right is None or left is None:
            return None
        cx = cx + (right - left) / 2.0
        r_x = (right + left) / 2.0
    else:
        r_x = math.hypot(half, cy - y0)  # the X chord sat this far off-centre
    if abs(r_x - r_y) > agree_um:
        return None
    return cx, cy


def _circle_3(p, q, r):
    """The circle through three points, or None when they are in a line."""
    (ax, ay), (bx, by), (cx, cy) = p, q, r
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-6:
        return None
    a2, b2, c2 = ax * ax + ay * ay, bx * bx + by * by, cx * cx + cy * cy
    ux = (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / d
    uy = (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / d
    return ux, uy, math.hypot(ax - ux, ay - uy)


def _circle_fit(pts):
    """Least-squares circle (Kasa) through any number of points."""
    n = len(pts)
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    u = [(x - mx, y - my) for x, y in pts]
    suu = sum(a * a for a, _ in u)
    svv = sum(b * b for _, b in u)
    suv = sum(a * b for a, b in u)
    suuu = sum(a ** 3 + a * b * b for a, b in u)
    svvv = sum(b ** 3 + b * a * a for a, b in u)
    det = suu * svv - suv * suv
    if abs(det) < 1e-9:
        return None
    uc = (svv * suuu - suv * svvv) / (2 * det)
    vc = (suu * svvv - suv * suuu) / (2 * det)
    r = math.sqrt(uc * uc + vc * vc + (suu + svv) / n)
    return mx + uc, my + vc, r


def _fit_edges(edges, tol_um=120, max_gap_deg=200):
    """The centre of the circle most of the edges sit on (um).

    Edges that found copper further out - another bit of the net beyond a
    gap - are left out: of every circle through three edges, the one the most
    edges agree with wins, then all of those are fitted together. Refuses
    when fewer than three agree, or they all sit on one side of the hole."""
    best, best_key = None, None
    for trio in itertools.combinations(edges, 3):
        c = _circle_3(*trio)
        if c is None:
            continue
        ins = [p for p in edges
               if abs(math.hypot(p[0] - c[0], p[1] - c[1]) - c[2]) < tol_um]
        f = _circle_fit(ins) or c
        rms = math.sqrt(sum((math.hypot(p[0] - f[0], p[1] - f[1]) - f[2]) ** 2
                            for p in ins) / len(ins))
        key = (len(ins), -rms)
        if best_key is None or key > best_key:
            best, best_key = (f, ins), key
    if best is None:
        raise ProbeError(
            "only %d edge(s) of this hole touch copper on the probed net — "
            "too few to centre it. Its copper is not connected to where the "
            "clip is; clip to the pad itself, or jog over the hole and "
            "measure it by eye." % len(edges))
    (cx, cy, _), ins = best
    angles = sorted(math.degrees(math.atan2(y - cy, x - cx)) % 360
                    for x, y in ins)
    gap = max([b - a for a, b in zip(angles, angles[1:])]
              + [angles[0] + 360 - angles[-1]])
    if gap > max_gap_deg:
        raise ProbeError(
            "the edges that touch copper all sit on one side of the hole, "
            "so its centre cannot be trusted. The copper round it is not on "
            "the probed net; clip to the pad itself, or jog over the hole "
            "and measure it by eye.")
    return cx, cy
