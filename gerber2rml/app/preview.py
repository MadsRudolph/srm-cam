"""Turn toolpaths into cut/rapid polylines (lists of (x,y)) for plotting."""


def toolpath_segments(toolpaths):
    """Return (cuts, rapids): each a list of polylines [[(x,y), ...], ...].
    Consecutive moves of the same kind (cut vs rapid) form one polyline; the
    boundary point is shared so the drawn path stays continuous.

    The ``rapids`` this returns carry almost no XY extent — see
    :func:`traverse_segments` for why. Anything drawing travel moves for a
    person to look at wants :func:`preview_segments` instead.
    """
    cuts, rapids = [], []
    for tp in toolpaths:
        if not tp:
            continue
        cur = [(tp[0].x, tp[0].y)]
        cur_rapid = tp[0].rapid
        for m in tp[1:]:
            if m.rapid == cur_rapid:
                cur.append((m.x, m.y))
            else:
                (rapids if cur_rapid else cuts).append(cur)
                cur = [cur[-1], (m.x, m.y)]   # share boundary point
                cur_rapid = m.rapid
        (rapids if cur_rapid else cuts).append(cur)
    return cuts, rapids


def traverse_segments(toolpaths):
    """The moves BETWEEN toolpaths: the end of one, to the start of the next.

    These are the flights across the board with the bit in the air, and they
    are not in the toolpath data at all. Every generator here emits one path
    per contour, each beginning with a rapid to its own start point, so within
    a path the only rapid runs are a plunge and a retract — both at a single
    XY. :func:`toolpath_segments` therefore reports rapid polylines that are
    one point, or two identical points, and a preview drawing them draws
    nothing: on the bundled demo board, all 50 of them.

    Both GUIs shipped a travel-move layer that had never displayed anything.

    The motion is real even though the geometry is implied — the tool has to
    get from where one contour ended to where the next one starts — and
    :func:`gerber2rml.engine.estimate.estimate_toolpaths_seconds` already
    charges for it, because it carries the tool position across paths. This
    returns exactly the motion that estimator is timing.
    """
    out = []
    last = None
    for tp in toolpaths:
        if not tp:
            continue
        first = (tp[0].x, tp[0].y)
        if last is not None and (abs(last[0] - first[0]) > 1e-9
                                 or abs(last[1] - first[1]) > 1e-9):
            out.append([last, first])
        last = (tp[-1].x, tp[-1].y)
    return out


def preview_segments(toolpaths):
    """``(cuts, rapids)`` for display, with the between-path traverses included.

    What a preview should draw: the cuts, and every move the machine makes in
    the air to join them up.
    """
    cuts, rapids = toolpath_segments(toolpaths)
    return cuts, rapids + traverse_segments(toolpaths)
