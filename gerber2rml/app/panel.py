"""Several boards on one sheet of copper, cut as one job.

Two Gerber folders, placed side by side on the stock, come off the machine in
one run: one isolation pass, one drill file, one cut-out. The engine never
learns this. It is handed ONE :class:`~gerber2rml.loader.Board` whose copper is
the union of every board's copper, whose outline is every board's outline, and
whose holes are all of them. Isolation, the shorts check, bed levelling, the
screw keep-out and the pre-flight checks then work exactly as they do for a
single board, and the cut-out and the dry run simply visit every outline.

What this module owns is the list of placed boards and the composition. The
app's state keeps the list; the interface moves the members around.
"""
from dataclasses import dataclass, field
from pathlib import Path

from shapely.geometry import Polygon
from shapely.ops import unary_union

from gerber2rml.loader import (Board, load_board, gerber_stem, rotate_board,
                               place_in_positive_quadrant, translate_board)

# Waste the app leaves between neighbouring boards when it places one for
# you. Each cut-out channel is one cutter wide, just outside its outline, so
# two 0.8 mm channels meet at 1.6 mm apart; 4 mm leaves a strip of stock
# between them wide enough to stay put when the boards come free.
PANEL_GAP_MM = 4.0


@dataclass
class Placed:
    """One board on the sheet: where it came from, and where it sits."""
    gerber_dir: Path
    name: str
    base: Board           # as loaded: mirrored or not, corner at the margin, unturned
    rotate: int = 0       # degrees CCW: 0, 90, 180 or 270
    place_x: float = 0.0  # shift from the loaded position, machine mm
    place_y: float = 0.0
    _cache: tuple = field(default=None, repr=False, compare=False)

    def oriented(self):
        """The base board turned to ``rotate``, back in the positive quadrant."""
        if self.rotate % 360:
            return place_in_positive_quadrant(rotate_board(self.base, self.rotate))
        return self.base

    def board(self):
        """The board as it sits on the bed.

        Handed back as the SAME object until something it depends on changes:
        the stage keys its built paths and its rendered raster on identity,
        so a fresh copy per call would re-stroke the scene every time a step
        was selected. The base is compared by identity too, and kept in the
        cache so a reloaded one can never reuse its address.
        """
        key = (self.rotate % 360, self.place_x, self.place_y)
        c = self._cache
        if c is None or c[0] is not self.base or c[1] != key:
            self._cache = (self.base, key,
                           translate_board(self.oriented(),
                                           self.place_x, self.place_y))
        return self._cache[2]

    def footprint(self):
        """The placed outline; the copper's hull for a board without one."""
        b = self.board()
        if b.outline is not None and not b.outline.is_empty:
            return b.outline
        return b.copper.convex_hull

    def bounds(self):
        """``(x0, y0, x1, y1)`` of the placed board, machine mm."""
        return self.footprint().bounds


def read_board(folder, *, mirror=True, taken=()):
    """Load ``folder`` as a :class:`Placed` sitting at the loaded position.

    Named after the KiCad project, and made distinct from ``taken`` - the names
    already on the sheet - because the same design twice is a normal panel
    ("two of these") and two members both called ``buck`` cannot be told apart
    in a list, on the stage or in the run plan.
    """
    folder = Path(folder)
    base = place_in_positive_quadrant(load_board(folder, mirror=mirror))
    stem = gerber_stem(folder) or folder.name or "board"
    name, n = stem, 1
    while name in taken:
        n += 1
        name = f"{stem} {n}"
    return Placed(gerber_dir=folder, name=name, base=base)


def compose(boards):
    """One :class:`Board` out of several placed ones.

    Copper is unioned, so isolation offsets around everything at once and the
    shorts check sees two boards placed too close as the short it is. Outlines
    are unioned as well: disjoint boards give a MultiPolygon that the cut-out
    and the dry run walk island by island, and overlapping ones merge, which
    :func:`clearances` reports before anything is written. Holes are simply
    all of them.

    One board comes back as itself, untouched, so a plain job is exactly what
    it was before panels existed.
    """
    boards = list(boards)
    if not boards:
        return None
    if len(boards) == 1:
        return boards[0]

    def union(geoms):
        geoms = [g for g in geoms if g is not None and not g.is_empty]
        return unary_union(geoms) if geoms else Polygon()

    return Board(copper=union(b.copper for b in boards),
                 outline=union(b.outline for b in boards),
                 holes=[h for b in boards for h in b.holes],
                 copper_top=union(b.copper_top for b in boards))


def extent(members):
    """The box round every placed board, or None."""
    boxes = [m.bounds() for m in members]
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def next_slot(members, newcomer, gap=PANEL_GAP_MM):
    """Where a board added to ``members`` should go: to the right of all of
    them, ``gap`` mm clear, with its front edge level with the panel's.

    Returns ``(place_x, place_y)`` for ``newcomer``.
    """
    ext = extent(members)
    if ext is None:
        return newcomer.place_x, newcomer.place_y
    x0, y0, x1, _y1 = ext
    nx0, ny0, _nx1, _ny1 = newcomer.bounds()
    return (newcomer.place_x + (x1 + gap) - nx0,
            newcomer.place_y + y0 - ny0)


def arrange_row(members, gap=PANEL_GAP_MM):
    """Lay the boards out left to right, in list order, ``gap`` mm apart and
    with their front edges level. The first stays where it is; the others
    are moved to follow it."""
    prev = None
    for m in members:
        if prev is not None:
            px0, py0, px1, _py1 = prev.bounds()
            mx0, my0, _mx1, _my1 = m.bounds()
            m.place_x += (px1 + gap) - mx0
            m.place_y += py0 - my0
        prev = m


def clearances(members):
    """How close every pair of boards is.

    ``[(name_a, name_b, gap_mm, overlap)]``, overlaps first and then nearest
    first, so the head of the list is the worst pair on the sheet.
    """
    out = []
    for i in range(len(members)):
        for j in range(i + 1, len(members)):
            fa, fb = members[i].footprint(), members[j].footprint()
            overlap = fa.intersects(fb) and fa.intersection(fb).area > 1e-6
            gap = 0.0 if overlap else fa.distance(fb)
            out.append((members[i].name, members[j].name, gap, overlap))
    out.sort(key=lambda t: (not t[3], t[2]))
    return out
