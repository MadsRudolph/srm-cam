"""Trace isolation: copper -> multi-pass isolation toolpaths."""
from shapely.geometry import MultiPolygon, Polygon
from gerber2rml.toolpath import Move


def _rings(geom):
    """Yield each exterior + interior ring coordinate list of a (Multi)Polygon."""
    polys = geom.geoms if isinstance(geom, MultiPolygon) else [geom]
    for poly in polys:
        if isinstance(poly, Polygon) and not poly.is_empty:
            yield list(poly.exterior.coords)
            for interior in poly.interiors:
                yield list(interior.coords)


def _ring_to_toolpath(coords, cut_z, travel_z):
    sx, sy = coords[0]
    tp = [Move(sx, sy, travel_z, rapid=True), Move(sx, sy, cut_z)]
    for (x, y) in coords[1:]:
        tp.append(Move(x, y, cut_z))
    tp.append(Move(coords[-1][0], coords[-1][1], travel_z, rapid=True))
    return tp


def isolate(copper, job):
    r = job.bit_diameter / 2.0
    step = job.stepover * job.bit_diameter
    n = job.offsets
    cut_z, travel_z = -job.cut_depth, job.travel_z
    paths = []
    i = 0
    while True:
        if n != -1 and i >= n:
            break
        grown = copper.buffer(r + i * step)
        if grown.is_empty:
            break
        rings = list(_rings(grown))
        if not rings:
            break
        for coords in rings:
            paths.append(_ring_to_toolpath(coords, cut_z, travel_z))
        if n == -1 and i > 1000:      # safety cap for clear-all mode
            break
        i += 1
    return paths
