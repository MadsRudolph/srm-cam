"""Board cutout: outline -> outward-offset cut with holding tabs.

One board is one ring, offset outward by the cutter's radius so the board
comes out at its drawn size. A window drawn inside the board is cut too, with
the tool inside it, before the ring that frees the board. A panel of several boards is cut island by
island, with two exceptions that make a panel cuttable from a sheet it only
just fits on:

* two boards closer together than the cutter get ONE channel between them,
  centred in the gap. Each loses half of what the cutter takes beyond the
  gap - 0.4 mm a side for touching boards and a 0.8 mm bit - and comes off
  the sheet separated, where two rings would have merged into one and left
  them joined;
* where a board's edge lies on the edge of the copper sheet, nothing is cut.
  The sheet edge is the board edge there, and a ring that ran along it would
  be a cutter in the air.
"""
import math

from shapely.geometry import LineString, MultiPolygon, Polygon, box
from shapely.ops import linemerge, unary_union
from gerber2rml.toolpath import Move

_SEGMENT_STEP_MM = 0.5  # interpolation resolution for cut segments

# How near the sheet's edge a board edge counts as being ON it, either side.
# A rim thinner than this is not a cut worth making: the cutter would be
# mostly in air, and the sliver it left breaks off by hand.
SHEET_EDGE_MM = 0.5

# Tabs go along the long sides, never in a corner: one left in a corner is very
# hard to cut off. A side counts as long from this share of the longest, so a
# square gets a tab on each side and a long board gets them all on its two.
LONG_SIDE_SHARE = 0.6
CORNER_CLEAR_MM = 2.0       # from a corner to the near edge of a tab
TINY_BOARD_CLEAR_MM = 0.5   # the same, on a board too small to leave that
_STRAIGHT_DEG = 2.0         # a turn smaller than this is still the same side


def _islands(geom):
    polys = geom.geoms if isinstance(geom, MultiPolygon) else [geom]
    polys = [p for p in polys if isinstance(p, Polygon) and not p.is_empty]
    if not polys:
        raise ValueError("the outline encloses no area to cut around")
    return polys


def _groups(polys, within):
    """Islands closer than ``within`` (touching included) share a group,
    because their outward rings would merge into one. Groups are ordered by
    position so the tool works its way across the sheet."""
    parent = list(range(len(polys)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(polys)):
        for j in range(i + 1, len(polys)):
            if polys[i].distance(polys[j]) <= within + 1e-9:
                parent[find(i)] = find(j)
    groups = {}
    for i, p in enumerate(polys):
        groups.setdefault(find(i), []).append(p)
    out = list(groups.values())
    out.sort(key=lambda g: min((p.bounds[0], p.bounds[1]) for p in g))
    return out


def _lines(geom):
    """Every LineString in ``geom`` with some length, as coordinate lists."""
    if geom is None or geom.is_empty:
        return []
    parts = [geom] if isinstance(geom, LineString) else [
        g for g in getattr(geom, "geoms", []) if isinstance(g, LineString)]
    return [list(g.coords) for g in parts if g.length > 1e-3]


def _separators(group, bit):
    """One centreline between each pair of islands the cutter cannot pass
    between: the points equidistant from both, over the stretch they face
    each other."""
    lines = []
    for i in range(len(group)):
        for j in range(i + 1, len(group)):
            a, b = group[i], group[j]
            gap = a.distance(b)
            if gap > bit + 1e-9:
                continue
            mid = LineString(a.buffer(gap / 2.0, join_style="mitre")
                             .exterior.coords)
            # A hair inside b's own offset, so the facing stretch of the
            # midline is found robustly and the corners of a contribute only
            # micron-long stubs, which the length filter and the simplify
            # below take out.
            near_b = b.buffer(gap / 2.0 + 1e-6, join_style="mitre")
            parts = [LineString(c) for c in _lines(mid.intersection(near_b))]
            if not parts:
                continue
            merged = linemerge(parts) if len(parts) > 1 else parts[0]
            lines += [[(round(x, 4), round(y, 4)) for x, y in c]
                      for c in _lines(merged.simplify(1e-4))]
    return lines


def _sheet_band(stock, r, edge_tol):
    """Where a ring runs along the sheet's edge - the outline within
    ``edge_tol`` of it, either side - as a region to take out of the ring."""
    x0, y0, x1, y1 = stock
    sheet = box(x0, y0, x1, y1)
    return (sheet.buffer(r + edge_tol, join_style="mitre")
            .difference(sheet.buffer(r - edge_tol, join_style="mitre")))


def _headings(coords):
    """``[(start distance, length, heading)]`` of each real segment."""
    out, along = [], 0.0
    for (x0, y0), (x1, y1) in zip(coords, coords[1:]):
        length = math.hypot(x1 - x0, y1 - y0)
        if length > 1e-9:
            out.append((along, length, math.atan2(y1 - y0, x1 - x0)))
            along += length
    return out


def _turn(a, b):
    return abs((b - a + math.pi) % (2 * math.pi) - math.pi)


def _straight_sides(coords):
    """``[(start distance, length)]`` of the straight runs along a line."""
    sides = []
    start, length, last = None, 0.0, None
    for along, seg, heading in _headings(coords):
        if last is not None and _turn(last, heading) <= math.radians(_STRAIGHT_DEG):
            length += seg
        else:
            if start is not None:
                sides.append((start, length))
            start, length = along, seg
        last = heading
    if start is not None:
        sides.append((start, length))
    return sides


def _start_at_corner(ring):
    """The same closed ring, started at its sharpest corner, so no straight
    side runs across the point where it begins and ends."""
    coords = [c[:2] for c in ring.coords]
    if coords[0] == coords[-1]:
        coords = coords[:-1]
    n = len(coords)
    best, at = -1.0, 0
    for i in range(n):
        a = _headings([coords[i - 1], coords[i]])
        b = _headings([coords[i], coords[(i + 1) % n]])
        if a and b:
            turn = _turn(a[0][2], b[0][2])
            if turn > best:
                best, at = turn, i
    return LineString(coords[at:] + coords[:at] + [coords[at]])


def _tab_centres(lines, tabs, tab_width):
    """Where the tabs go, as one sorted list of distances per line: spread
    along the long straight sides, clear of the corners. None if there is no
    straight side long enough, as on a round board, which has no corners."""
    for margin in (CORNER_CLEAR_MM, TINY_BOARD_CLEAR_MM):
        clear = tab_width / 2.0 + margin
        sides = [(i, start, length) for i, line in enumerate(lines)
                 for start, length in _straight_sides(list(line.coords))
                 if length >= 2 * clear]
        if sides:
            break
    else:
        return None
    longest = max(s[2] for s in sides)
    sides = [s for s in sides if s[2] >= LONG_SIDE_SHARE * longest]
    counts = [0] * len(sides)
    for _ in range(tabs):
        k = max(range(len(sides)), key=lambda j: sides[j][2] / (counts[j] + 1))
        counts[k] += 1
    centres = [[] for _ in lines]
    for (i, start, length), n in zip(sides, counts):
        for k in range(n):
            centres[i].append(start + length * (k + 1) / (n + 1))
    return [sorted(c) for c in centres]


def _keep_between(line, centres, tab_width):
    """The parts of ``line`` left to cut, with a tab at each centre."""
    keep, prev = [], 0.0
    for c in centres:
        if c - tab_width / 2.0 > prev:
            keep.append((prev, c - tab_width / 2.0))
        prev = max(prev, c + tab_width / 2.0)
    if line.length > prev:
        keep.append((prev, line.length))
    segments = []
    for (a, b) in keep:
        n = max(2, int((b - a) / _SEGMENT_STEP_MM))
        segments.append([line.interpolate(a + (b - a) * t / (n - 1)).coords[0]
                         for t in range(n)])
    return segments


def _segments_with_tabs(ring, tabs, tab_width):
    """Split the closed ring into kept segments, leaving `tabs` gaps."""
    L = ring.length
    if tabs <= 0:
        return [list(ring.coords)]
    turned = _start_at_corner(ring)
    placed = _tab_centres([turned], tabs, tab_width)
    if placed is not None and tabs * tab_width < L:
        segments = _keep_between(turned, placed[0], tab_width)
        if len(segments) > 1:
            # The ring starts and ends in a corner, not a tab: one cut, not two.
            segments[0] = segments[-1] + segments[0][1:]
            segments.pop()
        return segments
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


def _segments_with_tabs_open(pieces, tabs, tab_width):
    """Tabs along a ring that the sheet's edge has broken into pieces.

    A board with one side on the sheet edge keeps the same number of tabs, on
    the long sides that are cut."""
    lines = [LineString(p) for p in pieces]
    total = sum(l.length for l in lines)
    if tabs <= 0 or total <= 0:
        return [list(l.coords) for l in lines]
    placed = _tab_centres(lines, tabs, tab_width)
    if placed is not None:
        return [seg for line, centres in zip(lines, placed)
                for seg in _keep_between(line, centres, tab_width)]
    centres = [total * k / tabs for k in range(tabs)]
    segments, offset = [], 0.0
    for l in lines:
        local = sorted(c - offset for c in centres
                       if offset - tab_width / 2.0 < c < offset + l.length
                       + tab_width / 2.0)
        keep, prev = [], 0.0
        for c in local + [l.length]:
            gap_start = c - tab_width / 2.0
            if gap_start > prev:
                keep.append((prev, gap_start))
            prev = max(prev, c + tab_width / 2.0)
        for (a, b) in keep:
            n = max(2, int((b - a) / _SEGMENT_STEP_MM))
            segments.append([l.interpolate(a + (b - a) * t / (n - 1)).coords[0]
                             for t in range(n)])
        offset += l.length
    return segments


def _windows(poly):
    """The cut paths of the windows inside a board, ordered across it.

    ``poly`` is the board already grown by the cutter's radius, so each of its
    holes is the window shrunk by that radius: the line the tool's centre
    follows to cut the window at its drawn size. Each starts in a corner, and
    none gets tabs: the slug is waste, and it is still held by the tape the
    board is held by."""
    holes = sorted(poly.interiors, key=lambda h: (h.bounds[0], h.bounds[1]))
    return [list(_start_at_corner(h).coords) for h in holes]


def _warn_lost_windows(group, outer, bit):
    """Say so when a window is too small for the cutter to enter: growing
    the board by the cutter's radius closed it, and it will not be cut."""
    drawn = sum(len(p.interiors) for p in group)
    kept = sum(len(p.interiors) for p in _islands(outer))
    if kept < drawn:
        import warnings
        warnings.warn(
            f"{drawn - kept} window(s) in the outline are narrower than the "
            f"{bit} mm cut-out bit and will not be cut", stacklevel=3)


def cut_outline(outline, job, stock=None, edge_tol=SHEET_EDGE_MM):
    """Cut round ``outline`` - every island of it - to ``job.total_depth`` in
    passes of ``job.cut_depth``, leaving ``job.tabs`` tabs per island.

    ``stock`` is the copper sheet as ``(x0, y0, x1, y1)``, when the operator
    has declared one: where an island's edge lies on the sheet's edge, within
    ``edge_tol`` either side, that part of the ring is left out.

    Windows inside an island (holes in the outline: Edge.Cuts loops drawn
    inside the board) are cut with the tool inside them, before the island's
    own ring, while the board is still held all round.

    Islands closer together than the cutter get one channel between them,
    cut first and to full depth while everything is still held, and then one
    ring round the lot. Each island is taken to full depth before the next is
    started: on a sheet of several boards the alternative is a flight across
    the sheet for every pass of every board.
    """
    r = job.bit_diameter / 2.0
    band = _sheet_band(stock, r, edge_tol) if stock else None
    paths = []

    def cut(segments):
        depth = 0.0
        # The tolerance stops 3 x 0.6 = 1.7999999 from earning a fourth
        # lap, at the same depth, around the whole board.
        while depth < job.total_depth - 1e-6:
            depth = min(depth + job.cut_depth, job.total_depth)
            if job.total_depth - depth < 1e-6:
                depth = job.total_depth
            for seg in segments:
                sx, sy = seg[0]
                tp = [Move(sx, sy, job.travel_z, rapid=True), Move(sx, sy, -depth)]
                for (x, y) in seg[1:]:
                    tp.append(Move(x, y, -depth))
                tp.append(Move(seg[-1][0], seg[-1][1], job.travel_z, rapid=True))
                paths.append(tp)

    for group in _groups(_islands(outline), job.bit_diameter):
        seps = _separators(group, job.bit_diameter) if len(group) > 1 else []
        if band is not None:
            seps = [c for s in seps for c in _lines(LineString(s).difference(band))]
        if seps:
            cut(seps)
        outer = unary_union([p.buffer(r) for p in group])
        _warn_lost_windows(group, outer, job.bit_diameter)
        for poly in _islands(outer):
            for hole in _windows(poly):
                cut([hole])
            ring = LineString(poly.exterior.coords)
            if band is None:
                segments = _segments_with_tabs(ring, job.tabs, job.tab_width)
            else:
                pieces = _lines(ring.difference(band))
                if not pieces:
                    continue                    # every edge on the sheet's
                if len(pieces) == 1 and LineString(pieces[0]).is_ring:
                    segments = _segments_with_tabs(LineString(pieces[0]),
                                                   job.tabs, job.tab_width)
                else:
                    segments = _segments_with_tabs_open(pieces, job.tabs,
                                                        job.tab_width)
            cut(segments)
    return paths
