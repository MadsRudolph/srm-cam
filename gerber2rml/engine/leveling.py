"""Manual bed-leveling: probe-point programs + height-map Z compensation.

The SRM-20 in NC mode has no probe input (no ``G31``/``G38`` in its word list),
so the surface can't be measured automatically. Instead the operator measures a
grid of points by hand and we warp the G-code offline to follow the surface.

Workflow
--------
1. :func:`probe_points` lays out an ``nx x ny`` grid over the (placed) board.
2. :func:`write_probe_files` writes ONE tiny G-code program per point — spindle
   OFF, go to the point, approach to a small clearance, end. Queue them all in
   VPanel; pressing *Continue* advances to the next point. The operator zeroes Z
   on the copper at point 1 (the datum), then at each point jogs Z down to touch
   and records the Z reading.
3. The recorded ``(x, y, z)`` triples build a :class:`HeightMap`.
4. :func:`apply_leveling` warps every job's cut moves by the map so depth stays
   constant relative to the LOCAL surface, subdividing long moves so Z ramps
   along the warp instead of only at the endpoints.

The map and the toolpaths share one XY frame (machine/work coordinates), so this
must run AFTER placement/mirroring, exactly like :func:`gerber2rml.toolpath.offset`.
"""
import math
from gerber2rml.toolpath import Move


# ---------------------------------------------------------------------------
# Probe grid
# ---------------------------------------------------------------------------

def _linspace(a, b, n):
    if n <= 1:
        return [(a + b) / 2.0]
    return [a + (b - a) * i / (n - 1) for i in range(n)]


def probe_points(bounds, nx=3, ny=3, margin=2.0):
    """Grid of (x, y) probe points over *bounds* = (x0, y0, x1, y1), inset by
    ``margin`` mm so points sit ON the board, not on its edge. Row-major, bottom
    row first, left-to-right — the order the files are numbered and listed."""
    x0, y0, x1, y1 = bounds
    xs = _linspace(x0 + margin, x1 - margin, nx)
    ys = _linspace(y0 + margin, y1 - margin, ny)
    return [(round(x, 3), round(y, 3)) for y in ys for x in xs]


# ---------------------------------------------------------------------------
# Per-point probe G-code (SRM-20 NC, spindle off)
# ---------------------------------------------------------------------------

def _f(v):
    s = f"{v:.3f}".rstrip("0")
    return s if s.endswith(".") else s


def render_probe_point(x, y, idx, total, approach_z=2.0):
    """One probe program: spindle off, lift, go to (x, y), approach to
    ``approach_z`` mm above the Z0 plane, end. Only words on the SRM-20 NC list."""
    return "\n".join([
        "%",
        f"O{idx:04d}",
        f"( gerber2rml bed-level probe {idx}/{total}  X{x:.3f} Y{y:.3f} )",
        "G90 G17",
        "G21",
        "M5",                       # spindle OFF — hand touch-off, not a cut
        "G91",
        "G28 Z0.",                  # lift Z to home
        "G90",
        f"G0 X{_f(x)} Y{_f(y)}",    # go to the point
        f"G0 Z{_f(approach_z)}",    # approach — jog down from here to touch
        "M30",
        "%",
    ]) + "\n"


def write_probe_files(out_dir, name, points, approach_z=2.0):
    """Write one ``{name}_probe_NN.nc`` per point + a ``{name}_probe_checklist.txt``
    with a blank Z column to fill in. Returns the list of Paths written."""
    from pathlib import Path
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    total = len(points)
    written = []
    for i, (x, y) in enumerate(points, start=1):
        p = out_dir / f"{name}_probe_{i:02d}.nc"
        p.write_text(render_probe_point(x, y, i, total, approach_z))
        written.append(p)
    checklist = out_dir / f"{name}_probe_checklist.txt"
    lines = [
        f"BED-LEVELING PROBE: {name}  ({total} points)",
        "",
        "Queue all the _probe_NN.nc files in VPanel. Zero Z on the copper at",
        "point 1 (the datum) — its Z is 0. At each point, jog Z down to touch,",
        "read the Z, and write it below. Then enter these in the GUI.",
        "",
        f"{'#':>3} {'X':>8} {'Y':>8} {'measured Z':>12}",
    ]
    for i, (x, y) in enumerate(points, start=1):
        lines.append(f"{i:>3} {x:>8.3f} {y:>8.3f} {'________':>12}")
    checklist.write_text("\n".join(lines) + "\n", encoding="utf-8")
    written.append(checklist)
    return written


# ---------------------------------------------------------------------------
# Height map
# ---------------------------------------------------------------------------

def _solve3(A, b):
    """Solve a 3x3 system by Cramer's rule (no numpy/BLAS — tiny + robust)."""
    def det3(m):
        return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
                - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
                + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))
    D = det3(A)
    if abs(D) < 1e-12:
        raise ValueError("degenerate probe points (collinear?) — can't fit a plane")
    out = []
    for c in range(3):
        M = [row[:] for row in A]
        for r in range(3):
            M[r][c] = b[r]
        out.append(det3(M) / D)
    return out


class HeightMap:
    """Surface deviation ``dz = f(x, y)`` relative to the Z0 datum.

    Build with :meth:`from_grid` (bilinear — corrects bow/warp; needs a full
    ``nx x ny`` grid) or :meth:`from_plane` (least-squares plane — corrects tilt;
    needs >= 3 non-collinear points). :meth:`from_points` auto-picks: a complete
    grid -> bilinear, otherwise -> plane.
    """

    def __init__(self, fn):
        self._fn = fn

    def __call__(self, x, y):
        return self._fn(x, y)

    # -- plane fit (tilt) --
    @classmethod
    def from_plane(cls, points):
        n = len(points)
        if n < 3:
            raise ValueError("need >= 3 points for a plane fit")
        Sxx = Sxy = Sx = Syy = Sy = S1 = 0.0
        Sxz = Syz = Sz = 0.0
        for x, y, z in points:
            Sxx += x * x; Sxy += x * y; Sx += x
            Syy += y * y; Sy += y; S1 += 1
            Sxz += x * z; Syz += y * z; Sz += z
        A = [[Sxx, Sxy, Sx], [Sxy, Syy, Sy], [Sx, Sy, S1]]
        a, b, c = _solve3(A, [Sxz, Syz, Sz])
        return cls(lambda x, y: a * x + b * y + c)

    # -- bilinear over a regular grid (warp) --
    @classmethod
    def from_grid(cls, xs, ys, z):
        """``xs`` (len nx) and ``ys`` (len ny) ascending; ``z[j][i]`` is the
        measured deviation at (xs[i], ys[j])."""
        xs = list(xs); ys = list(ys)

        def _idx(vals, v):
            if v <= vals[0]:
                return 0, 0, 0.0
            if v >= vals[-1]:
                return len(vals) - 2, len(vals) - 1, 1.0
            for i in range(len(vals) - 1):
                if vals[i] <= v <= vals[i + 1]:
                    span = vals[i + 1] - vals[i]
                    t = (v - vals[i]) / span if span else 0.0
                    return i, i + 1, t
            return len(vals) - 2, len(vals) - 1, 1.0

        def fn(x, y):
            i0, i1, tx = _idx(xs, x)
            j0, j1, ty = _idx(ys, y)
            z00 = z[j0][i0]; z10 = z[j0][i1]
            z01 = z[j1][i0]; z11 = z[j1][i1]
            return ((z00 * (1 - tx) + z10 * tx) * (1 - ty)
                    + (z01 * (1 - tx) + z11 * tx) * ty)

        return cls(fn)

    @classmethod
    def from_points(cls, points, nx=None, ny=None):
        """Auto: a complete ``nx*ny`` grid (row-major, as :func:`probe_points`
        emits) -> bilinear; anything else -> plane fit."""
        if nx and ny and len(points) == nx * ny:
            xs = sorted({round(p[0], 3) for p in points})
            ys = sorted({round(p[1], 3) for p in points})
            if len(xs) == nx and len(ys) == ny:
                zmap = {(round(x, 3), round(y, 3)): z for x, y, z in points}
                z = [[zmap[(xs[i], ys[j])] for i in range(nx)] for j in range(ny)]
                return cls.from_grid(xs, ys, z)
        return cls.from_plane(points)


# ---------------------------------------------------------------------------
# Mesh sanity / probing advice
# ---------------------------------------------------------------------------

def _grid_arrays(points, nx, ny):
    """(xs, ys, z[j][i]) if *points* form a complete nx*ny grid, else None."""
    if not (nx and ny and len(points) == nx * ny):
        return None
    xs = sorted({round(p[0], 3) for p in points})
    ys = sorted({round(p[1], 3) for p in points})
    if len(xs) != nx or len(ys) != ny:
        return None
    zmap = {(round(x, 3), round(y, 3)): z for x, y, z in points}
    z = [[zmap[(xs[i], ys[j])] for i in range(nx)] for j in range(ny)]
    return xs, ys, z


def flag_outliers(points, tol=0.10):
    """Leave-one-out residuals: for each point, fit a smooth surface to all the
    OTHER points and flag it if it disagrees by more than ``tol`` mm.

    The reference surface is a quadratic when enough points remain (bow and
    saddle are legitimate board shapes — a plane would flag genuine warp),
    else a plane. This catches the classic flaky-touch case: one point that no
    smooth board surface can explain. A whole mis-measured ROW is fundamentally
    ambiguous from geometry alone — that's what the drift re-touch is for.

    Returns ``[(index, residual_mm), ...]`` sorted worst-first.
    """
    import numpy as np
    n = len(points)
    if n < 5:
        return []
    flagged = []
    for k in range(n):
        rest = [p for i, p in enumerate(points) if i != k]
        x = np.array([p[0] for p in rest])
        y = np.array([p[1] for p in rest])
        z = np.array([p[2] for p in rest])
        if len(rest) >= 8:
            A = np.column_stack([np.ones_like(x), x, y, x * x, x * y, y * y])
        else:
            A = np.column_stack([np.ones_like(x), x, y])
        try:
            coef, *_ = np.linalg.lstsq(A, z, rcond=None)
        except np.linalg.LinAlgError:
            continue
        px, py, pz = points[k]
        basis = ([1.0, px, py, px * px, px * py, py * py]
                 if A.shape[1] == 6 else [1.0, px, py])
        pred = float(np.dot(coef, basis))
        r = abs(pz - pred)
        if r > tol:
            flagged.append((k, r))
    flagged.sort(key=lambda t: -t[1])
    return flagged


def recommend_depth(points, nx=None, ny=None, copper=0.035, noise=0.03,
                    min_depth=0.15):
    """Recommend a trace cut depth that survives this mesh's uncertainty.

    The uncut-copper failure needs (surface-model error) > (depth - copper).
    Model error is estimated as the worst mid-cell interpolation risk: a smooth
    bow between two probe lines deviates from the straight (bilinear) chord by
    roughly a quarter of the corner-to-corner spread, plus a probe-noise floor.

    Returns ``{"depth", "range", "worst_spread", "est_error", "detail"}``.
    """
    zs = [p[2] for p in points]
    rng = (max(zs) - min(zs)) if zs else 0.0
    worst = 0.0
    where = ""
    g = _grid_arrays(points, nx, ny)
    if g:
        xs, ys, z = g
        for j in range(len(ys) - 1):
            for i in range(len(xs) - 1):
                corners = [z[j][i], z[j][i + 1], z[j + 1][i], z[j + 1][i + 1]]
                spread = max(corners) - min(corners)
                if spread > worst:
                    worst = spread
                    where = (f"cell x {xs[i]:.0f}..{xs[i + 1]:.0f}, "
                             f"y {ys[j]:.0f}..{ys[j + 1]:.0f}")
    else:
        worst = rng                      # no grid structure: be conservative
        where = "whole mesh (no complete grid)"
    # /3 (not the textbook /4) after the MegaPCB post-mortem: real meshes carry
    # measurement error on top of pure interpolation error, and under-cutting
    # costs a whole rework pass while 30 um of extra depth costs nothing with a
    # flat bit (isolation width doesn't grow with depth).
    est_error = worst / 3.0 + noise
    depth = max(min_depth, math.ceil((copper + est_error + 0.02) * 100) / 100)
    return {"depth": depth, "range": rng, "worst_spread": worst,
            "est_error": est_error,
            "detail": (f"mesh range {rng * 1000:.0f} um; worst cell spread "
                       f"{worst * 1000:.0f} um ({where}); est. mid-cell error "
                       f"{est_error * 1000:.0f} um -> cut >= {depth:.2f} mm")}


def suggest_refinement_rows(points, nx, ny, budget=0.08):
    """Where is the grid too coarse? For each adjacent pair of probe ROWS
    (columns), if the surface changes more than ``budget`` mm between them, a
    new full row (column) at their midpoint is worth probing — full lines keep
    the grid cartesian, so bilinear interpolation stays available.

    Returns ``{"rows": [y_mid, ...], "cols": [x_mid, ...]}`` (mm, sorted).
    """
    g = _grid_arrays(points, nx, ny)
    if not g:
        return {"rows": [], "cols": []}
    xs, ys, z = g
    rows = []
    for j in range(len(ys) - 1):
        jump = max(abs(z[j + 1][i] - z[j][i]) for i in range(len(xs)))
        if jump > budget:
            rows.append(round((ys[j] + ys[j + 1]) / 2.0, 3))
    cols = []
    for i in range(len(xs) - 1):
        jump = max(abs(z[j][i + 1] - z[j][i]) for j in range(len(ys)))
        if jump > budget:
            cols.append(round((xs[i] + xs[i + 1]) / 2.0, 3))
    return {"rows": rows, "cols": cols}


# ---------------------------------------------------------------------------
# Toolpath warp
# ---------------------------------------------------------------------------

def apply_leveling(paths, hmap, max_seg=1.0):
    """Warp toolpaths to follow the surface: add ``hmap(x, y)`` to every move's Z,
    subdividing feed (non-rapid) moves into <= ``max_seg`` mm steps so the Z
    correction ramps along the warp. Rapids keep constant clearance above the
    surface and need no subdivision. Returns new toolpaths; input is untouched."""
    out = []
    for tp in paths:
        new = []
        prev = None                       # previous NOMINAL move (pre-warp)
        for m in tp:
            if prev is None or m.rapid:
                new.append(Move(m.x, m.y, m.z + hmap(m.x, m.y), m.rapid))
            else:
                dist = math.hypot(m.x - prev.x, m.y - prev.y)
                n = max(1, math.ceil(dist / max_seg)) if dist else 1
                for k in range(1, n + 1):
                    t = k / n
                    x = prev.x + (m.x - prev.x) * t
                    y = prev.y + (m.y - prev.y) * t
                    z = prev.z + (m.z - prev.z) * t          # nominal Z lerp
                    new.append(Move(x, y, z + hmap(x, y), rapid=False))
            prev = m
        out.append(new)
    return out
