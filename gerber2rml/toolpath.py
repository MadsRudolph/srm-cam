"""Move dataclass + Toolpath alias: the engine<->backend contract."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Move:
    x: float
    y: float
    z: float
    rapid: bool = False


Toolpath = list  # list[Move]


def offset(paths, dx, dy):
    """Translate every move in a list of toolpaths by (dx, dy) mm. Used to place
    the whole job somewhere on the bed; Z is untouched. Returns the same list
    object when there is no shift, so callers pay nothing for the common case."""
    if not dx and not dy:
        return paths
    return [[Move(m.x + dx, m.y + dy, m.z, m.rapid) for m in tp] for tp in paths]


def sweep(pts, r):
    """The area a cutter of radius ``r`` sweeps along the polyline ``pts``.

    Not simply ``LineString(pts).buffer(r)``: GEOS mis-buffers a line that
    doubles straight back on itself and can drop most of the doubled stretch
    (seen on the gap cuts folded into isolation rings, which run into a gap
    and back). So the line is split wherever it turns back, and the pieces are
    buffered on their own.
    """
    from shapely.geometry import LineString, Point
    from shapely.ops import unary_union
    pts = [p for k, p in enumerate(pts) if k == 0 or p != pts[k - 1]]
    if not pts:
        return None
    if len(pts) == 1:
        return Point(pts[0]).buffer(r)
    pieces, run = [], [pts[0], pts[1]]
    for c in pts[2:]:
        a, b = run[-2], run[-1]
        ux, uy, vx, vy = b[0] - a[0], b[1] - a[1], c[0] - b[0], c[1] - b[1]
        nu, nv = (ux * ux + uy * uy) ** 0.5, (vx * vx + vy * vy) ** 0.5
        if nu > 0 and nv > 0 and (ux * vx + uy * vy) / (nu * nv) < -0.9:
            pieces.append(run)
            run = [b]
        run.append(c)
    pieces.append(run)
    shapes = [LineString(pc).buffer(r) for pc in pieces if len(pc) >= 2]
    return shapes[0] if len(shapes) == 1 else unary_union(shapes)
