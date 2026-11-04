"""The laser file for opening solder mask over the pads of a milled board.

The ink goes on the whole copper side and the fiber laser takes it off the pads
again. The laser needs a drawing of those pads: closed shapes it can fill, and
the board outline to place them by, in mm at 1:1. This module makes that drawing
from the same Gerber folder the mill's files came from, so the two cannot be
from different revisions of the board. Nothing here touches the milling files.

Four things decide whether the openings land on the pads:

Real shapes. The loader turns an obround or a rounded pad into its bounding box,
which is the safe mistake for isolation milling and the wrong one here: the
corners of the box would burn the ink off beside the pad. So flashes are expanded
into the aperture's own primitives. A rotated rectangle is built here rather than
with gerbonara's ``Rectangle.to_arc_poly``, which draws its bounding box instead
(checked against gerbonara 1.6.3; the fixture in tests/test_soldermask.py has one).

Smaller than the pad. The mill and the laser are registered by hand, so each
opening is drawn :data:`DEFAULT_SHRINK` mm smaller per side and a small error
leaves ink on the pad's edge rather than bare copper beside it. A pad too small
to survive that is reported, never quietly dropped.

Mirrored like the copper. KiCad plots every layer seen from the top. The milled
face is B.Cu, and it lies face up on the laser exactly as it did on the mill, so
the mask has to be mirrored once, in the same way ``load_board`` mirrors the
copper: x -> -x. The outline goes with it. The operator does not flip anything
in the laser software, and the file name says so.

Named layers, one file. The openings and the outline share a coordinate frame,
and two files would have to be lined up by hand in the laser software. One file
with the outline on its own layer and in its own colour cannot come apart.

The file itself is a small hand-written DXF so the app needs no new dependency
for it. Every loop is a closed LWPOLYLINE with its first point repeated at the
end, so a reader that ignores the closed flag still sees it closed. The container
follows the one KiCad writes (AC1018).
"""
import math
from dataclasses import dataclass, field
from pathlib import Path

from gerbonara import GerberFile
from gerbonara import graphic_primitives as gp
from gerbonara.graphic_objects import Arc, Line
from gerbonara.utils import MM
from shapely.affinity import scale, translate
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from gerber2rml.loader import _find_layer, _outline_to_shapely

DEFAULT_SHRINK = 0.1      # mm per side
MAX_SHRINK = 0.5          # past this the spin box stops; no pad survives it anyway
NARROW_MM = 0.2           # an opening thinner than this is worth a warning
ARC_ERROR_MM = 0.002      # how far a drawn arc may sit from the true one
_SLIVER_MM2 = 1e-4        # what a shrink can leave behind that is not an opening

LAYER_OPENINGS = "MASK_OPENINGS"
LAYER_OUTLINE = "OUTLINE"
# AutoCAD colour numbers: two that read apart from each other on a dark or light
# screen, so a reader that honours colours separates the outline by itself.
_COLOUR = {LAYER_OPENINGS: 5, LAYER_OUTLINE: 1}    # blue, red

_MASK_PATTERNS = {"bottom": ("*-B_Mask.*", "*.gbs"),
                  "top": ("*-F_Mask.*", "*.gts")}
_LAYER_NAME = {"bottom": "B.Mask", "top": "F.Mask"}


class MaskError(ValueError):
    """Why this folder cannot give a mask file, in words for the operator."""


@dataclass
class MaskArtwork:
    """One face's openings and outline, in the laser's frame.

    The outline's lower-left corner is at (0, 0), so the numbers are the same
    whatever origin KiCad plotted from.
    """
    side: str                 # "bottom" or "top"
    source: Path              # the mask Gerber it was read from
    mirrored: bool
    shrink: float             # mm per side
    openings: list            # shapely Polygons
    outline: Polygon
    # (x, y, w, h) of what the shrink affected, in the same frame.
    vanished: list = field(default_factory=list)
    narrow: list = field(default_factory=list)
    outside: int = 0          # openings not touching the board at all

    def warnings(self):
        """What the operator should know about this file, in words."""
        out = []
        if self.vanished:
            first = self.vanished[0]
            out.append(
                f"{len(self.vanished)} opening"
                f"{'' if len(self.vanished) == 1 else 's'} vanished: a "
                f"{first[2]:.2f} × {first[3]:.2f} mm pad at X{first[0]:.2f} "
                f"Y{first[1]:.2f} in the file is too small for a {self.shrink:.2f} mm "
                f"shrink, so it stays under the ink. Lower the shrink, or open "
                f"it by hand.")
        if self.narrow:
            first = self.narrow[0]
            out.append(
                f"{len(self.narrow)} opening"
                f"{'' if len(self.narrow) == 1 else 's'} under "
                f"{NARROW_MM:.2f} mm wide after the shrink, the first at "
                f"X{first[0]:.2f} Y{first[1]:.2f}. Check those pads under a "
                f"loupe once they are open.")
        if self.outside:
            out.append(
                f"{self.outside} opening"
                f"{' lies' if self.outside == 1 else 's lie'} outside the board "
                f"outline. The mask and Edge.Cuts look like they come from "
                f"different plots.")
        return out


def mask_layer_path(folder, side="bottom"):
    """The mask Gerber for ``side`` in ``folder``, or None."""
    return _find_layer(folder, *_MASK_PATTERNS[side])


def _missing_message(folder, side):
    """Name the layer, what is there instead, and the fix."""
    other = "top" if side == "bottom" else "bottom"
    there = mask_layer_path(folder, other)
    return (f"No {_LAYER_NAME[side]} Gerber in {folder}, so there is nothing "
            f"to make the solder mask file from."
            + (f" There is an {_LAYER_NAME[other]} ({there.name}), but that is "
               f"the other face of the board." if there else "")
            + f" In KiCad's Plot dialog, tick {_LAYER_NAME[side]} as well, "
              f"plot into this same folder, and try again.")


def _primitive_to_shapely(p):
    """One gerbonara primitive, in mm, as shapely geometry."""
    if isinstance(p, gp.Circle):
        return Point(p.x, p.y).buffer(p.r)
    if isinstance(p, gp.Rectangle):
        c, s = math.cos(p.rotation), math.sin(p.rotation)
        hw, hh = p.w / 2, p.h / 2
        return Polygon([(p.x + u * c - v * s, p.y + u * s + v * c)
                        for u, v in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh))])
    if isinstance(p, gp.Line):
        return LineString([(p.x1, p.y1), (p.x2, p.y2)]).buffer(p.width / 2)
    if isinstance(p, gp.Arc):
        p = p.to_arc_poly()
    pts = p.approximate_arcs(max_error=ARC_ERROR_MM).outline
    if len(pts) < 3:
        return Polygon()
    return Polygon(pts).buffer(0)


def _read_outline(path):
    """The Edge.Cuts polygon, in mm. The loader's helper reads coordinates off
    the objects as they stand, so a plot in inches is converted before it gets
    there, or the outline comes out 25.4 times small."""
    layer = GerberFile.open(str(path))
    layer.objects = [o.converted(MM) if isinstance(o, (Line, Arc)) else o
                     for o in layer.objects]
    return _outline_to_shapely(layer)


def _layer_to_shapely(layer):
    """Everything drawn on a Gerber layer, in order, as one geometry.

    Order matters: a clear object only clears what was drawn before it, so dark
    runs are unioned and each clear one is subtracted as it comes.
    """
    drawn = Polygon()
    run = []
    for obj in layer.objects:
        for prim in obj.to_primitives(MM):
            g = _primitive_to_shapely(prim)
            if prim.polarity_dark:
                run.append(g)
            else:
                drawn = unary_union([drawn, *run]).difference(g)
                run = []
    return unary_union([drawn, *run])


def _polygons(g):
    """The polygons of a geometry, ignoring lines and points."""
    if g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    return [p for p in getattr(g, "geoms", []) if isinstance(p, Polygon)]


def _width(poly):
    """How wide a shape is across its narrowest direction."""
    r = poly.minimum_rotated_rectangle
    if r.geom_type != "Polygon":
        return 0.0
    x, y = r.exterior.coords.xy
    return min(math.dist((x[0], y[0]), (x[1], y[1])),
               math.dist((x[1], y[1]), (x[2], y[2])))


def _size(poly):
    x0, y0, x1, y1 = poly.bounds
    return x1 - x0, y1 - y0


def build_mask(folder, *, side="bottom", shrink=DEFAULT_SHRINK, mirror=True):
    """Read one face's mask and the outline from a Gerber folder.

    Raises :class:`MaskError` when the folder cannot give a file: the layer is
    missing or empty, or there is no outline to place it by. ``mirror`` is whether
    the job's copper is mirrored, so the mask matches what the mill cut.
    """
    folder = Path(folder)
    if shrink < 0:
        raise MaskError("The shrink cannot be negative: the openings would be "
                        "bigger than the pads.")
    path = mask_layer_path(folder, side)
    if path is None:
        raise MaskError(_missing_message(folder, side))
    edge = _find_layer(folder, "*-Edge_Cuts.*", "*.gm1")
    if edge is None:
        raise MaskError(f"No board outline (Edge.Cuts) Gerber in {folder}. The "
                        f"mask file needs it to place the openings on the laser.")
    outline = _read_outline(edge)
    if outline.is_empty:
        raise MaskError(f"{edge.name} has no outline in it.")
    pads = _polygons(_layer_to_shapely(GerberFile.open(str(path))))
    if not pads:
        raise MaskError(
            f"{path.name} is empty: {_LAYER_NAME[side]} has no openings on it. "
            f"Re-plot it from KiCad once the board has its pads.")

    # The whole frame at once, so the openings and the outline stay together.
    if mirror:
        outline = scale(outline, xfact=-1, yfact=1, origin=(0, 0))
        pads = [scale(p, xfact=-1, yfact=1, origin=(0, 0)) for p in pads]
    x0, y0, _, _ = outline.bounds
    outline = translate(outline, -x0, -y0)
    pads = [translate(p, -x0, -y0) for p in pads]

    # Mitred: a concave corner stays square rather than being rounded off.
    # Shrinking after the union, so an opening drawn in several pieces (a pad
    # with a thermal, a region KiCad fractured) shrinks only at its real edge.
    openings, vanished, narrow, outside = [], [], [], 0
    board = outline.buffer(0.01)
    for pad in pads:
        small = (pad.buffer(-shrink, join_style="mitre") if shrink else pad)
        parts = [p for p in _polygons(small) if p.area >= _SLIVER_MM2]
        cx, cy = pad.representative_point().coords[0]
        if not parts:
            vanished.append((cx, cy, *_size(pad)))
            continue
        if not pad.intersects(board):
            outside += 1
        for part in parts:
            if _width(part) < NARROW_MM:
                narrow.append((cx, cy, *_size(part)))
            openings.append(part)
    return MaskArtwork(side=side, source=path, mirrored=mirror, shrink=shrink,
                       openings=openings, outline=outline, vanished=vanished,
                       narrow=narrow, outside=outside)


# ---------------------------------------------------------------------------
# The DXF
# ---------------------------------------------------------------------------

def _rings(poly):
    """Every closed loop of a polygon. A ring inside a pad stays a loop of its
    own, and the laser's compound fill leaves it covered."""
    return [poly.exterior, *poly.interiors]


def _lwpolyline(ring, layer, handle):
    # The ring's last point repeats its first, and that repeat is kept on
    # purpose: see the module's note on closed loops.
    pts = [(round(x, 5), round(y, 5)) for x, y in ring.coords]
    out = ["0", "LWPOLYLINE", "5", f"{handle:X}", "330", "1F",
           "100", "AcDbEntity", "8", layer, "62", str(_COLOUR[layer]),
           "100", "AcDbPolyline", "90", str(len(pts)), "70", "1"]
    for x, y in pts:
        out += ["10", f"{x:.5f}", "20", f"{y:.5f}"]
    return out


def _layer_record(name, handle):
    return ["0", "LAYER", "5", f"{handle:X}", "330", "2",
            "100", "AcDbSymbolTableRecord", "100", "AcDbLayerTableRecord",
            "2", name, "70", "0", "62", str(_COLOUR.get(name, 7)),
            "6", "Continuous"]


def _table(name, handle, records=(), extra=()):
    """A symbol table: a head that says how many records, the records, the end."""
    out = ["0", "TABLE", "2", name, "5", f"{handle:X}", "330", "0",
           "100", "AcDbSymbolTable", "70", str(len(records)), *extra]
    for r in records:
        out += r
    return out + ["0", "ENDTAB"]


def dxf_text(art):
    """The artwork as the text of a DXF file: mm, 1:1, two named layers."""
    # Handles 1-2F are the fixed container; entities count up from there.
    h = 0x30
    entities = []
    for poly in art.openings:
        for ring in _rings(poly):
            entities += _lwpolyline(ring, LAYER_OPENINGS, h)
            h += 1
    for ring in _rings(art.outline):
        entities += _lwpolyline(ring, LAYER_OUTLINE, h)
        h += 1

    head = ["0", "SECTION", "2", "HEADER",
            "9", "$ACADVER", "1", "AC1018",
            "9", "$HANDSEED", "5", f"{h:X}",
            "9", "$MEASUREMENT", "70", "1",
            "9", "$INSUNITS", "70", "4",     # millimetres
            "0", "ENDSEC"]
    ltype = lambda name, handle: [
        "0", "LTYPE", "5", f"{handle:X}", "330", "5",
        "100", "AcDbSymbolTableRecord", "100", "AcDbLinetypeTableRecord",
        "2", name, "70", "0", "3", "", "72", "65", "73", "0", "40", "0.0"]
    tables = ["0", "SECTION", "2", "TABLES"]
    tables += _table("VPORT", 3)
    tables += _table("LTYPE", 5, [ltype("ByBlock", 6), ltype("ByLayer", 7),
                                  ltype("Continuous", 8)])
    tables += _table("LAYER", 2, [_layer_record("0", 0x10),
                                  _layer_record(LAYER_OPENINGS, 0x11),
                                  _layer_record(LAYER_OUTLINE, 0x12)])
    tables += _table("STYLE", 0x13, [[
        "0", "STYLE", "5", "14", "330", "13",
        "100", "AcDbSymbolTableRecord", "100", "AcDbTextStyleTableRecord",
        "2", "Standard", "70", "0", "40", "0.0", "41", "1.0", "50", "0.0",
        "71", "0", "42", "2.5", "3", "txt", "4", ""]])
    tables += _table("VIEW", 0x15)
    tables += _table("UCS", 0x16)
    tables += _table("APPID", 0x17, [[
        "0", "APPID", "5", "18", "330", "17",
        "100", "AcDbSymbolTableRecord", "100", "AcDbRegAppTableRecord",
        "2", "ACAD", "70", "0"]])
    tables += _table("DIMSTYLE", 0x19, [[
        "0", "DIMSTYLE", "105", "1A", "330", "19",
        "100", "AcDbSymbolTableRecord", "100", "AcDbDimStyleTableRecord",
        "2", "Standard", "70", "0"]], extra=["100", "AcDbDimStyleTable"])
    block_record = lambda name, handle: [
        "0", "BLOCK_RECORD", "5", f"{handle:X}", "330", "1B",
        "100", "AcDbSymbolTableRecord", "100", "AcDbBlockTableRecord",
        "2", name, "340", "0"]
    tables += _table("BLOCK_RECORD", 0x1B, [block_record("*Model_Space", 0x1F),
                                            block_record("*Paper_Space", 0x1C)])
    tables += ["0", "ENDSEC"]

    def block(name, owner, begin, end):
        return ["0", "BLOCK", "5", begin, "330", owner,
                "100", "AcDbEntity", "8", "0", "100", "AcDbBlockBegin",
                "2", name, "70", "0", "10", "0.0", "20", "0.0", "30", "0.0",
                "3", name, "1", "",
                "0", "ENDBLK", "5", end, "330", owner,
                "100", "AcDbEntity", "8", "0", "100", "AcDbBlockEnd"]
    blocks = ["0", "SECTION", "2", "BLOCKS",
              *block("*Model_Space", "1F", "20", "21"),
              *block("*Paper_Space", "1C", "22", "23"),
              "0", "ENDSEC"]
    objects = ["0", "SECTION", "2", "OBJECTS",
               "0", "DICTIONARY", "5", "24", "330", "0",
               "100", "AcDbDictionary", "281", "1",
               "3", "ACAD_GROUP", "350", "25",
               "0", "DICTIONARY", "5", "25", "330", "24",
               "100", "AcDbDictionary", "281", "1",
               "0", "ENDSEC"]
    pairs = (head + tables + blocks
             + ["0", "SECTION", "2", "ENTITIES", *entities, "0", "ENDSEC"]
             + objects + ["0", "EOF"])
    return "\n".join(pairs) + "\n"


def mask_filename(name, art, *, per_face=False):
    """``<name>_mask_mirrored.dxf``: the name carries the one thing the operator
    must not get wrong in the laser software. ``per_face`` adds the face, for a
    double-sided job that writes two."""
    face = f"_{art.side}" if per_face else ""
    state = "mirrored" if art.mirrored else "not_mirrored"
    return f"{name}_mask{face}_{state}.dxf"


def write_mask_dxf(art, out_dir, name, *, per_face=False):
    """Write one face's file into ``out_dir``. Returns its path."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / mask_filename(name, art, per_face=per_face)
    path.write_text(dxf_text(art), encoding="ascii")
    return path


def write_mask_files(folder, out_dir, name, *, shrink=DEFAULT_SHRINK,
                     mirror=True, double_sided=False):
    """Write the job's mask file or files. Returns ``[(path, artwork), ...]``.

    The board's side comes from the job, as it does for the copper: the loader
    always mills B.Cu, so a single-sided job is B.Mask, and a missing one raises
    :class:`MaskError`. It follows ``mirror``, so a job loaded with Mirror off
    gets an unmirrored file, like its copper.

    A double-sided job gets a file per face. The bottom is always mirrored,
    because the double-sided writer always mirrors that copper. The top is drawn
    as plotted, because KiCad plots from the top and that face lies face up.
    """
    if not double_sided:
        art = build_mask(folder, shrink=shrink, mirror=mirror)
        return [(write_mask_dxf(art, out_dir, name), art)]
    bottom = build_mask(folder, side="bottom", shrink=shrink, mirror=True)
    top = build_mask(folder, side="top", shrink=shrink, mirror=False)
    return [(write_mask_dxf(a, out_dir, name, per_face=True), a)
            for a in (bottom, top)]
