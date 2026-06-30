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


def isolate(copper, job, outline=None):
    # Effective width/depth so a V-bit isolates by its (depth-dependent) cut
    # width while a flat endmill keeps using its diameter (see TraceJob).
    width = job.effective_diameter()
    r = width / 2.0
    step = job.stepover * width
    cut_z, travel_z = -job.effective_cut_depth(), job.travel_z
    paths = []
    if job.offsets == -1:
        clip = outline if (outline is not None and not outline.is_empty) else copper.envelope
        i = 0
        while True:
            grown = copper.buffer(r + i * step)
            clipped = grown.intersection(clip)
            for coords in _rings(clipped):
                paths.append(_ring_to_toolpath(coords, cut_z, travel_z))
            remaining = clip.difference(grown)
            if remaining.is_empty or remaining.area < 1e-3:
                break
            if i > 5000:                       # hard backstop
                break
            i += 1
        return paths
    for i in range(job.offsets):
        grown = copper.buffer(r + i * step)
        if grown.is_empty:
            break
        for coords in _rings(grown):
            paths.append(_ring_to_toolpath(coords, cut_z, travel_z))
    return paths
