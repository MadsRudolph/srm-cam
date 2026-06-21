"""Board cutout: outline -> outward-offset cut with holding tabs."""
from shapely.geometry import MultiPolygon, Polygon, LineString
from gerber2rml.toolpath import Move


def _largest_ring(geom):
    polys = geom.geoms if isinstance(geom, MultiPolygon) else [geom]
    polys = [p for p in polys if isinstance(p, Polygon) and not p.is_empty]
    biggest = max(polys, key=lambda p: p.area)
    return LineString(biggest.exterior.coords)


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
    segments = []
    for (a, b) in cut_ranges:
        n = max(2, int((b - a) / 0.5))
        pts = [ring.interpolate(a + (b - a) * t / (n - 1)).coords[0] for t in range(n)]
        segments.append(pts)
    return segments


def cut_outline(outline, job):
    r = job.bit_diameter / 2.0
    ring = _largest_ring(outline.buffer(r))
    segments = _segments_with_tabs(ring, job.tabs, job.tab_width)
    paths = []
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
