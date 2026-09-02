"""Warp a photo of the real board onto the bed, and check the job against it.

The point is not decoration. A board that has already been cut, or one being
reworked, differs from its design in ways the design cannot show — it sits a
degree off square, a trace lifted, a pad tore. Warping a phone photo into
machine coordinates puts the two in the same frame, so a rework box drawn on
the photo lands where the damage actually is rather than where the Gerbers say
it should be.

The maths is the engine's (:mod:`gerber2rml.engine.photofit`): four known holes
clicked in the photo give a homography, and ``warp_photo`` resamples the image
into millimetres. This module is the picking.

Written for this interface rather than copied: the first interface's dialogs
are matplotlib canvases, and this package draws with ``QPainter``. The
behaviour they earned is kept — click in order, undo the last one, a map of
the design beside the photo showing WHICH hole is wanted, and a running note
of how well the fit lands.
"""
import math

from PySide6.QtCore import Qt, QPointF, QRectF, QSize
from PySide6.QtGui import QImage, QPainter, QPen, QBrush, QColor, QPolygonF
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QVBoxLayout,
                               QWidget, QSizePolicy)

from gerber2rml.gui2 import theme, widgets

_MIN_ANCHORS = 4           # a homography needs four; fewer is a different fit


def pick_anchor_holes(holes, want=_MIN_ANCHORS):
    """Choose ``want`` well-spread holes to anchor a photo on.

    Spread is the whole game: four holes clustered in one corner fit a
    homography that is exact where they are and wrong everywhere else. Takes
    the hull-ish extremes — furthest from the centroid, then furthest from
    what is already chosen — which puts them near the corners of whatever
    shape the board actually is.
    """
    pts = [(float(x), float(y)) for x, y, *_ in (holes or [])]
    if len(pts) <= want:
        return pts
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    first = max(pts, key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)
    chosen = [first]
    while len(chosen) < want:
        nxt = max(pts, key=lambda p: min((p[0] - c[0]) ** 2 + (p[1] - c[1]) ** 2
                                         for c in chosen))
        if nxt in chosen:
            break
        chosen.append(nxt)
    # Clockwise from the lowest-left, so "the first one" means something a
    # person can follow around the board rather than an arbitrary order.
    mx = sum(p[0] for p in chosen) / len(chosen)
    my = sum(p[1] for p in chosen) / len(chosen)
    chosen.sort(key=lambda p: -math.atan2(p[1] - my, p[0] - mx))
    return chosen


class _PhotoCanvas(QWidget):
    """The photo, with the anchors clicked so far. Zoom on wheel, pan on drag."""

    def __init__(self, image, parent=None):
        super().__init__(parent)
        self._img = image
        self._pts = []
        self._scale = 1.0
        self._off = QPointF(0.0, 0.0)
        self._fitted = False
        self._panning = None
        self.setMinimumSize(520, 420)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(Qt.CrossCursor)
        self.setFocusPolicy(Qt.StrongFocus)

    def sizeHint(self):
        return QSize(720, 560)

    # -- view --------------------------------------------------------------
    def _fit(self):
        if self._img.isNull():
            return
        sx = self.width() / self._img.width()
        sy = self.height() / self._img.height()
        self._scale = min(sx, sy) * 0.98
        self._off = QPointF(
            (self.width() - self._img.width() * self._scale) / 2.0,
            (self.height() - self._img.height() * self._scale) / 2.0)
        self._fitted = True

    def resizeEvent(self, e):
        self._fit()
        super().resizeEvent(e)

    def _to_image(self, pos):
        return QPointF((pos.x() - self._off.x()) / self._scale,
                       (pos.y() - self._off.y()) / self._scale)

    def _to_widget(self, u, v):
        return QPointF(u * self._scale + self._off.x(),
                       v * self._scale + self._off.y())

    # -- input -------------------------------------------------------------
    def wheelEvent(self, e):
        if self._img.isNull():
            return
        before = self._to_image(e.position())
        step = 1.0015 ** e.angleDelta().y()
        self._scale = max(0.05, min(40.0, self._scale * step))
        after = self._to_image(e.position())
        self._off += (after - before) * self._scale
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MiddleButton or (
                e.button() == Qt.LeftButton
                and e.modifiers() & Qt.ShiftModifier):
            self._panning = e.position()
            self.setCursor(Qt.ClosedHandCursor)
            return
        if e.button() == Qt.LeftButton:
            p = self._to_image(e.position())
            if 0 <= p.x() < self._img.width() and 0 <= p.y() < self._img.height():
                self._pts.append((p.x(), p.y()))
                self.update()
                self.parent().anchor_changed()

    def mouseMoveEvent(self, e):
        if self._panning is not None:
            self._off += e.position() - self._panning
            self._panning = e.position()
            self.update()

    def mouseReleaseEvent(self, e):
        if self._panning is not None:
            self._panning = None
            self.setCursor(Qt.CrossCursor)

    def undo(self):
        if self._pts:
            self._pts.pop()
            self.update()
            self.parent().anchor_changed()

    def points(self):
        return list(self._pts)

    # -- paint -------------------------------------------------------------
    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(theme.INK))
        if self._img.isNull():
            p.end()
            return
        if not self._fitted:
            self._fit()
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawImage(QRectF(self._off.x(), self._off.y(),
                           self._img.width() * self._scale,
                           self._img.height() * self._scale), self._img)
        p.setRenderHint(QPainter.Antialiasing, True)
        for i, (u, v) in enumerate(self._pts, 1):
            c = self._to_widget(u, v)
            pen = QPen(QColor(theme.TOOL), 2)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.setBrush(QBrush(theme.alpha(theme.TOOL, 0.25)))
            p.drawEllipse(c, 9, 9)
            p.setPen(QPen(QColor(theme.TEXT)))
            p.setFont(theme.font("label"))
            p.drawText(QRectF(c.x() - 9, c.y() - 9, 18, 18),
                       Qt.AlignCenter, str(i))
        p.end()


class _DesignMap(QWidget):
    """The design, with the wanted anchor numbered — so the photo click is findable.

    "Machine X 43.2 Y 18.7" is not something anyone can locate on a board in
    their hand. A picture of the design with a ring round the next hole is.
    """

    def __init__(self, holes, outline, anchors, parent=None):
        super().__init__(parent)
        self._holes = [(float(x), float(y)) for x, y, *_ in (holes or [])]
        self._outline = outline
        self._anchors = list(anchors)
        self._next = 0
        self.setMinimumWidth(240)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

    def set_next(self, i):
        self._next = i
        self.update()

    def _bounds(self):
        xs = [p[0] for p in self._holes] + [a[0] for a in self._anchors]
        ys = [p[1] for p in self._holes] + [a[1] for a in self._anchors]
        if not xs:
            return (0.0, 0.0, 1.0, 1.0)
        m = 4.0
        return (min(xs) - m, min(ys) - m, max(xs) + m, max(ys) + m)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(theme.BED))
        x0, y0, x1, y1 = self._bounds()
        w, h = max(1e-6, x1 - x0), max(1e-6, y1 - y0)
        s = min(self.width() / w, self.height() / h) * 0.9
        ox = (self.width() - w * s) / 2.0
        oy = (self.height() - h * s) / 2.0

        def to_px(x, y):                      # y up, screen y down
            return QPointF(ox + (x - x0) * s, self.height() - oy - (y - y0) * s)

        p.setRenderHint(QPainter.Antialiasing, True)
        if self._outline is not None:
            try:
                geoms = (self._outline.geoms
                         if hasattr(self._outline, "geoms") else [self._outline])
                pen = QPen(QColor(theme.OUTLINE), 1)
                pen.setCosmetic(True)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                for g in geoms:
                    coords = list(getattr(g, "coords", []) or
                                  getattr(getattr(g, "exterior", None), "coords", []))
                    if len(coords) > 1:
                        p.drawPolyline(QPolygonF([to_px(cx, cy)
                                                  for cx, cy in coords]))
            except Exception:
                pass                          # a map that cannot draw the
                                              # outline is still a useful map
        pen = QPen(QColor(theme.HOLE), 1)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        for x, y in self._holes:
            p.drawEllipse(to_px(x, y), 2.0, 2.0)
        for i, (ax, ay) in enumerate(self._anchors, 1):
            c = to_px(ax, ay)
            wanted = (i == self._next + 1)
            ink = theme.TOOL if wanted else theme.TEXT_3
            pen = QPen(QColor(ink), 2 if wanted else 1)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.setBrush(QBrush(theme.alpha(ink, 0.20)) if wanted else Qt.NoBrush)
            p.drawEllipse(c, 8, 8)
            p.setPen(QPen(QColor(theme.TEXT if wanted else theme.TEXT_3)))
            p.setFont(theme.font("label"))
            p.drawText(QRectF(c.x() - 8, c.y() - 8, 16, 16),
                       Qt.AlignCenter, str(i))
        p.end()


class PhotoAnchorDialog(QDialog):
    """Click the anchor holes in the photo, in the order the map numbers them."""

    def __init__(self, parent, image, anchors, holes=None, outline=None):
        super().__init__(parent)
        self.setWindowTitle("Line the photo up with the board")
        self.setModal(True)
        self.resize(1040, 720)
        self._anchors = list(anchors)

        v = QVBoxLayout(self)
        v.setContentsMargins(theme.GAP_L + 4, theme.GAP_L, theme.GAP_L + 4,
                             theme.GAP_L)
        v.setSpacing(theme.GAP_M)
        head = QLabel("Line the photo up with the board")
        head.setFont(theme.font("title"))
        v.addWidget(head)
        self.prompt = QLabel("")
        self.prompt.setWordWrap(True)
        self.prompt.setFont(theme.font("body"))
        self.prompt.setStyleSheet("color: %s;" % theme.TEXT_2)
        v.addWidget(self.prompt)

        row = QHBoxLayout()
        row.setSpacing(theme.GAP_M)
        self.canvas = _PhotoCanvas(image, self)
        self.map = _DesignMap(holes, outline, self._anchors, self)
        row.addWidget(self.canvas, 1)
        row.addWidget(self.map)
        v.addLayout(row, 1)

        buttons = QHBoxLayout()
        self.undo_btn = widgets.button("Undo the last one", on=self.canvas.undo)
        self.ok_btn = widgets.button("Use these anchors", on=self.accept,
                                     enabled=False)
        buttons.addWidget(self.undo_btn)
        buttons.addStretch(1)
        buttons.addWidget(widgets.button("Cancel", on=self.reject))
        buttons.addWidget(self.ok_btn)
        v.addLayout(buttons)
        self.anchor_changed()

    def anchor_changed(self):
        n = len(self.canvas.points())
        self.map.set_next(n)
        self.ok_btn.setEnabled(n >= len(self._anchors))
        self.undo_btn.setEnabled(bool(n))
        if n >= len(self._anchors):
            self.prompt.setText(
                "All %d clicked. Use these anchors, or undo and redo any that "
                "look off — the fit is only as good as the clicks."
                % len(self._anchors))
        else:
            ax, ay = self._anchors[n]
            self.prompt.setText(
                "Click hole %d of %d in the photo — the one ringed on the map, "
                "at machine X %.1f, Y %.1f. Wheel zooms, shift-drag pans."
                % (n + 1, len(self._anchors), ax, ay))

    def photo_points(self):
        """The clicked ``(u, v)`` pixel coordinates, in anchor order."""
        return self.canvas.points()

    def machine_points(self):
        return list(self._anchors)


def to_qimage(rgba):
    """An HxWx4 uint8 array as a QImage that owns its pixels.

    The copy is not optional: QImage wraps the buffer it is given, and the
    numpy array behind a warp is temporary — without it the image renders as
    torn memory some time after the function that made it returned.
    """
    import numpy as np
    arr = np.ascontiguousarray(rgba.astype(np.uint8))
    h, w = arr.shape[0], arr.shape[1]
    fmt = QImage.Format_RGBA8888 if arr.shape[2] == 4 else QImage.Format_RGB888
    return QImage(arr.data, w, h, arr.strides[0], fmt).copy()
