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


def _finish(rings, copper, job, cut_z, travel_z):
    """The rings as toolpaths, with the gap cuts folded into them when the job
    asks for those (see :func:`gerber2rml.engine.pinch.splice_pinches`). A gap
    cut that cannot be folded in stays its own pass, after the rings, so the
    ordinary isolation is cut first and the deliberate damage happens on
    copper that is already free."""
    left = []
    if getattr(job, "cut_pinches", False):
        from gerber2rml.engine.pinch import pinch_centrelines, splice_pinches
        rings, left = splice_pinches(rings, pinch_centrelines(copper, job),
                                     copper, job.effective_diameter() / 2.0)
    paths = [_ring_to_toolpath(c, cut_z, travel_z) for c in rings]
    if left:
        from gerber2rml.engine.pinch import _line_toolpath
        paths += [_line_toolpath(list(ln.coords), cut_z, travel_z) for ln in left]
    return paths


def isolate(copper, job, outline=None):
    # Effective width/depth so a V-bit isolates by its (depth-dependent) cut
    # width while a flat endmill keeps using its diameter (see TraceJob).
    width = job.effective_diameter()
    r = width / 2.0
    step = job.stepover * width
    cut_z, travel_z = -job.effective_cut_depth(), job.travel_z
    rings = []
    if job.offsets == -1:
        clip = outline if (outline is not None and not outline.is_empty) else copper.envelope
        if not clip.is_valid:
            clip = clip.buffer(0)        # touching islands, dissolved for the clip
        i = 0
        while True:
            grown = copper.buffer(r + i * step)
            clipped = grown.intersection(clip)
            rings.extend(_rings(clipped))
            remaining = clip.difference(grown)
            if remaining.is_empty or remaining.area < 1e-3:
                break
            if i > 5000:                       # hard backstop
                break
            i += 1
        return _finish(rings, copper, job, cut_z, travel_z)
    for i in range(job.offsets):
        grown = copper.buffer(r + i * step)
        if grown.is_empty:
            break
        rings.extend(_rings(grown))
    return _finish(rings, copper, job, cut_z, travel_z)
