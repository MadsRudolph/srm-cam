"""OctoPrint-style 3D bed visualizer.

Renders the probed surface as a rotatable, color-mapped OpenGL mesh — blue
(low) to red (high) by deviation — with the probe points marked and a Z
exaggeration slider, since the warp is microns against a board tens of mm wide.
Mirrors the Qt/OpenGL pattern of :mod:`gerber2rml.gui.sim3d`.
"""
import numpy as np
import pyqtgraph.opengl as gl
from pyqtgraph import Vector
from matplotlib import colormaps
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider,
)
from PySide6.QtCore import Qt

_CMAP = colormaps["coolwarm"]


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
