"""Double-sided dowel-pin registration: layout + job builder.

Registration references machine-located features, never the board edge. Sheared
FR-4 is never truly square, so any edge- or bracket-based scheme inherits that
error. Two placement modes are offered (see :class:`DowelSpec`):

* ``"fresh"`` — the mill drills two dowel holes through the *stock* (in the
  waste frame just beyond the board, which the cut-out removes) and on into the
  sacrificial bed, all from the same origin as the cut. Seat two dowel pins of
  DIFFERENT diameters (large below, small above). Side-to-side registration is
  guaranteed because both sides reference the same machine-made hole; the grid
  pitch is irrelevant. The different diameters mean the board can only seat one
  way.

* ``"grid"`` — the dowels snap to holes of the bed's threaded grid. The mill
  drills two clearance holes through the stock at chosen grid positions; you
  seat reusable pins in the grid holes below. No fresh bed holes, but
  registration now leans on the grid pitch / origin being accurate, and the
  uniform grid-hole size forces equal-diameter pins — so the flip is keyed by
  ASYMMETRIC pin spacing (and an orientation mark) instead of by diameter.

The board flips about ONE axis and both dowels sit ON that axis, so they are
invariant under the flip: the board lifts off the pins, flips, and drops back
onto the same two pins. ``DowelSpec.placement`` chooses the axis:

* ``"topbottom"`` — dowels above and below the board on its vertical centre
  line; the board flips LEFT-TO-RIGHT about that vertical axis (the default).
* ``"leftright"`` — dowels left and right of the board on its horizontal centre
  line; the board flips TOP-TO-BOTTOM about that horizontal axis.

Pick whichever edge pair has the most waste room for the pins. Because the
bottom is mirrored for bottom-up milling about the SAME axis as the flip,
reflecting the front copper about that axis CANCELS the mirror — so the top
comes out as the plain, un-mirrored F.Cu design (in both preview and the cut)
while still registering after the physical flip.
"""
import math
from dataclasses import dataclass, replace
from pathlib import Path
from shapely.affinity import scale, translate
from gerber2rml.loader import load_board
from gerber2rml.engine.traces import isolate
from gerber2rml.engine.drill import drill_jobs, drill_single_bit
from gerber2rml.engine.cutout import cut_outline
from gerber2rml.backends import BACKENDS, DEFAULT_MACHINE
from gerber2rml.config import TraceJob, DrillJob, CutoutJob

PIN_LARGE = 3.1     # fresh: bottom dowel diameter (mm) — measured metal rod
PIN_SMALL = 1.9     # fresh: top dowel diameter (mm) — measured metal rod
# fresh: mm added to each dowel-HOLE diameter, PER PIN. Dialed in on the fit-test
# coupon (examples/hole_test): the 3.1 mm pin seats perfectly at +0.20, the 1.9 mm
# pin wants a touch tighter at +0.15. The kerf isn't identical at both diameters,
# so the two clearances differ. See memory: srm20-interpolated-hole-undersize.
CLEAR_LARGE = 0.20   # big (3.1 mm) dowel hole oversize
CLEAR_SMALL = 0.15   # small (1.9 mm) dowel hole oversize
DOWEL_BED_DEPTH = 5.0  # fresh: mm the dowel hole goes BELOW the stock into the
                       # sacrificial bed, so the pin has enough bite to stay put.
                       # Was 3.0 but only ~2 mm actually reached, so bumped for a
                       # solid bite. If the bit still can't reach, the work surface
                       # may be near the bottom of Z travel (see memory:
                       # srm20-z-travel-cuttable-range) — lower it, don't just bump.
EDGE_OFFSET = 8.0   # fresh: mm from the board edge to the dowel centre (waste)
GRID_PITCH = 14.2   # grid: hole-to-hole spacing (mm) — set to your measured grid
GRID_PIN = 4.0      # grid: dowel diameter = grid hole size (mm)
GRID_CLEARANCE = 1.5  # grid: min mm from the cut line to the dowel-hole edge


@dataclass
class DowelSpec:
    """How and where to place the two registration dowels.

    ``mode='fresh'`` uses ``pin_large``/``pin_small``/``edge_offset``;
    ``mode='grid'`` uses ``pitch_x``/``pitch_y``/``grid_pin``/``clearance``.
    ``placement`` chooses which edge pair carries the dowels (and hence the flip
    axis): ``"topbottom"`` (above/below, left-right flip) or ``"leftright"``
    (left/right, top-bottom flip).
    """
    mode: str = "fresh"                 # "fresh" | "grid"
    placement: str = "topbottom"        # "topbottom" | "leftright"
    pin_large: float = PIN_LARGE
    pin_small: float = PIN_SMALL
    clearance_large: float = CLEAR_LARGE  # fresh: big hole  = pin_large + this
    clearance_small: float = CLEAR_SMALL  # fresh: small hole = pin_small + this
    edge_offset: float = EDGE_OFFSET
    pitch_x: float = GRID_PITCH
    pitch_y: float = GRID_PITCH
    grid_pin: float = GRID_PIN
    clearance: float = GRID_CLEARANCE
    margin: float = 6.0                 # positive-quadrant / left clearance (mm)


@dataclass
class FiducialSpec:
    """2-4 corner reference holes for measured (non-dowel) registration.

    ``placement='onboard'`` insets the holes ``edge_offset`` mm inside the board
    corners (permanent holes, no oversized stock — works for full-bed boards);
    ``'waste'`` outsets them ``edge_offset`` mm beyond the corners (clean board,
    needs larger stock). ``'manual'`` places them at ``points`` — free positions
    for when neither corner scheme fits the stock (e.g. a large board with waste
    only on some edges). Holes are through-holes drilled stock-only (board
    thickness + ``breakthrough``); they never take the dowel bed bite.
    """
    count: int = 4                     # 2..4
    placement: str = "onboard"         # "onboard" | "waste" | "manual"
    edge_offset: float = 4.0           # inset (onboard) / outset (waste), mm
    hole_diameter: float = 0.8         # mm (drilled with the single bit)
    breakthrough: float = 0.3          # mm past the board, for a clean through-hole
    allow_scale: bool = False          # fit uniform scale too?
    margin: float = 6.0                # positive-quadrant clearance (mm)
    # manual placement: (x, y) pairs in DESIGN-frame board coordinates, relative
    # to the framed board box's lower-left corner. May be negative / beyond the
    # box to sit in the waste. The registration math only needs >=2 points with
    # some spread; the flip axis stays the board centre either way.
    points: tuple = ()


# corner order: FL, FR, BR, BL. count=2 -> FL,BR (diagonal); 3 -> FL,FR,BL.
_CORNER_PICK = {2: (0, 2), 3: (0, 1, 3), 4: (0, 1, 2, 3)}


def _place_fiducials(gx0, gy0, gx1, gy1, spec, mirrored=False):
    """Return (align_holes, flip_pos, dx, dy) for fiducial registration.

    Corners are insets (onboard) or outsets (waste) of the framed board box; the
    whole job is then shifted into the positive quadrant with ``margin``. The
    flip axis stays the board's vertical centre line so the top reflects exactly
    as in the dowel layout.

    ``placement='manual'`` uses ``spec.points`` (design-frame, relative to the
    box's lower-left) verbatim. ``mirrored=True`` says the caller's box is the
    bottom-up MACHINE frame, so manual points are mirrored across the box to
    keep the physical holes where the design-frame preview showed them. Manual
    fiducials are excluded from the positive-quadrant shift — dragging a pin
    must not move the whole job; the bed/stock-fit checks flag out-of-range
    pins instead."""
    cx = (gx0 + gx1) / 2.0
    if spec.placement == "manual" and spec.points:
        w = gx1 - gx0
        picked = [(gx0 + (w - px if mirrored else px), gy0 + py)
                  for (px, py) in spec.points]
        dx, dy = spec.margin - gx0, spec.margin - gy0     # board box only
    else:
        off = spec.edge_offset
        s = -1.0 if spec.placement == "onboard" else 1.0   # onboard insets inward
        corners = [(gx0 - s * off, gy0 - s * off),         # FL
                   (gx1 + s * off, gy0 - s * off),         # FR
                   (gx1 + s * off, gy1 + s * off),         # BR
                   (gx0 - s * off, gy1 + s * off)]         # BL
        n = max(2, min(4, spec.count))
        picked = [corners[i] for i in _CORNER_PICK[n]]
        allminx = min(gx0, min(x for x, _ in picked))
        allminy = min(gy0, min(y for _, y in picked))
        dx, dy = spec.margin - allminx, spec.margin - allminy
    align = [(x + dx, y + dy, spec.hole_diameter) for (x, y) in picked]
    return align, cx + dx, dx, dy


def nominal_top_fiducials(lay):
    """The registration holes reflected into the top-cut frame — where a perfect
    flip puts them, and the ``nominal`` points for ``engine.fiducial.fit_transform``."""
    return [(x, y) for (x, y, _d) in
            reflect_holes(lay.align_holes, lay.axis, lay.flip_pos)]


def _axis_of(spec):
    """Flip-axis orientation implied by the dowel placement: dowels on the
    top/bottom edges flip left-right about a VERTICAL axis; dowels on the
    left/right edges flip top-bottom about a HORIZONTAL axis."""
    return "horizontal" if spec.placement == "leftright" else "vertical"


def reflect_holes(holes, axis, pos):
    """Reflect (x, y, d) hole tuples about the flip line: the vertical line
    x = pos when ``axis == 'vertical'``, else the horizontal line y = pos."""
    if axis == "vertical":
        return [(2 * pos - x, y, d) for (x, y, d) in holes]
    return [(x, 2 * pos - y, d) for (x, y, d) in holes]


def reflect_x(holes, x_axis):
    """Reflect (x, y, d) hole tuples about the vertical line x = x_axis."""
    return reflect_holes(holes, "vertical", x_axis)


def _reflect_geom(geom, axis, pos):
    if axis == "vertical":
        return scale(geom, xfact=-1, yfact=1, origin=(pos, 0))
    return scale(geom, xfact=1, yfact=-1, origin=(0, pos))


def _mirror_all(b, axis):
    """Apply the bottom-up mill mirror to a freshly-loaded (unmirrored) board,
    about the flip axis: mirror X for a vertical axis, mirror Y for a horizontal
    one. Returns (copper, copper_top, outline, holes)."""
    if axis == "vertical":
        m = lambda g: scale(g, xfact=-1, yfact=1, origin=(0, 0))
        holes = [(-x, y, d) for (x, y, d) in b.holes]
    else:
        m = lambda g: scale(g, xfact=1, yfact=-1, origin=(0, 0))
        holes = [(x, -y, d) for (x, y, d) in b.holes]
    return m(b.copper), m(b.copper_top), m(b.outline), holes


def _frame(geoms):
    gx0 = min(g.bounds[0] for g in geoms); gy0 = min(g.bounds[1] for g in geoms)
    gx1 = max(g.bounds[2] for g in geoms); gy1 = max(g.bounds[3] for g in geoms)
    return gx0, gy0, gx1, gy1


def _place_fresh(gx0, gy0, gx1, gy1, spec):
    """Fresh-milled dowels: on the board's vertical centre line, in the waste
    just beyond the bottom (large) and top (small) edges; the whole job is then
    shifted into the positive quadrant with ``margin`` clearance.
    Returns (align_holes, x_axis, dx, dy) in the placed (machine) frame."""
    cx = (gx0 + gx1) / 2.0
    # milled hole runs pin + clearance wide for a slip fit; pin diameter itself
    # is reported in the run plan so you still seat the right rod.
    hole_l = spec.pin_large + spec.clearance_large
    hole_s = spec.pin_small + spec.clearance_small
    align_board = [(cx, gy0 - spec.edge_offset, hole_l),   # bottom (large)
                   (cx, gy1 + spec.edge_offset, hole_s)]   # top (small)
    # The positive-quadrant shift uses the NOMINAL pin extent, NOT the
    # clearance-widened hole, so the placement (and thus the dowel centres) is
    # invariant to the clearances — bump them and re-cut the align holes alone
    # and they land back on the existing holes.
    allminx = min(gx0, cx - spec.pin_large / 2.0)
    allminy = min(gy0 - spec.edge_offset - spec.pin_large / 2.0,
                  gy1 + spec.edge_offset - spec.pin_small / 2.0)
    dx, dy = spec.margin - allminx, spec.margin - allminy
    align = [(x + dx, y + dy, d) for (x, y, d) in align_board]
    return align, cx + dx, dx, dy


def _place_grid(gx0, gy0, gx1, gy1, spec):
    """Grid-seated dowels: the flip axis is the grid column nearest the board
    centre, and the two dowels are grid holes on that column just outside the
    bottom and top edges. Equal diameter (the grid hole size), keyed by
    ASYMMETRIC spacing so the board still seats only one way.
    Origin is the datum grid hole (0, 0). Returns (align, x_axis, dx, dy)."""
    px, py, pin, cl = spec.pitch_x, spec.pitch_y, spec.grid_pin, spec.clearance
    w = gx1 - gx0
    cx = (gx0 + gx1) / 2.0
    # flip-axis grid column, far enough out that the board keeps a left margin
    i_axis = max(1, math.ceil((spec.margin + w / 2.0) / px))
    x_axis = i_axis * px
    dx = x_axis - cx                       # centre the board on that column
    # drop the bottom dowel on grid row 1, sitting clearance+radius below the edge
    dy = py + cl + pin / 2.0 - gy0
    board_top = gy1 + dy
    y_b = py
    bottom_off = (gy0 + dy) - y_b          # == cl + pin/2 by construction
    j_t = math.ceil((board_top + cl + pin / 2.0) / py)
    y_t = j_t * py
    if abs((y_t - board_top) - bottom_off) < 0.5:   # keep the spacing asymmetric
        y_t += py
    align = [(x_axis, y_b, pin), (x_axis, y_t, pin)]
    return align, x_axis, dx, dy


def _place(gx0, gy0, gx1, gy1, spec):
    """Dispatch to the fresh/grid placement. ``_place_fresh``/``_place_grid``
    only ever solve the VERTICAL-axis (top/bottom dowel) case; the horizontal
    (left/right) case is the same problem with X and Y swapped, so we transpose
    the box, solve, and transpose the result back. Mirror-about-X in transposed
    space is mirror-about-Y in real space — exactly the horizontal flip — and the
    geometry mirror is applied separately by :func:`_mirror_all`.
    Returns (align_holes, flip_pos, dx, dy)."""
    fn = _place_grid if spec.mode == "grid" else _place_fresh
    if _axis_of(spec) == "vertical":
        return fn(gx0, gy0, gx1, gy1, spec)
    align_t, axis_t, dxt, dyt = fn(gy0, gx0, gy1, gx1, spec)
    align = [(y, x, d) for (x, y, d) in align_t]
    return align, axis_t, dyt, dxt    # flip_pos is now a y; dx/dy swap back


@dataclass
class DoubleSidedLayout:
    bottom_copper: object  # mirrored B.Cu (milled bottom-up)
    top_copper: object     # plain F.Cu (mirror cancelled by the flip) — as cut
    outline: object
    top_outline: object    # outline reflected about the flip axis
    holes: list            # placed through-holes (bottom frame)
    align_holes: list      # 2 dowel pins on the flip axis (the two waste edges)
    axis: str              # "vertical" (left-right flip) | "horizontal" (top-bottom)
    flip_pos: float        # the flip axis: constant x if vertical, constant y if horizontal
    frame0: tuple = (0.0, 0.0)  # placed lower-left of the framed board box (mm)


def _offset_layout(lay, offset):
    """Translate a layout (both PreviewLayout and DoubleSidedLayout) by (dx, dy)
    mm so the whole job can be placed anywhere on the bed."""
    dx, dy = offset
    if not dx and not dy:
        return lay
    t = lambda g: translate(g, xoff=dx, yoff=dy)
    h = lambda holes: [(x + dx, y + dy, d) for (x, y, d) in holes]
    kw = dict(bottom_copper=t(lay.bottom_copper), top_copper=t(lay.top_copper),
              outline=t(lay.outline), holes=h(lay.holes),
              align_holes=h(lay.align_holes),
              frame0=(lay.frame0[0] + dx, lay.frame0[1] + dy))
    if hasattr(lay, "top_outline"):
        kw["top_outline"] = t(lay.top_outline)
    return replace(lay, **kw)


def _load_rotated(folder, rotate):
    """Load the board (design frame) and rotate it by ``rotate`` degrees, re-
    normalised to the positive quadrant. Rotating here — before the mirror, dowel
    placement and framing — keeps the whole job (board + dowels) consistent, so
    the registration is unchanged for the rotated orientation."""
    b = load_board(folder, mirror=False)
    if rotate % 360:
        from gerber2rml.loader import rotate_board, place_in_positive_quadrant
        b = place_in_positive_quadrant(rotate_board(b, rotate))
    return b


def layout_double_sided(folder, dowels: DowelSpec = None, offset=(0.0, 0.0),
                        rotate=0, registration="dowel", fiducials: FiducialSpec = None):
    dowels = dowels or DowelSpec()
    folder = Path(folder)
    axis = "vertical" if registration == "fiducial" else _axis_of(dowels)
    b = _load_rotated(folder, rotate)
    copper, copper_top, outline_g, holes_raw = _mirror_all(b, axis)  # bottom-up mirror
    geoms = [g for g in (copper, outline_g) if not g.is_empty]
    gx0, gy0, gx1, gy1 = _frame(geoms)
    if registration == "fiducial":
        align_holes, flip_pos, dx, dy = _place_fiducials(
            gx0, gy0, gx1, gy1, fiducials or FiducialSpec(), mirrored=True)
    else:
        align_holes, flip_pos, dx, dy = _place(gx0, gy0, gx1, gy1, dowels)
    bottom_copper = translate(copper, xoff=dx, yoff=dy)
    top_src = translate(copper_top, xoff=dx, yoff=dy)
    outline = translate(outline_g, xoff=dx, yoff=dy)
    holes = [(x + dx, y + dy, d) for (x, y, d) in holes_raw]
    top_copper = _reflect_geom(top_src, axis, flip_pos)
    top_outline = _reflect_geom(outline, axis, flip_pos)
    return _offset_layout(
        DoubleSidedLayout(bottom_copper, top_copper, outline, top_outline,
                          holes, align_holes, axis, flip_pos,
                          frame0=(gx0 + dx, gy0 + dy)), offset)


@dataclass
class PreviewLayout:
    """Design-frame layout for the on-screen preview only (NOT the cut). Both
    copper layers and the holes are in their true KiCad coordinates, so they
    register: holes land on pads and the top reads as the plain F.Cu. The
    physical mirror (bottom-up) and the left-right flip are applied only at
    export time in :func:`build_double_sided`."""
    bottom_copper: object  # B.Cu as KiCad exports it (X-ray view)
    top_copper: object     # F.Cu, true/plain
    outline: object
    holes: list
    align_holes: list      # 2 dowel pins on the flip axis (the two waste edges)
    axis: str
    flip_pos: float
    frame0: tuple = (0.0, 0.0)  # placed lower-left of the framed board box (mm)


def preview_layout_double_sided(folder, dowels: DowelSpec = None, offset=(0.0, 0.0),
                                rotate=0, registration="dowel",
                                fiducials: FiducialSpec = None):
    """Layout for the preview: load WITHOUT mirroring so both copper layers and
    the holes sit in the same design frame and overlay correctly."""
    dowels = dowels or DowelSpec()
    folder = Path(folder)
    b = _load_rotated(folder, rotate)      # design frame: F.Cu true, B.Cu X-ray
    geoms = [g for g in (b.copper, b.outline) if not g.is_empty]
    gx0, gy0, gx1, gy1 = _frame(geoms)
    if registration == "fiducial":
        align_holes, flip_pos, dx, dy = _place_fiducials(
            gx0, gy0, gx1, gy1, fiducials or FiducialSpec())
    else:
        align_holes, flip_pos, dx, dy = _place(gx0, gy0, gx1, gy1, dowels)
    bottom_copper = translate(b.copper, xoff=dx, yoff=dy)
    top_copper = translate(b.copper_top, xoff=dx, yoff=dy)
    outline = translate(b.outline, xoff=dx, yoff=dy)
    holes = [(x + dx, y + dy, d) for (x, y, d) in b.holes]
    align_holes = [(x, y, d) for (x, y, d) in align_holes]
    axis = "vertical" if registration == "fiducial" else _axis_of(dowels)
    return _offset_layout(
        PreviewLayout(bottom_copper, top_copper, outline, holes,
                      align_holes, axis, flip_pos,
                      frame0=(gx0 + dx, gy0 + dy)), offset)


def _align_drill(drill, dowels, align_depth, board_thickness,
                 bed_depth=DOWEL_BED_DEPTH):
    """Drill spec for the dowel/align holes (single bit, interpolated to the hole
    diameter). Fresh dowels go through the stock AND ``bed_depth`` mm into the bed;
    grid dowels only clear the stock (the grid hole is already there)."""
    if align_depth is None:
        # fresh: through the stock + the bed bite (adapts to stock thickness).
        # grid: just clear the stock onto the pin already in the grid.
        align_depth = (board_thickness + bed_depth if dowels.mode == "fresh"
                       else board_thickness + 1.0)
    return replace(drill, total_depth=align_depth, single_bit=True), align_depth


def _fiducial_align_drill(drill, fiducials, board_thickness):
    """Drill spec for fiducial holes: through the stock + a small breakthrough,
    single bit. NO bed bite (that is the dowel-only behaviour)."""
    depth = board_thickness + fiducials.breakthrough
    return replace(drill, total_depth=depth, single_bit=True), depth


def build_align_only(folder, out_dir, name, drill=None, dowels: DowelSpec = None,
                     align_depth: float = None, board_thickness: float = 1.6,
                     machine=DEFAULT_MACHINE, offset=(0.0, 0.0), rotate=0,
                     bed_depth=DOWEL_BED_DEPTH):
    """Build ONLY the dowel-hole (align) toolpath — nothing else.

    For the test-fit loop: cut the dowel holes, check the rods seat; if they
    bind, bump ``dowels.clearance_large`` / ``clearance_small`` and re-run THIS to
    re-cut just the holes a touch wider. The dowel centres are invariant to the
    clearances (see :func:`_place_fresh`), so the re-cut lands back on the existing
    holes as long as the XY origin is unchanged. Returns the single Path written.
    """
    dowels = dowels or DowelSpec()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    drill = drill or DrillJob()
    backend = BACKENDS[machine]
    lay = layout_double_sided(folder, dowels=dowels, offset=offset, rotate=rotate)
    align_drill, _ = _align_drill(drill, dowels, align_depth, board_thickness, bed_depth)
    out = out_dir / f"{name}_align{backend.ext}"
    out.write_text(backend.render(
        drill_single_bit(lay.align_holes, align_drill),
        xy_feed=align_drill.xy_feed, plunge_feed=align_drill.plunge_feed))
    return out


def build_double_sided(folder, out_dir, name, trace=None, drill=None, cutout=None,
                       dowels: DowelSpec = None, align_depth: float = None,
                       board_thickness: float = 1.6, machine=DEFAULT_MACHINE,
                       offset=(0.0, 0.0), level=None, rotate=0,
                       bed_depth=DOWEL_BED_DEPTH,
                       registration="dowel", fiducials: FiducialSpec = None,
                       lead_in=True):
    """Build all job files for a double-sided board + a text run plan.

    ``machine`` selects the output backend (RML or G-code). Returns a list of
    Path objects for every file written (5 toolpath files + 1 .txt).

    ``level`` (optional) is a height-map callable ``hmap(x, y) -> dz`` measured in
    the BOTTOM-side machine frame. It warps the Z of the operations cut in that
    setup — the dowel/align holes, bottom drill, bottom traces and the cut-out —
    but NOT the top traces, which are milled after the flip on the other face
    (that surface isn't the one we probed; it would need a second probe pass).
    """
    dowels = dowels or DowelSpec()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    trace = trace or TraceJob()
    drill = drill or DrillJob()
    cutout = cutout or CutoutJob()
    backend = BACKENDS[machine]          # (render fn, file extension)
    ext = backend.ext
    lay = layout_double_sided(folder, dowels=dowels, offset=offset, rotate=rotate,
                              registration=registration, fiducials=fiducials)
    top_outline = lay.top_outline
    if registration == "fiducial":
        fiducials = fiducials or FiducialSpec()
        align_drill, align_depth = _fiducial_align_drill(drill, fiducials,
                                                         board_thickness)
    else:
        align_drill, align_depth = _align_drill(drill, dowels, align_depth,
                                                board_thickness, bed_depth)
    from gerber2rml.engine.estimate import estimate_toolpaths_seconds, format_duration
    from gerber2rml.engine.leadin import apply_lead_in
    _leadin = apply_lead_in if lead_in else (lambda p: p)
    written = []
    est = {}                                     # fname -> estimated seconds

    def _write(fname, paths, job, leveled=False):
        if level is not None and leveled:
            from gerber2rml.engine.leveling import apply_leveling
            paths = apply_leveling(paths, level)   # warp Z to the probed surface
        (out_dir / fname).write_text(
            backend.render(paths, xy_feed=job.xy_feed, plunge_feed=job.plunge_feed))
        est[fname] = estimate_toolpaths_seconds(paths, job.xy_feed, job.plunge_feed)
        written.append(out_dir / fname)

    # Bottom-side setup (the probed surface) -> leveled. Top traces are cut after
    # the flip on the other face, so they are NOT leveled.
    _write(f"{name}_align{ext}", drill_single_bit(lay.align_holes, align_drill),
           align_drill, leveled=True)
    bottom_drill_files = drill_jobs(lay.holes, drill, f"{name}_bottom_drill", ext=ext)
    for fname, paths in bottom_drill_files:
        _write(fname, paths, drill, leveled=True)
    _write(f"{name}_bottom_traces{ext}",
           _leadin(isolate(lay.bottom_copper, trace, outline=lay.outline)),
           trace, leveled=True)
    _write(f"{name}_top_traces{ext}",
           _leadin(isolate(lay.top_copper, trace, outline=top_outline)),
           trace, leveled=False)
    _write(f"{name}_cutout{ext}",
           _leadin(cut_outline(lay.outline, cutout)), cutout, leveled=True)

    drill_step = _drill_runplan_line(bottom_drill_files, drill)
    level_block = ("Bed leveling applied to the BOTTOM-side jobs (align, drill, "
                   "bottom traces, cut-out); top traces are NOT leveled (cut after "
                   "the flip).\n" if level is not None else "")
    est_block = (level_block
                 + "Estimated run time (excludes tool changes, spin-up and pauses):\n"
                 + "".join(f"   {fn}: ~{format_duration(est[fn])}\n"
                           for fn in (p.name for p in written) if fn in est)
                 + f"   TOTAL: ~{format_duration(sum(est.values()))}\n")
    runplan = out_dir / f"{name}_runplan.txt"
    if registration == "fiducial":
        rp = _fiducial_runplan_text(name, machine, lay, fiducials or FiducialSpec(),
                                    drill_step, align_depth, board_thickness)
    else:
        rp = _runplan_text(name, machine, lay, dowels, drill_step,
                           align_depth, board_thickness)
    runplan.write_text(rp + est_block, encoding="utf-8")
    written.append(runplan)
    return written


def build_top_traces(folder, out_dir, name, trace=None, dowels: DowelSpec = None,
                     machine=DEFAULT_MACHINE, offset=(0.0, 0.0), rotate=0, level=None,
                     registration="dowel", fiducials: FiducialSpec = None,
                     measured_fiducials=None, allow_scale=False, lead_in=True):
    """Re-export ONLY the top (F.Cu) isolation traces, optionally warped by a
    fiducial fit and/or a fresh height map probed on the FLIPPED board.

    Top-side leveling is a two-phase thing: the full export writes the top traces
    UNleveled (you can't probe that face until you flip). After the flip + a
    top-side probe you call this to overwrite ``<name>_top_traces`` with a copy
    warped to the just-measured surface. ``level`` is a height map in the TOP
    machine frame (the frame the top traces are cut in).

    For FIDUCIAL registration, pass ``measured_fiducials`` (the probed X/Y of the
    corner holes after the flip): the top toolpaths are first warped by the
    best-fit transform (rotation + translation, plus uniform scale if
    ``allow_scale``) from the nominal top-frame fiducials to the measured ones,
    then leveled. XY comes from the fit; Z from leveling. Returns the Path written.
    """
    dowels = dowels or DowelSpec()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    trace = trace or TraceJob()
    backend = BACKENDS[machine]
    lay = layout_double_sided(folder, dowels=dowels, offset=offset, rotate=rotate,
                              registration=registration, fiducials=fiducials)
    paths = isolate(lay.top_copper, trace, outline=lay.top_outline)
    if lead_in:
        from gerber2rml.engine.leadin import apply_lead_in
        paths = apply_lead_in(paths)
    if measured_fiducials:
        from gerber2rml.engine.fiducial import fit_transform, apply_to_toolpaths
        nom = nominal_top_fiducials(lay)[:len(measured_fiducials)]
        t = fit_transform(nom, measured_fiducials, allow_scale=allow_scale)
        paths = apply_to_toolpaths(paths, t)   # warp XY to the measured flip
    if level is not None:
        from gerber2rml.engine.leveling import apply_leveling
        paths = apply_leveling(paths, level)   # warp Z to the flipped-side surface
    out = out_dir / f"{name}_top_traces{backend.ext}"
    out.write_text(backend.render(paths, xy_feed=trace.xy_feed,
                                  plunge_feed=trace.plunge_feed))
    return out


def _runplan_text(name, machine, lay, dowels, drill_step, align_depth, thickness):
    (bx, by, bd), (tx, ty, td) = lay.align_holes
    horiz = lay.axis == "horizontal"
    lo, hi = ("LEFT", "RIGHT") if horiz else ("BOTTOM", "TOP")
    flip_dir = ("TOP-TO-BOTTOM about the horizontal pin line" if horiz
                else "LEFT-TO-RIGHT about the vertical pin line")
    mark = (f"mark the LEFT edge so you flip about the horizontal (not vertical)" if horiz
            else f"mark the bottom edge so you flip about the vertical (not horizontal)")
    bigger = "wider" if horiz else "taller"
    centre = "horizontal centre line" if horiz else "centre line"
    head = (f"DOUBLE-SIDED run plan: {name}  [{machine}]  registration: {dowels.mode}"
            f"  dowels: {dowels.placement}\n\n")
    common_tail = (
        f"3. FLIP the board {flip_dir} and drop it back\n"
        f"   onto the pins. Re-zero Z on the new surface.\n"
        f"   (Bed leveling: to level this side too, re-probe now in View=Top and\n"
        f"    use 'Export top traces (leveled)' to refresh {name}_top_traces.)\n"
        f"4. {name}_top_traces: plain F.Cu, already reflected so it aligns after the flip.\n"
        f"5. {name}_cutout LAST: frees the board from the waste/dowels (leave the tabs).\n")
    if dowels.mode == "grid":
        px, py = dowels.pitch_x, dowels.pitch_y
        return head + (
            f"GRID mode: pins live in the bed's threaded grid; nothing is drilled into\n"
            f"  the bed. Dowel holes (grid cells, from the datum hole = origin):\n"
            f"    {lo.lower():<6} X{bx:.2f} Y{by:.2f}  ~ col {round(bx/px)}, row {round(by/py)}\n"
            f"    {hi.lower():<6} X{tx:.2f} Y{ty:.2f}  ~ col {round(tx/px)}, row {round(ty/py)}\n"
            f"  Both {bd:.1f} mm. Spacing is asymmetric so the board seats only one way;\n"
            f"  still {mark}.\n"
            f"\n"
            f"0. Set XY origin EXACTLY on the datum grid hole you call (0,0). RE-ZERO Z\n"
            f"   after every bit change AND after the flip.\n"
            f"1. Clamp the stock over the work area with the grid screws. Seat the two\n"
            f"   {bd:.1f} mm pins in the grid holes above.\n"
            f"2. {name}_align: drills the two clearance holes {align_depth:.1f} mm through the\n"
            f"   stock down onto the pins. Bottom side: {drill_step}. Then {name}_bottom_traces.\n"
            + common_tail)
    waste = dowels.edge_offset + dowels.pin_large
    pl, ps = dowels.pin_large, dowels.pin_small
    cl_l, cl_s = dowels.clearance_large, dowels.clearance_small
    clear_note = (f"  Holes are milled oversize for fit: {bd:.2f} mm (+{cl_l:.2f}) bottom, "
                  f"{td:.2f} mm (+{cl_s:.2f}) top.\n" if (cl_l or cl_s) else "")
    return head + (
        f"FRESH mode: the mill drills its own dowel holes; the grid screws only hold\n"
        f"  the stock down. Load copper at least ~{waste:.0f} mm {bigger} than the board on\n"
        f"  the {centre} - the two dowels sit in that waste and are cut away at the end.\n"
        f"  Pins: {pl:.1f} mm ({lo}) and {ps:.1f} mm ({hi}); the different sizes mean the\n"
        f"  board can only flip back on ONE way.\n"
        + clear_note +
        f"\n"
        f"0. Set XY zero ONCE (e.g. stock lower-left) and do NOT re-zero XY between jobs.\n"
        f"   RE-ZERO Z after every bit change AND after the flip.\n"
        f"1. {name}_align: mills the two dowel holes {align_depth:.1f} mm deep (through the\n"
        f"   {thickness:.1f} mm stock AND {align_depth - thickness:.1f} mm into the bed). Seat the {pl:.1f} mm pin {lo.lower()} and\n"
        f"   the {ps:.1f} mm pin {hi.lower()}; firm in the bed, slip-fit in the board.\n"
        f"2. Bottom side: {drill_step}. Then {name}_bottom_traces.\n"
        + common_tail)


def _fiducial_runplan_text(name, machine, lay, fiducials, drill_step,
                           align_depth, thickness):
    nom = nominal_top_fiducials(lay)
    rows = "".join(f"    fiducial {i + 1}: X{x:.3f} Y{y:.3f}\n"
                   for i, (x, y) in enumerate(nom))
    where = ("inside the board corners" if fiducials.placement == "onboard"
             else "in the waste beyond the board corners")
    scale = ("rotation + translation + uniform scale" if fiducials.allow_scale
             else "rotation + translation")
    return (
        f"DOUBLE-SIDED run plan: {name}  [{machine}]  registration: FIDUCIAL\n\n"
        f"FIDUCIAL mode: {len(nom)} reference holes {where}, drilled "
        f"{align_depth:.2f} mm (through the {thickness:.1f} mm stock only - NOT "
        f"into the bed). Onboard holes stay in the finished board; pick corners "
        f"clear of copper.\n\n"
        f"0. Set XY zero ONCE and do NOT re-zero XY for the bottom side.\n"
        f"1. {name}_align: drills the {len(nom)} fiducial holes. Bottom side: "
        f"{drill_step}. Then {name}_bottom_traces.\n"
        f"2. FLIP the board left-to-right and re-place it (no pins needed).\n"
        f"   Re-zero Z on the new surface.\n"
        f"3. Probe each fiducial and record its measured X/Y. Nominal (perfect-\n"
        f"   flip) positions to probe near:\n{rows}"
        f"4. In the app, enter/capture the measured X/Y and 'Fit & export top\n"
        f"   traces' (fit: {scale}). Check the RMS - a high value means a bad\n"
        f"   re-placement; re-seat and re-probe before cutting.\n"
        f"5. {name}_top_traces (now warped to the fit): cut it.\n"
        f"6. {name}_cutout LAST.\n")


def _drill_runplan_line(drill_files, drill):
    """One-line description of the drill files for the run plan."""
    if drill.single_bit:
        return (f"{drill_files[0][0]} with one {drill.bit_diameter} mm bit "
                f"(plunge holes that fit, interpolate larger ones)")
    return ("change bit between files - " +
            ", ".join(f for (f, _p) in drill_files))
