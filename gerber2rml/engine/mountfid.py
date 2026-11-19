"""The board's own holes as the reference holes of a double-sided job.

A double-sided board is found again after the flip by reference (fiducial)
holes the probe drops into. Drilled in the waste they need a bigger sheet;
drilled inside the corners they stay in the finished board. A board that
already has mounting holes needs neither: those holes are drilled anyway, so
they can be the reference holes, and nothing extra is cut.

Pure: which holes, out of a board's ``(x, y, d)`` list. What makes a hole
usable is what the finder needs (:mod:`gerber2rml.engine.fidfind`, and
``AutoRun._locate``):

* wide enough for the probe bit to drop in with room for runout - the bit
  plus 0.8 mm, the same rule as a drilled reference hole;
* not so wide that the four touches 2.5 mm out from its centre, which take
  the surface height before the search, land inside it;
* at least two of one size, far apart: the fit turns the whole top face
  about them, so two holes side by side would let a hair of error at the
  holes become tenths of a millimetre at the far edge.
"""
import math

MAX_D = 4.0            # mm; see the module docstring
ROOM_FOR_BIT = 0.8     # mm the hole must be wider than the bit
MIN_SPREAD = 0.5       # of the board's longer side, between the two furthest


def min_diameter(bit_mm):
    return round(bit_mm + ROOM_FOR_BIT, 2)


def pick(holes, box, bit_mm=0.8, max_d=MAX_D, count=4):
    """The holes to use: up to ``count`` of ``(x, y, d)``, or [] when the
    board has none that will do.

    ``box`` is the board's ``(x0, y0, x1, y1)``. One hole per corner, the
    nearest of its size; sizes are not mixed, because a job has one
    reference-hole diameter. Among sizes, more corners win, then spread.
    """
    x0, y0, x1, y1 = box
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]      # FL FR BR BL
    lo = min_diameter(bit_mm)
    by_size = {}
    for x, y, d in holes:
        if lo - 1e-6 <= d <= max_d + 1e-6:
            by_size.setdefault(round(d, 2), []).append((x, y, d))
    need = MIN_SPREAD * max(x1 - x0, y1 - y0)
    best, best_key = [], None
    for _d, group in sorted(by_size.items()):
        picked = []
        for cx, cy in corners:
            h = min(group, key=lambda h: math.hypot(h[0] - cx, h[1] - cy))
            if h not in picked:
                picked.append(h)
        picked = picked[:max(2, min(4, count))]
        if len(picked) < 2:
            continue
        spread = max(math.hypot(a[0] - b[0], a[1] - b[1])
                     for a in picked for b in picked)
        if spread < need:
            continue
        key = (len(picked), spread)
        if best_key is None or key > best_key:
            best, best_key = picked, key
    return best


# A drill hole the bit can still drop into: wider than the bit by this. A
# hole drilled with the bit itself (0.8 in 0.8) has nothing to drop into.
ANY_ROOM_FOR_BIT = 0.1
WIDTH_BONUS_MM = 10.0


def pick_any(holes, box, bit_mm=0.8, max_d=MAX_D, count=4):
    """Holes to find a re-seated board by when it has no mounting holes:
    up to ``count`` of ``(x, y, d)``, one per corner, or [].

    Any drill hole wider than the bit will do, sizes mixed - each is looked
    for at its own size (``AutoRun._realign``). In each corner's quarter of
    the board the hole nearest the corner wins, a wider one counting
    ``WIDTH_BONUS_MM`` nearer per millimetre it is wider: far-apart holes
    turn the fit about the most board, and a wide hole is found in a few
    touches where one barely wider than the bit takes many.
    """
    x0, y0, x1, y1 = box
    mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]      # FL FR BR BL
    lo = bit_mm + ANY_ROOM_FOR_BIT
    usable = [h[:3] for h in holes if lo - 1e-6 <= h[2] <= max_d + 1e-6]
    picked = []
    for cx, cy in corners:
        quarter = [h for h in usable
                   if (h[0] < mx) == (cx < mx) and (h[1] < my) == (cy < my)]
        if not quarter:
            continue
        h = min(quarter, key=lambda h: math.hypot(h[0] - cx, h[1] - cy)
                - WIDTH_BONUS_MM * (h[2] - bit_mm))
        picked.append(h)
    picked = picked[:max(2, min(4, count))]
    if len(picked) < 2:
        return []
    need = MIN_SPREAD * max(x1 - x0, y1 - y0)
    spread = max(math.hypot(a[0] - b[0], a[1] - b[1])
                 for a in picked for b in picked)
    return picked if spread >= need else []
