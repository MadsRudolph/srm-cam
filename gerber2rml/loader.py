"""Gerber/Excellon loading.

Reads a folder of KiCad-exported Gerbers + the Excellon drill file with
``gerbonara``, converts copper / outline / holes into ``shapely`` geometry,
mirrors for bottom-up single-sided milling, and detects/validates units.

## gerbonara API notes (from Task 0 spike, gerbonara 1.5.0)

Verified against the buck board fixture in tests/fixtures/mosfet_test/.
All coordinates are in millimetres (float).  The fixture was exported by
KiCad with the standard RS-274X / Excellon settings.

### Opening a directory of Gerbers

    stack = LayerStack.open(path)   # path: str | Path to a dir, file or zip

LayerStack.open() is a classmethod; the old open_dir() alias also exists but
open() is the canonical entry point.

### Graphic layer dict

The internal store is:

    stack.graphic_layers  ->  dict[(side: str, use: str), GerberFile]

Keys present for a standard KiCad two-layer board:

    ('top',        'copper')
    ('top',        'mask')
    ('top',        'silk')
    ('bottom',     'copper')
    ('bottom',     'mask')
    ('mechanical', 'outline')

Subscript sugar (delegates to graphic_layers after splitting on the space):

    stack[('bottom', 'copper')]   # tuple form
    stack['bottom copper']        # string form — side + ' ' + use

### Bottom copper layer

    b_cu = stack.graphic_layers[('bottom', 'copper')]  # GerberFile
    # or equivalently:
    b_cu = stack['bottom copper']

    b_cu.objects   -> list of graphic objects

Object classes present on B.Cu (buck fixture):
    Line   (68)  — routed traces
    Flash  (27)  — pad flashes
    Region (14)  — copper pours / filled zones
    Arc objects were NOT present in this fixture (arcs are uncommon in KiCad
    exports for standard boards but are possible).

### Edge.Cuts / board outline layer

    outline = stack.graphic_layers[('mechanical', 'outline')]  # GerberFile
    # The .outline property is a shortcut that returns the same object:
    outline = stack.outline

    outline.objects  -> list — Line objects forming the board perimeter.

### Drill / Excellon data

KiCad exports a single combined (mixed-plating) drill file.  gerbonara
places it in a private list rather than the named attributes:

    stack.drill_pth   -> None   (set only when gerbonara sees an explicit
    stack.drill_npth  -> None    PTH-only or NPTH-only file)
    stack.drill_mixed -> None   (not used for KiCad mixed files)

    stack._drill_layers  -> list[ExcellonFile]  (always populated)
    drill_file = stack._drill_layers[0]

    drill_file.objects  -> list[Flash]
    # Each Flash represents one drill hit:
    hit = drill_file.objects[0]
    hit.x                   -> float  (mm)
    hit.y                   -> float  (mm)
    hit.aperture            -> ExcellonTool
    hit.aperture.diameter   -> float  (mm)

The generator property drill_layers (no underscore) yields all drill files,
but is a generator — not a list.  Prefer _drill_layers for indexed access.

### Graphic object attributes

**Line** (routed trace):
    line.x1, line.y1, line.x2, line.y2   -> float (mm)
    line.p1, line.p2                       -> (float, float) tuple shortcuts
    line.aperture                          -> CircleAperture (always for lines)
    line.aperture.diameter                 -> float (mm) — the stroke width

**Flash** (pad):
    flash.x, flash.y           -> float (mm) — centre position
    flash.aperture             -> one of:
        CircleAperture       -> .diameter (float, mm)
        RectangleAperture    -> .w, .h    (float, mm)
        ObroundAperture      -> .w, .h    (float, mm)
        ApertureMacroInstance -> complex shape; use .flash() to get primitives

    Aperture types observed on B.Cu flash objects (buck fixture):
        CircleAperture, RectangleAperture, ObroundAperture, ApertureMacroInstance

    For Task 4 (loader), the safe approach for arbitrary apertures is to call
    aperture.flash(x, y, unit) which returns graphic primitives, or to use
    shapely buffering on a point with radius = diameter/2 for circle pads.

**Region** (copper pour / filled zone):
    region.outline             -> list[(float, float)]  — closed polygon vertices
                                  (the last point is NOT repeated; close manually)
    len(region.outline)        -> can be large (306 points for one pour in the fixture)

    To convert to shapely:  Polygon(region.outline)

### Units

All coordinates from LayerStack.open() are in millimetres by default
(gerbonara normalises units on parse).  ExcellonFile coordinates are also
normalised to mm.  No manual unit conversion is needed.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from gerbonara import LayerStack
from gerbonara.excellon import ExcellonFile
from gerbonara.apertures import (
    ApertureMacroInstance,
    CircleAperture,
    ObroundAperture,
    RectangleAperture,
)
from shapely.affinity import scale, translate as _translate
from shapely.geometry import LineString, Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import polygonize, unary_union

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

HoleTuple = Tuple[float, float, float]  # (x, y, diameter) in mm

_OUTLINE_FALLBACK_STROKE_MM = 0.05


@dataclass
class Board:
    """Shapely representation of a loaded PCB."""

    copper: BaseGeometry    # shapely geometry — union of all B.Cu shapes
    outline: BaseGeometry   # shapely geometry — board perimeter polygon
    holes: list             # drill hits as (x, y, diameter) in mm
    copper_top: BaseGeometry = None  # shapely geometry — union of all F.Cu shapes (empty if absent)


# ---------------------------------------------------------------------------
# Aperture → shapely helpers
# ---------------------------------------------------------------------------

def _circle_aperture(flash) -> object:
    """CircleAperture Flash → filled circle."""
    return Point(flash.x, flash.y).buffer(flash.aperture.diameter / 2)


def _rect_aperture(flash) -> object:
    """RectangleAperture Flash → axis-aligned box."""
    x, y = flash.x, flash.y
    w, h = flash.aperture.w, flash.aperture.h
    return box(x - w / 2, y - h / 2, x + w / 2, y + h / 2)


def _obround_aperture(flash) -> object:
    """ObroundAperture Flash → approximated as a box (v1 approximation).

    True obround = rectangle with semicircular ends.  A box slightly
    over-estimates the copper area, which is conservative for isolation
    milling.
    """
    x, y = flash.x, flash.y
    w, h = flash.aperture.w, flash.aperture.h
    return box(x - w / 2, y - h / 2, x + w / 2, y + h / 2)


def _macro_aperture(flash) -> object:
    """ApertureMacroInstance Flash → bounding-box approximation.

    gerbonara's bounding_box(unit='mm') returns
    ``((xmin_offset, ymin_offset), (xmax_offset, ymax_offset))`` relative to
    the flash centre.  This gives a conservative (slightly over-sized) polygon
    that is safe for isolation milling.
    """
    x, y = flash.x, flash.y
    ap = flash.aperture
    try:
        (xmin_off, ymin_off), (xmax_off, ymax_off) = ap.bounding_box(unit='mm')
        return box(x + xmin_off, y + ymin_off, x + xmax_off, y + ymax_off)
    except Exception:
        # Absolute fallback: 1 mm circle if bounding_box fails
        return Point(x, y).buffer(0.5)


def _flash_to_shapely(flash) -> object | None:
    """Convert a gerber Flash object to shapely geometry.

    Returns None (with a warning) for completely unknown aperture types so
    that the union continues rather than crashing.
    """
    ap = flash.aperture
    if isinstance(ap, CircleAperture):
        return _circle_aperture(flash)
    if isinstance(ap, RectangleAperture):
        return _rect_aperture(flash)
    if isinstance(ap, ObroundAperture):
        return _obround_aperture(flash)
    if isinstance(ap, ApertureMacroInstance):
        return _macro_aperture(flash)
    # Unknown aperture type — use bounding_box if available, else skip
    try:
        (xmin_off, ymin_off), (xmax_off, ymax_off) = ap.bounding_box(unit='mm')
        warnings.warn(
            f"Unknown aperture type {type(ap).__name__!r}; using bounding-box fallback.",
            stacklevel=3,
        )
        return box(
            flash.x + xmin_off, flash.y + ymin_off,
            flash.x + xmax_off, flash.y + ymax_off,
        )
    except Exception:
        warnings.warn(
            f"Unknown aperture type {type(ap).__name__!r} with no bounding-box; skipping.",
            stacklevel=3,
        )
        return None


# ---------------------------------------------------------------------------
# Layer converters
# ---------------------------------------------------------------------------

def _copper_to_shapely(b_cu_layer) -> object:
    """Convert a GerberFile (B.Cu) to a single unioned shapely geometry."""
    shapes = []

    for obj in b_cu_layer.objects:
        obj_type = type(obj).__name__

        if obj_type == 'Line':
            width = obj.aperture.diameter
            ls = LineString([(obj.x1, obj.y1), (obj.x2, obj.y2)])
            shapes.append(ls.buffer(width / 2, cap_style="round"))

        elif obj_type == 'Flash':
            geom = _flash_to_shapely(obj)
            if geom is not None:
                shapes.append(geom)

        elif obj_type == 'Region':
            pts = list(obj.outline)
            if len(pts) < 3:
                continue
            poly = Polygon(pts).buffer(0)
            shapes.append(poly)

        # Arc and other types not seen in the fixture — skip silently.

    if not shapes:
        return Point(0, 0).buffer(0)  # empty geometry

    return unary_union(shapes)


def _outline_to_shapely(outline_layer) -> object:
    """Convert Edge.Cuts lines to a board outline polygon.

    Strategy:
    1. Collect edge Lines as LineString segments.
    2. polygonize() to form closed polygon(s) — works when the outline is a
       clean closed rectangle.
    3. Fallback A: if polygonize yields nothing, buffer the edge lines so the
       cutout engine can still use outline.buffer(r).
    4. Return the largest polygon by area.
    """
    edge_lines = []
    for obj in outline_layer.objects:
        if type(obj).__name__ == 'Line':
            ls = LineString([(obj.x1, obj.y1), (obj.x2, obj.y2)])
            edge_lines.append(ls)

    if not edge_lines:
        return Point(0, 0).buffer(0)

    polys = list(polygonize(edge_lines))
    if polys:
        # Return the largest polygon (boards with slots may yield multiple)
        return max(polys, key=lambda p: p.area)

    # Fallback: buffer union of edge lines to produce a filled region
    combined = unary_union(edge_lines)
    buffered = combined.buffer(_OUTLINE_FALLBACK_STROKE_MM)  # thin stroke to create a filled area
    if buffered.geom_type == 'MultiPolygon':
        return max(buffered.geoms, key=lambda p: p.area)
    return buffered


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def select_drill_holes(
    folder: Path | str,
    outline=None,
    margin: float = 1.0,
) -> List[HoleTuple]:
    """Read drill hits from a Gerber folder with robust file selection.

    Preference order:
    1. KiCad split files (``*-PTH.drl`` / ``*-NPTH.drl`` or ``*_PTH.drl`` /
       ``*_NPTH.drl``) — avoids the doubled-holes bug when a stale combined
       ``<name>.drl`` sits alongside freshly-exported split files.
    2. All ``*.drl`` files when no split files are present.

    After collection, duplicate hits (same x/y/diameter rounded to 3 dp) are
    removed and holes outside the board outline (plus *margin* mm) are dropped.
    """
    folder = Path(folder)
    drl = sorted(folder.glob("*.drl"))
    split = [
        p for p in drl
        if p.stem.upper().endswith(("-PTH", "-NPTH", "_PTH", "_NPTH"))
    ]
    sources = split if split else drl

    holes: List[HoleTuple] = []
    for p in sources:
        ex = ExcellonFile.open(str(p))
        for o in ex.objects:
            if type(o).__name__ == "Flash":
                holes.append((o.x, o.y, getattr(o.aperture, "diameter", 0) or 0))

    # Deduplicate
    seen: set = set()
    uniq: List[HoleTuple] = []
    for h in holes:
        k = (round(h[0], 3), round(h[1], 3), round(h[2], 3))
        if k not in seen:
            seen.add(k)
            uniq.append(h)

    # Filter to outline + margin
    if outline is not None and not outline.is_empty:
        x0, y0, x1, y1 = outline.bounds
        uniq = [
            (x, y, d) for (x, y, d) in uniq
            if x0 - margin <= x <= x1 + margin and y0 - margin <= y <= y1 + margin
        ]

    return uniq


def load_board(folder: Path | str, *, mirror: bool = True) -> Board:
    """Load a KiCad Gerber folder into a ``Board`` of shapely geometry.

    Parameters
    ----------
    folder:
        Directory containing KiCad-exported RS-274X Gerbers and an Excellon
        drill file (``*.drl``).
    mirror:
        When ``True`` (default), mirror all geometry about x=0 using
        ``scale(geom, xfact=-1, origin=(0,0))``.  Required for bottom-up
        single-sided milling where the board is flipped before machining.

    Returns
    -------
    Board
        ``.copper``  — shapely geometry (union of all B.Cu objects).
        ``.outline`` — shapely polygon from Edge.Cuts lines.
        ``.holes``   — list of ``(x, y, diameter)`` tuples in mm.
    """
    folder = Path(folder)
    stack = LayerStack.open(folder)

    # ---- Bottom copper ----
    b_cu = stack.graphic_layers.get(('bottom', 'copper'))
    if b_cu is None:
        raise ValueError(
            f"No bottom-copper layer found in {folder} (expected a B.Cu Gerber)"
        )
    copper = _copper_to_shapely(b_cu)

    # ---- Outline ----
    outline_layer = stack.graphic_layers.get(('mechanical', 'outline'))
    if outline_layer is None:
        raise ValueError(
            f"No outline layer found in {folder} (expected an Edge.Cuts / mechanical outline Gerber)"
        )
    outline = _outline_to_shapely(outline_layer)

    # ---- Drill holes ----
    # select_drill_holes prefers KiCad split (-PTH/-NPTH) files over a stale
    # combined <name>.drl, deduplicates, and filters to the raw (pre-mirror)
    # outline so phantom holes from mis-matched origins are dropped.
    holes: List[HoleTuple] = select_drill_holes(folder, outline=outline)
    if not holes:
        warnings.warn(
            f"No drill file found in {folder}; holes will be empty.",
            stacklevel=2,
        )

    # ---- Top copper (F.Cu) ----
    t_cu = stack.graphic_layers.get(('top', 'copper'))
    copper_top = _copper_to_shapely(t_cu) if t_cu is not None else Polygon()

    # ---- Mirror if requested ----
    if mirror:
        copper = scale(copper, xfact=-1, yfact=1, origin=(0, 0))
        outline = scale(outline, xfact=-1, yfact=1, origin=(0, 0))
        copper_top = scale(copper_top, xfact=-1, yfact=1, origin=(0, 0))
        holes = [(-x, y, d) for x, y, d in holes]

    return Board(copper=copper, outline=outline, holes=holes, copper_top=copper_top)


def place_in_positive_quadrant(board: Board, margin: float = 2.0) -> Board:
    """Translate copper, outline and holes so the board's lower-left corner
    sits at (margin, margin). Machine coordinates (operator zeroes at the board
    corner) expect positive X/Y."""
    geoms = [g for g in (board.copper, board.outline) if not g.is_empty]
    if not geoms:
        return board
    minx = min(g.bounds[0] for g in geoms)
    miny = min(g.bounds[1] for g in geoms)
    dx, dy = margin - minx, margin - miny
    copper_top = board.copper_top if board.copper_top is not None else Polygon()
    return Board(
        copper=_translate(board.copper, xoff=dx, yoff=dy),
        outline=_translate(board.outline, xoff=dx, yoff=dy),
        holes=[(x + dx, y + dy, d) for (x, y, d) in board.holes],
        copper_top=_translate(copper_top, xoff=dx, yoff=dy),
    )
