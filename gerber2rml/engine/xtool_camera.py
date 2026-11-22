"""The F1 Ultra's camera: a straight-down picture of the bed, and the height of
whatever is under the head.

The laser keeps two calibration files, made at the factory, that xTool's own
software downloads (``/file?action=download&filename=...&filetype=3``):

``global_calib.json``
    Where each point of a 23 x 23 grid, 10 mm apart, appears in the camera's
    4656 x 3496 photo of a surface in focus. The grid is stored turned half
    round: point (i, j) is the laser's coordinate (220 - 10 i, 220 - 10 j) mm.
    Found on the lab's machine by firing the dot at (110, 50) and (50, 110),
    which came out at Y 170.8 and X 170.5 before this was allowed for. A photo
    resampled through the grid is then a map of the bed in the same millimetres
    the job file uses.

``global_ir.json``
    The same grid at 21 surface heights, -50 to +50 mm from the focal plane:
    where a dot fired at grid point (i, j) appears when the surface is that far
    above (+) or below (-) focus. The camera rides on the head, so the heights
    are relative to the head's current focus, not to the bed.

Autofocus is triangulation with the second file, as xTool Studio does it: the
blue diode on at a glow (S30) as a dot at (110, 110), the lights off, a photo,
the dot found, and its row in the picture read against the 21 heights. The
answer is how far to move the head; about 4 px of picture per mm of height, so
a quarter of a millimetre. Checked on the lab's machine: raising the head 3 mm
read -3.15.

numpy is needed here; it comes with the GUI's dependencies, and only the GUI
uses this module.
"""
import json
import math
import re
from dataclasses import dataclass

import numpy as np

GRID_N = 23
GRID_MM = 10.0
DOT_AT = (110.0, 110.0)          # mm; the grid point (11, 11)
DOT_MIN = 150                    # the dot's score (blue + mean), at least
DOT_CONTRAST = 120               # and this far above the dark around it


class CameraError(RuntimeError):
    pass


class Calibration:
    """The two factory files, parsed."""

    def __init__(self, calib, ir):
        if isinstance(calib, (bytes, str)):
            calib = json.loads(calib)
        if isinstance(ir, (bytes, str)):
            ir = json.loads(ir)
        pts = [tuple(map(float, t.split(",")))
               for t in re.findall(r"\[([^\]]+)\]", calib["data0"])]
        n = int(calib.get("grid_num_w", GRID_N))
        if len(pts) != n * n:
            raise CameraError(f"global_calib.json has {len(pts)} points, not {n * n}.")
        self.n = n
        self.grid = np.array(pts, float).reshape(n, n, 2)          # [j, i] -> px
        self.src_size = (int(calib["image_src_w"]), int(calib["image_src_h"]))
        self.ir_z = np.array(ir["z"], float)                        # ascending
        self.ir = np.array(ir["map"], float).reshape(len(ir["z"]), n, n, 2)

    @property
    def extent_mm(self):
        return (self.n - 1) * GRID_MM

    # -- the picture -----------------------------------------------------
    def rectify(self, rgb, px_per_mm=4, offset=(0.0, 0.0)):
        """``rgb`` (h, w, 3) uint8 photo -> a bed map, ``px_per_mm`` pixels
        per mm, row 0 at Y 0 and column 0 at X 0 of the laser's coordinates.

        ``offset`` is the camera's own error, learned from a real cut: where a
        hole the laser cut at P shows up, minus P. The factory grid on the
        lab's machine shows everything about (-0.55, -0.85) mm off. Each pixel
        of the map is taken from that far off in the photo, so the map lands
        on what the fiber really cuts."""
        h, w = rgb.shape[:2]
        sw, sh = self.src_size
        size = int(round(self.extent_mm * px_per_mm))
        mm = np.arange(size) / px_per_mm
        X, Y = np.meshgrid(mm, mm)
        X = X + offset[0]
        Y = Y + offset[1]
        e = self.extent_mm
        f = self._bilinear(self.grid, (e - X) / GRID_MM, (e - Y) / GRID_MM)
        px = np.clip(np.rint(f[..., 0] * w / sw).astype(int), 0, w - 1)
        py = np.clip(np.rint(f[..., 1] * h / sh).astype(int), 0, h - 1)
        return np.ascontiguousarray(rgb[py, px])

    def _bilinear(self, grid, fi, fj):
        n = self.n
        i0 = np.clip(np.floor(fi).astype(int), 0, n - 2)
        j0 = np.clip(np.floor(fj).astype(int), 0, n - 2)
        u = (fi - i0)[..., None]
        v = (fj - j0)[..., None]
        return (grid[j0, i0] * (1 - u) * (1 - v) + grid[j0, i0 + 1] * u * (1 - v)
                + grid[j0 + 1, i0] * (1 - u) * v + grid[j0 + 1, i0 + 1] * u * v)

    # -- the height ------------------------------------------------------
    def dot_track(self, at=DOT_AT):
        """Where the dot fired at ``at`` appears, for each of the heights."""
        e = self.extent_mm
        i = int(round((e - at[0]) / GRID_MM))
        j = int(round((e - at[1]) / GRID_MM))
        return self.ir[:, j, i, :]                                  # (z, 2)

    def find_dot(self, rgb, at=DOT_AT):
        """The dot's centre in the photo, in the calibration's pixels, and how
        many pixels lit. Looks only along the track the dot can take."""
        h, w = rgb.shape[:2]
        sw, sh = self.src_size
        track = self.dot_track(at) * (w / sw, h / sh)
        x0, y0 = (track.min(axis=0) - 60).astype(int)
        x1, y1 = (track.max(axis=0) + 60).astype(int)
        x0, y0 = max(x0, 0), max(y0, 0)
        win = rgb[y0:y1, x0:x1].astype(int)
        if win.size == 0:
            raise CameraError("The dot's search window is off the photo.")
        score = win[..., 2] + win.sum(axis=2) // 3        # blue, and bright
        top = score.max()
        # The lights are off, so the window is near black (median ~1) and
        # the dot stands far above it. A dot on a cut line or the edge of a
        # hole scatters less back: at the machine one read 282-290 where the
        # rest read 350-510, and a fixed 300 threw away the whole focus map.
        # So: well above the window's own background, and above a floor.
        if top < max(DOT_MIN, np.median(score) + DOT_CONTRAST):
            raise CameraError("No dot in the photo: is the lid closed and the "
                              "material under the head?")
        ys, xs = np.nonzero(score > top - 40)
        if len(xs) > 4000:
            raise CameraError("The photo is too bright to find the dot in.")
        return ((x0 + xs.mean()) * sw / w, (y0 + ys.mean()) * sh / h), len(xs)

    def height(self, dot_px, at=DOT_AT):
        """mm of surface above the focal plane for a dot seen at ``dot_px``.
        Positive means the head must go up by that much."""
        ys = self.dot_track(at)[:, 1]
        z = self.ir_z
        order = np.argsort(ys)
        y = dot_px[1]
        if not ys.min() - 20 <= y <= ys.max() + 20:
            raise CameraError(f"The dot is outside the calibrated ±"
                              f"{abs(z).max():g} mm: move the head by hand.")
        return float(np.interp(y, ys[order], z[order]))


def decode_jpeg(data):
    """JPEG bytes -> (h, w, 3) uint8, through Qt so nothing else is needed."""
    from PySide6.QtGui import QImage
    img = QImage.fromData(data)
    if img.isNull():
        raise CameraError("The camera sent something that is not a picture.")
    img = img.convertToFormat(QImage.Format_RGB888)
    w, h = img.width(), img.height()
    a = np.frombuffer(img.constBits(), np.uint8).reshape(h, img.bytesPerLine())
    return np.array(a[:, :w * 3].reshape(h, w, 3))


# ---------------------------------------------------------------------------
# Alignment: find holes already cut, after the foil has moved
# ---------------------------------------------------------------------------

def _box_blur(a, r):
    """Mean over a (2r+1)^2 box, by summed-area table."""
    p = np.pad(a, r + 1, mode="edge").cumsum(0).cumsum(1)
    k = 2 * r + 1
    s = p[k:, k:] - p[:-k, k:] - p[k:, :-k] + p[:-k, :-k]
    return s[:a.shape[0], :a.shape[1]] / (k * k)


def darkness(rgb, px_per_mm, scale_mm=2.0):
    """How much darker each pixel is than the foil around it, 0..1. A hole cut
    through bright foil is dark; a large dark area (tape, the bed) is not
    darker than its own surroundings, so it mostly drops out."""
    g = rgb.astype(np.float32).mean(axis=2)
    bg = _box_blur(g, max(1, int(scale_mm * px_per_mm)))
    d = np.clip(bg - g, 0, None)
    top = np.percentile(d, 99.7) or 1.0
    return np.clip(d / top, 0, 1)


def _raster(paths, origin, shape, px_per_mm):
    """Filled holes (bed mm) as a float image of ``shape``, (0, 0) at ``origin``."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPolygonF
    h, w = shape
    img = QImage(w, h, QImage.Format_Grayscale8)
    img.fill(0)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(QColor(255, 255, 255)))
    ox, oy = origin
    for path in paths:
        p.drawPolygon(QPolygonF([QPointF((x - ox) * px_per_mm, (y - oy) * px_per_mm)
                                 for x, y in path]))
    p.end()
    a = np.frombuffer(img.constBits(), np.uint8).reshape(h, img.bytesPerLine())[:, :w]
    return a.astype(np.float32) / 255.0


def _turn(paths, centre, deg):
    """Paths turned ``deg`` clockwise on the bed (Y down) about ``centre``."""
    t = np.radians(deg)
    c, s = np.cos(t), np.sin(t)
    cx, cy = centre
    return [[(cx + (x - cx) * c - (y - cy) * s, cy + (x - cx) * s + (y - cy) * c)
             for x, y in p] for p in paths]


@dataclass
class Alignment:
    dx: float           # mm to move the holes' middle
    dy: float
    turn: float         # degrees clockwise on the bed, about the holes' middle
    found: int          # holes that sit on a dark spot after the move
    total: int
    score: float        # 0..1, how much of the pattern's area lands on darkness
    need: float = 0.85  # of the holes found before the fit is believed

    @property
    def ok(self):
        return (self.total >= 2 and self.found >= max(2, self.need * self.total)
                and self.score > 0.2)


# Holes cut in steel show bright plate through every one: 85 %. Holes drilled
# in a board sit over the bed's slats, and over a bright slat a hole hardly
# reads dark: at the machine 42-44 of 52 on a drilled board, the fit the same
# every time. A wrong place or a wrong way round finds far fewer. Under solder
# mask ink many holes are part filled and read paler still: the env board of
# the analog synth (2026-11-22) matched 131-141 of 205 at its true place, 64-69
# %, and at most 71 (35 %) anywhere wrong. 75 % turned the right fit away.
DRILLED_NEED = 0.55


@dataclass
class PointAlignment:
    transform: object
    errors: list
    rms: float


def fit_reference_points(drawing, photo, *, max_error_mm=0.3):
    """Rigid registration of matching points in corrected bed millimetres.

    Never scale or reflect the job to conceal mismatched picks. All points
    participate; an inconsistent reference must be corrected explicitly.
    """
    from gerber2rml.engine.fiducial import fit_transform, residuals, rms
    p, q = np.asarray(drawing, dtype=float), np.asarray(photo, dtype=float)
    if p.ndim != 2 or p.shape[1:] != (2,) or p.shape != q.shape or len(p) < 2:
        raise CameraError("Pick at least two matching drawing/photo points.")
    if not np.isfinite(p).all() or not np.isfinite(q).all():
        raise CameraError("Reference coordinates must be finite.")
    for points in (p, q):
        distances = np.linalg.norm(points[:, None] - points[None, :], axis=2)
        if distances.max() < 5:
            raise CameraError("Pick references at least 5 mm apart for a reliable angle.")
        if np.min(distances[np.triu_indices(len(points), 1)]) < 0.5:
            raise CameraError("Two references overlap. Remove the duplicate and pick a distinct point.")
    transform = fit_transform(p, q)
    errors = residuals(transform, p, q)
    if max(errors) > max_error_mm:
        worst = int(np.argmax(errors)) + 1
        raise CameraError(f"Reference {worst} disagrees by {max(errors):.2f} mm. "
                          "Check the matching points; alignment was not applied.")
    return PointAlignment(transform, errors, rms(transform, p, q))


def align(bed_rgb, px_per_mm, holes, *, search_mm=25.0, max_turn=6.0, polarity="dark",
          need=0.85):
    """Where the cut ``holes`` (bed mm, as the overlay has them now) really are
    in a straightened photo ``bed_rgb`` of ``px_per_mm``.

    A correlation over shift for each of a fan of small turns, then a finer fan
    round the best, then a check hole by hole."""
    if len(holes) < 2:
        raise CameraError("Choose at least two automatic references, or pick matching points.")
    pts = np.array([q for p in holes for q in p], float)
    cx, cy = pts.mean(axis=0)
    x0, y0 = pts.min(axis=0) - search_mm - 3
    x1, y1 = pts.max(axis=0) + search_mm + 3
    H, W = bed_rgb.shape[:2]
    c0, r0 = max(int(x0 * px_per_mm), 0), max(int(y0 * px_per_mm), 0)
    c1, r1 = min(int(x1 * px_per_mm), W), min(int(y1 * px_per_mm), H)
    if c1 - c0 < 8 or r1 - r0 < 8:
        raise CameraError("The stencil is off the photo.")
    if polarity not in ("dark", "bright"):
        raise CameraError("Choose dark or bright automatic references.")
    crop = bed_rgb[r0:r1, c0:c1]
    D = darkness(255 - crop if polarity == "bright" else crop, px_per_mm)
    origin = (c0 / px_per_mm, r0 / px_per_mm)
    FD = np.fft.rfft2(D)
    lim = int(search_mm * px_per_mm)

    def score(deg):
        T = _raster(_turn(holes, (cx, cy), deg), origin, D.shape, px_per_mm)
        area = T.sum()
        if area <= 0:
            return -1, 0, 0
        corr = np.fft.irfft2(FD * np.conj(np.fft.rfft2(T)), s=D.shape)
        # corr[dy, dx] = sum D(p + d) T(p); keep shifts within the search
        win = np.zeros_like(corr, bool)
        win[:lim + 1, :lim + 1] = win[:lim + 1, -lim:] = True
        win[-lim:, :lim + 1] = win[-lim:, -lim:] = True
        corr = np.where(win, corr, -np.inf)
        k = np.unravel_index(np.argmax(corr), corr.shape)
        dy = k[0] if k[0] <= lim else k[0] - D.shape[0]
        dx = k[1] if k[1] <= lim else k[1] - D.shape[1]
        # Sub-pixel: a parabola through the peak and its neighbours, each way.
        n0, n1 = D.shape

        def vertex(m, c, p):
            d = m - 2 * c + p
            return 0.0 if not np.isfinite(d) or d >= 0 else 0.5 * (m - p) / d
        c = corr[k]
        fy = vertex(corr[(k[0] - 1) % n0, k[1]], c, corr[(k[0] + 1) % n0, k[1]])
        fx = vertex(corr[k[0], (k[1] - 1) % n1], c, corr[k[0], (k[1] + 1) % n1])
        return c / area, dx + fx, dy + fy

    best = max(((score(a), a) for a in np.arange(-max_turn, max_turn + 1e-9, 1.0)),
               key=lambda t: t[0][0])
    a0 = best[1]
    best = max(((score(a), a) for a in np.arange(a0 - 0.9, a0 + 0.91, 0.15)),
               key=lambda t: t[0][0])
    (s, dx, dy), deg = best
    dx_mm, dy_mm = dx / px_per_mm, dy / px_per_mm

    # Hole by hole: does each one, moved, sit on darkness?
    moved = [[(x + dx_mm, y + dy_mm) for x, y in p]
             for p in _turn(holes, (cx, cy), deg)]
    found = 0
    for p in moved:
        T = _raster([p], origin, D.shape, px_per_mm)
        a = T.sum()
        if a > 0 and (D * T).sum() / a > 0.2:
            found += 1
    return Alignment(dx=dx_mm, dy=dy_mm, turn=float(deg), found=found,
                     total=len(holes), score=float(s), need=need)


# ---------------------------------------------------------------------------
# Test openings: where a few burnt pads landed against their own holes
# ---------------------------------------------------------------------------

PAD_SEARCH_MM = 1.5      # how far a pad may be from where its opening burnt
PAD_RING_MM = (0.0, 0.25)   # the trench round a pad, out from the opening + shrink
PAD_SHRINK_MM = 0.1      # openings are drawn this much inside their pads



# The test fire's image work, in numpy alone: the installer leaves scipy out
# (packaging/srm-cam.spec), so these stand in for scipy.signal.fftconvolve and
# scipy.ndimage's label and binary_fill_holes, with their defaults.

def _correlate_same(a, t):
    """``a`` correlated with ``t``, the size of ``a``: what
    ``fftconvolve(a, t[::-1, ::-1], mode="same")`` gives."""
    k = t[::-1, ::-1]
    sh = (a.shape[0] + k.shape[0] - 1, a.shape[1] + k.shape[1] - 1)
    full = np.fft.irfft2(np.fft.rfft2(a, sh) * np.fft.rfft2(k, sh), sh)
    y0, x0 = (k.shape[0] - 1) // 2, (k.shape[1] - 1) // 2
    return full[y0:y0 + a.shape[0], x0:x0 + a.shape[1]]


def _label(mask):
    """The 4-connected pieces of bool ``mask``: (labels 1..n, n), numbered
    in the order a row-by-row scan meets them, as ndimage.label numbers them."""
    H, W = mask.shape
    lab = np.zeros((H, W), np.int32)
    n = 0
    for y0, x0 in zip(*np.nonzero(mask)):
        if lab[y0, x0]:
            continue
        n += 1
        lab[y0, x0] = n
        stack = [(y0, x0)]
        while stack:
            y, x = stack.pop()
            for yy, xx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= yy < H and 0 <= xx < W and mask[yy, xx] and not lab[yy, xx]:
                    lab[yy, xx] = n
                    stack.append((yy, xx))
    return lab, n


def _fill_holes(mask):
    """``mask`` with every hole in it filled: what is not reached from the
    border through 4-connected background is set."""
    H, W = mask.shape
    out = np.zeros((H, W), bool)
    stack = [(y, x) for y in range(H) for x in (0, W - 1) if not mask[y, x]]
    stack += [(y, x) for x in range(W) for y in (0, H - 1) if not mask[y, x]]
    for y, x in stack:
        out[y, x] = True
    while stack:
        y, x = stack.pop()
        for yy, xx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= yy < H and 0 <= xx < W and not mask[yy, xx] and not out[yy, xx]:
                out[yy, xx] = True
                stack.append((yy, xx))
    return ~out


def _pad_centre(gray, px_per_mm, opening, hole, near, *, search_mm=PAD_SEARCH_MM):
    """Where the pad of ``opening`` (drawn, bed mm) is in ``gray`` (a photo
    from before the burn), within ``search_mm`` of ``near``: the middle of
    the best fit of its outline ring and its hole (dx, dy, d from the
    opening's middle) on the darkness there. Bed mm, or None."""
    from matplotlib.path import Path as _MPath
    from shapely.affinity import translate as _tr
    from shapely.geometry import Point
    c = opening.centroid
    shape = _tr(opening, -c.x, -c.y)
    padp = shape.buffer(PAD_SHRINK_MM)
    ring = padp.buffer(PAD_RING_MM[1]).difference(padp.buffer(PAD_RING_MM[0]))
    hx, hy, hd = hole
    disc = Point(hx, hy).buffer(max(hd, 0.3) / 2)
    x0, y0, x1, y1 = padp.buffer(PAD_RING_MM[1]).bounds
    kr = int(np.ceil(max(-x0, x1, -y0, y1) * px_per_mm)) + 1
    ky, kx = np.mgrid[-kr:kr + 1, -kr:kr + 1]
    pts = np.c_[kx.ravel() / px_per_mm, ky.ravel() / px_per_mm]

    def raster(geom):
        out = np.zeros(len(pts), bool)
        for gg in getattr(geom, "geoms", [geom]):
            m = _MPath(np.asarray(gg.exterior.coords)).contains_points(pts)
            for r in gg.interiors:
                m &= ~_MPath(np.asarray(r.coords)).contains_points(pts)
            out |= m
        return out.reshape(kx.shape)
    T = raster(ring).astype(np.float32) + raster(disc).astype(np.float32)
    T -= T.mean()
    H, W = gray.shape
    s = int(np.ceil(search_mm * px_per_mm)) + kr + 2
    ci, cj = int(round(near[0] * px_per_mm)), int(round(near[1] * px_per_mm))
    if ci - s < 0 or cj - s < 0 or ci + s >= W or cj + s >= H:
        return None
    win = gray[cj - s:cj + s + 1, ci - s:ci + s + 1]
    bg = _box_blur(win, max(2, int(1.0 * px_per_mm)))
    D = np.clip(bg - win, 0, None)
    score = _correlate_same(D, T)
    m = int(np.ceil(search_mm * px_per_mm))
    yy, xx = np.mgrid[-s:s + 1, -s:s + 1]
    score[(xx * xx + yy * yy) > m * m] = -np.inf
    j, i = np.unravel_index(np.argmax(score), score.shape)
    if not np.isfinite(score[j, i]) or score[j, i] <= 0:
        return None

    def vertex(a_, b_, c_):
        d = a_ - 2 * b_ + c_
        return 0.0 if not np.isfinite(d) or d >= 0 else 0.5 * (a_ - c_) / d
    fx = vertex(score[j, i - 1], score[j, i], score[j, i + 1]) if 0 < i < score.shape[1] - 1 else 0.0
    fy = vertex(score[j - 1, i], score[j, i], score[j + 1, i]) if 0 < j < score.shape[0] - 1 else 0.0
    return ((ci - s + i + fx) / px_per_mm, (cj - s + j + fy) / px_per_mm)


HOLE_REACH_MM = 0.15     # past the burnt opening's edge, short of the trench
HOLE_DARK = 0.6          # of the bare copper's brightness: the hole is darker
HOLE_UNDER_INK = 0.75    # and of the ink's round the opening


@dataclass
class OpeningFit:
    """How to move a job so its test openings sit on their holes."""
    dx: float               # mm on the bed, Y down
    dy: float
    turn: float             # degrees clockwise about ``centre``
    centre: tuple           # middle of the openings as drawn
    offsets: list           # per opening: (drawn centre, hole minus opening)
    total: int
    used: int = 0           # measured and agreeing with the rest

    @property
    def worst(self):
        return max((math.hypot(*o) for _c, o in self.offsets), default=0.0)


def _blob_near(mask, at, px_per_mm):
    """The connected piece of ``mask`` nearest ``at`` (px), as a bool image."""
    lab, n = _label(mask)
    if not n:
        return None
    best, bd = None, None
    for i in range(1, n + 1):
        yy, xx = np.nonzero(lab == i)
        if len(yy) < 0.15 * px_per_mm ** 2:         # specks
            continue
        d = math.hypot(xx.mean() - at[0], yy.mean() - at[1])
        if bd is None or d < bd:
            best, bd = i, d
    return None if best is None else lab == best


def fit_test_openings(before, after, px_per_mm, tests, *, search_mm=3.0,
                      min_spread_mm=15.0, max_off_mm=2.0, outlier_mm=0.3):
    """``before`` and ``after`` straightened photos (same frame, ``px_per_mm``)
    either side of burning a few openings; ``tests`` are (opening polygon,
    hole (x, y, diameter)) on the bed as drawn. Each opening is found where it
    changed the photo, its hole as the darkest hole-sized spot round it, both
    in the same photo, so the camera's own error cancels. Returns an
    :class:`OpeningFit` moving the job onto the holes (a turn too when the
    openings are spread out), or None when none could be measured."""
    g0 = before.astype(np.float32).mean(axis=2)
    g1 = after.astype(np.float32).mean(axis=2)
    H, W = g1.shape
    drawn, moved = [], []
    offsets = []
    k = int(search_mm * px_per_mm)
    for opening, (hx, hy, hd) in tests:
        c = opening.centroid
        ci, cj = int(round(c.x * px_per_mm)), int(round(c.y * px_per_mm))
        if ci - k < 0 or cj - k < 0 or ci + k >= W or cj + k >= H:
            continue
        win0 = g0[cj - k:cj + k + 1, ci - k:ci + k + 1]
        win1 = g1[cj - k:cj + k + 1, ci - k:ci + k + 1]
        diff = win1 - win0
        if diff.max() < 25:
            continue
        blob = _blob_near(diff > max(25.0, 0.4 * float(diff.max())), (k, k), px_per_mm)
        if blob is None:
            continue
        # The hole is dark in both photos, so it is a gap in what changed;
        # where it sits at the opening's edge, a notch. The opening's middle
        # is the middle of its extent, which neither moves.
        blob = _fill_holes(blob)
        yy, xx = np.nonzero(blob)
        ox = (xx.min() + xx.max()) / 2                      # the opening, px
        oy = (yy.min() + yy.max()) / 2
        # The pad, in the photo from before: the trench etched round it and
        # its drilled hole both show through the ink (after the burn the hole
        # hides in the opening's edge). A drawing of that ring and hole is
        # slid over the darkness there; where it fits best is the pad. The
        # job is lined up on the copper, so a hole drilled a little off its
        # pad does not pull it.
        sx_mm = (ci - k + ox) / px_per_mm
        sy_mm = (cj - k + oy) / px_per_mm
        pad = _pad_centre(g0, px_per_mm, opening, (hx - c.x, hy - c.y, hd),
                          (sx_mm, sy_mm), search_mm=PAD_SEARCH_MM)
        if pad is None:
            continue
        off = (pad[0] - sx_mm, pad[1] - sy_mm)
        if math.hypot(*off) > max_off_mm:
            continue
        drawn.append((c.x, c.y))
        moved.append((c.x + off[0], c.y + off[1]))
        offsets.append(((c.x, c.y), off))
    if not drawn:
        return None
    # A hole the mill put a little off its pad says the job is off when it
    # is not: with three or more, the ones further than ``outlier_mm`` from
    # the best turn-and-shift of them all are left out (and still listed).
    P, Q = np.array(drawn), np.array(moved)
    spread = len(P) >= 2 and np.ptp(P, axis=0).max() >= min_spread_mm

    def rigid(P, Q):
        pm, qm = P.mean(axis=0), Q.mean(axis=0)
        th = 0.0
        if spread and len(P) >= 2:
            A, B = P - pm, Q - qm
            th = math.atan2((A[:, 0] * B[:, 1] - A[:, 1] * B[:, 0]).sum(),
                            (A * B).sum())
        return pm, qm, th

    pm, qm, th = rigid(P, Q)
    if len(P) >= 3:
        c_, s_ = math.cos(th), math.sin(th)
        fit = (P - pm) @ np.array([[c_, s_], [-s_, c_]]) + qm
        keep = np.hypot(*(fit - Q).T) <= outlier_mm
        if 2 <= keep.sum() < len(P):
            P, Q = P[keep], Q[keep]
            pm, qm, th = rigid(P, Q)
    turn = math.degrees(th)
    return OpeningFit(dx=float(qm[0] - pm[0]), dy=float(qm[1] - pm[1]), turn=turn,
                      centre=(float(pm[0]), float(pm[1])), offsets=offsets,
                      total=len(tests), used=len(P))


# ---------------------------------------------------------------------------
# Proof: where the laser's own marks show up, from a photo before and after
# ---------------------------------------------------------------------------

@dataclass
class ChangeFit:
    dx: float           # mm from where the marks were drawn to where they show
    dy: float
    found: int          # marks that show where the fit puts them
    total: int
    score: float        # 0..1, how much of the marks' area changed
    level: float        # grey levels the marks changed the photo by

    @property
    def ok(self):
        need = 1 if self.total == 1 else max(2, int(np.ceil(0.6 * self.total)))
        return self.total >= 1 and self.found >= need and self.score > 0.25


def _geoms(shape):
    return list(getattr(shape, "geoms", [shape]))


def _raster_polys(polys, origin, shape, px_per_mm):
    """Shapely polygons (bed mm), holes kept open, as a float image."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPainterPath, QPolygonF
    h, w = shape
    img = QImage(w, h, QImage.Format_Grayscale8)
    img.fill(0)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(QColor(255, 255, 255)))
    ox, oy = origin
    for shape_ in polys:
        for poly in _geoms(shape_):
            if poly.is_empty or not hasattr(poly, "exterior"):
                continue
            path = QPainterPath()
            path.setFillRule(Qt.OddEvenFill)
            for ring in (poly.exterior, *poly.interiors):
                path.addPolygon(QPolygonF([QPointF((x - ox) * px_per_mm,
                                                   (y - oy) * px_per_mm)
                                           for x, y in ring.coords]))
                path.closeSubpath()
            p.drawPath(path)
    p.end()
    a = np.frombuffer(img.constBits(), np.uint8).reshape(h, img.bytesPerLine())[:, :w]
    return a.astype(np.float32) / 255.0


def _best_shift(D, T, lim):
    """The shift of template ``T`` over map ``D`` (same shape) with the most
    overlap, within ``lim`` pixels each way: (overlap per template area, dx,
    dy), to a fraction of a pixel."""
    area = T.sum()
    if area <= 0:
        return -1.0, 0.0, 0.0
    corr = np.fft.irfft2(np.fft.rfft2(D) * np.conj(np.fft.rfft2(T)), s=D.shape)
    win = np.zeros_like(corr, bool)
    win[:lim + 1, :lim + 1] = win[:lim + 1, -lim:] = True
    win[-lim:, :lim + 1] = win[-lim:, -lim:] = True
    corr = np.where(win, corr, -np.inf)
    k = np.unravel_index(np.argmax(corr), corr.shape)
    n0, n1 = D.shape
    dy = k[0] if k[0] <= lim else k[0] - n0
    dx = k[1] if k[1] <= lim else k[1] - n1

    def vertex(m, c, q):
        d = m - 2 * c + q
        return 0.0 if not np.isfinite(d) or d >= 0 else 0.5 * (m - q) / d
    c = corr[k]
    fy = vertex(corr[(k[0] - 1) % n0, k[1]], c, corr[(k[0] + 1) % n0, k[1]])
    fx = vertex(corr[k[0], (k[1] - 1) % n1], c, corr[k[0], (k[1] + 1) % n1])
    return float(c / area), dx + fx, dy + fy


def locate_change(before, after, px_per_mm, marks, *, search_mm=3.0, min_level=8.0):
    """Where marks the laser has just made show up, from two straightened
    photos of the same bed: one before, one after. ``marks`` are shapely
    shapes in bed mm, where they were drawn.

    Only what changed between the photos counts, so it does not matter whether
    a mark reads dark or bright, nor what the board looks like around it."""
    marks = [m for m in marks if m is not None and not m.is_empty]
    if not marks:
        raise CameraError("There are no proof marks to look for.")
    if before.shape != after.shape:
        raise CameraError("The two photos are not the same size.")
    b = np.array([m.bounds for m in marks], float)
    x0, y0 = b[:, 0].min() - search_mm - 3, b[:, 1].min() - search_mm - 3
    x1, y1 = b[:, 2].max() + search_mm + 3, b[:, 3].max() + search_mm + 3
    H, W = before.shape[:2]
    c0, r0 = max(int(x0 * px_per_mm), 0), max(int(y0 * px_per_mm), 0)
    c1, r1 = min(int(x1 * px_per_mm), W), min(int(y1 * px_per_mm), H)
    if c1 - c0 < 8 or r1 - r0 < 8:
        raise CameraError("The proof marks are off the photo.")
    g = np.abs(after[r0:r1, c0:c1].astype(np.float32)
               - before[r0:r1, c0:c1].astype(np.float32)).mean(axis=2)
    g = _box_blur(g, 1)
    g = np.clip(g - np.median(g), 0, None)      # a change in the light is not a mark
    origin = (c0 / px_per_mm, r0 / px_per_mm)
    T = _raster_polys(marks, origin, g.shape, px_per_mm)
    n = int(max(4, round(T.sum())))
    level = float(np.sort(g, axis=None)[-n:].mean())
    if level < min_level:
        return ChangeFit(0.0, 0.0, 0, len(marks), 0.0, level)
    D = np.clip(g / level, 0, 1)
    s, dx, dy = _best_shift(D, T, int(search_mm * px_per_mm))
    dx_mm, dy_mm = dx / px_per_mm, dy / px_per_mm
    from shapely.affinity import translate
    found = 0
    for m in marks:
        t = _raster_polys([translate(m, dx_mm, dy_mm)], origin, g.shape, px_per_mm)
        a = t.sum()
        if a > 0 and (D * t).sum() / a > 0.25:
            found += 1
    return ChangeFit(dx_mm, dy_mm, found, len(marks), s, level)


MATERIAL_MIN = 100.0     # brightness: below this a spot is the dark bed
MATERIAL_SHARE = 0.5     # of the board's own brightness


def sheet_continues(rgb, px_per_mm, spots, inside):
    """Whether there is material under each of ``spots`` (bed mm points
    outside the board): the board is still in a bigger sheet, so there is
    waste to mark.

    Material is bright and the bed is dark. A spot counts when it is bright in
    itself and at least half as bright as the board, judged by the brightest
    of the ``inside`` points (plain copper; another may land on a hole). It
    used to have to match its own inside point in colour, and next to the
    corners' mounting holes that point was the hole: the output board read as
    having no waste and was marked on the isolation instead."""
    if not spots or len(spots) != len(inside):
        return False
    H, W = rgb.shape[:2]
    r = max(2, int(0.6 * px_per_mm))

    def lum(p):
        c, row = int(round(p[0] * px_per_mm)), int(round(p[1] * px_per_mm))
        if not (r <= c < W - r and r <= row < H - r):
            return None
        q = rgb[row - r:row + r + 1, c - r:c + r + 1].reshape(-1, 3).astype(np.float32)
        return float(q.mean(axis=0) @ np.array([0.299, 0.587, 0.114], np.float32))
    board = [v for v in (lum(q) for q in inside) if v is not None]
    if not board:
        return False
    need = max(MATERIAL_MIN, MATERIAL_SHARE * max(board))
    for a in spots:
        v = lum(a)
        if v is None or v < need:
            return False
    return True
