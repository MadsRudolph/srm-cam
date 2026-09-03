"""Board cutout: outline -> outward-offset cut with holding tabs.

An outline with several islands (a panel of boards) is cut island by island."""
from shapely.geometry import MultiPolygon, Polygon, LineString
from gerber2rml.toolpath import Move

_SEGMENT_STEP_MM = 0.5  # interpolation resolution for cut segments


def _outer_rings(geom):
    """The exterior of every polygon in ``geom``, left to right.

    A board is one polygon and one ring. A panel of several boards is a
    MultiPolygon, and every one of them has to come off the sheet, so it is a
    ring per board - ordered by position so the cutting order is stable and
    the tool works its way across the sheet rather than back and forth.
    """
    polys = geom.geoms if isinstance(geom, MultiPolygon) else [geom]
    polys = [p for p in polys if isinstance(p, Polygon) and not p.is_empty]
    if not polys:
        raise ValueError("the outline encloses no area to cut around")
    polys.sort(key=lambda p: (p.bounds[0], p.bounds[1]))
    return [LineString(p.exterior.coords) for p in polys]


def _segments_with_tabs(ring, tabs, tab_width):
    """Split the closed ring into kept segments, leaving `tabs` gaps."""
    L = ring.length
    if tabs <= 0:
        return [list(ring.coords)]
    gap_centers = [L * k / tabs for k in range(tabs)]
    cut_ranges = []  # (start_dist, end_dist) to KEEP
    prev = 0.0
    for c in gap_centers + [L]:
        gap_start = c - tab_width / 2.0
        if gap_start > prev:
            cut_ranges.append((prev, gap_start))
        prev = c + tab_width / 2.0
    if not cut_ranges:
        raise ValueError(
            f"tabs x tab_width ({tabs} x {tab_width}mm = {tabs * tab_width:.1f}mm) "
            f">= cut ring length ({L:.1f}mm): no material would be cut"
        )
    segments = []
    for (a, b) in cut_ranges:
        n = max(2, int((b - a) / _SEGMENT_STEP_MM))
        pts = [ring.interpolate(a + (b - a) * t / (n - 1)).coords[0] for t in range(n)]
        segments.append(pts)
    return segments


def cut_outline(outline, job):
    """Cut round ``outline`` - every island of it - to ``job.total_depth`` in
    passes of ``job.cut_depth``, leaving ``job.tabs`` tabs per island.

    Each island is taken to full depth before the next is started: on a sheet
    of several boards the alternative is a flight across the sheet for every
    pass of every board."""
    r = job.bit_diameter / 2.0
    paths = []
    for ring in _outer_rings(outline.buffer(r)):
        segments = _segments_with_tabs(ring, job.tabs, job.tab_width)
        depth = 0.0
        while depth < job.total_depth:
            depth = min(depth + job.cut_depth, job.total_depth)
            for seg in segments:
                sx, sy = seg[0]
                tp = [Move(sx, sy, job.travel_z, rapid=True), Move(sx, sy, -depth)]
                for (x, y) in seg[1:]:
                    tp.append(Move(x, y, -depth))
                tp.append(Move(seg[-1][0], seg[-1][1], job.travel_z, rapid=True))
                paths.append(tp)
    return paths
