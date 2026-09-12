"""Isolation DRC: find copper that the bit physically cannot separate.

Isolation milling cuts along each copper polygon's outline buffered by half
the bit diameter. When two SEPARATE copper polygons sit closer than one bit
diameter, their buffered outlines merge — the toolpath routes AROUND the pair
and the gap between them is never cut: a permanent short no leveling, feed,
or depth can fix. Today that's discovered after cutting, with a multimeter.

This check finds those spots before any G-code exists: group the raw copper
polygons by "buffered outlines merge", and for each group locate the pinch
points (nearest points of polygon pairs closer than the bit).
"""
from shapely.geometry import MultiPolygon
from shapely.ops import nearest_points
from shapely.strtree import STRtree


def isolation_pairs(copper_geom, bit_d):
    """``[(poly_a, poly_b, gap), ...]`` for separate copper polygons closer
    than ``bit_d`` mm.

    The geometry behind :func:`isolation_bridges`, kept as its own function
    because the pinch cutter (:mod:`gerber2rml.engine.pinch`) needs the
    polygons themselves, not just where they nearly touch.
    """
    if copper_geom is None or copper_geom.is_empty:
        return []
    if isinstance(copper_geom, MultiPolygon):
        polys = list(copper_geom.geoms)
    elif copper_geom.geom_type == "Polygon":
        return []                        # one polygon: nothing to isolate from
    else:                                # GeometryCollection etc.
        polys = [g for g in getattr(copper_geom, "geoms", [])
                 if g.geom_type == "Polygon"]
    if len(polys) < 2:
        return []

    tree = STRtree(polys)
    out = []
    seen = set()
    for i, p in enumerate(polys):
        # candidate neighbours: anything whose envelope comes within a bit
        for j in tree.query(p.buffer(bit_d)):
            j = int(j)
            if j <= i:
                continue
            q = polys[j]
            gap = p.distance(q)
            if gap <= 1e-9:              # touching = same copper, not a gap
                continue
            if gap < bit_d:
                key = (i, j)
                if key in seen:
                    continue
                seen.add(key)
                out.append((p, q, gap))
    out.sort(key=lambda t: t[2])
    return out


def isolation_bridges(copper_geom, bit_d):
    """Find pairs of separate copper polygons closer than ``bit_d`` mm.

    Returns a list of dicts ``{"x", "y", "gap"}`` — the midpoint of each
    pinch and the actual copper-to-copper distance there. Pairs are reported
    once; polygons that TOUCH (same net / one polygon) are skipped: only a
    genuine gap smaller than the bit is a milling short.
    """
    out = []
    for p, q, gap in isolation_pairs(copper_geom, bit_d):
        a, b = nearest_points(p, q)
        out.append({"x": (a.x + b.x) / 2.0, "y": (a.y + b.y) / 2.0,
                    "gap": gap})
    out.sort(key=lambda d: d["gap"])
    return out
