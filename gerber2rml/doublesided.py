"""Double-sided dowel-pin registration: layout + job builder.

The board flips LEFT-TO-RIGHT about a vertical axis through its centre. The two
alignment pins sit on that axis (above and below the board), invariant under the
flip. Because the bottom is already mirrored for bottom-up milling, reflecting
the front copper about the same vertical axis CANCELS that mirror — so the top
comes out as the plain, un-mirrored F.Cu design (in both preview and the cut),
while still registering after the physical flip. Pins sit beyond the 104 mm
laser-jig box (or beyond the board if it is taller).
"""
from dataclasses import dataclass, replace
from pathlib import Path
from shapely.affinity import scale, translate
from gerber2rml.loader import load_board
from gerber2rml.engine.traces import isolate
from gerber2rml.engine.drill import drill_holes, drill_jobs
from gerber2rml.engine.cutout import cut_outline
from gerber2rml.backends import srm20
from gerber2rml.config import TraceJob, DrillJob, CutoutJob

def reflect_x(holes, x_axis):
    """Reflect (x, y, d) hole tuples about the vertical line x = x_axis."""
    return [(2 * x_axis - x, y, d) for (x, y, d) in holes]

def _reflect_geom(geom, x_axis):
    return scale(geom, xfact=-1, yfact=1, origin=(x_axis, 0))

@dataclass
class DoubleSidedLayout:
    bottom_copper: object  # mirrored B.Cu (milled bottom-up)
    top_copper: object     # plain F.Cu (mirror cancelled by the flip) — as cut
    outline: object
    top_outline: object    # outline reflected about the vertical flip axis
    holes: list            # placed through-holes (bottom frame)
    align_holes: list      # 2 alignment pins on the flip axis (above & below)
    x_axis: float          # vertical flip axis (constant x)

def layout_double_sided(folder, pin_diameter: float = 3.0, margin: float = 6.0,
                        box_size: float = 104.0):
    folder = Path(folder)
    b = load_board(folder, mirror=True)   # raw, mirrored (bottom-up convention)
    geoms = [g for g in (b.copper, b.outline) if not g.is_empty]
    gx0 = min(g.bounds[0] for g in geoms); gy0 = min(g.bounds[1] for g in geoms)
    gx1 = max(g.bounds[2] for g in geoms); gy1 = max(g.bounds[3] for g in geoms)
    cx = (gx0 + gx1) / 2.0
    cy = (gy0 + gy1) / 2.0
    # pins on the vertical flip axis (x = cx), beyond the top & bottom of the
    # board (or beyond the laser-jig box, whichever is larger)
    half = max((gy1 - gy0) / 2.0, box_size / 2.0) + pin_diameter
    align_raw = [(cx, cy - half, pin_diameter),
                 (cx, cy + half, pin_diameter)]
    allminx = min(gx0, cx - pin_diameter / 2.0)
    allminy = min(gy0, cy - half - pin_diameter / 2.0)
    dx, dy = margin - allminx, margin - allminy
    bottom_copper = translate(b.copper, xoff=dx, yoff=dy)
    top_src = translate(b.copper_top, xoff=dx, yoff=dy)
    outline = translate(b.outline, xoff=dx, yoff=dy)
    holes = [(x + dx, y + dy, d) for (x, y, d) in b.holes]
    align_holes = [(x + dx, y + dy, d) for (x, y, d) in align_raw]
    x_axis = cx + dx
    top_copper = _reflect_geom(top_src, x_axis)
    top_outline = _reflect_geom(outline, x_axis)
    return DoubleSidedLayout(bottom_copper, top_copper, outline, top_outline,
                             holes, align_holes, x_axis)


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
    align_holes: list      # 2 dowel pins on the vertical flip axis (above/below)
    x_axis: float


def preview_layout_double_sided(folder, pin_diameter: float = 3.0,
                                margin: float = 6.0, box_size: float = 104.0):
    """Layout for the preview: load WITHOUT mirroring so both copper layers and
    the holes sit in the same design frame and overlay correctly."""
    folder = Path(folder)
    b = load_board(folder, mirror=False)   # design frame: F.Cu true, B.Cu X-ray
    geoms = [g for g in (b.copper, b.outline) if not g.is_empty]
    gx0 = min(g.bounds[0] for g in geoms); gy0 = min(g.bounds[1] for g in geoms)
    gx1 = max(g.bounds[2] for g in geoms); gy1 = max(g.bounds[3] for g in geoms)
    cx = (gx0 + gx1) / 2.0
    cy = (gy0 + gy1) / 2.0
    half = max((gy1 - gy0) / 2.0, box_size / 2.0) + pin_diameter
    align_raw = [(cx, cy - half, pin_diameter), (cx, cy + half, pin_diameter)]
    allminx = min(gx0, cx - pin_diameter / 2.0)
    allminy = min(gy0, cy - half - pin_diameter / 2.0)
    dx, dy = margin - allminx, margin - allminy
    bottom_copper = translate(b.copper, xoff=dx, yoff=dy)
    top_copper = translate(b.copper_top, xoff=dx, yoff=dy)
    outline = translate(b.outline, xoff=dx, yoff=dy)
    holes = [(x + dx, y + dy, d) for (x, y, d) in b.holes]
    align_holes = [(x + dx, y + dy, d) for (x, y, d) in align_raw]
    return PreviewLayout(bottom_copper, top_copper, outline, holes,
                         align_holes, cx + dx)


def build_double_sided(folder, out_dir, name, trace=None, drill=None, cutout=None,
                       pin_diameter: float = 3.0, margin: float = 6.0,
                       box_size: float = 104.0, align_depth: float = 6.0):
    """Build all RML job files for a double-sided board + a text run plan.

    Returns a list of Path objects for every file written (5 RML + 1 .txt).
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    trace = trace or TraceJob()
    drill = drill or DrillJob()
    cutout = cutout or CutoutJob()
    lay = layout_double_sided(folder, pin_diameter=pin_diameter, margin=margin,
                              box_size=box_size)
    top_outline = lay.top_outline
    # the alignment job drills deeper (through the board AND into the bed) so the
    # dowel pins anchor; the board's own holes use the normal drill depth. The
    # align job always plunges the two pin holes with one bit, never split.
    align_drill = replace(drill, total_depth=align_depth, single_bit=False)
    written = []

    def _write(fname, paths, job):
        (out_dir / fname).write_text(
            srm20.render(paths, xy_feed=job.xy_feed, plunge_feed=job.plunge_feed))
        written.append(out_dir / fname)

    _write(f"{name}_align.rml", drill_holes(lay.align_holes, align_drill), align_drill)
    bottom_drill_files = drill_jobs(lay.holes, drill, f"{name}_bottom_drill")
    for fname, paths in bottom_drill_files:
        _write(fname, paths, drill)
    _write(f"{name}_bottom_traces.rml",
           isolate(lay.bottom_copper, trace, outline=lay.outline), trace)
    _write(f"{name}_top_traces.rml",
           isolate(lay.top_copper, trace, outline=top_outline), trace)
    _write(f"{name}_cutout.rml", cut_outline(lay.outline, cutout), cutout)

    drill_step = _drill_runplan_line(bottom_drill_files, drill)
    runplan = out_dir / f"{name}_runplan.txt"
    runplan.write_text(
        f"DOUBLE-SIDED run plan: {name}\n"
        f"0. Set XY zero ONCE (e.g. the stock lower-left corner) and do NOT re-zero "
        f"between jobs - registration comes from the pins, not from re-zeroing.\n"
        f"1. {name}_align: drills the two {pin_diameter} mm holes {align_depth} mm deep "
        f"(through the {1.6} mm board AND into the sacrificial bed); seat dowel pins.\n"
        f"2. Drill board holes: {drill_step}. Then {name}_bottom_traces (B.Cu).\n"
        f"3. FLIP the board LEFT-TO-RIGHT about the vertical pin line; drop onto the pins.\n"
        f"4. {name}_top_traces (plain F.Cu - not mirrored).\n"
        f"5. {name}_cutout last.\n",
        encoding="utf-8")
    written.append(runplan)
    return written


def _drill_runplan_line(drill_files, drill):
    """One-line description of the drill files for the run plan."""
    if drill.single_bit:
        return (f"{drill_files[0][0]} with one {drill.bit_diameter} mm bit "
                f"(plunge holes that fit, interpolate larger ones)")
    return ("change bit between files - " +
            ", ".join(f for (f, _p) in drill_files))
