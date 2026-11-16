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
import re
from dataclasses import dataclass

import numpy as np

GRID_N = 23
GRID_MM = 10.0
DOT_AT = (110.0, 110.0)          # mm; the grid point (11, 11)


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
        if top < 300:
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

    @property
    def ok(self):
        return self.total >= 2 and self.found >= max(2, 0.85 * self.total) and self.score > 0.2


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


def align(bed_rgb, px_per_mm, holes, *, search_mm=25.0, max_turn=6.0, polarity="dark"):
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
                     total=len(holes), score=float(s))
