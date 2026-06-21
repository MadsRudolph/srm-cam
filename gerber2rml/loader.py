"""Gerber/Excellon loading.

Reads a folder of KiCad-exported Gerbers + the Excellon drill file with
``gerbonara``, converts copper / outline / holes into ``shapely`` geometry,
mirrors for bottom-up single-sided milling, and detects/validates units.

Stub — see ``docs/design.md`` §3-4.

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
