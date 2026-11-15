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
        for x, y in ((x0 - spare, y0 - spare), (x1 + spare, y0 - spare),
                     (x1 + spare, y1 + spare), (x0 - spare, y1 + spare)):
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
