"""The laser page: the bed as the F1 Ultra's camera sees it, the stencil on it,
and the buttons to focus, show and cut. What XCS's canvas does for a stencil,
without XCS.

* **Photo** takes the camera's picture and straightens it with the machine's own
  calibration (``engine/xtool_camera.py``), so a millimetre on the screen is a
  millimetre of the laser's coordinates.
* The stencil is drawn on it: drag it onto clean foil, or type X and Y (its
  outline's top-left corner, in the laser's mm).
* **Autofocus** measures the height with the blue dot, as XCS does, and moves the
  head. After it, the photo is true for the foil's surface whatever the plate
  height: the camera rides on the head.
* **Show where** runs the blue diode round the outline, faint enough not to mark
  steel. **Cut** runs the zoned job (``engine/xtool.py``) at the focus the head is
  at. **Stop** always works.

Every laser call runs on a worker thread; the page only shows what comes back.
"""
from PySide6.QtCore import QPointF, QRectF, QSettings, Qt, QThread, Signal
from PySide6.QtGui import (QBrush, QColor, QImage, QPainterPath, QPen, QPixmap,
                           QPolygonF)
from PySide6.QtWidgets import (QDialog, QDoubleSpinBox, QGraphicsItem,
                               QGraphicsPathItem, QGraphicsScene, QGraphicsView,
                               QHBoxLayout, QProgressBar, QSpinBox, QVBoxLayout,
                               QWidget)

from gerber2rml.engine import xtool
from gerber2rml.gui2 import theme, widgets

_SETTINGS = ("SRM-CAM", "stencil-laser")
_PX_PER_MM = 4
_FIELD = 220.0          # mm the camera calibration covers


class _Worker(QThread):
    progress = Signal(float)
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            self.finished_ok.emit(self._fn(self.progress.emit))
        except Exception as e:              # noqa: BLE001 - shown to the operator
            self.failed.emit(str(e))


class _StencilItem(QGraphicsPathItem):
    """The stencil, in mm, with its position at the outline's top-left corner."""

    def __init__(self, art, on_move):
        super().__init__()
        self._on_move = on_move
        w, h = art.size
        path = QPainterPath()
        path.setFillRule(Qt.OddEvenFill)
        for poly in art.apertures:
            for ring in (poly.exterior, *poly.interiors):
                pts = [QPointF(x, h - y) for x, y in ring.coords]
                path.addPolygon(QPolygonF(pts))
                path.closeSubpath()
        self.setPath(path)
        self.setBrush(QBrush(QColor(255, 80, 40, 200)))
        self.setPen(QPen(Qt.NoPen))
        outline = QPainterPath()
        for ring in (art.outline.exterior, *art.outline.interiors):
            outline.addPolygon(QPolygonF([QPointF(x, h - y) for x, y in ring.coords]))
        self._outline = QGraphicsPathItem(outline, self)
        pen = QPen(QColor(255, 210, 0))
        pen.setCosmetic(True)
        pen.setWidth(2)
        self._outline.setPen(pen)
        self.setFlags(QGraphicsItem.ItemIsMovable
                      | QGraphicsItem.ItemSendsGeometryChanges)
        self.setCursor(Qt.OpenHandCursor)

    def shape(self):                # grab it anywhere inside the outline
        s = QPainterPath()
        s.addRect(self._outline.path().boundingRect())
        return s

    def boundingRect(self):
        return self._outline.path().boundingRect().adjusted(-1, -1, 1, 1)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            self._on_move(self.pos())
        return super().itemChange(change, value)


class _BedView(QGraphicsView):
    """Keeps the bed in view; the wheel zooms."""

    def __init__(self, scene):
        super().__init__(scene)
        self.setRenderHints(self.renderHints())
        self.setDragMode(QGraphicsView.NoDrag)
        self.setBackgroundBrush(QColor(30, 30, 30))
        self._fitted = True

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._fitted:
            self.fitInView(QRectF(0, 0, _FIELD, _FIELD), Qt.KeepAspectRatio)

    def wheelEvent(self, e):
        f = 1.25 if e.angleDelta().y() > 0 else 0.8
        self._fitted = False
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.scale(f, f)

    def mouseDoubleClickEvent(self, e):
        self._fitted = True
        self.resetTransform()
        self.fitInView(QRectF(0, 0, _FIELD, _FIELD), Qt.KeepAspectRatio)


def _spin(value, lo, hi, step, decimals=2, suffix=" mm"):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setSingleStep(step)
    s.setValue(value)
    s.setKeyboardTracking(False)
    s.setSuffix(suffix)
    return s


def _ispin(value, lo, hi):
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setValue(value)
    return s


class StencilLaserDialog(QDialog):
    """``art`` is a :class:`gerber2rml.engine.stencil.StencilArtwork`."""

    def __init__(self, art, parent=None, laser=None):
        super().__init__(parent)
        self.art = art
        self.laser = laser or xtool.F1Ultra()
        self._cal = None
        self._worker = None
        self._syncing = False
        self.setWindowTitle("xTool F1 Ultra · solder paste stencil")
        self.resize(1280, 820)
        cfg = QSettings(*_SETTINGS)
        r = xtool.DEFAULT_RECIPE

        # -- the bed -----------------------------------------------------
        self.scene = QGraphicsScene(-10, -10, _FIELD + 20, _FIELD + 20)
        self._bg = self.scene.addPixmap(self._grid_pixmap())
        self._bg.setScale(1 / _PX_PER_MM)
        self._bg.setZValue(-10)
        self.item = _StencilItem(art, self._dragged)
        self.scene.addItem(self.item)
        self.view = _BedView(self.scene)

        # -- the panel ---------------------------------------------------
        panel = QWidget()
        panel.setFixedWidth(340)
        v = QVBoxLayout(panel)
        v.setSpacing(theme.GAP_S)
        w, h = art.size
        v.addWidget(widgets.head(f"{len(art.apertures)} holes · {w:.1f} × {h:.1f} mm"))
        v.addWidget(widgets.hint(
            f"{'Mirrored' if art.mirrored else 'Not mirrored'}, kerf "
            f"{art.kerf:g} mm. Drag it onto clean foil."))
        for msg in art.warnings():
            n = widgets.hint(msg)
            n.setStyleSheet(f"color: {theme.CAUTION};")
            v.addWidget(n)

        self.photo_btn = widgets.button("Take photo", on=self.take_photo)
        self.focus_btn = widgets.button(
            "Autofocus", on=self.autofocus,
            tip="Measures the height at the middle of the bed (X110 Y110) with "
                "the blue dot and moves the head, as XCS does. Put the foil there.")
        row = QWidget()
        hb = QHBoxLayout(row)
        hb.setContentsMargins(0, 0, 0, 0)
        hb.addWidget(self.photo_btn)
        hb.addWidget(self.focus_btn)
        v.addWidget(row)
        self.focus_note = widgets.hint("Focus: not measured yet.")
        v.addWidget(self.focus_note)

        self.x = _spin(float(cfg.value("x", 60.0)), -50, _FIELD, 0.1)
        self.y = _spin(float(cfg.value("y", 60.0)), -50, _FIELD, 0.1)
        self.x.valueChanged.connect(self._typed)
        self.y.valueChanged.connect(self._typed)
        v.addWidget(widgets.Field("X", self.x))
        v.addWidget(widgets.Field("Y", self.y))

        self.thickness = _spin(float(cfg.value("thickness", 4.1)), 0, 137, 0.1)
        self.set_focus_btn = widgets.button("Set", on=self.set_thickness)
        trow = QWidget()
        th = QHBoxLayout(trow)
        th.setContentsMargins(0, 0, 0, 0)
        th.addWidget(widgets.Field("Thickness", self.thickness), 1)
        th.addWidget(self.set_focus_btn)
        v.addWidget(trow)
        v.addWidget(widgets.hint("Or type XCS's thickness and press Set: the head "
                                 "goes to it + 8 mm."))

        self.passes = _ispin(r.total_passes, 1, 200)
        self.burst = _ispin(r.passes_per_burst, 1, 50)
        self.rest = _spin(r.rest_s, 0, 120, 1, 0, " s")
        self.zones = _ispin(r.zones, 1, 12)
        more = widgets.Disclosure("Recipe", key="stencil-recipe")
        more.body.addWidget(widgets.Field(
            "Passes", self.passes, help="Per hole, in total. 30 cuts 0.1 mm 304 "
                                        "stainless on the lab's F1 Ultra."))
        more.body.addWidget(widgets.Field("Per burst", self.burst))
        more.body.addWidget(widgets.Field(
            "Rest", self.rest, help="Laser off after every burst; each zone "
                                    "cools while the others are cut."))
        more.body.addWidget(widgets.Field("Zones", self.zones))
        v.addWidget(more)

        self.trace_btn = widgets.button(
            "Show where", on=self.trace,
            tip="The blue diode round the outline, faint enough not to mark steel.")
        self.cut_btn = widgets.button("Cut", kind="primary", on=self.cut)
        self.stop_btn = widgets.button("Stop", kind="stop", on=self.stop)
        row2 = QWidget()
        hb2 = QHBoxLayout(row2)
        hb2.setContentsMargins(0, 0, 0, 0)
        hb2.addWidget(self.trace_btn)
        hb2.addWidget(self.cut_btn)
        v.addWidget(row2)
        v.addWidget(self.stop_btn)

        self.status = widgets.body("")
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        v.addWidget(self.status)
        v.addWidget(self.bar)
        v.addStretch(1)

        top = QHBoxLayout(self)
        top.addWidget(self.view, 1)
        top.addWidget(panel)
        self._typed()
        self._busy(False)

    # -- the bed picture -------------------------------------------------
    @staticmethod
    def _grid_pixmap():
        n = int(_FIELD * _PX_PER_MM)
        img = QImage(n, n, QImage.Format_RGB888)
        img.fill(QColor(70, 70, 70))
        pm = QPixmap.fromImage(img)
        from PySide6.QtGui import QPainter
        p = QPainter(pm)
        p.setPen(QPen(QColor(95, 95, 95), 1))
        for k in range(0, int(_FIELD) + 1, 10):
            p.drawLine(k * _PX_PER_MM, 0, k * _PX_PER_MM, n)
            p.drawLine(0, k * _PX_PER_MM, n, k * _PX_PER_MM)
        p.end()
        return pm

    def show_bed(self, rgb):
        h, w = rgb.shape[:2]
        img = QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888).copy()
        self._bg.setPixmap(QPixmap.fromImage(img))

    # -- position ----------------------------------------------------------
    def origin(self):
        return self.x.value(), self.y.value()

    def _dragged(self, pos):
        if self._syncing:
            return
        self._syncing = True
        self.x.setValue(round(pos.x(), 2))
        self.y.setValue(round(pos.y(), 2))
        self._syncing = False

    def _typed(self, *_a):
        if self._syncing:
            return
        self._syncing = True
        self.item.setPos(self.x.value(), self.y.value())
        self._syncing = False

    def recipe(self):
        return xtool.Recipe(total_passes=self.passes.value(),
                            passes_per_burst=self.burst.value(),
                            rest_s=self.rest.value(), zones=self.zones.value())

    def paths(self):
        return xtool.stencil_paths(self.art, self.origin())

    def _remember(self):
        cfg = QSettings(*_SETTINGS)
        cfg.setValue("x", self.x.value())
        cfg.setValue("y", self.y.value())
        cfg.setValue("thickness", self.thickness.value())

    # -- actions -----------------------------------------------------------
    def _calibration(self):
        if self._cal is None:
            self._cal = self.laser.calibration()
        return self._cal

    def take_photo(self):
        def work(_p):
            from gerber2rml.engine.xtool_camera import decode_jpeg
            cal = self._calibration()
            self.laser.lights(True)
            return cal.rectify(decode_jpeg(self.laser.snap()), _PX_PER_MM)

        def shown(rgb):
            self.show_bed(rgb)
            return "Photo taken. Autofocus first if the foil height changed."
        self._start(work, "Taking a photo…", shown)

    def autofocus(self):
        def work(_p):
            return self.laser.autofocus(self._calibration())

        def done(z):
            self.thickness.setValue(z - xtool.FOCUS_OFFSET)
            self.focus_note.setText(f"Focus: Z {z:.2f} (XCS thickness "
                                    f"{z - xtool.FOCUS_OFFSET:.2f}).")
            self._remember()
            return "In focus. Take a new photo to place the stencil."
        self._start(work, "Autofocus: measuring with the blue dot…", done)

    def set_thickness(self):
        t = self.thickness.value()

        def done(z):
            self.focus_note.setText(f"Focus: Z {z:.2f} (thickness {t:g}).")
            self._remember()
            return "Head moved."
        self._start(lambda _p: self.laser.focus(t), "Moving the head…", done)

    def trace(self):
        try:
            _, outline = self.paths()
            text = xtool.trace_job(outline)
        except ValueError as e:
            return self._say(str(e), warn=True)
        self._remember()

        def work(_p):
            self.laser.run(text)
            self.laser.wait(180)
        self._start(work, "Tracing the outline in blue…",
                    lambda _r: "Traced. Drag the stencil if it was off.")

    def cut(self):
        try:
            holes, outline = self.paths()
            job = xtool.stencil_job(holes, outline, self.recipe())
        except ValueError as e:
            return self._say(str(e), warn=True)
        self._remember()
        self.bar.setRange(0, max(1, int(job.seconds)))
        self.bar.setValue(0)
        self.bar.setVisible(True)

        def work(progress):
            z = self.laser.z()
            self.laser.run(job.text)
            self.laser.wait(job.seconds * 2 + 120, progress=progress)
            return z
        self._start(work, f"Cutting, about {job.seconds / 60:.0f} min "
                          f"({len(job.zones)} zones)…",
                    lambda z: f"Cut at Z {z:.2f}: {sum(job.zones)} holes, "
                              f"{job.passes} passes. Push out any slugs.")

    def stop(self):
        try:
            self.laser.stop()
            self._say("Stopped.")
        except xtool.LaserError as e:
            self._say(str(e), warn=True)

    # -- plumbing ----------------------------------------------------------
    def _start(self, fn, text, done=None):
        self._say(text)
        self._busy(True)
        self._worker = _Worker(fn, self)
        self._worker.progress.connect(lambda s: self.bar.setValue(int(s)))
        self._worker.finished_ok.connect(
            lambda r: self._done((done(r) if done else None) or "Done.", False))
        self._worker.failed.connect(lambda m: self._done(m, True))
        self._worker.start()

    def _done(self, msg, warn):
        self._busy(False)
        self.bar.setVisible(False)
        self._say(msg, warn=warn)

    def _busy(self, on):
        for b in (self.photo_btn, self.focus_btn, self.set_focus_btn,
                  self.trace_btn, self.cut_btn):
            b.setEnabled(not on)
        self.item.setFlag(QGraphicsItem.ItemIsMovable, not on)

    def _say(self, text, warn=False):
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {theme.CAUTION};" if warn else "")

    def closeEvent(self, e):
        if self._worker is not None and self._worker.isRunning():
            self._say("The laser is still running: press Stop first.", warn=True)
            e.ignore()
            return
        super().closeEvent(e)
