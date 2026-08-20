"""The dry-run outline — where the board will be, traced in the air.

Without the machine link there is no probe, no live position and no way to ask
the machine "is the copper where I think it is?". The only feedback a student
gets is the first cut, and by then the answer is expensive.

So: trace the board's outline with the spindle off and the bit held clear of
everything, at a feed slow enough to watch. If the stock is misplaced you see
the bit run off the edge of the copper and you stop, having lost twenty
seconds. It is the cheapest possible check and it needs no hardware at all.

Nothing here can cut: every move is at one constant height, and the renderer
is asked not to start the spindle.
"""
from gerber2rml.toolpath import Move

DEFAULT_HEIGHT = 5.0      # mm above the work Z zero — clear of stock and tape
DEFAULT_FEED = 15.0       # mm/s; fast enough not to be tedious, slow enough to
                          # follow with your eyes and hit the pause button


def _ring(outline):
    """The outline's exterior as a closed list of (x, y), or None."""
    geom = outline
    if geom is None or geom.is_empty:
        return None
    if geom.geom_type == "MultiPolygon":
        geom = max(geom.geoms, key=lambda g: g.area)     # the board itself
    if geom.geom_type != "Polygon":
        geom = geom.envelope
    return list(geom.exterior.coords)


def air_path(outline, height=DEFAULT_HEIGHT):
    """One closed loop over *outline* at *height*, as a toolpath list.

    The first move is a rapid to the start (nothing is near the tool at this
    height); everything after is a feed move, because a rapid is far too fast
    to react to and this exists to be watched.
    """
    ring = _ring(outline)
    if not ring:
        return []

    x0, y0 = ring[0]
    moves = [Move(x0, y0, height, rapid=True)]
    moves += [Move(x, y, height) for x, y in ring[1:]]
    if (round(ring[-1][0], 6), round(ring[-1][1], 6)) != (round(x0, 6), round(y0, 6)):
        moves.append(Move(x0, y0, height))               # close the loop
    return [moves]
