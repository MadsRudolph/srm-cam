"""Drilling a board that was made somewhere else.

The traces were etched on the laser, or the board came off another machine,
and only the holes are left for the mill. Nothing the mill cut is on it, so
there is no origin to trust: the board goes down wherever it goes down and the
drill file has to be moved to it rather than the other way round.

The pads already on the board are the reference. Pick a few holes from the
drill file, measure where their pads really are on the machine (jog over the
centre, or find a bare drill mark electrically), and fit the same rigid
transform the fiducial flip uses (:mod:`gerber2rml.engine.fiducial`) from
where the design puts them to where they are. Every hole is then moved by it.

Three pads, not two. A rigid move keeps distances, and a mirror image keeps
them too, so two pads fit a board etched the other way round exactly as well
as the right one. Three pads that are not in a line also have a handedness - the
order they go round in - and no rotation can turn that inside out, so a
mirrored board comes out millimetres wrong. That only holds while each pad is
recognised by what it IS (which pin of which part), never by where it sits in
the picture: measure "the top-left pad" of a mirrored picture and the numbers
describe the picture, and fit it perfectly.
"""
import math

from gerber2rml.engine.drill import drill_jobs
from gerber2rml.engine.fiducial import fit_transform, rms

MIN_PADS = 3


def nearest_hole(holes, x, y):
    """Index of the hole in ``holes`` ([(x, y, d)]) closest to (x, y), or None."""
    best, best_d = None, float("inf")
    for i, (hx, hy, *_r) in enumerate(holes or []):
        d = math.hypot(hx - x, hy - y)
        if d < best_d:
            best, best_d = i, d
    return best


def _area(a, b, c):
    return abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])) / 2


def suggest_pads(holes, n=MIN_PADS):
    """Indices of ``n`` holes worth measuring: far apart, and not in a line.

    The first two are the farthest pair - spread is what makes the rotation
    accurate. The third makes the biggest triangle with them, which is what
    gives the set a handedness a mirrored board cannot match. Further picks,
    if asked for, keep adding the hole farthest from all chosen.
    """
    pts = [(h[0], h[1]) for h in holes or []]
    # Distinct positions only: a drill file can list a hole twice.
    uniq = []
    for i, p in enumerate(pts):
        if all(math.dist(p, pts[j]) > 1e-6 for j in uniq):
            uniq.append(i)
    if len(uniq) <= n:
        return uniq
    a, b = max(((i, j) for k, i in enumerate(uniq) for j in uniq[k + 1:]),
               key=lambda ij: math.dist(pts[ij[0]], pts[ij[1]]))
    chosen = [a, b]
    rest = [i for i in uniq if i not in chosen]
    chosen.append(max(rest, key=lambda i: _area(pts[a], pts[b], pts[i])))
    while len(chosen) < n:
        rest = [i for i in uniq if i not in chosen]
        chosen.append(max(rest, key=lambda i: min(
            math.dist(pts[i], pts[c]) for c in chosen)))
    return chosen


def mirror_ambiguous(points, tol=0.3):
    """True when these points would ALSO fit a board mirrored left-right.

    The mirror image, pad for pad, is fitted back onto the originals rigidly;
    if that fits to within ``tol`` mm a mirrored board would pass with a clean
    residual. It happens when the pads are (nearly) in one line - and always
    with two.
    """
    pts = [(float(x), float(y)) for x, y in points]
    if len(pts) < MIN_PADS:
        return True
    flipped = [(-x, y) for x, y in pts]
    try:
        t = fit_transform(flipped, pts)
    except ValueError:
        return True
    return rms(t, flipped, pts) < tol


def warp_holes(holes, t):
    """Every hole moved by transform ``t``; diameters untouched."""
    return [(*t.apply(x, y), d) for (x, y, d) in holes]


def write_fitted_drill(holes, drill, t, out_dir, name, machine, level=None):
    """Write the drill file(s) for ``holes`` moved onto the measured board.

    ``holes`` are machine mm as the design places them; ``t`` maps that onto
    the board that is actually on the bed. Named ``<name>_drill_fitted`` so it
    can never be mistaken for, or overwrite, a normal job's drill file.
    Returns the paths written.
    """
    from pathlib import Path
    from gerber2rml.backends import BACKENDS
    backend = BACKENDS[machine]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    deg = math.degrees(t.theta)
    for fname, paths in drill_jobs(warp_holes(holes, t), drill,
                                   f"{name}_drill_fitted", ext=backend.ext):
        if level is not None:
            from gerber2rml.engine.leveling import apply_leveling
            paths = apply_leveling(paths, level)
        p = out_dir / fname
        p.write_text(backend.render(
            paths, xy_feed=drill.xy_feed, plunge_feed=drill.plunge_feed,
            header=[f"{name} - DRILL ONLY, fitted to a board already made",
                    f"bit {drill.bit_diameter} mm, through {drill.total_depth} mm",
                    f"moved {t.tx:+.3f}, {t.ty:+.3f} mm, turned {deg:+.3f} deg"
                    + (f", scaled x{t.scale:.4f}" if abs(t.scale - 1) > 1e-9
                       else ""),
                    "do NOT move the board or the XY origin after measuring"]))
        written.append(p)
    return written
