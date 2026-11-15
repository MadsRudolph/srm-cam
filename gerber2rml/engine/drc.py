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

# A gap this close to the cutter's own width is a gap the cutter FITS. It is
# KiCad's own DRC epsilon: a board routed with the clearance set to the bit
# passes DRC with gaps down to this much under it, and a track laid at exactly
# the clearance comes out of the arithmetic as 0.7999999 as often as 0.8.
# Calling those shorts told people who had done what the check asked that
# they had not.
EXACT_FIT_MM = 0.0005
# ...and up to this much OVER the width the two grown outlines still land on
# each other, merge, and leave no pass between them: the gap is not narrower
# than the bit, and was never cut. Both ends are "exact fits" - one pass down
# the middle (engine/pinch.py) takes the gap and nothing else.
TOUCHING_MM = 1e-6


def isolation_pairs(copper_geom, bit_d, nets=None):
    """``[(poly_a, poly_b, gap), ...]`` for separate copper polygons closer
    than ``bit_d`` mm.

    The geometry behind :func:`isolation_bridges`, kept as its own function
    because the pinch cutter (:mod:`gerber2rml.engine.pinch`) needs the
    polygons themselves, not just where they nearly touch.

    ``nets`` (``Board.copper_nets``: a set of net names per polygon, in the
    order of ``copper_geom.geoms``) keeps only the pairs that join two
    DIFFERENT nets. Copper the cutter cannot separate ends up as one piece:
    the pieces are grouped by "too close to part", and a group is a short
    only if it holds more than one net name. So two islands of one GND pour
    are not reported, nor is a loose island of copper beside a net - but an
    unnamed island with a different net close on each side is, because it
    bridges them. Without ``nets``, separate copper is separate nets.
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
    found = []                           # (i, j, gap)
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
                found.append((i, j, gap))

    if nets is not None and len(nets) == len(polys):
        found = _between_nets(found, nets)
    out = [(polys[i], polys[j], gap) for i, j, gap in found]
    out.sort(key=lambda t: t[2])
    return out


def _between_nets(found, nets):
    """The pairs of ``found`` that are part of a join between two nets."""
    group = {}

    def root(k):
        while group.setdefault(k, k) != k:
            group[k] = group[group[k]]
            k = group[k]
        return k

    for i, j, _gap in found:
        group[root(i)] = root(j)
    names = {}
    for k in list(group):
        names.setdefault(root(k), set()).update(nets[k])
    keep = []
    for i, j, gap in found:
        if len(names[root(i)]) < 2:
            continue                     # one net, or loose copper: no short
        if nets[i] and nets[j] and nets[i] == nets[j]:
            continue                     # two pieces of the same net
        keep.append((i, j, gap))
    return keep


def exact_fit_pairs(copper_geom, bit_d):
    """``[(poly_a, poly_b, gap), ...]`` for polygons whose gap IS the cutter's
    width, to within :data:`EXACT_FIT_MM` under and :data:`TOUCHING_MM` over.
    Not shorts - the cutter goes down the middle and takes no copper - but
    not cut by the ordinary passes either, whose two outlines coincide."""
    return [(p, q, gap)
            for p, q, gap in isolation_pairs(copper_geom, bit_d + TOUCHING_MM)
            if gap >= bit_d - EXACT_FIT_MM]


def isolation_bridges(copper_geom, bit_d, nets=None):
    """Find pairs of separate copper polygons closer than ``bit_d`` mm.

    Returns a list of dicts ``{"x", "y", "gap"}`` — the midpoint of each
    pinch and the actual copper-to-copper distance there. Pairs are reported
    once; polygons that TOUCH (same net / one polygon) are skipped: only a
    genuine gap smaller than the bit is a milling short. A gap that is the
    bit's own width (:func:`exact_fit_pairs`) is not one.
    """
    out = []
    for p, q, gap in isolation_pairs(copper_geom, bit_d - EXACT_FIT_MM,
                                     nets=nets):
        a, b = nearest_points(p, q)
        out.append({"x": (a.x + b.x) / 2.0, "y": (a.y + b.y) / 2.0,
                    "gap": gap})
    out.sort(key=lambda d: d["gap"])
    return out
