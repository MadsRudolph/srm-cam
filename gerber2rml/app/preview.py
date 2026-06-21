"""Turn toolpaths into cut/rapid polylines (lists of (x,y)) for plotting."""


def toolpath_segments(toolpaths):
    """Return (cuts, rapids): each a list of polylines [[(x,y), ...], ...].
    Consecutive moves of the same kind (cut vs rapid) form one polyline; the
    boundary point is shared so the drawn path stays continuous."""
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
