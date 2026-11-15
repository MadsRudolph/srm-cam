"""The corner bracket the stock is pushed into, as the part on the bed.

The bracket is an L of flat bar screwed into the spoilboard's tapped holes
(:mod:`gerber2rml.engine.spoilboard`). It is not anywhere: it is in a hole
position, and moving it means unscrewing it and screwing it into other holes,
a whole 10 mm pitch at a time. So it is modelled as the hole its corner screw
is in, and its inside corner - where the stock's corner sits, the one point
Automatic mode measures everything from - follows from that.

What makes this exact is a measurement and the grid's pitch. The lab's standard
position is back-right, corner screw in hole (19, 12), with the printed bracket
(hardware/probe_bracket). Its inside corner was read with the bit over it at
X 191.79, Y 128.43 (2026-11-03). The back-left offset is the old bracket's, at X 22.49,
Y 129.47 in hole (1, 12) (2026-11-02). Moving the bracket by whole holes keeps its
side's offset.

The part itself (the picture on the stage; nothing that cuts depends on it):

    bar width            10 mm, straight walls
    arms                 61 mm outside, both
    screws               the corner, and the last hole of each arm

Its tongue carries the probe wire onto the copper, on the arm along X. The
tongue reaches over the stock, so the bit must stay out from under it
(:meth:`Bracket.keepout`). Only the back-right part exists; the other corners
are that shape mirrored.

The two front corners are not measured: they use their side's offset, mirrored.
"""
from dataclasses import dataclass

from gerber2rml.engine import spoilboard
from gerber2rml.engine.stockfind import CORNERS

# MEASURED: how far the inside corner is from the corner screw's hole centre,
# in mm, as (towards the stock in X, towards the back in Y) on a back corner.
CORNER_FROM_HOLE = {"left": (6.07, -5.11), "right": (4.63, -6.15)}

BAR_W = 10.0             # mm, width of the bar
ARM_X = 61.0             # mm, the arm along X, outside length
ARM_Y = 61.0             # mm, the arm along Y, outside length
HOLES_PER_ARM = 6        # counting the corner hole, at the grid's pitch

# The tongue, from the inside corner along the X arm, and how far it reaches
# over the stock. Mm, as in hardware/probe_bracket/build.py.
TONGUE_U = (2.5, 26.0)
TONGUE_V = 4.0
TONGUE_CLEARANCE = 0.5   # mm kept between the tongue and anything the bit cuts

DEFAULT_CORNER = "back-right"


def _axes(corner):
    """``(a, b)``: +1/-1 along X and Y from the inside corner INTO the stock."""
    if corner not in CORNERS:
        raise ValueError("corner must be one of %s" % (CORNERS,))
    return (1 if "left" in corner else -1, -1 if "back" in corner else 1)


@dataclass(frozen=True)
class Bracket:
    """The bracket with its corner screw in hole ``(i, j)`` of the grid."""
    i: int
    j: int
    corner: str = DEFAULT_CORNER

    def _local(self, u, v, grid):
        """Bracket-local (u, v) mm -> machine (x, y). The origin is the
        inside corner, +u and +v run along the arms, into the stock."""
        a, b = _axes(self.corner)
        cx, cy = self.inside_corner(grid)
        return cx + a * u, cy + b * v

    def inside_corner(self, grid=None):
        """Machine (x, y) mm of the corner the stock's corner sits in."""
        grid = grid or spoilboard.measured_grid()
        a, b = _axes(self.corner)
        hx, hy = grid.centre(self.i, self.j)
        dx, dy = CORNER_FROM_HOLE["left" if "left" in self.corner else "right"]
        # Mirrored for the corner: b = -1 at the back.
        return hx + a * dx, hy - b * dy

    def outline(self, grid=None):
        """The L, as a closed polygon of machine (x, y) mm."""
        grid = grid or spoilboard.measured_grid()
        w = BAR_W
        u0, u1 = TONGUE_U
        local = [(-w, -w), (ARM_X - w, -w), (ARM_X - w, 0.0), (u1, 0.0),
                 (u1, TONGUE_V), (u0, TONGUE_V), (u0, 0.0), (0.0, 0.0),
                 (0.0, ARM_Y - w), (-w, ARM_Y - w)]
        return [self._local(u, v, grid) for u, v in local]

    def keepout(self, grid=None):
        """(x0, y0, x1, y1) machine mm the bit must stay out of: the tongue
        over the stock, with its clearance."""
        grid = grid or spoilboard.measured_grid()
        c = TONGUE_CLEARANCE
        ax, ay = self._local(TONGUE_U[0] - c, 0.0, grid)
        bx, by = self._local(TONGUE_U[1] + c, TONGUE_V + c, grid)
        return min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)

    def arms(self, grid=None):
        """``[(x0, y0, x1, y1), ...]`` machine mm: the two bars of the L.
        They stand beside the stock, taller than the copper, so a cutter that
        runs off the stock's edge on those two sides runs into them."""
        grid = grid or spoilboard.measured_grid()
        w = BAR_W
        out = []
        for (u0, v0), (u1, v1) in (((-w, -w), (ARM_X - w, 0.0)),
                                   ((-w, -w), (0.0, ARM_Y - w))):
            ax, ay = self._local(u0, v0, grid)
            bx, by = self._local(u1, v1, grid)
            out.append((min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)))
        return out

    def screws(self):
        """``[(i, j)]``: the holes its screws are in, the corner one first."""
        a, b = _axes(self.corner)
        n = HOLES_PER_ARM - 1
        return [(self.i, self.j), (self.i + a * n, self.j),
                (self.i, self.j + b * n)]

    def screw_points(self, grid=None):
        grid = grid or spoilboard.measured_grid()
        return [grid.centre(i, j) for i, j in self.screws()]


def fits(bracket, grid=None, bed=None):
    """Can it be screwed down there, with its corner where the bit reaches?

    Every screw needs a hole in the plate. The outer ring counts: the
    measured position has its corner screw in it."""
    grid = grid or spoilboard.measured_grid()
    for i, j in bracket.screws():
        if not (0 <= i < grid.nx and 0 <= j < grid.ny):
            return False
    if bed is not None:
        x, y = bracket.inside_corner(grid)
        if not (0.0 <= x <= bed[0] and 0.0 <= y <= bed[1]):
            return False
    return True


def snap(x, y, corner=DEFAULT_CORNER, grid=None, bed=None):
    """The position it can be screwed into whose inside corner is nearest
    (x, y), or None if it fits nowhere."""
    grid = grid or spoilboard.measured_grid()
    best, best_d = None, None
    for j in range(grid.ny):
        for i in range(grid.nx):
            b = Bracket(i, j, corner)
            if not fits(b, grid, bed):
                continue
            cx, cy = b.inside_corner(grid)
            d = (cx - x) ** 2 + (cy - y) ** 2
            if best_d is None or d < best_d:
                best, best_d = b, d
    return best


DEFAULT = Bracket(19, 12, DEFAULT_CORNER)
# Where the standard was until 2026-11-03. A machine that saved this did not
# choose it, it took the default: it follows the standard to the new place.
OLD_DEFAULT = Bracket(1, 12, "back-left")


def to_text(b):
    return "%d,%d,%s" % (b.i, b.j, b.corner)


def from_text(raw):
    """A saved ``"i,j,corner"``, or None if it is not one."""
    try:
        i, j, c = str(raw or "").split(",")
        if c in CORNERS:
            return Bracket(int(i), int(j), c)
    except ValueError:
        pass
    return None


# How close a dragged board has to come to the corner before it snaps into
# it, per axis, in mm.
SNAP_MM = 3.0


def corner_place(corner, stock, extent, keepout=None, bit_mm=0.8,
                 margin_mm=3.0):
    """Where a board goes when it sits in the bracket's corner of the stock.

    Returns ``(x0, y0)``, the front-left corner of ``extent`` (the board's
    ``(x0, y0, x1, y1)``) placed ``margin_mm`` in from both edges the bracket
    holds - and, where that would put it under the probe tongue, moved away
    from the tongue's arm until the bit clears it by 0.2 mm more than the
    run's own check (:meth:`AutoRun._clear_of_keepout`) asks. ``stock`` is
    ``(x, y, w, h)`` with its ``corner`` in the bracket.
    """
    sx, sy, sw, sh = stock
    w, h = extent[2] - extent[0], extent[3] - extent[1]
    back = "back" in corner
    nx = sx + margin_mm if "left" in corner else sx + sw - margin_mm - w
    ny = sy + sh - margin_mm - h if back else sy + margin_mm
    if keepout is not None:
        kx0, ky0, kx1, ky1 = keepout
        c = bit_mm + 0.2
        if (nx - c < kx1 and nx + w + c > kx0
                and ny - c < ky1 and ny + h + c > ky0):
            ny = ky0 - c - h if back else ky1 + c
    return nx, ny


def stock_needed(corner, stock, extent, keepout=None, bit_mm=0.8,
                 margin_mm=3.0):
    """``(w, h)`` mm the stock must be at least for the board to sit in the
    corner as :func:`corner_place` puts it, with nothing hanging off."""
    sx, sy, sw, sh = stock
    nx, ny = corner_place(corner, stock, extent, keepout, bit_mm, margin_mm)
    w, h = extent[2] - extent[0], extent[3] - extent[1]
    need_w = (nx + w - sx) if "left" in corner else (sx + sw - nx)
    need_h = (sy + sh - ny) if "back" in corner else (ny + h - sy)
    return need_w, need_h


def snap_offset(corner, stock, extent, dx, dy, keepout=None, bit_mm=0.8,
                margin_mm=3.0, snap_mm=SNAP_MM):
    """A drag of ``(dx, dy)`` mm, pulled into the corner place on each axis
    it comes within ``snap_mm`` of."""
    nx, ny = corner_place(corner, stock, extent, keepout, bit_mm, margin_mm)
    if abs(extent[0] + dx - nx) <= snap_mm:
        dx = nx - extent[0]
    if abs(extent[1] + dy - ny) <= snap_mm:
        dy = ny - extent[1]
    return dx, dy


def far_place(corner, stock, extent, flipped=False):
    """Where a board that is NOT cut out goes: against the two edges of the
    stock away from the bracket, which gives the tongue and the arms all the
    room the sheet has. Returns ``(x0, y0)`` like :func:`corner_place`.

    ``flipped``: a double-sided board is turned over left to right and lands
    mirrored across the stock, so room on one side this way up is room on
    the other side then. It is centred across the stock instead, and both
    faces get the same."""
    sx, sy, sw, sh = stock
    w, h = extent[2] - extent[0], extent[3] - extent[1]
    if flipped:
        nx = sx + (sw - w) / 2.0
    else:
        nx = sx + sw - w if "left" in corner else sx
    ny = sy if "back" in corner else sy + sh - h
    return nx, ny


def path_hit(paths, rect, grow):
    """Where the tool would come within ``grow`` mm of ``rect``, or None.

    ``paths`` are toolpaths (lists of moves with ``x`` and ``y``). Every
    move counts, cutting or not, and so do the hops from the end of one
    path to the start of the next: over the bracket the question is not how
    deep the bit is but whether it is there at all. Returns ``(x, y)`` on
    the tool's line, inside the grown rectangle.
    """
    from shapely.geometry import LineString, Point, box
    pts = []
    for tp in paths:
        for m in tp:
            if not pts or pts[-1] != (m.x, m.y):   # a plunge moves nowhere
                pts.append((m.x, m.y))
    if not pts:
        return None
    zone = box(rect[0] - grow, rect[1] - grow, rect[2] + grow, rect[3] + grow)
    line = LineString(pts) if len(pts) > 1 else Point(pts[0])
    if not line.intersects(zone):
        return None
    inside = line.intersection(zone)
    if inside.is_empty:
        return pts[0]
    at = inside.representative_point()
    return at.x, at.y


def level_area_clear(area, rect, grow, inset):
    """``area`` (x0, y0, x1, y1) shrunk so a grid of surface touches, set
    ``inset`` mm in from its edges, has no point within ``grow`` of ``rect``.

    The tongue lies along one edge of the stock, so the area gives way in Y:
    its near edge is pulled back until the row of touches along it clears.
    The copper under the tongue is not measured; the height map carries its
    last row out to it. Returns ``area`` unchanged when nothing is near.
    """
    x0, y0, x1, y1 = area
    kx0, ky0, kx1, ky1 = (rect[0] - grow, rect[1] - grow,
                          rect[2] + grow, rect[3] + grow)
    if x1 - inset < kx0 or x0 + inset > kx1:
        return area                      # no touch is ever in its X span
    top, bottom = y1 - inset, y0 + inset
    if top < ky0 or bottom > ky1:
        return area
    # Give way on the side the rectangle sits nearer to.
    if (ky0 + ky1) / 2.0 >= (y0 + y1) / 2.0:
        y1 = ky0 + inset - 1e-6
    else:
        y0 = ky1 - inset + 1e-6
    return (x0, y0, x1, y1)


# -- work that would be under the bracket ------------------------------------
#
# A board that is not cut out can lie right up to the bracket, and then some
# of its isolation runs where the tongue is. That part cannot be cut. It is
# taken out of the pass, the bit is led round the tongue instead of over it,
# and what is left uncut is then PROVED harmless by milling the passes out
# of the sheet on paper: if two nets end up on one piece of copper the run
# does not start.

AVOID_SPARE_MM = 0.05


def _zone(rect, grow):
    from shapely.geometry import box
    return box(rect[0] - grow, rect[1] - grow, rect[2] + grow, rect[3] + grow)


def _round(a, b, zones, inside, margin=0.6):
    """Waypoints that take a hop from ``a`` to ``b`` round the ``zones``
    instead of across them: the shortest dog-leg along a side of any of them
    that crosses none and stays inside ``inside`` (x0, y0, x1, y1). None
    when a straight hop is clear; [] when no way round was found."""
    from shapely.geometry import LineString
    from shapely.ops import unary_union
    blocked = unary_union(zones)
    if not LineString([a, b]).intersects(blocked):
        return None
    ix0, iy0, ix1, iy1 = inside
    ways = []
    for zone in zones:
        zx0, zy0, zx1, zy1 = zone.bounds
        for y in (zy0 - margin, zy1 + margin):
            ways.append([(a[0], y), (b[0], y)])
        for x in (zx0 - margin, zx1 + margin):
            ways.append([(x, a[1]), (x, b[1])])
    best = None
    for way in ways:
        if any(not (ix0 <= x <= ix1 and iy0 <= y <= iy1) for x, y in way):
            continue
        line = LineString([a] + way + [b])
        if line.intersects(blocked):
            continue
        if best is None or line.length < best[0]:
            best = (line.length, way)
    return [] if best is None else best[1]


def avoid(paths, rects, inside):
    """``paths`` with nothing under the bracket.

    ``rects`` is ``[((x0, y0, x1, y1), grow), ...]`` - the tongue and the
    bars, each with how far the tool's centre must stay from it; ``inside``
    the stock, which a way round must stay on. Cutting moves inside a zone
    are taken out (the pass lifts before it and comes down after it), and a
    hop that would cross a zone is led round it. Returns ``(paths,
    uncut_mm)``: the new toolpaths and the length of cut that was left out.

    Only for passes at one depth that may be left partly uncut - isolation.
    A hole or a cut-out under the bracket is not something to leave out.
    """
    from shapely.geometry import LineString, Point
    from shapely.ops import unary_union
    from gerber2rml.toolpath import Move
    # A hair wider than the zones the run then checks against, so what is
    # kept ends clear of them rather than on their edge.
    zones = [_zone(r, g + AVOID_SPARE_MM) for r, g in rects]
    checked = [_zone(r, g) for r, g in rects]     # what a hop must miss
    if not zones or not paths:
        return paths, 0.0
    zone = unary_union(zones)
    out, uncut = [], 0.0
    for tp in paths:
        cut = [m for m in tp if not m.rapid]
        if len(cut) < 2:
            out.append(tp)
            continue
        line = LineString([(m.x, m.y) for m in cut])
        if not line.intersects(zone):
            out.append(tp)
            continue
        travel = max(m.z for m in tp)
        depth = min(m.z for m in cut)
        kept = line.difference(zone)
        parts = [g for g in getattr(kept, "geoms", [kept])
                 if g.geom_type == "LineString" and g.length > 0.05]
        parts.sort(key=lambda g: line.project(Point(g.coords[0])))
        uncut += line.length - sum(g.length for g in parts)
        for g in parts:
            cs = list(g.coords)
            new = [Move(cs[0][0], cs[0][1], travel, rapid=True),
                   Move(cs[0][0], cs[0][1], depth)]
            new += [Move(x, y, depth) for x, y in cs[1:]]
            new.append(Move(cs[-1][0], cs[-1][1], travel, rapid=True))
            out.append(new)
    # Hops: from the end of one path to the start of the next, in the air.
    for i in range(1, len(out)):
        a, b = out[i - 1][-1], out[i][0]
        travel = max(m.z for m in out[i])
        way = _round((a.x, a.y), (b.x, b.y), checked, inside)
        if way == []:
            # No single dog-leg does it - two clamps in a row, say. The
            # corner-to-corner router (engine/nogo.py) finds what there is.
            from gerber2rml.engine.nogo import route
            way = route((a.x, a.y), (b.x, b.y), checked, inside) or []
        if way:
            out[i] = ([Move(x, y, travel, rapid=True) for x, y in way]
                      + list(out[i]))
    return out, uncut


def joined_nets(copper, nets, paths, sheet, radius):
    """Mill ``paths`` out of ``sheet`` and say which nets are left on one
    piece of copper: ``[[name, name, ...], ...]``, empty when every net
    stands alone.

    The sheet is copper everywhere, as it is on the bed: what the passes
    do not take stays, design or not. ``copper`` and ``nets`` are the
    board's polygons and their net names (``Board.copper_nets``); without
    names each polygon counts as its own net, which is the careful reading.
    ``radius`` is the cutter's.
    """
    from shapely.geometry import LineString, box
    from shapely.ops import unary_union
    from shapely.strtree import STRtree
    polys = list(getattr(copper, "geoms", [copper]))
    if nets is None or len(nets) != len(polys):
        nets = [{"copper %d" % i} for i in range(len(polys))]
    lines = []
    for tp in paths:
        run = []
        for m in tp:
            if m.rapid:
                if len(run) > 1:
                    lines.append(LineString(run))
                run = []
            else:
                run.append((m.x, m.y))
        if len(run) > 1:
            lines.append(LineString(run))
    whole = box(*sheet) if not hasattr(sheet, "geom_type") else sheet
    left = whole if not lines else whole.difference(
        unary_union(lines).buffer(max(radius - 0.002, 0.001)))
    pieces = [g for g in getattr(left, "geoms", [left])
              if g.geom_type == "Polygon" and not g.is_empty]
    if not pieces:
        return []
    tree = STRtree(pieces)
    names = {}
    for poly, net in zip(polys, nets):
        if not net:
            continue
        pt = poly.representative_point()
        for i in tree.query(pt):
            if pieces[int(i)].contains(pt):
                names.setdefault(int(i), set()).update(net)
                break
    return [sorted(n) for n in names.values() if len(n) > 1]
