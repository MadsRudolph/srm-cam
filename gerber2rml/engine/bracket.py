"""The corner bracket the stock is pushed into, as the part on the bed.

The bracket is an L of flat bar screwed into the spoilboard's tapped holes
(:mod:`gerber2rml.engine.spoilboard`). It is not anywhere: it is in a hole
position, and moving it means unscrewing it and screwing it into other holes,
a whole 10 mm pitch at a time. So it is modelled as the hole its corner screw
is in, and its inside corner - where the stock's corner sits, the one point
Automatic mode measures everything from - follows from that.

What makes this exact is a measurement and the grid's pitch. The lab's standard
position is back-right, corner screw in hole (19, 12), with the printed bracket
(hardware/probe_bracket). Its inside corner was read with the bit over it at
X 191.79, Y 128.43 (2026-11-03). The back-left offset is the old bracket's, at X 22.49,
Y 129.47 in hole (1, 12) (2026-11-02). Moving the bracket by whole holes keeps its
side's offset.

The part itself (the picture on the stage; nothing that cuts depends on it):

    bar width            10 mm, straight walls
    arms                 61 mm outside, both
    screws               the corner, and the last hole of each arm

Its tongue carries the probe wire onto the copper, on the arm along X. The
tongue reaches over the stock, so the bit must stay out from under it
(:meth:`Bracket.keepout`). Only the back-right part exists; the other corners
are that shape mirrored.

The two front corners are not measured: they use their side's offset, mirrored.
"""
from dataclasses import dataclass

from gerber2rml.engine import spoilboard
from gerber2rml.engine.stockfind import CORNERS

# MEASURED: how far the inside corner is from the corner screw's hole centre,
# in mm, as (towards the stock in X, towards the back in Y) on a back corner.
CORNER_FROM_HOLE = {"left": (6.07, -5.11), "right": (4.63, -6.15)}

BAR_W = 10.0             # mm, width of the bar
ARM_X = 61.0             # mm, the arm along X, outside length
ARM_Y = 61.0             # mm, the arm along Y, outside length
HOLES_PER_ARM = 6        # counting the corner hole, at the grid's pitch

# The tongue, from the inside corner along the X arm, and how far it reaches
# over the stock. Mm, as in hardware/probe_bracket/build.py.
TONGUE_U = (2.5, 26.0)
TONGUE_V = 4.0
TONGUE_CLEARANCE = 0.5   # mm kept between the tongue and anything the bit cuts

DEFAULT_CORNER = "back-right"


def _axes(corner):
    """``(a, b)``: +1/-1 along X and Y from the inside corner INTO the stock."""
    if corner not in CORNERS:
        raise ValueError("corner must be one of %s" % (CORNERS,))
    return (1 if "left" in corner else -1, -1 if "back" in corner else 1)


@dataclass(frozen=True)
class Bracket:
    """The bracket with its corner screw in hole ``(i, j)`` of the grid."""
    i: int
    j: int
    corner: str = DEFAULT_CORNER

    def _local(self, u, v, grid):
        """Bracket-local (u, v) mm -> machine (x, y). The origin is the
        inside corner, +u and +v run along the arms, into the stock."""
        a, b = _axes(self.corner)
        cx, cy = self.inside_corner(grid)
        return cx + a * u, cy + b * v

    def inside_corner(self, grid=None):
        """Machine (x, y) mm of the corner the stock's corner sits in."""
        grid = grid or spoilboard.measured_grid()
        a, b = _axes(self.corner)
        hx, hy = grid.centre(self.i, self.j)
        dx, dy = CORNER_FROM_HOLE["left" if "left" in self.corner else "right"]
        # Mirrored for the corner: b = -1 at the back.
        return hx + a * dx, hy - b * dy

    def outline(self, grid=None):
        """The L, as a closed polygon of machine (x, y) mm."""
        grid = grid or spoilboard.measured_grid()
        w = BAR_W
        u0, u1 = TONGUE_U
        local = [(-w, -w), (ARM_X - w, -w), (ARM_X - w, 0.0), (u1, 0.0),
                 (u1, TONGUE_V), (u0, TONGUE_V), (u0, 0.0), (0.0, 0.0),
                 (0.0, ARM_Y - w), (-w, ARM_Y - w)]
        return [self._local(u, v, grid) for u, v in local]

    def keepout(self, grid=None):
        """(x0, y0, x1, y1) machine mm the bit must stay out of: the tongue
        over the stock, with its clearance."""
        grid = grid or spoilboard.measured_grid()
        c = TONGUE_CLEARANCE
        ax, ay = self._local(TONGUE_U[0] - c, 0.0, grid)
        bx, by = self._local(TONGUE_U[1] + c, TONGUE_V + c, grid)
        return min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)

    def screws(self):
        """``[(i, j)]``: the holes its screws are in, the corner one first."""
        a, b = _axes(self.corner)
        n = HOLES_PER_ARM - 1
        return [(self.i, self.j), (self.i + a * n, self.j),
                (self.i, self.j + b * n)]

    def screw_points(self, grid=None):
        grid = grid or spoilboard.measured_grid()
        return [grid.centre(i, j) for i, j in self.screws()]


def fits(bracket, grid=None, bed=None):
    """Can it be screwed down there, with its corner where the bit reaches?

    Every screw needs a hole in the plate. The outer ring counts: the
    measured position has its corner screw in it."""
    grid = grid or spoilboard.measured_grid()
    for i, j in bracket.screws():
        if not (0 <= i < grid.nx and 0 <= j < grid.ny):
            return False
    if bed is not None:
        x, y = bracket.inside_corner(grid)
        if not (0.0 <= x <= bed[0] and 0.0 <= y <= bed[1]):
            return False
    return True


def snap(x, y, corner=DEFAULT_CORNER, grid=None, bed=None):
    """The position it can be screwed into whose inside corner is nearest
    (x, y), or None if it fits nowhere."""
    grid = grid or spoilboard.measured_grid()
    best, best_d = None, None
    for j in range(grid.ny):
        for i in range(grid.nx):
            b = Bracket(i, j, corner)
            if not fits(b, grid, bed):
                continue
            cx, cy = b.inside_corner(grid)
            d = (cx - x) ** 2 + (cy - y) ** 2
            if best_d is None or d < best_d:
                best, best_d = b, d
    return best


DEFAULT = Bracket(19, 12, DEFAULT_CORNER)
# Where the standard was until 2026-11-03. A machine that saved this did not
# choose it, it took the default: it follows the standard to the new place.
OLD_DEFAULT = Bracket(1, 12, "back-left")


def to_text(b):
    return "%d,%d,%s" % (b.i, b.j, b.corner)


def from_text(raw):
    """A saved ``"i,j,corner"``, or None if it is not one."""
    try:
        i, j, c = str(raw or "").split(",")
        if c in CORNERS:
            return Bracket(int(i), int(j), c)
    except ValueError:
        pass
    return None
