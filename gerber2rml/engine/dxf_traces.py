"""Copper traces from a DXF, for the xTool laser page.

A board drawn outside KiCad (Fusion, LibreCAD, Inkscape, an old project) often
only exists as a DXF. This reads one into the same :class:`xtool.LaserArt` a
Gerber folder gives, so everything on the laser page works on it: isolation,
the recipe, Align and the proof on the drilled holes.

What a DXF means here, decided by layer name first and by shape second:

* **Outline**: a layer whose name has edge, outline, profile, border or contour
  in it. Without one, a closed shape that holds everything else is the
  outline. Without that either, the copper's extent plus 1 mm.
* **Drills**: circles on a layer named for drills or holes (drill, hole, PTH,
  NPTH). On any other layer, a circle that sits inside a piece of copper (a
  pad with a hole in it) is a drill too.
* **Copper**: everything else. If some layers are named for copper (F.Cu,
  B.Cu, Copper, Top/Bottom copper) only those count, and when both faces are
  there the face chosen on the page picks its own layer. Closed shapes are
  filled, nested ones cut holes (even-odd, as a DXF viewer fills them); lines
  and arcs that join end to end into a closed loop are filled the same way.
  Lines with a width are tracks of that width; lines without one that do not
  close are tracks of :data:`DEFAULT_TRACK_MM`.

Read: LINE, ARC, CIRCLE, ELLIPSE, LWPOLYLINE and POLYLINE (bulges, widths),
SPLINE, SOLID, and INSERT of blocks (moved, scaled and turned). Units follow
``$INSUNITS``; a drawing without units is taken as mm. No new dependency:
the format is read by hand, as engine/soldermask.py writes it by hand.
"""
import math
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_TRACK_MM = 0.25     # an open line with no width is a track this wide
JOIN_MM = 0.01              # ends this close are the same point
ARC_TOL_MM = 0.005          # chord error when an arc becomes straight lines
NO_OUTLINE_MARGIN_MM = 1.0

# $INSUNITS -> mm. 0 (unitless) is taken as mm.
_UNITS = {0: 1.0, 1: 25.4, 2: 304.8, 4: 1.0, 5: 10.0, 6: 1000.0,
          8: 25.4e-6, 9: 0.0254, 10: 914.4, 13: 0.001, 14: 100.0}
_UNIT_NAME = {1: "inches", 2: "feet", 5: "cm", 6: "metres", 8: "microinches",
              9: "mils", 10: "yards", 13: "microns", 14: "decimetres"}


class DxfError(ValueError):
    """The file cannot be read as a DXF drawing of a board."""


# ---------------------------------------------------------------------------
# Reading the file: group code / value pairs into entities
# ---------------------------------------------------------------------------

@dataclass
class _Ent:
    kind: str
    tags: list                      # [(code, value-string), ...]
    children: list = field(default_factory=list)    # VERTEXes of a POLYLINE

    def get(self, code, default=None):
        for c, v in self.tags:
            if c == code:
                return v
        return default

    def num(self, code, default=0.0):
        v = self.get(code)
        try:
            return float(v) if v is not None else default
        except ValueError:
            return default

    def all(self, code):
        return [v for c, v in self.tags if c == code]

    @property
    def layer(self):
        return (self.get(8) or "0").strip()


def _pairs(text):
    lines = text.splitlines()
    for i in range(0, len(lines) - 1, 2):
        try:
            code = int(lines[i].strip())
        except ValueError:
            raise DxfError(f"Line {i + 1} should be a group code, not "
                           f"{lines[i].strip()[:30]!r}: not an ASCII DXF.")
        yield code, lines[i + 1].strip()


def _sections(text):
    """{section name: [(code, value), ...]}"""
    out, name, cur = {}, None, None
    it = _pairs(text)
    for code, val in it:
        if code == 0 and val == "SECTION":
            code2, name = next(it, (None, None))
            cur = out.setdefault(name, [])
        elif code == 0 and val == "ENDSEC":
            name, cur = None, None
        elif cur is not None:
            cur.append((code, val))
    return out


def _entities(pairs):
    """Group a section's pairs into entities; VERTEXes go under their
    POLYLINE."""
    ents, cur, poly = [], None, None
    for code, val in pairs:
        if code == 0:
            if cur is not None:
                if cur.kind == "VERTEX" and poly is not None:
                    poly.children.append(cur)
                else:
                    ents.append(cur)
            if val == "SEQEND":
                poly, cur = None, None
                continue
            cur = _Ent(val, [])
            if val == "POLYLINE":
                poly = cur
        elif cur is not None:
            cur.tags.append((code, val))
    if cur is not None and cur.kind != "VERTEX":
        ents.append(cur)
    return ents


def _blocks(pairs):
    """{block name: (base point, [entities])}"""
    out, name, base, body = {}, None, (0.0, 0.0), None
    for e in _entities(pairs):
        if e.kind == "BLOCK":
            name, base, body = e.get(2), (e.num(10), e.num(20)), []
        elif e.kind == "ENDBLK":
            if name is not None:
                out[name] = (base, body)
            name, body = None, None
        elif body is not None:
            body.append(e)
    return out


def _header_units(pairs):
    for i, (code, val) in enumerate(pairs):
        if code == 9 and val == "$INSUNITS" and i + 1 < len(pairs):
            try:
                return int(pairs[i + 1][1])
            except ValueError:
                return 0
    return 0


# ---------------------------------------------------------------------------
# Entities into points (mm, WCS)
# ---------------------------------------------------------------------------

def _arc_points(cx, cy, r, a0, sweep):
    """Points along an arc from angle ``a0`` (radians) through ``sweep``,
    within :data:`ARC_TOL_MM` of the true curve."""
    if r <= 0:
        return [(cx, cy)]
    step = 2 * math.acos(max(-1.0, 1 - ARC_TOL_MM / r)) if r > ARC_TOL_MM else math.pi / 4
    n = max(2, int(math.ceil(abs(sweep) / max(step, 1e-3))), int(abs(sweep) / (math.pi / 32)))
    pts = [(cx + r * math.cos(a0 + sweep * i / n), cy + r * math.sin(a0 + sweep * i / n))
           for i in range(n + 1)]
    if abs(abs(sweep) - 2 * math.pi) < 1e-12:
        pts[-1] = pts[0]                # closed exactly, not 1e-16 short
    return pts


def _bulge_points(p1, p2, b):
    """The arc a polyline bulge ``b`` draws from p1 to p2, without p1."""
    if abs(b) < 1e-9:
        return [p2]
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    c = math.hypot(dx, dy)
    if c < 1e-12:
        return [p2]
    theta = 4 * math.atan(b)
    r = abs(c / (2 * math.sin(theta / 2)))
    h = c / (2 * math.tan(theta / 2))
    mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
    cx, cy = mx - h * dy / c, my + h * dx / c
    a0 = math.atan2(p1[1] - cy, p1[0] - cx)
    pts = _arc_points(cx, cy, r, a0, theta)[1:]
    pts[-1] = p2
    return pts


def _bspline(degree, knots, ctrl, weights, n_out):
    """Points along a (rational) B-spline, by de Boor."""
    k = degree
    if len(ctrl) <= k or len(knots) != len(ctrl) + k + 1:
        return list(ctrl)
    w = weights if len(weights) == len(ctrl) else [1.0] * len(ctrl)
    hom = [(x * wi, y * wi, wi) for (x, y), wi in zip(ctrl, w)]
    t0, t1 = knots[k], knots[len(ctrl)]
    out = []
    for i in range(n_out + 1):
        t = t0 + (t1 - t0) * i / n_out
        s = k
        while s < len(ctrl) - 1 and t >= knots[s + 1]:
            s += 1
        d = [list(hom[j + s - k]) for j in range(k + 1)]
        for r in range(1, k + 1):
            for j in range(k, r - 1, -1):
                lo, hi = knots[j + s - k], knots[j + 1 + s - r]
                a = 0.0 if hi == lo else (t - lo) / (hi - lo)
                d[j] = [(1 - a) * d[j - 1][q] + a * d[j][q] for q in range(3)]
        x, y, wt = d[k]
        out.append((x / wt, y / wt) if wt else (x, y))
    return out


@dataclass
class _Piece:
    """One drawn thing: a path (closed or open) with a width, or a circle."""
    layer: str
    points: list
    closed: bool
    width: float = 0.0
    circle: tuple = None            # (cx, cy, r) when it is a whole circle


def _ocs(ent):
    """A transform for entities drawn in their own coordinate system: with
    the extrusion pointing down (-Z, common from Fusion and SolidWorks) X
    runs the other way."""
    if ent.num(230, 1.0) < 0:
        return lambda p: (-p[0], p[1])
    return lambda p: p


def _pieces(ents, blocks, unsupported, depth=0, xf=None):
    """Every entity as :class:`_Piece`s, in drawing units, WCS."""
    xf = xf or (lambda p: p)
    out = []
    for e in ents:
        k = e.kind
        o = _ocs(e)
        T = lambda p, o=o: xf(o(p))         # noqa: E731
        if k == "LINE":
            out.append(_Piece(e.layer, [xf((e.num(10), e.num(20))),
                                        xf((e.num(11), e.num(21)))], False))
        elif k == "CIRCLE":
            cx, cy, r = e.num(10), e.num(20), e.num(40)
            pts = [T(p) for p in _arc_points(cx, cy, r, 0.0, 2 * math.pi)]
            c = T((cx, cy))
            edge = T((cx + r, cy))
            out.append(_Piece(e.layer, pts, True,
                              circle=(c[0], c[1], math.dist(c, edge))))
        elif k == "ARC":
            a0, a1 = math.radians(e.num(50)), math.radians(e.num(51))
            sweep = (a1 - a0) % (2 * math.pi) or 2 * math.pi
            pts = _arc_points(e.num(10), e.num(20), e.num(40), a0, sweep)
            out.append(_Piece(e.layer, [T(p) for p in pts], False))
        elif k == "ELLIPSE":
            cx, cy = e.num(10), e.num(20)
            mx, my = e.num(11), e.num(21)
            ratio = e.num(40, 1.0)
            t0, t1 = e.num(41, 0.0), e.num(42, 2 * math.pi)
            sweep = (t1 - t0) % (2 * math.pi) or 2 * math.pi
            sign = -1.0 if e.num(230, 1.0) < 0 else 1.0
            nx, ny = -my * ratio * sign, mx * ratio * sign
            n = max(16, int(64 * sweep / (2 * math.pi)))
            pts = [xf((cx + mx * math.cos(t) + nx * math.sin(t),
                       cy + my * math.cos(t) + ny * math.sin(t)))
                   for t in (t0 + sweep * i / n for i in range(n + 1))]
            whole = abs(sweep - 2 * math.pi) < 1e-6
            out.append(_Piece(e.layer, pts, whole))
        elif k in ("LWPOLYLINE", "POLYLINE"):
            flags = int(e.num(70, 0))
            if k == "POLYLINE" and flags & (16 | 64):
                unsupported[k + " mesh"] = unsupported.get(k + " mesh", 0) + 1
                continue
            closed = bool(flags & 1)
            if k == "LWPOLYLINE":
                verts, bulges, cur = [], [], None
                for c, v in e.tags:
                    if c == 10:
                        cur = [float(v), 0.0]
                        verts.append(cur)
                        bulges.append(0.0)
                    elif c == 20 and cur is not None:
                        cur[1] = float(v)
                    elif c == 42 and bulges:
                        bulges[-1] = float(v)
                width = e.num(43, 0.0)
                if not width:
                    starts = [float(v) for v in e.all(40)]
                    if starts and len(set(starts)) == 1:
                        width = starts[0]
                verts = [tuple(v) for v in verts]
            else:
                verts = [(v.num(10), v.num(20)) for v in e.children]
                bulges = [v.num(42) for v in e.children]
                width = e.num(40, 0.0)
            if not verts:
                continue
            pts = [verts[0]]
            n = len(verts)
            for i in range(n - 1 + (1 if closed else 0)):
                pts += _bulge_points(verts[i], verts[(i + 1) % n], bulges[i])
            out.append(_Piece(e.layer, [T(p) for p in pts], closed and n > 2,
                              width=abs(width)))
        elif k == "SPLINE":
            degree = int(e.num(71, 3))
            knots = [float(v) for v in e.all(40)]
            weights = [float(v) for v in e.all(41)]
            ctrl = list(zip((float(v) for v in e.all(10)), (float(v) for v in e.all(20))))
            fit = list(zip((float(v) for v in e.all(11)), (float(v) for v in e.all(21))))
            if ctrl:
                pts = _bspline(degree, knots, ctrl, weights, max(32, 16 * len(ctrl)))
            else:
                pts = fit
            if len(pts) < 2:
                continue
            closed = bool(int(e.num(70, 0)) & 1) or math.dist(pts[0], pts[-1]) < 1e-9
            out.append(_Piece(e.layer, [xf(p) for p in pts], closed))
        elif k in ("SOLID", "TRACE"):
            c = [(e.num(10 + i), e.num(20 + i)) for i in range(4)]
            out.append(_Piece(e.layer, [T(c[0]), T(c[1]), T(c[3]), T(c[2])], True))
        elif k == "INSERT":
            name = e.get(2)
            if name not in blocks or depth > 8:
                unsupported["INSERT"] = unsupported.get("INSERT", 0) + 1
                continue
            (bx, by), body = blocks[name]
            sx, sy = e.num(41, 1.0), e.num(42, 1.0)
            rot = math.radians(e.num(50, 0.0))
            ix, iy = o((e.num(10), e.num(20)))
            cr, sr = math.cos(rot), math.sin(rot)
            flip = e.num(230, 1.0) < 0

            def ins(p, bx=bx, by=by, sx=sx, sy=sy, cr=cr, sr=sr, ix=ix, iy=iy,
                    flip=flip):
                x, y = (p[0] - bx) * sx, (p[1] - by) * sy
                x, y = x * cr - y * sr, x * sr + y * cr
                if flip:
                    x = -x
                return xf((x + ix, y + iy))
            for pc in _pieces(body, blocks, unsupported, depth + 1, ins):
                if pc.layer == "0":         # block contents on 0 take the insert's
                    pc.layer = e.layer
                if pc.circle is not None:
                    # The points are already transformed; the circle is
                    # rebuilt from them.
                    xs = [p[0] for p in pc.points]
                    ys = [p[1] for p in pc.points]
                    ccx, ccy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
                    rr = (max(xs) - min(xs) + max(ys) - min(ys)) / 4
                    if abs((max(xs) - min(xs)) - (max(ys) - min(ys))) > 1e-6 * max(rr, 1):
                        pc.circle = None            # scaled unevenly: an ellipse
                    else:
                        pc.circle = (ccx, ccy, rr)
                out.append(pc)
        elif k in ("TEXT", "MTEXT", "DIMENSION", "POINT", "VIEWPORT", "ATTDEF",
                   "ATTRIB", "LEADER", "MLEADER"):
            continue                        # annotation, not copper
        else:
            unsupported[k] = unsupported.get(k, 0) + 1
    return out


# ---------------------------------------------------------------------------
# Pieces into geometry
# ---------------------------------------------------------------------------

def _chain(paths, tol=JOIN_MM):
    """Join open paths end to end. Returns (closed loops, open paths).

    Ends are looked up in a grid of ``tol`` cells, so a KiCad export of
    ten thousand lines joins in a moment. Where more than two ends meet (a
    trace running into a copper pour) the walk may take either way: the fill
    only counts lines crossed, not which loop they were walked in."""
    from collections import defaultdict
    paths = [list(p) for p in paths if len(p) >= 2]
    n = len(paths)

    def key(pt):
        return (round(pt[0] / tol), round(pt[1] / tol))
    index = defaultdict(list)
    for i, p in enumerate(paths):
        index[key(p[0])].append((i, 0))
        index[key(p[-1])].append((i, 1))
    used = [False] * n

    def take(pt):
        kx, ky = key(pt)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j, end in index.get((kx + dx, ky + dy), ()):
                    if used[j]:
                        continue
                    q = paths[j][0] if end == 0 else paths[j][-1]
                    if math.dist(pt, q) <= tol:
                        used[j] = True
                        return paths[j] if end == 0 else paths[j][::-1]
        return None

    def closed(cur):
        return len(cur) > 2 and math.dist(cur[0], cur[-1]) <= tol

    loops, done = [], []
    for i in range(n):
        if used[i]:
            continue
        used[i] = True
        cur = list(paths[i])
        while not closed(cur):
            nxt = take(cur[-1])
            if nxt is None:
                break
            cur += nxt[1:]
        while not closed(cur):
            nxt = take(cur[0])
            if nxt is None:
                break
            cur = nxt[::-1][:-1] + cur
        if len(cur) > 3 and closed(cur):
            cur[-1] = cur[0]
            loops.append(cur)
        else:
            done.append(cur)
    return loops, done


def _length(points):
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def _unique(pieces):
    """Each shape once, and nothing with no length. CAD exports (KiCad's
    among them) draw some lines and circles twice; filled even-odd, a line
    drawn twice cancels itself and copper and gap swap places beside it.
    Returns (pieces, how many were left out as repeats)."""
    seen, out, twice = set(), [], 0
    for pc in pieces:
        if pc.circle is None and _length(pc.points) <= 1e-9:
            continue
        if pc.circle is not None:
            key = ("c", pc.layer, pc.width) + tuple(round(v, 4) for v in pc.circle)
        else:
            pts = tuple((round(x, 4), round(y, 4)) for x, y in pc.points)
            key = ("p", pc.layer, pc.width, pc.closed, min(pts, pts[::-1]))
        if key in seen:
            twice += 1
            continue
        seen.add(key)
        out.append(pc)
    return out, twice


def _poly(points):
    from shapely.geometry import Polygon
    p = Polygon(points)
    if not p.is_valid:
        p = p.buffer(0)
    return p


def _fill(rings):
    """The area closed ``rings`` enclose, filled even-odd as a DXF viewer
    fills them: a point is inside when a ray from it crosses the lines an odd
    number of times. Rings may touch, share stretches or nest; the drawing is
    cut into its faces and each face is tested on its own."""
    import numpy as np
    from shapely.geometry import MultiLineString, Polygon
    from shapely.ops import polygonize, unary_union
    segs = []
    for r in rings:
        if len(r) < 3:
            continue
        # Snapped to a nanometre: a ring that misses closing by a rounding
        # error is a dangle to polygonize, and its face is lost.
        a = np.round(np.asarray(r, dtype=float), 6)
        if (a[0] != a[-1]).any():
            a = np.vstack([a, a[:1]])
        segs.append(np.hstack([a[:-1], a[1:]]))
    if not segs:
        return Polygon()
    S = np.vstack(segs)
    S = S[(S[:, 0] != S[:, 2]) | (S[:, 1] != S[:, 3])]
    # Noded and dissolved: a stretch drawn twice, even split at different
    # points, is one line here, and is crossed once.
    noded = unary_union(MultiLineString([((a, b), (c, d)) for a, b, c, d in S]))
    parts = []
    for g in getattr(noded, "geoms", [noded]):
        c = np.asarray(g.coords)
        if len(c) > 1:
            parts.append(np.hstack([c[:-1], c[1:]]))
    S = np.vstack(parts)
    x1, y1, x2, y2 = S.T
    faces = polygonize(noded)
    keep = []
    for f in getattr(faces, "geoms", faces):
        if f.area < 1e-9:
            continue
        pt = f.representative_point()
        px, py = pt.x, pt.y
        across = (y1 > py) != (y2 > py)
        xs = x1[across] + (py - y1[across]) * (x2[across] - x1[across]) / (
            y2[across] - y1[across])
        if np.count_nonzero(xs > px) % 2:
            keep.append(f)
    return unary_union(keep) if keep else Polygon()


def _same_shape(a, b, share=0.01):
    if a.is_empty or b.is_empty:
        return False
    return a.symmetric_difference(b).area <= share * max(a.area, b.area)


# Layer roles, by name
_OUTLINE_WORDS = ("edge", "outline", "profile", "border", "contour", "gko", "gm1")
_DRILL_WORDS = ("drill", "hole")
_DRILL_TOKENS = {"pth", "npth", "drl", "via", "vias"}
_COPPER_TOKENS = {"cu", "copper", "fcu", "bcu", "gtl", "gbl"}
_BOTTOM_TOKENS = {"b", "bottom", "back", "bcu", "gbl", "bot"}
_TOP_TOKENS = {"f", "top", "front", "fcu", "gtl"}


def _tokens(name):
    import re
    return [t for t in re.split(r"[^a-z0-9]+", name.lower()) if t]


def layer_role(name):
    """"outline", "drill", "copper-top", "copper-bottom", "copper" or "other"."""
    low, tok = name.lower(), set(_tokens(name))
    if any(w in low for w in _OUTLINE_WORDS):
        return "outline"
    if any(w in low for w in _DRILL_WORDS) or tok & _DRILL_TOKENS:
        return "drill"
    if tok & _COPPER_TOKENS or "copper" in low:
        if tok & _BOTTOM_TOKENS:
            return "copper-bottom"
        if tok & _TOP_TOKENS:
            return "copper-top"
        return "copper"
    return "other"


@dataclass
class DxfBoard:
    """A DXF read as a board, in mm, as drawn (Y up, any origin)."""
    copper: object
    outline: object
    drills: list                    # [(x, y, diameter)]
    notes: list
    faces: tuple                    # the copper faces it has layers for


def read_dxf(path, side="top"):
    """Read ``path`` as a board. ``side`` picks the copper layer when the
    drawing has one for each face."""
    from shapely.geometry import LineString, Point, box
    from shapely.ops import unary_union
    path = Path(path)
    raw = path.read_bytes()
    if raw.startswith(b"AutoCAD Binary DXF"):
        raise DxfError(f"{path.name} is a binary DXF. Save it as an ASCII DXF "
                       f"(any version) and open that.")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")
    secs = _sections(text)
    if "ENTITIES" not in secs:
        raise DxfError(f"{path.name} has no drawing in it (no ENTITIES section).")
    units = _header_units(secs.get("HEADER", []))
    k = _UNITS.get(units, 1.0)
    notes = []
    if units not in (0, 4):
        notes.append(f"{path.name} is drawn in {_UNIT_NAME.get(units, 'other units')}; "
                     f"it is read as mm at {k:g} mm a unit.")
    unsupported = {}
    pieces = _pieces(_entities(secs["ENTITIES"]), _blocks(secs.get("BLOCKS", [])),
                     unsupported)
    for pc in pieces:
        pc.points = [(x * k, y * k) for x, y in pc.points]
        pc.width *= k
        if pc.circle is not None:
            cx, cy, r = pc.circle
            pc.circle = (cx * k, cy * k, r * k)
    pieces, twice = _unique(pieces)
    if twice:
        notes.append(f"{twice} shape{'s are' if twice != 1 else ' is'} drawn twice "
                     f"in {path.name}; each is counted once.")
    if unsupported:
        notes.append("Left out, not read: " + ", ".join(
            f"{n} × {kind}" for kind, n in sorted(unsupported.items()))
            + ". Explode them to lines and arcs if they are copper.")
    if not pieces:
        raise DxfError(f"{path.name} has nothing drawn that the laser can use.")

    roles = {pc.layer: layer_role(pc.layer) for pc in pieces}
    faces = tuple(f for f in ("top", "bottom") if f"copper-{f}" in roles.values())
    named_copper = any(r.startswith("copper") for r in roles.values())

    def is_copper(layer):
        r = roles[layer]
        if not named_copper:
            return r in ("other", "copper")
        if r == "copper":
            return True
        if r in ("copper-top", "copper-bottom"):
            want = side if side in faces else faces[0]
            return r == f"copper-{want}"
        return False

    if named_copper:
        left = sorted({l for l, r in roles.items() if r == "other"})
        if left:
            notes.append("Not copper, left out: layer" + ("s " if len(left) > 1 else " ")
                         + ", ".join(left) + ".")
    if len(faces) == 2:
        want = side if side in faces else faces[0]
        lay = sorted(l for l, r in roles.items() if r == f"copper-{want}")
        notes.append(f"Copper from {', '.join(lay)} ({'F.Cu' if want == 'top' else 'B.Cu'}).")

    # -- outline --
    outline = None
    o_pieces = [pc for pc in pieces if roles[pc.layer] == "outline"]
    if o_pieces:
        loops, _ = _chain([pc.points for pc in o_pieces if not pc.closed])
        g = _fill([pc.points for pc in o_pieces if pc.closed] + loops)
        parts = [p for p in getattr(g, "geoms", [g]) if p.geom_type == "Polygon"]
        if not parts:
            raise DxfError(f"The outline layer in {path.name} does not close: "
                           f"its lines must join end to end.")
        outline = max(parts, key=lambda p: p.area)
        if len(parts) > 1:
            notes.append(f"The outline layer has {len(parts)} separate shapes; "
                         f"the biggest is the board.")

    # -- drills on drill layers --
    drills = []
    for pc in pieces:
        if roles[pc.layer] != "drill":
            continue
        if pc.circle is not None:
            drills.append((pc.circle[0], pc.circle[1], 2 * pc.circle[2]))
        elif pc.closed:
            p = _poly(pc.points)
            if not p.is_empty:
                c = p.centroid
                drills.append((c.x, c.y, 2 * math.sqrt(p.area / math.pi)))

    # -- copper --
    cu = [pc for pc in pieces if is_copper(pc.layer)]
    wide = [pc for pc in cu if pc.width > 0]
    circles = [pc for pc in cu if pc.circle is not None and pc.width == 0]
    shapes = [pc for pc in cu if pc.closed and pc.circle is None and pc.width == 0]
    loops, open_paths = _chain([pc.points for pc in cu
                                if not pc.closed and pc.width == 0])
    rings = [pc.points for pc in shapes] + loops
    polys = [_poly(r) for r in rings]

    # A closed shape around everything else, and no outline layer: the outline.
    if outline is None and polys:
        i_big = max(range(len(polys)), key=lambda i: polys[i].area)
        big = polys[i_big]
        rest = [p for i, p in enumerate(polys) if i != i_big]
        rest += [Point(c.circle[:2]).buffer(c.circle[2]) for c in circles]
        rest += [LineString(p) for p in open_paths if len(p) > 1]
        rest += [LineString(pc.points) for pc in wide if len(pc.points) > 1]
        rest += [Point(x, y) for x, y, _ in drills]
        if rest and big.buffer(JOIN_MM).covers(unary_union(rest)):
            outline = big
            rings = [r for i, r in enumerate(rings) if i != i_big]
            polys = [p for i, p in enumerate(polys) if i != i_big]
            notes.append("No outline layer: the shape drawn round everything is "
                         "taken as the board's edge.")

    # A loop on the copper layer that is the outline itself is not copper.
    if outline is not None:
        keep = [not _same_shape(p, outline) for p in polys]
        if not all(keep):
            notes.append("The board outline is drawn on the copper layer too; it "
                         "is left out, so the laser does not go round the edge.")
        rings = [r for r, k in zip(rings, keep) if k]

    # Filled as a viewer fills it, circles included: a pad drawn as a circle
    # is copper, the hole drawn inside it is not.
    copper_fill = _fill(rings + [c.points for c in circles])

    # A circle empty inside with copper all round it is a drilled hole. The
    # copper is put back over it: a pad is solid, as in a Gerber, and the
    # hole is the drill's.
    holes = []
    for c in circles:
        cx, cy, r = c.circle
        disc = Point(cx, cy).buffer(r, quad_segs=32)
        ring = disc.buffer(min(0.1, r)).difference(disc)
        inside = copper_fill.intersection(disc).area / max(disc.area, 1e-12)
        around = copper_fill.intersection(ring).area / max(ring.area, 1e-12)
        if inside < 0.2 and around > 0.5:
            drills.append((cx, cy, 2 * r))
            holes.append(disc)
    pads = holes

    strokes = [LineString(pc.points).buffer(pc.width / 2, quad_segs=8)
               if len(pc.points) > 1 else Point(pc.points[0]).buffer(pc.width / 2)
               for pc in wide if not pc.closed]
    strokes += [_poly(pc.points).union(LineString(pc.points).buffer(pc.width / 2,
                                                                     quad_segs=8))
                for pc in wide if pc.closed and len(pc.points) > 2]
    thin = [p for p in open_paths if _length(p) > 2 * JOIN_MM]
    if thin:
        strokes += [LineString(p).buffer(DEFAULT_TRACK_MM / 2, quad_segs=8) for p in thin]
        notes.append(f"{len(thin)} open line{'s' if len(thin) != 1 else ''} with no "
                     f"width {'are' if len(thin) != 1 else 'is'} drawn as "
                     f"{DEFAULT_TRACK_MM:g} mm tracks.")
    copper = unary_union([copper_fill, *pads, *strokes])
    if copper.is_empty:
        raise DxfError(f"{path.name} has no copper in it: nothing closed, and no "
                       f"lines, on a copper layer.")

    if outline is None:
        x0, y0, x1, y1 = copper.bounds
        m = NO_OUTLINE_MARGIN_MM
        outline = box(x0 - m, y0 - m, x1 + m, y1 + m)
        notes.append(f"No board outline in {path.name}: the copper's extent plus "
                     f"{m:g} mm is used. Put the edge on a layer named Edge.Cuts "
                     f"or Outline to set it.")

    near = outline.buffer(1.0)
    seen, uniq = set(), []
    for x, y, d in drills:
        key = (round(x, 3), round(y, 3), round(d, 3))
        if key not in seen and near.contains(Point(x, y)):
            seen.add(key)
            uniq.append((x, y, d))
    w, h = outline.bounds[2] - outline.bounds[0], outline.bounds[3] - outline.bounds[1]
    if max(w, h) < 5 and units == 0:
        notes.append(f"The board is only {w:.2f} × {h:.2f} mm: if it was drawn in "
                     f"inches, set the drawing's units to inches and save again.")
    return DxfBoard(copper=copper, outline=outline, drills=uniq, notes=notes,
                    faces=faces)


def build_dxf_traces(path, *, side=None, mirror=None, **recipe):
    """A traces :class:`xtool.LaserArt` from a DXF. The drawing is the board
    seen from above, so the top face is as drawn and the bottom is mirrored
    unless ``mirror`` says otherwise. ``side`` None: the bottom when the only
    copper layer is named for it (KiCad's ``-B_Cu.dxf``), else the top. ``recipe`` passes on to
    :func:`xtool.traces_art` (offsets, kerf, lines_per_cm, strategy,
    spot_drills)."""
    from gerber2rml.engine import xtool
    try:
        board = read_dxf(path, side=side or "top")
    except DxfError as e:
        raise xtool.TracesError(str(e)) from None
    except OSError as e:
        raise xtool.TracesError(f"{Path(path).name} could not be read: {e}") from None
    if side is None:
        side = "bottom" if board.faces == ("bottom",) else "top"
    if mirror is None:
        mirror = side == "bottom"
    copper = board.copper.intersection(board.outline)
    if copper.is_empty:
        raise xtool.TracesError(f"None of the copper in {Path(path).name} is "
                                f"inside its outline.")
    return xtool.traces_art(copper, board.outline, board.drills, side=side,
                            mirror=mirror, notes=board.notes, **recipe)
