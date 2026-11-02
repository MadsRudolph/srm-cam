"""The corner bracket the stock is pushed into, as the part on the bed.

The bracket is an L of flat bar screwed into the spoilboard's tapped holes
(:mod:`gerber2rml.engine.spoilboard`). It is not anywhere: it is in a hole
position, and moving it means unscrewing it and screwing it into other holes,
a whole 10 mm pitch at a time. So it is modelled as the hole its corner screw
is in, and its inside corner - where the stock's corner sits, the one point
Automatic mode measures everything from - follows from that.

What makes this exact is one measurement and the grid's pitch. The inside
corner of the back-left bracket was measured with the bit at X 22.49, Y
129.47 (2026-11-02), with its corner screw in hole (1, 12): 6.07 mm right of
and 5.11 mm in front of that hole's centre. Moving the bracket by whole holes
keeps that offset, so every position it can be screwed into is known to the
same accuracy as the one that was measured.

ESTIMATED from a photo of the lab's fixture, not measured - the picture on
the stage only, nothing that cuts depends on them:

    bar width            11 mm
    arm along X          60 mm, outside
    arm along Y          45 mm, outside
    screws               the corner, and one near the end of each arm

The offsets for the other three corners are the back-left's, mirrored.
"""
from dataclasses import dataclass

from gerber2rml.engine import spoilboard
from gerber2rml.engine.stockfind import CORNERS

# MEASURED (2026-11-02): inside corner minus the corner screw's hole centre,
# back-left bracket, in mm. +x is to the right, +y is towards the back.
CORNER_FROM_HOLE = (6.07, -5.11)

# ESTIMATED from a photo - measure the brackets and replace these.
BAR_W = 11.0             # mm, width of the flat bar
ARM_X = 60.0             # mm, the arm along X, outside length
ARM_Y = 45.0             # mm, the arm along Y, outside length
SCREW_END_MARGIN = 5.0   # mm, the last screw's centre from the arm's end

DEFAULT_CORNER = "back-left"


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
        dx, dy = CORNER_FROM_HOLE
        # The back-left's offset, mirrored: a = +1, b = -1 there.
        return hx + a * dx, hy - b * dy

    def outline(self, grid=None):
        """The L, as a closed polygon of machine (x, y) mm."""
        grid = grid or spoilboard.measured_grid()
        w = BAR_W
        local = [(-w, -w), (ARM_X - w, -w), (ARM_X - w, 0.0), (0.0, 0.0),
                 (0.0, ARM_Y - w), (-w, ARM_Y - w)]
        return [self._local(u, v, grid) for u, v in local]

    def screws(self):
        """``[(i, j)]``: the holes its screws are in, the corner one first."""
        a, b = _axes(self.corner)
        dx, dy = CORNER_FROM_HOLE
        p = spoilboard.PITCH
        # The furthest hole along each arm that is still inside it.
        nx = int((ARM_X - BAR_W - SCREW_END_MARGIN + abs(dx)) // p)
        ny = int((ARM_Y - BAR_W - SCREW_END_MARGIN + abs(dy)) // p)
        return [(self.i, self.j), (self.i + a * nx, self.j),
                (self.i, self.j + b * ny)]

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


DEFAULT = Bracket(1, 12, DEFAULT_CORNER)


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
