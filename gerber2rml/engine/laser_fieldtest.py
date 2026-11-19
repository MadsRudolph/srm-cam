"""The field test: is it focus, or the laser's field, that leaves a board's
edges unfinished?

drums1 (2026-11-19) came out perfect in the middle and not through at the
sides and top, after a focus map that said the board was flat to 0.3 mm and
ran it in bands. Either the map is wrong at the edges - the blue dot reads
heights weakly there, and a correction of up to 1.3 mm was taken off - or the
focus is right and the galvo's field is weaker towards its edges (the beam
meets the copper at an angle, the spot is bigger), which no refocusing can
cure. One etch on a spare sheet tells them apart:

* **Coupons** - a 2.5 mm pad and a 0.3 mm trace 0.3 mm from it, as fine as
  the boards - on a 5 x 3 grid over a 150 x 90 mm sheet, all at the focus
  the page has: how clearing falls off from the middle to the edges.
* **Ladders** - four more coupons beside a grid row, at -0.6, -0.3, +0.3 and
  +0.6 mm from that focus - at the left, the right and the middle, front and
  back. Where the grid coupon at an edge is unfinished but one of its
  ladder's is clean, it is focus, and the height that cleans says by how
  much. Where every one at an edge is unfinished, it is the field.

Pure: the art and each coupon's height. The laser page runs it
(``gui2/laser_fieldtest_ui.py``) with the recipe it cuts boards with.
"""
from dataclasses import dataclass

SIZE = (150.0, 90.0)                       # fits the lab's 160 x 100 stock
GRID_X = (12.0, 43.5, 75.0, 106.5, 138.0)
GRID_Y = (12.0, 45.0, 78.0)
LADDER_DZ = (-0.6, -0.3, 0.3, 0.6)
LADDER_ROWS = (28.5, 61.5)                 # between the grid rows
LADDER_X = {"left": (8.0, 17.0, 26.0, 35.0),
            "middle": (57.0, 66.0, 84.0, 93.0),
            "right": (115.0, 124.0, 133.0, 142.0)}
PAD = 2.5
TRACE_W = 0.3
GAP = 0.3
TRACE_L = 5.0
NOTE = "field test"


@dataclass(frozen=True)
class Coupon:
    x: float          # the coupon's middle, mm from the test's corner
    y: float
    dz: float         # mm above the page's focus it is cut at
    label: str


def coupon_shapes(cx, cy):
    """The copper of one coupon: a pad, and a fine trace beside it."""
    from shapely.geometry import box
    w = PAD + GAP + TRACE_W
    x0 = cx - w / 2.0
    pad = box(x0, cy - PAD / 2.0, x0 + PAD, cy + PAD / 2.0)
    tx = x0 + PAD + GAP
    trace = box(tx, cy - TRACE_L / 2.0, tx + TRACE_W, cy + TRACE_L / 2.0)
    return [pad, trace]


def coupons():
    """Every coupon, grid first, then the ladders."""
    out = []
    for j, y in enumerate(GRID_Y):
        for i, x in enumerate(GRID_X):
            out.append(Coupon(x, y, 0.0, f"grid {j + 1}.{i + 1}"))
    for row, y in zip(("between rows 1-2", "between rows 2-3"), LADDER_ROWS):
        for side, xs in LADDER_X.items():
            for x, dz in zip(xs, LADDER_DZ):
                out.append(Coupon(x, y, dz, f"{side} ladder {row}, {dz:+.1f}"))
    return out


def field_test_art():
    """``(art, heights)``: the test as a traces job, and the height to cut
    each of its apertures at (mm above focus), aperture for aperture."""
    from shapely.geometry import box
    from shapely.ops import unary_union
    from gerber2rml.engine.xtool import LaserArt
    shapes, heights = [], []
    for c in coupons():
        for s in coupon_shapes(c.x, c.y):
            shapes.append(s)
            heights.append(c.dz)
    w, h = SIZE
    art = LaserArt(kind="traces", apertures=shapes, outline=box(0, 0, w, h),
                   note=NOTE, copper=unary_union(shapes), drills=[],
                   features=[], side="top", mirrored=False)
    return art, heights


def groups(heights, only=None):
    """``[(dz, {aperture index})]``, one per height, lowest first."""
    by = {}
    for k, dz in enumerate(heights):
        if only is None or k in only:
            by.setdefault(round(dz, 3), set()).add(k)
    return sorted(by.items())


def key():
    """How to read the etched sheet, for the page to show."""
    return ("Field test, 150 x 90 mm. Grid: 5 coupons across, 3 deep, all at "
            "focus. Ladders between the grid rows, at the left, middle and "
            "right: four coupons each at -0.6, -0.3, +0.3, "
            "+0.6 mm, left to right. A coupon is clean when the gap between "
            "the pad and the thin trace is clear to the board all along. "
            "Edges unfinished on the grid but clean on a ladder coupon: "
            "focus, by that height. Unfinished on all of them: the field - "
            "the edges need more passes.")
