"""OctoPrint-style 3D bed visualizer.

Renders the probed surface as a rotatable, color-mapped OpenGL mesh — blue
(low) to red (high) by deviation — with the probe points marked and a Z
exaggeration slider, since the warp is microns against a board tens of mm wide.
Hover a probe marker to read its exact X/Y and Z deviation.
Mirrors the Qt/OpenGL pattern of :mod:`gerber2rml.gui.sim3d`.
"""
import math

import numpy as np
import pyqtgraph.opengl as gl
from pyqtgraph import Vector
from matplotlib import colormaps
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QToolTip,
)
from PySide6.QtCore import Qt, QEvent, QPoint

_CMAP = colormaps["coolwarm"]
_HOVER_PX = 18                       # pick radius for the hover tooltip (pixels)


def _nearest_index(screen, px, py, max_px=_HOVER_PX):
    """Index of the screen point ((sx, sy) or None) closest to (px, py) within
    ``max_px``, or None if nothing is in range. Pure — no GL needed (testable)."""
    best, bestd = None, float(max_px)
    for i, s in enumerate(screen):
        if s is None:
            continue
        d = math.hypot(s[0] - px, s[1] - py)
        if d < bestd:
            best, bestd = i, d
    return best


def _hover_text(points, zmin, zmax, i):
    """Rich tooltip for probe ``points[i]`` ((x, y, dz) mm), placing its deviation
    within the measured [zmin, zmax] band. Pure — testable without a window."""
    x, y, dz = points[i]
    rng = (zmax - zmin) or 1.0
    pos = (dz - zmin) / rng * 100.0
    return (f"Probe #{i + 1} of {len(points)}\n"
            f"X {x:.3f}   Y {y:.3f} mm\n"
            f"Δz {dz * 1000:+.0f} µm   ({dz:+.4f} mm)\n"
            f"{pos:.0f}% of range   (lo {zmin * 1000:+.0f} … hi {zmax * 1000:+.0f} µm)")


class BedVisualizerWindow(QMainWindow):
    """``xs``/``ys``: 1D board coordinates (mm). ``Z``: 2D deviation (mm), shaped
    ``(len(xs), len(ys))`` with ``Z[i][j]`` at ``(xs[i], ys[j])``. ``points``:
    probed ``(x, y, dz)`` in mm."""

    def __init__(self, xs, ys, Z, points, title="Bed visualizer", parent=None,
                 exaggeration=200):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(900, 720)
        self._xs = np.asarray(xs, dtype=float)
        self._ys = np.asarray(ys, dtype=float)
        self._Z = np.asarray(Z, dtype=float)
        self._points = list(points or [])
        self._exag = int(exaggeration)
        self._surface = self._scatter = None

        self.view = gl.GLViewWidget()
        self.view.setBackgroundColor("#1e1e1e")
        self.view.setMouseTracking(True)         # fire move events without a button
        self.view.installEventFilter(self)       # so we can read the surface on hover

        self.exag_slider = QSlider(Qt.Horizontal)
        self.exag_slider.setRange(10, 1000)
        self.exag_slider.setValue(self._exag)
        self.exag_slider.setToolTip("Z exaggeration — scales the deviation so the warp is visible")
        self.exag_slider.valueChanged.connect(self._on_exag)
        self.range_lbl = QLabel()
        self.range_lbl.setStyleSheet("color:#d4d4d4;")

        self._build_static()
        self._rebuild()      # needs range_lbl, so build controls first

        controls = QWidget()
        cl = QHBoxLayout(controls)
        cl.setContentsMargins(8, 4, 8, 6)
        cl.addWidget(QLabel("Z ×", styleSheet="color:#d4d4d4;"))
        cl.addWidget(self.exag_slider)
        cl.addWidget(QLabel("hover a point for its value",
                            styleSheet="color:#888;"))
        cl.addStretch(1)
        cl.addWidget(self.range_lbl)

        central = QWidget()
        v = QVBoxLayout(central)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.view, 1)
        v.addWidget(controls)
        self.setCentralWidget(central)

    def _build_static(self):
        cx, cy = float(self._xs.mean()), float(self._ys.mean())
        span = float(max(np.ptp(self._xs), np.ptp(self._ys), 1.0))
        grid = gl.GLGridItem()
        grid.setSize(span * 1.3, span * 1.3)
        grid.setSpacing(10, 10)
        grid.translate(cx, cy, 0)
        self.view.addItem(grid)
        self.view.setCameraPosition(pos=Vector(cx, cy, 0.0),
                                    distance=span * 2.2, elevation=32, azimuth=-60)

    def _colors(self):
        zmax = max(abs(float(self._Z.min())), abs(float(self._Z.max())), 1e-4)
        norm = (self._Z + zmax) / (2.0 * zmax)        # centre 0 -> middle of cmap
        return _CMAP(norm).astype(np.float32)

    def _rebuild(self):
        if self._surface is not None:
            self.view.removeItem(self._surface)
        if self._scatter is not None:
            self.view.removeItem(self._scatter)
            self._scatter = None
        zexag = self._Z * self._exag
        self._surface = gl.GLSurfacePlotItem(
            x=self._xs, y=self._ys, z=zexag, colors=self._colors(),
            shader="shaded", smooth=True)
        self.view.addItem(self._surface)
        if self._points:
            pos = np.array([[x, y, dz * self._exag] for (x, y, dz) in self._points],
                           dtype=float)
            self._scatter = gl.GLScatterPlotItem(pos=pos, size=9,
                                                 color=(1, 1, 1, 1), pxMode=True)
            self.view.addItem(self._scatter)
        lo, hi = float(self._Z.min()) * 1000, float(self._Z.max()) * 1000
        self.range_lbl.setText(
            f"surface {lo:+.0f}..{hi:+.0f} um   (blue low → red high)   "
            f"Z exaggerated {self._exag}×")

    def _on_exag(self, v):
        self._exag = int(v)
        self._rebuild()

    # ---- hover read-out -------------------------------------------------------
    @staticmethod
    def _m2np(m):
        """QMatrix4x4 -> 4x4 numpy array (its .data() is column-major)."""
        return np.array(m.data(), dtype=float).reshape(4, 4, order="F")

    def _project(self, x, y, z):
        """World ``(x, y, z)`` -> widget pixel ``(px, py)``, or None if it's behind
        the camera / off-screen. Done in numpy from the MVP matrix (PySide's
        QMatrix4x4 * QVector4D operator is unreliable here). NDC is
        resolution-independent, so this is correct on HiDPI too."""
        try:
            vp = self.view.getViewport()
            mvp = self._m2np(self.view.projectionMatrix(vp, vp)) @ \
                self._m2np(self.view.viewMatrix())
            q = mvp @ np.array([float(x), float(y), float(z), 1.0])
        except Exception:
            return None
        w = q[3]
        if w == 0:
            return None
        ndc = q[:3] / w
        if not (-1.0 <= ndc[2] <= 1.0):          # clipped by near/far -> not visible
            return None
        W, H = self.view.width(), self.view.height()
        return ((ndc[0] * 0.5 + 0.5) * W, (1.0 - (ndc[1] * 0.5 + 0.5)) * H)

    def _pick(self, px, py):
        """Index of the probe point whose marker is under (px, py), or None. Points
        are projected at the SAME exaggerated Z the scatter is drawn at."""
        screen = [self._project(x, y, dz * self._exag) for (x, y, dz) in self._points]
        return _nearest_index(screen, px, py)

    def eventFilter(self, obj, ev):
        if obj is self.view and ev.type() == QEvent.MouseMove and self._points:
            p = ev.position() if hasattr(ev, "position") else ev.pos()
            px, py = p.x(), p.y()
            i = self._pick(px, py)
            if i is None:
                QToolTip.hideText()
            else:
                txt = _hover_text(self._points, float(self._Z.min()),
                                  float(self._Z.max()), i)
                gp = self.view.mapToGlobal(QPoint(int(px), int(py)))
                QToolTip.showText(gp, txt, self.view)
        return super().eventFilter(obj, ev)
