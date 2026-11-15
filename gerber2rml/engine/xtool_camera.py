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
    def rectify(self, rgb, px_per_mm=4):
        """``rgb`` (h, w, 3) uint8 photo -> a bed map, ``px_per_mm`` pixels
        per mm, row 0 at Y 0 and column 0 at X 0 of the laser's coordinates."""
        h, w = rgb.shape[:2]
        sw, sh = self.src_size
        size = int(round(self.extent_mm * px_per_mm))
        mm = np.arange(size) / px_per_mm
        X, Y = np.meshgrid(mm, mm)
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
