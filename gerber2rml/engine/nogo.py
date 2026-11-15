"""A way round: the shortest path between two points that enters no zone.

The automatic run keeps the bit out of no-go zones - the clamps somebody
drew a box round (engine/autorun.py). Staying out of one is easy; getting
from one side of it to the other is this module. The head is led round the
zones at the height it is already at, corner to corner, instead of being
taken to the top of Z and back: on a board with a clamp on each edge that
is a climb of fifty millimetres between every other pair of touches.

Plain geometry, no machine: zones are shapely polygons already grown to
where the tool's CENTRE may not be, so a path that misses them is a path the
tool can take.
"""
import heapq
import math

# How far outside a zone's corner a path turns. The zone is already the
# clearance; this only keeps a turn from grazing its edge on rounding.
CORNER_SPARE_MM = 0.3

# A zone is either a box somebody drew by eye, ``(x0, y0, x1, y1)``, or one
# of the lab's printed cam clamps, ``(cx, cy, d)``: a disc, from its model in
# hardware/probe_bracket/hold_down.py. 26 mm across, 1.8 mm above the copper;
# the thumbscrew (14.4 mm head, 5.5 mm off centre) stands inside that disc.
# Its boss pushes against the sheet's edge, so its flat lip lies LIP mm in
# over the copper - which is all of it the bit can reach.
CLAMP_D_MM = 26.0
CLAMP_LIP_MM = 2.0
# The tool's edge is kept this far beyond a zone. A box drawn by eye gets
# room for a millimetre or two of slack in the drawing; a clamp is its real
# shape, set against the sheet's edge, so only the click along the edge is
# a guess.
NOGO_CLEAR_MM = 2.0
CLAMP_CLEAR_MM = 1.0
# A click this close to a sheet edge (either side) puts a clamp on that edge.
CLAMP_SNAP_MM = 20.0


def is_clamp(z):
    """A clamp is ``(cx, cy, d)`` or, screwed into a bed hole,
    ``(cx, cy, d, sx, sy)`` with the screw's centre."""
    return len(z) in (3, 5)


def zone_shape(z, grow):
    """The shapely shape the tool's centre stays out of: zone ``z`` grown by
    ``grow`` (the tool's radius plus a box's clearance). A clamp is grown
    by its own, smaller, clearance instead."""
    from shapely.geometry import Point, box
    if is_clamp(z):
        cx, cy, d = z[:3]
        g = grow - NOGO_CLEAR_MM + CLAMP_CLEAR_MM
        return Point(cx, cy).buffer(d / 2.0 + g, 64)
    return box(z[0] - grow, z[1] - grow, z[2] + grow, z[3] + grow)


def zone_bounds(z):
    if is_clamp(z):
        cx, cy, d = z[:3]
        return (cx - d / 2.0, cy - d / 2.0, cx + d / 2.0, cy + d / 2.0)
    return tuple(z)


def zone_contains(z, x, y):
    """Is (x, y) on zone ``z`` itself, not grown? For picking one."""
    if is_clamp(z):
        return math.hypot(x - z[0], y - z[1]) <= z[2] / 2.0
    return z[0] <= x <= z[2] and z[1] <= y <= z[3]


def normal(z):
    """A zone as it is kept: a box with its corners in order, rounded."""
    if is_clamp(z):
        return tuple(round(v, 2) for v in z)
    return (round(min(z[0], z[2]), 2), round(min(z[1], z[3]), 2),
            round(max(z[0], z[2]), 2), round(max(z[1], z[3]), 2))


CLAMP_CAM_MM = 5.5      # the screw off the clamp's centre (hold_down.CAM_E)
# The click names the hole the clamp is screwed into when one is this near.
HOLE_PICK_MM = 10.0


def clamp_on_screw(screw, stock, click=None, d=CLAMP_D_MM, lip=CLAMP_LIP_MM,
                   cam=CLAMP_CAM_MM):
    """The clamp screwed into the bed hole at ``screw``: a list with its one
    zone, ``(cx, cy, d, sx, sy)``.

    It is a cam: its centre is ``cam`` mm off the screw, and it is turned
    until its boss (``d - 2 lip`` across) meets the nearest edge of the
    ``stock`` (x0, y0, x1, y1) - hardware/probe_bracket/hold_down.py,
    ``clamp``. Two turns of it meet the edge, mirror images along it, and
    only one holds: the thumbscrew is tightened clockwise and drags the cam
    with it, so the clamp must sit where turning on clockwise drives it
    harder into the sheet - the first touch going clockwise. The other
    would be turned off the sheet by tightening (Mads, 2026-11-15). Seen
    from above, machine Y to the back, that is the centre turned
    anticlockwise of the line from the screw to the edge, so ``click``
    picks nothing but the hole. A hole nearer the edge than the
    cam lets the boss clear has the clamp turned fully away from the sheet;
    one too far for the boss to reach it, fully towards it. With no stock
    the clamp is centred on the screw: every way it could turn is within
    ``cam`` of that, and the zone says so by being ``2 cam`` wider."""
    sx, sy = screw
    if stock is None:
        return [normal((sx, sy, d + 2 * cam, sx, sy))]
    boss = d / 2.0 - lip
    x0, y0, x1, y1 = stock
    # (reach, inward unit) for each edge the screw is beside and out past:
    # reach is how far the edge is from the screw.
    edges = [(x0 - sx, (1.0, 0.0), y0 - boss <= sy <= y1 + boss),
             (sx - x1, (-1.0, 0.0), y0 - boss <= sy <= y1 + boss),
             (y0 - sy, (0.0, 1.0), x0 - boss <= sx <= x1 + boss),
             (sy - y1, (0.0, -1.0), x0 - boss <= sx <= x1 + boss)]
    out = [(reach, u) for reach, u, beside in edges if beside and reach > 0]
    if not out:
        return [normal((sx, sy, d + 2 * cam, sx, sy))]
    reach, (ux, uy) = min(out)
    along = max(-cam, min(cam, reach - boss))   # centre's offset to the edge
    side = math.sqrt(max(0.0, cam * cam - along * along))
    # u turned a quarter anticlockwise: turning clockwise from that side
    # carries the centre towards u, onto the sheet.
    px, py = -uy, ux
    bx, by = sx + ux * along, sy + uy * along
    return [normal((bx + px * side, by + py * side, d, sx, sy))]


def clamp_at(x, y, stock=None, holes=None, d=CLAMP_D_MM, lip=CLAMP_LIP_MM):
    """The clamp zones for a click at (x, y): a list of ``(cx, cy, d...)``.

    ``holes`` are the bed's screw holes [(x, y)]: with one within
    :data:`HOLE_PICK_MM` of the click, the clamp is the one screwed in there
    (:func:`clamp_on_screw`) - exact, because a clamp can only be where its
    screw and the stock's edge let it. Otherwise, with the ``stock`` known
    (x0, y0, x1, y1) and the click within :data:`CLAMP_SNAP_MM` of an edge,
    it is set on that edge with ``lip`` mm over the copper, where along it
    the click says. Elsewhere it is centred on the click."""
    if holes:
        hx, hy = min(holes, key=lambda h: math.hypot(h[0] - x, h[1] - y))
        if math.hypot(hx - x, hy - y) <= HOLE_PICK_MM:
            return clamp_on_screw((hx, hy), stock, (x, y), d, lip)
    if stock is not None:
        x0, y0, x1, y1 = stock
        out = d / 2.0 - lip
        edges = []
        if y0 - CLAMP_SNAP_MM <= y <= y1 + CLAMP_SNAP_MM:
            edges += [(abs(x - x0), 0, (x0 - out, y)),
                      (abs(x - x1), 1, (x1 + out, y))]
        if x0 - CLAMP_SNAP_MM <= x <= x1 + CLAMP_SNAP_MM:
            edges += [(abs(y - y0), 2, (x, y0 - out)),
                      (abs(y - y1), 3, (x, y1 + out))]
        near = [e for e in edges if e[0] <= CLAMP_SNAP_MM]
        if near:
            _d, side, (cx, cy) = min(near)
            # Along the edge it stays on the sheet: a clamp past a corner
            # would hold nothing.
            if side < 2:
                cy = min(max(cy, y0), y1)
            else:
                cx = min(max(cx, x0), x1)
            return [normal((cx, cy, d))]
    return [normal((x, y, d))]


def route(a, b, zones, inside=None, spare=CORNER_SPARE_MM):
    """The points to pass through between ``a`` and ``b``, in order.

    ``[]`` when the straight line is clear. ``None`` when there is no way:
    an end is in a zone, or the zones wall it off inside ``inside``
    (x0, y0, x1, y1) - the rectangle the turns must stay in, which for the
    run is the stock, the one place known to be flat and clear. The ends
    themselves may be anywhere.

    A visibility graph over the zones' corners and Dijkstra over that: a
    handful of clamps is a handful of corners, and the shortest path round
    rectangles always turns at their corners.
    """
    from shapely.geometry import LineString, Point
    from shapely.ops import unary_union
    a, b = (float(a[0]), float(a[1])), (float(b[0]), float(b[1]))
    zones = [z for z in zones if z is not None and not z.is_empty]
    if not zones:
        return []
    blocked = unary_union(zones)
    if blocked.intersects(Point(a)) or blocked.intersects(Point(b)):
        return None

    def clear(p, q):
        return p == q or not LineString([p, q]).intersects(blocked)

    if clear(a, b):
        return []
    nodes = [a, b]
    for z in zones:
        x0, y0, x1, y1 = z.bounds
        turns = [(x0 - spare, y0 - spare), (x1 + spare, y0 - spare),
                 (x1 + spare, y1 + spare), (x0 - spare, y1 + spare)]
        if z.area < 0.95 * (x1 - x0) * (y1 - y0):
            # A clamp's disc: round it on an octagon drawn outside it, not
            # out at the corners of its bounding square.
            cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            r = ((x1 - x0) / 2.0 + spare) / math.cos(math.pi / 8.0)
            turns += [(cx + r * math.cos(k * math.pi / 4.0),
                       cy + r * math.sin(k * math.pi / 4.0))
                      for k in range(8)]
        for x, y in turns:
            if inside is not None and not (inside[0] <= x <= inside[2]
                                           and inside[1] <= y <= inside[3]):
                continue
            if blocked.intersects(Point(x, y)):
                continue                # in the next zone along
            nodes.append((x, y))
    dist = {0: 0.0}
    prev = {}
    heap = [(0.0, 0)]
    done = set()
    while heap:
        d, i = heapq.heappop(heap)
        if i in done:
            continue
        done.add(i)
        if i == 1:
            break
        for j in range(len(nodes)):
            if j in done or not clear(nodes[i], nodes[j]):
                continue
            nd = d + math.dist(nodes[i], nodes[j])
            if nd < dist.get(j, math.inf):
                dist[j], prev[j] = nd, i
                heapq.heappush(heap, (nd, j))
    if 1 not in prev:
        return None
    way, i = [], prev[1]
    while i != 0:
        way.append(nodes[i])
        i = prev[i]
    return way[::-1]


def detour(paths, zones, inside=None):
    """``paths`` with every move through the AIR led round the ``zones``.

    A job is cuts joined by travel: up, across, down. The cuts are where the
    design put them and are left alone - one in a zone is for the run to
    refuse. The travel between them is the run's own choice of line, and a
    straight line from one hole to the next has no reason to respect a
    clamp. So each travelling move that would cross a zone - a rapid inside
    a path, or the hop from the end of one path to the start of the next -
    gets the way round put in front of it (:func:`route`), at the height it
    travels at.

    Returns ``(paths, led)``: new toolpaths and how many moves were led
    round. A move with no way round is left as it was, for the check that
    follows to find.
    """
    from shapely.geometry import LineString
    from shapely.ops import unary_union
    from gerber2rml.toolpath import Move
    zones = [z for z in zones if z is not None and not z.is_empty]
    if not zones or not paths:
        return paths, 0
    blocked = unary_union(zones)
    out, led, prev = [], 0, None
    for tp in paths:
        new = []
        for i, m in enumerate(tp):
            # A path's first move is reached from the last path's end,
            # in the air, whatever that move itself is flagged as.
            in_air = m.rapid or i == 0
            if (prev is not None and in_air
                    and (prev.x, prev.y) != (m.x, m.y)
                    and LineString([(prev.x, prev.y),
                                    (m.x, m.y)]).intersects(blocked)):
                way = route((prev.x, prev.y), (m.x, m.y), zones, inside)
                if way:
                    z = max(prev.z, m.z)
                    new += [Move(x, y, z, rapid=True) for x, y in way]
                    led += 1
            new.append(m)
            prev = m
        out.append(new)
    return out, led
