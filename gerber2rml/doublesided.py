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
              align_holes=h(lay.align_holes))
    if hasattr(lay, "top_outline"):
        kw["top_outline"] = t(lay.top_outline)
    return replace(lay, **kw)


def layout_double_sided(folder, dowels: DowelSpec = None, offset=(0.0, 0.0)):
    dowels = dowels or DowelSpec()
    folder = Path(folder)
    axis = _axis_of(dowels)
    b = load_board(folder, mirror=False)
    copper, copper_top, outline_g, holes_raw = _mirror_all(b, axis)  # bottom-up mirror
    geoms = [g for g in (copper, outline_g) if not g.is_empty]
    gx0, gy0, gx1, gy1 = _frame(geoms)
    align_holes, flip_pos, dx, dy = _place(gx0, gy0, gx1, gy1, dowels)
    bottom_copper = translate(copper, xoff=dx, yoff=dy)
    top_src = translate(copper_top, xoff=dx, yoff=dy)
    outline = translate(outline_g, xoff=dx, yoff=dy)
    holes = [(x + dx, y + dy, d) for (x, y, d) in holes_raw]
    top_copper = _reflect_geom(top_src, axis, flip_pos)
    top_outline = _reflect_geom(outline, axis, flip_pos)
    return _offset_layout(
        DoubleSidedLayout(bottom_copper, top_copper, outline, top_outline,
                          holes, align_holes, axis, flip_pos), offset)


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


def preview_layout_double_sided(folder, dowels: DowelSpec = None, offset=(0.0, 0.0)):
    """Layout for the preview: load WITHOUT mirroring so both copper layers and
    the holes sit in the same design frame and overlay correctly."""
    dowels = dowels or DowelSpec()
    folder = Path(folder)
    b = load_board(folder, mirror=False)   # design frame: F.Cu true, B.Cu X-ray
    geoms = [g for g in (b.copper, b.outline) if not g.is_empty]
    gx0, gy0, gx1, gy1 = _frame(geoms)
    align_holes, flip_pos, dx, dy = _place(gx0, gy0, gx1, gy1, dowels)
    bottom_copper = translate(b.copper, xoff=dx, yoff=dy)
    top_copper = translate(b.copper_top, xoff=dx, yoff=dy)
    outline = translate(b.outline, xoff=dx, yoff=dy)
    holes = [(x + dx, y + dy, d) for (x, y, d) in b.holes]
    align_holes = [(x, y, d) for (x, y, d) in align_holes]
    return _offset_layout(
        PreviewLayout(bottom_copper, top_copper, outline, holes,
                      align_holes, _axis_of(dowels), flip_pos), offset)


def _align_drill(drill, dowels, align_depth, board_thickness):
    """Drill spec for the dowel/align holes (single bit, interpolated to the hole
    diameter). Fresh dowels go through the stock AND into the bed (deep); grid
    dowels only clear the stock (the grid hole is already there)."""
    if align_depth is None:
        # fresh: through the stock + a fixed bite into the bed (adapts to stock
        # thickness). grid: just clear the stock onto the pin already in the grid.
        align_depth = (board_thickness + DOWEL_BED_DEPTH if dowels.mode == "fresh"
                       else board_thickness + 1.0)
    return replace(drill, total_depth=align_depth, single_bit=True), align_depth


def build_align_only(folder, out_dir, name, drill=None, dowels: DowelSpec = None,
                     align_depth: float = None, board_thickness: float = 1.6,
                     machine=DEFAULT_MACHINE, offset=(0.0, 0.0)):
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
    lay = layout_double_sided(folder, dowels=dowels, offset=offset)
    align_drill, _ = _align_drill(drill, dowels, align_depth, board_thickness)
    out = out_dir / f"{name}_align{backend.ext}"
    out.write_text(backend.render(
        drill_single_bit(lay.align_holes, align_drill),
        xy_feed=align_drill.xy_feed, plunge_feed=align_drill.plunge_feed))
    return out


def build_double_sided(folder, out_dir, name, trace=None, drill=None, cutout=None,
                       dowels: DowelSpec = None, align_depth: float = None,
                       board_thickness: float = 1.6, machine=DEFAULT_MACHINE,
                       offset=(0.0, 0.0)):
    """Build all job files for a double-sided board + a text run plan.

    ``machine`` selects the output backend (RML or G-code). Returns a list of
    Path objects for every file written (5 toolpath files + 1 .txt).
    """
    dowels = dowels or DowelSpec()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    trace = trace or TraceJob()
    drill = drill or DrillJob()
    cutout = cutout or CutoutJob()
    backend = BACKENDS[machine]          # (render fn, file extension)
    ext = backend.ext
    lay = layout_double_sided(folder, dowels=dowels, offset=offset)
    top_outline = lay.top_outline
    align_drill, align_depth = _align_drill(drill, dowels, align_depth, board_thickness)
    from gerber2rml.engine.estimate import estimate_toolpaths_seconds, format_duration
    written = []
    est = {}                                     # fname -> estimated seconds

    def _write(fname, paths, job):
        (out_dir / fname).write_text(
            backend.render(paths, xy_feed=job.xy_feed, plunge_feed=job.plunge_feed))
        est[fname] = estimate_toolpaths_seconds(paths, job.xy_feed, job.plunge_feed)
        written.append(out_dir / fname)

    _write(f"{name}_align{ext}", drill_single_bit(lay.align_holes, align_drill), align_drill)
    bottom_drill_files = drill_jobs(lay.holes, drill, f"{name}_bottom_drill", ext=ext)
    for fname, paths in bottom_drill_files:
        _write(fname, paths, drill)
    _write(f"{name}_bottom_traces{ext}",
           isolate(lay.bottom_copper, trace, outline=lay.outline), trace)
    _write(f"{name}_top_traces{ext}",
           isolate(lay.top_copper, trace, outline=top_outline), trace)
    _write(f"{name}_cutout{ext}", cut_outline(lay.outline, cutout), cutout)

    drill_step = _drill_runplan_line(bottom_drill_files, drill)
    est_block = ("Estimated run time (excludes tool changes, spin-up and pauses):\n"
                 + "".join(f"   {fn}: ~{format_duration(est[fn])}\n"
                           for fn in (p.name for p in written) if fn in est)
                 + f"   TOTAL: ~{format_duration(sum(est.values()))}\n")
    runplan = out_dir / f"{name}_runplan.txt"
    runplan.write_text(_runplan_text(name, machine, lay, dowels, drill_step,
                                     align_depth, board_thickness) + est_block,
                       encoding="utf-8")
    written.append(runplan)
    return written


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


def _drill_runplan_line(drill_files, drill):
    """One-line description of the drill files for the run plan."""
    if drill.single_bit:
        return (f"{drill_files[0][0]} with one {drill.bit_diameter} mm bit "
                f"(plunge holes that fit, interpolate larger ones)")
    return ("change bit between files - " +
            ", ".join(f for (f, _p) in drill_files))
