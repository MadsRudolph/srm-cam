"""Rework selection: clip existing toolpaths to a picked region for a 2nd pass.

When an isolation (or cutout) pass leaves copper not cut all the way through,
the operator can box-select the problem area in the GUI and re-run *only* that
part instead of the whole job. This module takes the already-generated
:class:`~gerber2rml.toolpath.Move` lists and keeps just the cut geometry inside
the selected rectangle -- trimming partial segments to the box edge -- then
rebuilds a proper rapid -> plunge -> cut -> retract cycle for each retained run
so the result is a valid stand-alone program.

Cut depth (the ``z`` of each cut move) is preserved verbatim, so a clipped job
is a faithful repeat of the original pass over the chosen area. To cut deeper,
bump the job's depth, regenerate the preview, then export the selection again.
"""
from gerber2rml.toolpath import Move

_EPS = 1e-9


def _norm_bbox(bbox):
    x0, y0, x1, y1 = bbox
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def _close(a, b):
    return abs(a[0] - b[0]) < _EPS and abs(a[1] - b[1]) < _EPS


def _clip_segment(p, q, bbox):
    """Liang-Barsky clip of segment p->q to ``bbox``.

    Returns the ``(a, b)`` endpoints of the portion inside the box (each a
    ``(x, y)`` tuple), or ``None`` if the segment misses the box entirely.
    ``a == p``/``b == q`` mean that end was already inside.
    """
    x0, y0, x1, y1 = bbox
    dx, dy = q[0] - p[0], q[1] - p[1]
    t0, t1 = 0.0, 1.0
    for num, den in (
        (p[0] - x0, -dx),    # left   edge: x >= x0
        (x1 - p[0], dx),     # right  edge: x <= x1
        (p[1] - y0, -dy),    # bottom edge: y >= y0
        (y1 - p[1], dy),     # top    edge: y <= y1
    ):
        # parametric edge test; den==0 means parallel to this edge
        if abs(den) < _EPS:
            if num < 0:
                return None          # parallel and outside this edge
            continue
        t = num / den
        if den < 0:                  # entering -> raise the near bound
            if t > t1:
                return None
            if t > t0:
                t0 = t
        else:                        # leaving -> lower the far bound
            if t < t0:
                return None
            if t < t1:
                t1 = t
    a = (p[0] + t0 * dx, p[1] + t0 * dy)
    b = (p[0] + t1 * dx, p[1] + t1 * dy)
    return a, b


def _run_to_toolpath(run, cut_z, travel_z):
    """Wrap a run of (x, y) points with rapid approach, plunge, cuts, retract."""
    sx, sy = run[0]
    tp = [Move(sx, sy, travel_z, rapid=True), Move(sx, sy, cut_z)]
    for (x, y) in run[1:]:
        tp.append(Move(x, y, cut_z))
    tp.append(Move(run[-1][0], run[-1][1], travel_z, rapid=True))
    return tp


def clip_toolpaths_to_bbox(toolpaths, bbox, cut_z=None):
    """Return new toolpaths covering only the cut geometry inside ``bbox``.

    ``bbox`` is ``(x0, y0, x1, y1)`` in board millimetres, in any corner order.
    Cut segments are clipped to the box (partial segments are trimmed to the
    edge); each maximal connected run inside the box becomes its own toolpath
    with a fresh rapid approach and retract at the source toolpath's travel
    height.

    ``cut_z`` (machine mm, negative for below the surface) overrides the depth
    the rework cuts at; when None each run keeps the source pass's own depth.
    Use it to re-cut a missed area deeper than the first pass without touching
    the original job.
    """
    bbox = _norm_bbox(bbox)
    result = []
    for tp in toolpaths:
        travel_z = max((m.z for m in tp if m.rapid), default=None)
        cut_moves = [m for m in tp if not m.rapid]
        if len(cut_moves) < 2:
            continue
        run_cut_z = cut_moves[0].z if cut_z is None else cut_z
        if travel_z is None:                          # no rapid -> park above cuts
            travel_z = max(m.z for m in cut_moves)
        pts = [(m.x, m.y) for m in cut_moves]
        run = []
        for p, q in zip(pts, pts[1:]):
            clip = _clip_segment(p, q, bbox)
            if clip is None:
                if run:
                    result.append(_run_to_toolpath(run, run_cut_z, travel_z))
                    run = []
                continue
            a, b = clip
            if run and _close(run[-1], a):
                run.append(b)
            else:
                if run:
                    result.append(_run_to_toolpath(run, run_cut_z, travel_z))
                run = [a, b]
            if not _close(b, q):                      # segment exits the box at b
                result.append(_run_to_toolpath(run, run_cut_z, travel_z))
                run = []
        if run:
            result.append(_run_to_toolpath(run, run_cut_z, travel_z))
    return result
