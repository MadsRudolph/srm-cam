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

Two more things the first interface learned are here as well. The anchor
holes can be chosen by hand (:class:`HolePickDialog`): the automatic pick
takes the corner-most holes, which is right when the board has dowel or
fiducial holes and wrong on a single-sided board, whose corner holes may be
tiny or impossible to tell apart in a photo. And the photo's strength and the
design's fade over it are sliders (:class:`PhotoControls`) rather than one
fixed number, because checking a placement and finding a torn pad want the
two set differently.
"""
import math

from PySide6.QtCore import Qt, QPointF, QRectF, QSize, Signal
from PySide6.QtGui import QImage, QPainter, QPen, QBrush, QColor, QPolygonF
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QVBoxLayout,
                               QWidget, QSizePolicy, QSlider, QGridLayout)

from gerber2rml.gui2 import theme, widgets, dialogs

_MIN_ANCHORS = 4           # a homography needs four; fewer is a different fit
MIN_SPREAD_MM = 3.0        # the picked set's narrow axis: kills a collinear pick
SNAP_MM = 0.25             # a saved pick further than this from any hole is stale


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


def anchor_spread(pts):
    """How wide the picked set is across its NARROWEST direction, in mm.

    Twice the standard deviation along the minor axis of the points. Four
    holes along one edge of a board give a set that is long one way and
    nearly zero the other, and a homography fitted to it is exact on that
    edge and unbounded off it; the fit itself only raises an error when the
    points are exactly collinear, which a 0.3 mm scatter never is.
    """
    pts = [(float(x), float(y)) for x, y in (pts or [])]
    n = len(pts)
    if n < 2:
        return 0.0
    cx = sum(p[0] for p in pts) / n
    cy = sum(p[1] for p in pts) / n
    sxx = sum((p[0] - cx) ** 2 for p in pts) / n
    syy = sum((p[1] - cy) ** 2 for p in pts) / n
    sxy = sum((p[0] - cx) * (p[1] - cy) for p in pts) / n
    tr, det = sxx + syy, sxx * syy - sxy * sxy
    lam_min = tr / 2.0 - math.sqrt(max(tr * tr / 4.0 - det, 0.0))
    return 2.0 * math.sqrt(max(lam_min, 0.0))


def snap_picks(picks, holes, tol=SNAP_MM):
    """The operator's chosen anchors, re-matched to the holes on screen now.

    The picks are stored as machine coordinates, and the board can have been
    moved or reloaded since they were made. Each is snapped to the nearest
    hole within ``tol``; if any has none — the picks belong to a board that
    is no longer where it was — the whole set is stale and None comes back,
    so the caller falls back to the automatic pick rather than fitting a
    photo to holes that are not there.
    """
    hs = [(float(x), float(y)) for x, y, *_ in (holes or [])]
    if not picks or not hs:
        return None
    out = []
    for px, py in picks:
        hx, hy = min(hs, key=lambda h: math.hypot(h[0] - px, h[1] - py))
        if math.hypot(hx - px, hy - py) > tol or (hx, hy) in out:
            return None
        out.append((hx, hy))
    return out if len(out) >= _MIN_ANCHORS else None


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

    def _mapping(self):
        """``(scale, ox, oy, x0, y0)``: mm to pixels, the design fitted in
        the widget with a margin. One place, so the painter and a click agree
        about where a hole is."""
        x0, y0, x1, y1 = self._bounds()
        w, h = max(1e-6, x1 - x0), max(1e-6, y1 - y0)
        s = min(self.width() / w, self.height() / h) * 0.9
        ox = (self.width() - w * s) / 2.0
        oy = (self.height() - h * s) / 2.0
        return s, ox, oy, x0, y0

    def to_px(self, x, y):                    # y up, screen y down
        s, ox, oy, x0, y0 = self._mapping()
        return QPointF(ox + (x - x0) * s, self.height() - oy - (y - y0) * s)

    def to_mm(self, pos):
        s, ox, oy, x0, y0 = self._mapping()
        return ((pos.x() - ox) / s + x0,
                (self.height() - oy - pos.y()) / s + y0)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(theme.BED))
        to_px = self.to_px
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
            wanted = (i == self._next + 1) or self._next < 0
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


class _HolePickCanvas(_DesignMap):
    """The design map, but the holes on it can be clicked to become anchors.

    A click lands on the nearest hole within a grab radius, never on empty
    board: an anchor that is not a drilled hole cannot be found in the photo.
    """
    changed = Signal()
    GRAB_PX = 14

    def __init__(self, holes, outline, preset=None, parent=None):
        super().__init__(holes, outline, [], parent)
        self._next = -1                       # every pick is "wanted": all lit
        self.setCursor(Qt.CrossCursor)
        self.setMinimumSize(520, 420)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        for x, y in (preset or []):
            hit = self._hole_near_mm(x, y, SNAP_MM)
            if hit is not None and hit not in self._anchors:
                self._anchors.append(hit)

    def sizeHint(self):
        return QSize(640, 480)

    def _hole_near_mm(self, x, y, tol):
        best, bd = None, tol
        for hx, hy in self._holes:
            d = math.hypot(hx - x, hy - y)
            if d < bd:
                best, bd = (hx, hy), d
        return best

    def pick_at(self, pos):
        """Add the hole under a widget position; True if one was there."""
        if not self._holes:
            return False
        s = self._mapping()[0]
        x, y = self.to_mm(pos)
        hit = self._hole_near_mm(x, y, self.GRAB_PX / max(s, 1e-6))
        if hit is None or hit in self._anchors:
            return False
        self._anchors.append(hit)
        self.update()
        self.changed.emit()
        return True

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.pick_at(e.position())

    def undo(self):
        if self._anchors:
            self._anchors.pop()
            self.update()
            self.changed.emit()

    def picks(self):
        return list(self._anchors)


class HolePickDialog(dialogs.Sheet):
    """Choose which drilled holes anchor the photo.

    ``anchors()`` returns the picks in click order, which is the order the
    photo dialog then asks for them.
    """

    def __init__(self, parent, holes, outline=None, preset=None):
        super().__init__(parent, "Choose the holes that anchor the photo",
                         width=720)
        self.say("Click at least four holes you will be able to find again in "
                 "the photo, spread towards the corners. The automatic choice "
                 "takes the corner-most holes, which is right when the board "
                 "has dowel or fiducial holes — a single-sided board has "
                 "none, and its corner holes may be tiny or look alike.")
        self.canvas = _HolePickCanvas(holes, outline, preset, self)
        self.canvas.changed.connect(self._sync)
        self.add(self.canvas, grow=True)
        self.prompt = self.say("", small=True)
        self.undo_btn = self.act("Undo the last one", on=self.canvas.undo)
        self.act("Cancel", on=self.reject)
        self.ok_btn = self.act("Use these holes", kind="primary",
                               on=self.accept, default=True)
        self._sync()

    def _sync(self):
        picks = self.canvas.picks()
        n = len(picks)
        thin = n >= _MIN_ANCHORS and anchor_spread(picks) < MIN_SPREAD_MM
        self.undo_btn.setEnabled(n > 0)
        self.ok_btn.setEnabled(n >= _MIN_ANCHORS and not thin)
        if thin:
            self.prompt.setText(
                "Those holes are nearly in a line, so a photo fitted on them "
                "would be right along that line and wrong everywhere else. "
                "Add one away from it.")
        elif n < _MIN_ANCHORS:
            self.prompt.setText("%d chosen — %d more to go. Click a hole to "
                                "add it." % (n, _MIN_ANCHORS - n))
        else:
            self.prompt.setText(
                "%d chosen, numbered in the order the photo will ask for "
                "them. Add more if the photo is at an angle; undo any that "
                "look alike." % n)

    def anchors(self):
        return self.canvas.picks()


class PhotoControls(QWidget):
    """Two sliders: how strongly the photo shows, and how far the design is
    faded over it. Lives in the View menu next to the photo actions, so it
    is where the photo was put on, and it keeps the menu open while a slider
    is dragged — the bed updates underneath as it moves."""
    opacity_changed = Signal(float)
    dim_changed = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        g = QGridLayout(self)
        g.setContentsMargins(theme.GAP_M + 4, theme.GAP_S, theme.GAP_M + 4,
                             theme.GAP_S)
        g.setHorizontalSpacing(theme.GAP_S)
        g.setVerticalSpacing(2)
        self.opacity = QSlider(Qt.Horizontal)
        self.opacity.setRange(0, 100)
        self.opacity.setValue(100)
        self.opacity.setToolTip("How strongly the photo shows on the bed.")
        self.dim = QSlider(Qt.Horizontal)
        self.dim.setRange(0, 100)
        self.dim.setValue(55)
        self.dim.setToolTip("How far the copper and toolpaths are faded so "
                            "the photo underneath reads clearly. Rework "
                            "boxes stay at full strength.")
        for s in (self.opacity, self.dim):
            s.setMinimumWidth(160)
        g.addWidget(widgets.micro("Photo"), 0, 0)
        g.addWidget(self.opacity, 0, 1)
        g.addWidget(widgets.micro("Fade the design"), 1, 0)
        g.addWidget(self.dim, 1, 1)
        self.opacity.valueChanged.connect(
            lambda v: self.opacity_changed.emit(v / 100.0))
        self.dim.valueChanged.connect(lambda v: self.dim_changed.emit(v / 100.0))

    def set_values(self, opacity, dim):
        """Put saved values on the sliders without firing them: the caller
        applies them itself, in the order it needs."""
        for s, v in ((self.opacity, opacity), (self.dim, dim)):
            s.blockSignals(True)
            s.setValue(int(round(max(0.0, min(1.0, float(v))) * 100)))
            s.blockSignals(False)

    def values(self):
        return self.opacity.value() / 100.0, self.dim.value() / 100.0


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
