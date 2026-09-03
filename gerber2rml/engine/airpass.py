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


def _rings(outline):
    """The exterior of every island in *outline* as closed (x, y) lists.

    One board is one loop. A sheet of several boards is a MultiPolygon and
    gets a loop per board, left to right - the point of the dry run is to
    watch each of them land on copper, not just the biggest.
    """
    if outline is None or outline.is_empty:
        return []
    if outline.geom_type == "MultiPolygon":
        polys = sorted(outline.geoms, key=lambda g: (g.bounds[0], g.bounds[1]))
    elif outline.geom_type == "Polygon":
        polys = [outline]
    else:
        polys = [outline.envelope]
    return [list(p.exterior.coords) for p in polys if not p.is_empty]


def air_path(outline, height=DEFAULT_HEIGHT):
    """A closed loop over every island of *outline* at *height*, as a toolpath
    list - one path per island.

    The first move of each is a rapid to its start (nothing is near the tool
    at this height); everything after is a feed move, because a rapid is far
    too fast to react to and this exists to be watched.
    """
    paths = []
    for ring in _rings(outline):
        x0, y0 = ring[0]
        moves = [Move(x0, y0, height, rapid=True)]
        moves += [Move(x, y, height) for x, y in ring[1:]]
        if (round(ring[-1][0], 6), round(ring[-1][1], 6)) != (round(x0, 6), round(y0, 6)):
            moves.append(Move(x0, y0, height))           # close the loop
        paths.append(moves)
    return paths
