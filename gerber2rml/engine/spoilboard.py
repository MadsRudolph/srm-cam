"""The spoilboard's screw grid, and picking four holes to bolt the copper down.

The bed is an MDF spoilboard drilled on a regular grid, and every hole lines up
with a threaded hole in the metal plate underneath. So the copper can be held
down with M4 screws straight into the plate — no tape, no clamps in the way of
the cutter, and the stock cannot creep mid-job.

The catch is that a screw hole has to land on a grid hole. Miss it and the bit
goes through the copper, through the MDF, and into solid steel. That is why the
grid is modelled from measured numbers rather than eyeballed, and why
:func:`candidates` refuses anything it cannot place confidently.

MEASURED on the lab's spoilboard (2026-08):

    board          220 x 150 mm
    holes          20 across, 13 deep, 4 mm diameter
    pitch          10.0 mm, both axes
    edge margin    15.0 mm from board edge to the first hole centre, all sides

The pitch came from two spans — 190 mm across 20 holes and 120 mm across 13 —
which give exactly 10.0 each. The 15 mm margin then falls out symmetrically on
all four sides. Two independent measurements agreeing on round numbers is what
makes this safe to drill against; a single hole-to-hole measurement would not
have been, because a 0.3 mm error there compounds to 6 mm across the board.

The OUTERMOST RING is not available: those holes are the spoilboard's own
mounting screws and sit outside the usable build area.
"""
from dataclasses import dataclass

PITCH = 10.0             # mm, centre to centre, both axes
HOLE_D = 4.0             # mm, the hole in the MDF
NX, NY = 20, 13          # holes across, holes deep
BOARD = (220.0, 150.0)   # mm, the MDF itself
EDGE_MARGIN = 15.0       # mm, board edge -> first hole centre

# The M4 screws in the lab, measured 2026-08. The head is what the machine has
# to negotiate, not the 4 mm shank: 8 mm across, standing 3 mm proud of the
# copper once tightened.
M4_HEAD_D = 8.0          # mm across the head - the keep-out footprint
M4_HEAD_H = 3.0          # mm the head stands above the copper surface

# Clearance between the top of a screw head and a rapid traverse. 1 mm is
# enough to be safe and small enough not to eat the SRM-20's limited Z range.
HEAD_CLEARANCE = 1.0


def min_travel_z(head_h=M4_HEAD_H, clearance=HEAD_CLEARANCE):
    """Lowest safe rapid height above the copper when screws are holding it.

    Z zero is the copper surface, so a screw head occupies everything from 0 up
    to ``head_h``. A rapid at the usual 2 mm would pass a millimetre BELOW the
    top of every screw.
    """
    return head_h + clearance


def travel_z_problem(travel_z, head_h=M4_HEAD_H, clearance=HEAD_CLEARANCE):
    """Describe the collision if ``travel_z`` is too low, else None.

    This is the failure mode of the whole screw fixture, and it is silent: the
    toolpaths are all perfectly correct in XY, every cut is at the right depth,
    and the spindle drives into a screw head on the first traverse. Nothing in
    the geometry catches it, because the screws are not in the geometry.
    """
    needed = min_travel_z(head_h, clearance)
    if travel_z >= needed:
        return None
    return (f"Travel Z is {travel_z:g} mm, but the screw heads stand {head_h:g} mm "
            f"above the copper — a rapid would hit one. Raise travel Z to at "
            f"least {needed:g} mm on every operation before running this job.")

# --- where the grid actually sits on OUR machine ---------------------------
# Measured 2026-08 with the SPI DRO, by jogging a bit down into a hole until it
# dropped in and centred itself:
#
#     hole (1, 0), 2nd from the front-left:   X  16.44   Y 14.58
#     hole (18, 0), last before the bolt:     X 186.40   Y 14.58
#
# 169.96 mm across 17 pitches = 9.9976 mm, i.e. 10.0 within the accuracy of
# feeling a bit into a hole. Both readings give the same origin to 40 microns
# over 180 mm, and both Y values are IDENTICAL, so the board is square to the
# axes and needs no rotation term.
#
# The confirmation that matters: this anchor puts the 220 mm board 8.58 mm off
# the left of travel and 8.22 mm off the right, totalling 16.80 mm - which is
# exactly 220 - 203.2. Three independent numbers agreeing is what makes this
# safe to drill against.
#
# CONFIRMED IN PRACTICE (2026-08): holes drilled from this model lined up with
# the threads well enough for M4 screws to go straight in. That is a harder
# test than jogging into a hole - a screw either catches the thread or it does
# not - and it is what validates the Y pitch, which was otherwise derived from
# one measured row plus the 120 mm / 13 span.
#
# RE-MEASURE if the spoilboard is ever unbolted, resurfaced or replaced.
MEASURED_ORIGIN = (6.42, 14.58)


# Clearance hole for an M4 shank through the copper. Deliberately bigger than
# the 4 mm hole in the MDF below it: the screw must pass through the copper
# freely so tightening pulls the copper DOWN rather than wedging on the shank.
M4_CLEARANCE_D = 4.5


@dataclass(frozen=True)
class HoleGrid:
    """The grid, positioned in machine coordinates.

    ``origin`` is the machine XY of the centre of hole (0, 0) — the front-left
    hole of the full grid. It must be MEASURED on the machine (jog a bit down
    into a known hole until it centres itself, read the DRO); nothing about the
    spoilboard's own dimensions tells us where it was screwed down.
    """
    origin: tuple
    nx: int = NX
    ny: int = NY
    pitch: float = PITCH
    hole_diameter: float = HOLE_D
    skip_border: int = 1          # rings of outer holes that are unavailable

    def centre(self, i, j):
        """Machine XY of hole ``(i, j)``, counting from the front-left."""
        ox, oy = self.origin
        return (ox + i * self.pitch, oy + j * self.pitch)

    def holes(self):
        """Every hole a screw may use: ``(i, j, x, y)``, front-left first.

        Excludes ``skip_border`` rings around the edge — on this machine those
        are the spoilboard's own mounting screws and are outside the build
        area anyway.
        """
        b = self.skip_border
        for j in range(b, self.ny - b):
            for i in range(b, self.nx - b):
                x, y = self.centre(i, j)
                yield (i, j, x, y)


def measured_grid(**kw):
    """The lab's grid, anchored where it was measured."""
    return HoleGrid(origin=MEASURED_ORIGIN, **kw)


def reachable(grid, bed):
    """Holes the spindle can actually get to, given the machine travel.

    The spoilboard is wider than the SRM-20 can reach (220 mm of board against
    203.2 mm of X travel), so some columns exist physically and cannot be
    drilled. Offering one of those would be a hole the machine simply refuses
    to move to.
    """
    bx, by = bed
    return [(i, j, x, y) for (i, j, x, y) in grid.holes()
            if 0.0 <= x <= bx and 0.0 <= y <= by]


def candidates(grid, stock, bed, head_d=M4_HEAD_D, edge_clear=1.0):
    """Holes a screw could use for this piece of copper.

    ``stock`` is ``(x0, y0, w, h)`` in machine coordinates — where the copper
    actually sits. A hole qualifies when the whole screw HEAD lands on copper,
    not merely the hole: a head hanging over the edge cannot clamp, it just
    tips and lets the stock lift.
    """
    x0, y0, w, h = stock
    inset = head_d / 2.0 + edge_clear
    return [(i, j, x, y) for (i, j, x, y) in reachable(grid, bed)
            if x0 + inset <= x <= x0 + w - inset
            and y0 + inset <= y <= y0 + h - inset]


def _clear_of(x, y, keepout, radius):
    """Is a screw head at ``(x, y)`` clear of the ``keepout`` geometry?"""
    if keepout is None or getattr(keepout, "is_empty", False):
        return True
    from shapely.geometry import Point
    return not keepout.intersects(Point(x, y).buffer(radius))


def pick_fasteners(grid, stock, bed, keepout=None, head_d=M4_HEAD_D,
                   edge_clear=1.0, count=4):
    """Choose screw holes, spread toward the corners of the stock.

    One per corner rather than the four closest together: screws bunched at one
    end leave the far end free to lift and chatter, which is the failure this
    whole fixture exists to prevent.

    ``keepout`` is the design footprint (a shapely geometry in machine
    coordinates). A screw head overlapping it would be cut into, so those holes
    are dropped — which is also why this can return FEWER than ``count``. That
    is a real answer, not a failure to be padded out: if the copper is too
    small or the design too close to the edge, the honest result is "there are
    only two places a screw can go", and the caller should say so rather than
    invent a third.
    """
    pool = [(x, y) for (_i, _j, x, y) in candidates(grid, stock, bed, head_d,
                                                    edge_clear)
            if _clear_of(x, y, keepout, head_d / 2.0)]
    if not pool:
        return []

    x0, y0, w, h = stock

    # Farthest-point selection, not nearest-to-each-corner. Corner-picking
    # looks right until the design blocks most of the copper, and then every
    # corner's nearest CLEAR hole is in the same leftover strip - four screws
    # in a line, which is a hinge rather than a clamp. Taking each next screw
    # as far as possible from the ones already placed spreads them as widely as
    # the available holes allow, and degrades gracefully instead of collapsing.
    start = min(pool, key=lambda p: (p[0] - x0) ** 2 + (p[1] - y0) ** 2)
    chosen = [start]
    while len(chosen) < count:
        remaining = [p for p in pool if p not in chosen]
        if not remaining:
            break
        chosen.append(max(remaining, key=lambda p: min(
            (p[0] - c[0]) ** 2 + (p[1] - c[1]) ** 2 for c in chosen)))
    return chosen


def spread_problem(points, stock, min_fraction=0.25):
    """Describe a screw arrangement that cannot hold the copper flat, else None.

    Four screws strung out in a line clamp along that line and leave the copper
    free to pivot about it. The count alone does not reveal this - you get the
    four you asked for and they are useless - so the spread is checked
    separately from the count.
    """
    if len(points) < 2:
        return None                     # too few to be a spread problem
    _x0, _y0, w, h = stock
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    span_x, span_y = max(xs) - min(xs), max(ys) - min(ys)
    if w > 0 and span_x < w * min_fraction:
        return (f"All {len(points)} screws sit within {span_x:.0f} mm across a "
                f"{w:.0f} mm wide piece - the copper can pivot about that line. "
                f"Move the design to free up copper on the other side.")
    if h > 0 and span_y < h * min_fraction:
        return (f"All {len(points)} screws sit within {span_y:.0f} mm up a "
                f"{h:.0f} mm tall piece - the copper can pivot about that line. "
                f"Move the design to free up copper above or below it.")
    return None


def point_problem(point, stock, keepout=None, head_d=M4_HEAD_D, edge_clear=1.0):
    """Why this screw position is a bad idea, or None if it is fine.

    Used for HAND-PICKED holes. The automatic pass simply never offers a bad
    one, but an operator can see the bed and may have a reason we do not know
    about, so a hand pick is reported rather than refused.
    """
    x, y = point
    x0, y0, w, h = stock
    inset = head_d / 2.0 + edge_clear
    if not (x0 <= x <= x0 + w and y0 <= y <= y0 + h):
        return "is not on the copper at all"
    if not (x0 + inset <= x <= x0 + w - inset
            and y0 + inset <= y <= y0 + h - inset):
        return ("is too close to the edge - the screw head would overhang the "
                "copper and tip instead of clamping")
    if not _clear_of(x, y, keepout, head_d / 2.0):
        return "is under the design - the cutter would run into the screw head"
    return None


def fastener_toolpaths(points, clearance_d=M4_CLEARANCE_D, copper_thickness=1.6,
                       bit_diameter=0.8, travel_z=2.0, step=0.6,
                       breakthrough=0.3):
    """Drill the clearance holes, reusing the normal drill engine.

    Depth is the copper plus a little breakthrough and no more. There is
    already a 4 mm hole in the MDF underneath every one of these, so the bit
    exits into fresh air — there is nothing to gain from going deeper and a
    bit to lose if a hole is fractionally off.
    """
    from gerber2rml.config import DrillJob
    from gerber2rml.engine.drill import drill_single_bit

    holes = [(x, y, clearance_d) for (x, y) in points]
    job = DrillJob(bit_diameter=bit_diameter, single_bit=True,
                   cut_depth=step, total_depth=copper_thickness + breakthrough,
                   travel_z=travel_z)
    return drill_single_bit(holes, job)


def procedure(points, grid, clearance_d=M4_CLEARANCE_D):
    """The operator's instructions, written out with the job."""
    if not points:
        return ("SRM-20 screw fixture\n\n"
                "No usable screw positions were found for this placement.\n"
                "Move the copper so it covers more of the spoilboard grid, or "
                "use a larger piece.\n")
    listed = "\n".join(
        f"     screw {n}:  X {x:8.2f}   Y {y:8.2f}"
        for n, (x, y) in enumerate(points, start=1))
    return (
        f"SRM-20 screw fixture — {len(points)} M4 screws\n"
        f"\n"
        f"Holds the copper to the threaded plate through the spoilboard grid,\n"
        f"so the stock cannot creep and no clamp sits in the cutter's way.\n"
        f"\n"
        f"1. Place the copper over the grid and set the XY work origin as\n"
        f"   usual. DO NOT move it again after this.\n"
        f"2. Set Z zero on the copper surface.\n"
        f"3. Run this file. It drills {len(points)} x {clearance_d:g} mm "
        f"clearance holes\n"
        f"   through the copper only, at:\n"
        f"{listed}\n"
        f"4. Drop an M4 screw through each and tighten into the plate.\n"
        f"   Snug, not hard — you are clamping copper, not building a bridge.\n"
        f"5. Re-zero Z (the board may have pulled down slightly as you\n"
        f"   tightened).\n"
        f"6. RAISE TRAVEL Z TO AT LEAST {min_travel_z():g} mm on every "
        f"operation before running the job.\n"
        f"   The heads stand {M4_HEAD_H:g} mm above the copper and the default "
        f"travel height is 2 mm, so a rapid would drive the spindle\n"
        f"   into a screw. Nothing in the toolpath geometry catches this,\n"
        f"   because the screws are not in the geometry.\n"
        f"\n"
        f"Keep the design clear of the heads too. The screw positions are\n"
        f"checked against the design footprint, but a hand-edited job is not.\n")
