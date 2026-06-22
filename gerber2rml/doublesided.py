"""Double-sided dowel-pin registration: layout + job builder.

The two alignment holes sit on a horizontal axis through the board's vertical
centre (invariant under the flip). Top transform = bottom transform reflected
about that axis, so the sides register after the physical flip. Pins sit beyond
the 104 mm laser-jig box (or beyond the board if it is wider).
"""
from dataclasses import dataclass, replace
from pathlib import Path
from shapely.affinity import scale, translate
from gerber2rml.loader import load_board
from gerber2rml.engine.traces import isolate
from gerber2rml.engine.drill import drill_holes
from gerber2rml.engine.cutout import cut_outline
from gerber2rml.backends import srm20
from gerber2rml.config import TraceJob, DrillJob, CutoutJob

def reflect_y(holes, y_axis):
    """Reflect (x, y, d) hole tuples about the horizontal line y = y_axis."""
    return [(x, 2 * y_axis - y, d) for (x, y, d) in holes]

def _reflect_geom(geom, y_axis):
    return scale(geom, xfact=1, yfact=-1, origin=(0, y_axis))

@dataclass
class DoubleSidedLayout:
    bottom_copper: object
    top_copper: object
    outline: object
    top_outline: object   # outline reflected about the flip axis (front-side clip)
    holes: list           # placed through-holes (bottom frame)
    align_holes: list     # 2 alignment holes on the flip axis
    y_axis: float

def layout_double_sided(folder, pin_diameter: float = 3.0, margin: float = 6.0,
                        box_size: float = 104.0):
    folder = Path(folder)
    b = load_board(folder, mirror=True)   # raw, mirrored
    geoms = [g for g in (b.copper, b.outline) if not g.is_empty]
    gx0 = min(g.bounds[0] for g in geoms); gy0 = min(g.bounds[1] for g in geoms)
    gx1 = max(g.bounds[2] for g in geoms); gy1 = max(g.bounds[3] for g in geoms)
    cx = (gx0 + gx1) / 2.0
    y_axis_raw = (gy0 + gy1) / 2.0
    half = max((gx1 - gx0) / 2.0, box_size / 2.0) + pin_diameter
    align_raw = [(cx - half, y_axis_raw, pin_diameter),
                 (cx + half, y_axis_raw, pin_diameter)]
    allminx = min(gx0, cx - half - pin_diameter / 2.0)
    allminy = min(gy0, y_axis_raw - pin_diameter / 2.0)
    dx, dy = margin - allminx, margin - allminy
    bottom_copper = translate(b.copper, xoff=dx, yoff=dy)
    top_src = translate(b.copper_top, xoff=dx, yoff=dy)
    outline = translate(b.outline, xoff=dx, yoff=dy)
    holes = [(x + dx, y + dy, d) for (x, y, d) in b.holes]
    align_holes = [(x + dx, y + dy, d) for (x, y, d) in align_raw]
    y_axis = y_axis_raw + dy
    top_copper = _reflect_geom(top_src, y_axis)
    top_outline = _reflect_geom(outline, y_axis)
    return DoubleSidedLayout(bottom_copper, top_copper, outline, top_outline,
                             holes, align_holes, y_axis)


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
    # dowel pins anchor; the board's own holes use the normal drill depth.
    align_drill = replace(drill, total_depth=align_depth)
    jobs = [
        (f"{name}_align.rml",
         drill_holes(lay.align_holes, align_drill), align_drill),
        (f"{name}_bottom_drill.rml",
         drill_holes(lay.holes, drill), drill),
        (f"{name}_bottom_traces.rml",
         isolate(lay.bottom_copper, trace, outline=lay.outline), trace),
        (f"{name}_top_traces.rml",
         isolate(lay.top_copper, trace, outline=top_outline), trace),
        (f"{name}_cutout.rml",
         cut_outline(lay.outline, cutout), cutout),
    ]
    written = []
    for fname, paths, job in jobs:
        (out_dir / fname).write_text(
            srm20.render(paths, xy_feed=job.xy_feed, plunge_feed=job.plunge_feed))
        written.append(out_dir / fname)
    runplan = out_dir / f"{name}_runplan.txt"
    runplan.write_text(
        f"DOUBLE-SIDED run plan: {name}\n"
        f"0. Set XY zero ONCE (e.g. the stock lower-left corner) and do NOT re-zero "
        f"between jobs - registration comes from the pins, not from re-zeroing.\n"
        f"1. {name}_align: drills the two {pin_diameter} mm holes {align_depth} mm deep "
        f"(through the {1.6} mm board AND into the sacrificial bed); seat dowel pins.\n"
        f"2. {name}_bottom_drill (board holes only), then {name}_bottom_traces (B.Cu).\n"
        f"3. FLIP the board top-over-bottom about the horizontal pin line;"
        f" drop onto the pins.\n"
        f"4. {name}_top_traces (F.Cu).\n"
        f"5. {name}_cutout last.\n",
        encoding="utf-8")
    written.append(runplan)
    return written
