"""3D G-code simulation window: orbit the toolpath and play a tool head along
it, like ncviewer.com.

Renders the flattened toolpath (cyan cuts, dim rapids) in an OpenGL scene the
operator can orbit/zoom/pan, with a moving endmill cone driven by a play/pause
timer, a speed control, and a scrub timeline. Rapids ride up at travel height
and cuts dip to depth, so the Z motion shows the tool lifting and plunging just
as the machine will run it.

The heavy lifting (path flattening, arc-length interpolation) lives in
:mod:`gerber2rml.engine.simulate`; this module is the Qt/OpenGL shell.
"""
import os

# pyqtgraph must use the SAME Qt binding as the app (PySide6); otherwise it
# defaults to a stray PyQt6/PyQt5 in the env and loads a second, mismatched Qt
# runtime, crashing with "DLL load failed ... procedure not found". Set before
# pyqtgraph is imported.
os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")

import numpy as np
import pyqtgraph.opengl as gl
from pyqtgraph import Vector
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QSlider, QLabel,
    QStyle,
)
from PySide6.QtCore import Qt, QTimer

from gerber2rml.engine.simulate import build_path, split_segments, position_at, index_at

_TICK_MS = 30                      # ~33 fps animation timer
_CUT_COLOR = (0.0, 1.0, 1.0, 1.0)   # cyan
_RAPID_COLOR = (0.4, 0.4, 0.4, 1.0)  # dim grey
_TRAIL_COLOR = (1.0, 0.85, 0.1, 1.0)  # bright amber "already cut"
_TOOL_COLOR = (1.0, 0.3, 0.3, 1.0)


def _pairs(segments):
    """Flatten [(p0, p1), ...] -> (2N, 3) array for GLLinePlotItem 'lines' mode."""
    if not segments:
        return np.empty((0, 3), dtype=float)
    return np.array([p for seg in segments for p in seg], dtype=float)


def _box_meshdata(x0, y0, z0, x1, y1, z1):
    """MeshData for an axis-aligned box (12 triangles) -- the PCB stock slab."""
    v = np.array([[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
                  [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]], dtype=float)
    f = np.array([[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7],
                  [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5],
                  [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]], dtype=int)
    return gl.MeshData(vertexes=v, faces=f)


class Simulation3DWindow(QMainWindow):
    def __init__(self, toolpaths, title="3D simulation", parent=None,
                 board=None, bed=None, thickness=1.6):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(900, 700)

        self._board = board          # (x0, y0, x1, y1) PCB outline bounds, or None
        self._bed = bed              # (width, height) machine work area, or None
        self._thickness = thickness  # PCB stock thickness (mm)
        self._points, self._is_rapid, self._cum = build_path(toolpaths)
        self._total = self._cum[-1] if self._cum else 0.0
        self._dist = 0.0
        self._playing = False

        self.view = gl.GLViewWidget()
        self.view.setBackgroundColor('#1e1e1e')

        self._build_scene()

        # ---- controls -------------------------------------------------
        self.play_btn = QPushButton()
        self._set_play_icon(False)
        self.play_btn.clicked.connect(self._toggle_play)
        self.reset_btn = QPushButton()
        self.reset_btn.setIcon(self.style().standardIcon(
            QStyle.StandardPixmap.SP_MediaSkipBackward))
        self.reset_btn.clicked.connect(self._reset)

        self.speed = QSlider(Qt.Horizontal)
        self.speed.setRange(1, 100)          # arbitrary units -> mm/s below
        self.speed.setValue(25)
        self.speed.setMaximumWidth(140)
        self.speed.setToolTip("Playback speed")

        self.timeline = QSlider(Qt.Horizontal)
        self.timeline.setRange(0, 1000)
        self.timeline.setValue(0)
        self.timeline.setToolTip("Scrub the toolpath")
        self.timeline.valueChanged.connect(self._on_scrub)

        self.pos_label = QLabel()
        self.pos_label.setMinimumWidth(230)

        controls = QHBoxLayout()
        controls.addWidget(self.play_btn)
        controls.addWidget(self.reset_btn)
        controls.addWidget(QLabel("Speed"))
        controls.addWidget(self.speed)
        controls.addWidget(self.timeline, 1)
        controls.addWidget(self.pos_label)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.view, 1)
        layout.addLayout(controls)
        self.setCentralWidget(central)

        self.timer = QTimer(self)
        self.timer.setInterval(_TICK_MS)
        self.timer.timeout.connect(self._on_tick)

        self._update_tool()
        self._frame_camera()

    # ---- scene construction -------------------------------------------
    def _bounds(self):
        if not self._points:
            return (0, 0, 0), (1, 1, 1), 1.0
        arr = np.array(self._points, dtype=float)
        lo = arr.min(axis=0)
        hi = arr.max(axis=0)
        diag = float(np.linalg.norm(hi - lo)) or 1.0
        return tuple(lo), tuple(hi), diag

    def _build_scene(self):
        lo, hi, diag = self._bounds()
        cx, cy = (lo[0] + hi[0]) / 2.0, (lo[1] + hi[1]) / 2.0

        # ground grid at the work surface (Z=0), extended to cover the bed
        grid = gl.GLGridItem()
        span = max(hi[0] - lo[0], hi[1] - lo[1]) or 10.0
        gx, gy = cx, cy
        if self._bed:
            span = max(span, self._bed[0], self._bed[1])
            gx, gy = self._bed[0] / 2.0, self._bed[1] / 2.0
        grid.setSize(span * 1.4, span * 1.4)
        step = max(span / 10.0, 1.0)
        grid.setSpacing(step, step)
        grid.translate(gx, gy, 0)
        grid.setColor((80, 80, 80, 160))
        self.view.addItem(grid)

        # machine bed outline (work area) at Z=0, home corner marked at the origin
        if self._bed:
            bw, bh = self._bed
            loop = np.array([[0, 0, 0], [bw, 0, 0], [bw, bh, 0], [0, bh, 0],
                             [0, 0, 0]], dtype=float)
            self.view.addItem(gl.GLLinePlotItem(
                pos=loop, color=(0.25, 0.8, 0.5, 1.0), width=1.5,
                mode='line_strip', antialias=True))
            self.view.addItem(gl.GLScatterPlotItem(
                pos=np.array([[0, 0, 0]], dtype=float), size=12,
                color=(1.0, 0.7, 0.1, 1.0)))

        # PCB stock as a translucent slab from the surface (Z=0) down to -thickness;
        # the cuts dip into it so you see depth and placement in context
        if self._board:
            x0, y0, x1, y1 = self._board
            slab = gl.GLMeshItem(
                meshdata=_box_meshdata(x0, y0, -self._thickness, x1, y1, 0.0),
                color=(0.15, 0.5, 0.28, 0.30), smooth=False,
                glOptions='translucent')
            self.view.addItem(slab)
            top = np.array([[x0, y0, 0], [x1, y0, 0], [x1, y1, 0], [x0, y1, 0],
                            [x0, y0, 0]], dtype=float)
            self.view.addItem(gl.GLLinePlotItem(
                pos=top, color=(0.4, 0.9, 0.55, 1.0), width=1.5,
                mode='line_strip', antialias=True))

        cut, rapid = split_segments(self._points, self._is_rapid)
        self._cut_item = gl.GLLinePlotItem(
            pos=_pairs(cut), color=_CUT_COLOR, width=1.5, mode='lines',
            antialias=True)
        self._rapid_item = gl.GLLinePlotItem(
            pos=_pairs(rapid), color=_RAPID_COLOR, width=1.0, mode='lines',
            antialias=True)
        self.view.addItem(self._rapid_item)
        self.view.addItem(self._cut_item)

        # bright "already travelled" trail, grows as the tool advances
        self._trail_item = gl.GLLinePlotItem(
            pos=np.empty((0, 3)), color=_TRAIL_COLOR, width=3.0,
            mode='line_strip', antialias=True)
        self.view.addItem(self._trail_item)

        # endmill: a cone whose tip sits at the tool position, pointing up
        self._tool_len = max(diag * 0.04, 1.0)
        r = self._tool_len * 0.35
        md = gl.MeshData.cylinder(rows=2, cols=20, radius=[0.0, r],
                                  length=self._tool_len)
        self._tool_item = gl.GLMeshItem(meshdata=md, color=_TOOL_COLOR,
                                        smooth=True, shader='shaded',
                                        glOptions='opaque')
        self.view.addItem(self._tool_item)

    def _frame_camera(self):
        lo, hi, diag = self._bounds()
        cx, cy = (lo[0] + hi[0]) / 2.0, (lo[1] + hi[1]) / 2.0
        self.view.opts['center'] = Vector(cx, cy, 0)
        self.view.setCameraPosition(distance=diag * 1.8, elevation=35,
                                    azimuth=-60)

    # ---- playback ------------------------------------------------------
    def _set_play_icon(self, playing):
        pix = (QStyle.StandardPixmap.SP_MediaPause if playing
               else QStyle.StandardPixmap.SP_MediaPlay)
        self.play_btn.setIcon(self.style().standardIcon(pix))

    def _toggle_play(self):
        if self._playing:
            self._pause()
        else:
            self._play()

    def _play(self):
        if self._total <= 0:
            return
        if self._dist >= self._total:        # restart from the top
            self._dist = 0.0
        self._playing = True
        self._set_play_icon(True)
        self.timer.start()

    def _pause(self):
        self._playing = False
        self._set_play_icon(False)
        self.timer.stop()

    def _reset(self):
        self._pause()
        self._dist = 0.0
        self._update_tool()

    def _speed_mm_s(self):
        # 1..100 slider -> ~2..200 mm/s of simulated travel
        return self.speed.value() * 2.0

    def _on_tick(self):
        self._dist += self._speed_mm_s() * (_TICK_MS / 1000.0)
        if self._dist >= self._total:
            self._dist = self._total
            self._update_tool()
            self._pause()
            return
        self._update_tool()

    def _on_scrub(self, val):
        # only react to user drags, not our own programmatic updates
        if self.timeline.signalsBlocked():
            return
        self._dist = (val / 1000.0) * self._total
        self._update_tool()

    def _update_tool(self):
        pos = position_at(self._points, self._cum, self._dist)
        if pos is None:
            return
        # move the cone so its tip sits at the tool position
        self._tool_item.resetTransform()
        self._tool_item.translate(pos[0], pos[1], pos[2])

        k = index_at(self._cum, self._dist)
        trail = self._points[:k]
        trail = (trail + [pos]) if trail else [pos]
        self._trail_item.setData(pos=np.array(trail, dtype=float))

        # sync timeline + readout without re-triggering _on_scrub
        self.timeline.blockSignals(True)
        self.timeline.setValue(int(1000 * (self._dist / self._total))
                               if self._total else 0)
        self.timeline.blockSignals(False)
        pct = (100.0 * self._dist / self._total) if self._total else 0.0
        self.pos_label.setText(
            f"X{pos[0]:7.2f} Y{pos[1]:7.2f} Z{pos[2]:6.2f}   {pct:5.1f}%")

    def closeEvent(self, event):
        self.timer.stop()
        super().closeEvent(event)
