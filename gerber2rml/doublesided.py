"""Double-sided dowel-pin registration: layout + job builder.

The two alignment holes sit on a horizontal axis through the board's vertical
centre (invariant under the flip). Top transform = bottom transform reflected
about that axis, so the sides register after the physical flip. Pins sit beyond
the 104 mm laser-jig box (or beyond the board if it is wider).
"""
from dataclasses import dataclass
from pathlib import Path
from shapely.affinity import scale, translate
from gerber2rml.loader import load_board

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
    return DoubleSidedLayout(bottom_copper, top_copper, outline, holes,
                             align_holes, y_axis)
