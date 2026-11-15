"""The laser page: the bed as the F1 Ultra's camera sees it, the stencil on it,
and everything needed to place, focus and cut it. What XCS's canvas does for a
stencil, without XCS.

Layout, like XCS: a toolbar over the picture, the settings in cards on the
right, a status bar under both.

* **Photo** takes the camera's picture and straightens it with the machine's own
  calibration (``engine/xtool_camera.py``): a millimetre on the screen is a
  millimetre of the laser's coordinates.
* **The stencil** sits on the photo. Drag it; nudge it with the arrow keys
  (Shift x10, Ctrl x100); turn it a quarter at a time; right-click to centre it
  where you click. X and Y are its outline's top-left corner.
* **Autofocus** measures the height with the blue dot under the focus mark (a
  cross on the factory's 10 mm grid, at the stencil's middle unless you
  right-click "Autofocus here") and moves the head.
* **Select** mode picks holes, by click or by dragging a box; **Cut** then cuts
  only those, for the ones that did not go through.
* **Cut** shows the zone being cut and the time left, and takes a photo when it
  is done. **Stop** always works.

Every laser call runs on a worker thread; the page only shows what comes back.
"""
import json

from PySide6.QtCore import QPointF, QRectF, QSettings, Qt, QThread, Signal
from PySide6.QtGui import (QAction, QBrush, QColor, QFont, QImage, QPainter,
                           QPainterPath, QPen, QPixmap, QPolygonF)
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox,
                               QFrame, QGraphicsItem, QGraphicsPathItem,
                               QGraphicsScene, QGraphicsSimpleTextItem,
                               QGraphicsView, QHBoxLayout, QInputDialog, QLabel,
                               QMenu, QProgressBar, QScrollArea, QSpinBox,
                               QToolButton, QVBoxLayout, QWidget)

from gerber2rml.engine import xtool
from gerber2rml.gui2 import theme, widgets

_SETTINGS = ("SRM-CAM", "stencil-laser")
_PX_PER_MM = 4
_FIELD = 220.0          # mm the camera calibration covers

_HOLE = QColor(255, 96, 48)
_HOLE_SELECTED = QColor(40, 200, 255)
_HOLE_ACTIVE = QColor(120, 255, 90)
_HOLE_DIM = QColor(255, 96, 48, 150)
_OUTLINE = QColor(255, 214, 0)
_FOCUS = QColor(255, 60, 200)

BUILTIN_PRESETS = {
    "0.1 mm 304 stainless": xtool.DEFAULT_RECIPE,
    "Marking test (1 pass)": xtool.Recipe(power=30, total_passes=1,
                                          passes_per_burst=1, rest_s=0, zones=1,
                                          mark_passes=0),
}
_RECIPE_FIELDS = ("power", "speed", "frequency", "total_passes",
                  "passes_per_burst", "rest_s", "zones", "mark_power",
                  "mark_passes")


def _recipe_dict(r):
    return {f: getattr(r, f) for f in _RECIPE_FIELDS}


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


# ---------------------------------------------------------------------------
# The stencil on the bed
# ---------------------------------------------------------------------------

class _Hole(QGraphicsPathItem):
    def __init__(self, index, path, parent):
        super().__init__(path, parent)
        self.index = index
        self.setPen(QPen(Qt.NoPen))
        self.setAcceptHoverEvents(True)
        r = path.boundingRect()
        self.setToolTip(f"Hole {index + 1}: {r.width():.2f} × {r.height():.2f} mm")


class _StencilItem(QGraphicsPathItem):
    """The outline (this item) with a child per hole, positioned at the
    outline's top-left corner, in mm."""

    def __init__(self, art, on_move):
        super().__init__()
        self._on_move = on_move
        w, h = art.size
        outline = QPainterPath()
        for ring in (art.outline.exterior, *art.outline.interiors):
            outline.addPolygon(QPolygonF([QPointF(x, h - y) for x, y in ring.coords]))
        self.setPath(outline)
        pen = QPen(_OUTLINE)
        pen.setCosmetic(True)
        pen.setWidth(2)
        self.setPen(pen)
        self.holes = []
        for k, poly in enumerate(art.apertures):
            p = QPainterPath()
            p.setFillRule(Qt.OddEvenFill)
            for ring in (poly.exterior, *poly.interiors):
                p.addPolygon(QPolygonF([QPointF(x, h - y) for x, y in ring.coords]))
                p.closeSubpath()
            self.holes.append(_Hole(k, p, self))
        self.setFlags(QGraphicsItem.ItemIsMovable
                      | QGraphicsItem.ItemSendsGeometryChanges)
        self.setCursor(Qt.OpenHandCursor)

    def shape(self):                # grab it anywhere inside the outline
        s = QPainterPath()
        s.addRect(self.path().boundingRect())
        return s

    def paint_holes(self, selected, active=None, dim_unselected=False):
        for hole in self.holes:
            if active is not None and hole.index in active:
                c = _HOLE_ACTIVE
            elif hole.index in selected:
                c = _HOLE_SELECTED
            elif dim_unselected:
                c = _HOLE_DIM
            else:
                c = _HOLE
            hole.setBrush(QBrush(c))

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            self._on_move(self.pos())
        return super().itemChange(change, value)


class _BedView(QGraphicsView):
    """Keeps the bed in view; wheel zooms, double-click fits, arrows nudge,
    right-click offers placing and focusing at that point."""

    moved = Signal(QPointF)
    nudge = Signal(float, float)
    context = Signal(QPointF, object)
    boxed = Signal(QRectF, bool)

    def __init__(self, scene):
        super().__init__(scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setBackgroundBrush(QColor(28, 28, 28))
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._fitted = True
        self.select_mode = False
        self.rubberBandChanged.connect(self._band)
        self._last_band = QRectF()

    def fit(self):
        self._fitted = True
        self.resetTransform()
        self.fitInView(QRectF(-12, -12, _FIELD + 24, _FIELD + 24), Qt.KeepAspectRatio)

    def zoom(self, f):
        self._fitted = False
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.scale(f, f)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._fitted:
            self.fit()

    def wheelEvent(self, e):
        self.zoom(1.25 if e.angleDelta().y() > 0 else 0.8)

    def mouseDoubleClickEvent(self, e):
        self.fit()

    def mouseMoveEvent(self, e):
        self.moved.emit(self.mapToScene(e.position().toPoint()))
        super().mouseMoveEvent(e)

    def keyPressEvent(self, e):
        step = 0.1
        if e.modifiers() & Qt.ShiftModifier:
            step = 1.0
        if e.modifiers() & Qt.ControlModifier:
            step = 10.0
        d = {Qt.Key_Left: (-step, 0), Qt.Key_Right: (step, 0),
             Qt.Key_Up: (0, -step), Qt.Key_Down: (0, step)}.get(e.key())
        if d:
            self.nudge.emit(*d)
            return
        super().keyPressEvent(e)

    def contextMenuEvent(self, e):
        self.context.emit(self.mapToScene(e.pos()), e.globalPos())

    def set_select_mode(self, on):
        self.select_mode = on
        self.setDragMode(QGraphicsView.RubberBandDrag if on else QGraphicsView.NoDrag)

    def _band(self, rect, a, b):
        if not rect.isNull():
            self._last_band = self.mapToScene(rect).boundingRect()

    def mouseReleaseEvent(self, e):
        band = self._last_band
        self._last_band = QRectF()
        super().mouseReleaseEvent(e)
        if self.select_mode:
            add = bool(e.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier))
            if band.width() > 0.3 or band.height() > 0.3:
                self.boxed.emit(band, add)
            else:
                p = self.mapToScene(e.position().toPoint())
                self.boxed.emit(QRectF(p, p), add)


# ---------------------------------------------------------------------------
# Small widgets
# ---------------------------------------------------------------------------

def _spin(value, lo, hi, step, decimals=2, suffix=" mm"):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setSingleStep(step)
    s.setValue(value)
    s.setKeyboardTracking(False)
    s.setSuffix(suffix)
    return s


def _ispin(value, lo, hi, suffix=""):
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setValue(value)
    if suffix:
        s.setSuffix(suffix)
    return s


def _tool(text, tip, on, checkable=False):
    b = QToolButton()
    b.setText(text)
    b.setToolTip(tip)
    b.setCheckable(checkable)
    b.setToolButtonStyle(Qt.ToolButtonTextOnly)
    b.setCursor(Qt.PointingHandCursor)
    (b.toggled if checkable else b.clicked).connect(on)
    return b


class _Card(QFrame):
    def __init__(self, title):
        super().__init__()
        self.setObjectName("card")
        self.setStyleSheet("#card { border: 1px solid rgba(255,255,255,0.10);"
                           " border-radius: 6px; }")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(10, 8, 10, 10)
        self.body.setSpacing(6)
        self.body.addWidget(widgets.eyebrow(title))


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------

class StencilLaserDialog(QDialog):
    """``art`` is a :class:`gerber2rml.engine.stencil.StencilArtwork`."""

    def __init__(self, art, parent=None, laser=None):
        super().__init__(parent)
        self.base_art = art
        self.turns = 0
        self.art = art
        self.laser = laser or xtool.F1Ultra()
        self._cal = None
        self._worker = None
        self._syncing = False
        self.selected = set()
        self._job = None
        self._focus_point = None            # None: follow the stencil's middle
        self._bed_rgb = None
        self.setWindowTitle("xTool F1 Ultra · solder paste stencil")
        self.resize(1360, 880)
        cfg = QSettings(*_SETTINGS)

        # -- the bed -----------------------------------------------------
        self.scene = QGraphicsScene(-14, -14, _FIELD + 28, _FIELD + 28)
        self._bg = self.scene.addPixmap(self._grid_pixmap())
        self._bg.setScale(1 / _PX_PER_MM)
        self._bg.setZValue(-10)
        self._add_rulers()
        self._focus_mark = self._make_focus_mark()
        self.item = None
        self.view = _BedView(self.scene)
        self.view.moved.connect(self._cursor)
        self.view.nudge.connect(self._nudge)
        self.view.context.connect(self._context)
        self.view.boxed.connect(self._boxed)

        # -- toolbar -----------------------------------------------------
        bar = QWidget()
        tb = QHBoxLayout(bar)
        tb.setContentsMargins(0, 0, 0, 0)
        tb.setSpacing(4)
        self.photo_btn = _tool("📷 Photo", "Take a picture of the bed", self.take_photo)
        self.focus_btn = _tool("◎ Autofocus", "Measure the height under the pink "
                               "cross with the blue dot and move the head",
                               lambda: self.autofocus())
        self.rot_l = _tool("Turn ◂", "Turn the stencil a quarter anticlockwise",
                           lambda: self.rotate(-1))
        self.rot_r = _tool("Turn ▸", "Turn the stencil a quarter clockwise",
                           lambda: self.rotate(1))
        self.select_btn = _tool("⬚ Select holes", "Click holes or drag a box; "
                                "Ctrl or Shift adds. Cut then cuts only those.",
                                self._select_mode, checkable=True)
        self.all_btn = _tool("All", "Select every hole", self.select_all)
        self.none_btn = _tool("None", "Clear the selection", self.select_none)
        zin = _tool("＋", "Zoom in", lambda: self.view.zoom(1.25))
        zout = _tool("－", "Zoom out", lambda: self.view.zoom(0.8))
        fit = _tool("⤢ Fit", "Show the whole bed", self.view.fit)
        for w in (self.photo_btn, self.focus_btn, self._sep(), self.rot_l,
                  self.rot_r, self._sep(), self.select_btn, self.all_btn,
                  self.none_btn):
            tb.addWidget(w)
        tb.addStretch(1)
        for w in (zout, zin, fit):
            tb.addWidget(w)

        # -- status bar --------------------------------------------------
        self.cursor_lbl = QLabel("X —  Y —")
        self.laser_lbl = QLabel("Laser: not asked yet")
        self.sel_lbl = QLabel("")
        sb = QWidget()
        sbl = QHBoxLayout(sb)
        sbl.setContentsMargins(4, 0, 4, 0)
        for w in (self.cursor_lbl, self.sel_lbl):
            w.setFont(theme.font("small"))
            sbl.addWidget(w)
            sbl.addSpacing(18)
        sbl.addStretch(1)
        self.laser_lbl.setFont(theme.font("small"))
        sbl.addWidget(self.laser_lbl)

        # -- cards -------------------------------------------------------
        panel = QWidget()
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(10)

        c = _Card("Stencil")
        w, h = art.size
        self.size_lbl = widgets.head("")
        c.body.addWidget(self.size_lbl)
        c.body.addWidget(widgets.hint(
            f"{'Mirrored' if art.mirrored else 'Not mirrored'} · kerf {art.kerf:g} mm"))
        for msg in art.warnings():
            n = widgets.hint(msg)
            n.setStyleSheet(f"color: {theme.CAUTION};")
            c.body.addWidget(n)
        self.x = _spin(float(cfg.value("x", 60.0)), -50, _FIELD, 0.1)
        self.y = _spin(float(cfg.value("y", 60.0)), -50, _FIELD, 0.1)
        self.x.valueChanged.connect(self._typed)
        self.y.valueChanged.connect(self._typed)
        c.body.addWidget(widgets.Field("X", self.x))
        c.body.addWidget(widgets.Field("Y", self.y))
        self.turn_lbl = widgets.hint("")
        c.body.addWidget(self.turn_lbl)
        pv.addWidget(c)

        c = _Card("Focus")
        self.focus_note = widgets.body("Not measured yet.")
        c.body.addWidget(self.focus_note)
        self.thickness = _spin(float(cfg.value("thickness", 4.1)), 0, 137, 0.1)
        self.set_focus_btn = widgets.button("Set", on=self.set_thickness)
        trow = QWidget()
        th = QHBoxLayout(trow)
        th.setContentsMargins(0, 0, 0, 0)
        th.addWidget(widgets.Field("Thickness", self.thickness), 1)
        th.addWidget(self.set_focus_btn)
        c.body.addWidget(trow)
        c.body.addWidget(widgets.hint("XCS's thickness; Set moves the head to it + 8 mm."))
        pv.addWidget(c)

        c = _Card("Recipe")
        self.preset = QComboBox()
        self.preset.currentTextChanged.connect(self._load_preset)
        prow = QWidget()
        ph = QHBoxLayout(prow)
        ph.setContentsMargins(0, 0, 0, 0)
        ph.addWidget(self.preset, 1)
        ph.addWidget(widgets.button("Save…", on=self.save_preset,
                                    tip="Save these numbers as a named recipe"))
        self.del_btn = widgets.button("Delete", on=self.delete_preset)
        ph.addWidget(self.del_btn)
        c.body.addWidget(prow)
        r = xtool.DEFAULT_RECIPE
        self.power = _spin(r.power, 1, 100, 1, 0, " %")
        self.speed = _spin(r.speed, 10, 5000, 10, 0, " mm/s")
        self.freq = _spin(r.frequency, 1, 60, 1, 0, " kHz")
        self.passes = _ispin(r.total_passes, 1, 300)
        self.burst = _ispin(r.passes_per_burst, 1, 50)
        self.rest = _spin(r.rest_s, 0, 120, 1, 0, " s")
        self.zones = _ispin(r.zones, 1, 12)
        self.mark = QCheckBox("Mark the outline afterwards")
        self.mark.setChecked(True)
        grid = [("Power", self.power), ("Speed", self.speed), ("Frequency", self.freq),
                ("Passes", self.passes), ("Per burst", self.burst),
                ("Rest", self.rest), ("Zones", self.zones)]
        for name, wdg in grid:
            c.body.addWidget(widgets.Field(name, wdg))
        c.body.addWidget(self.mark)
        self.recipe_lbl = widgets.hint("")
        c.body.addWidget(self.recipe_lbl)
        for wdg in (self.power, self.speed, self.freq, self.passes, self.burst,
                    self.rest, self.zones):
            wdg.valueChanged.connect(self._recipe_changed)
        self.mark.toggled.connect(self._recipe_changed)
        pv.addWidget(c)

        c = _Card("Run")
        self.trace_btn = widgets.button(
            "Show where", on=self.trace,
            tip="The blue diode round the outline, faint enough not to mark steel.")
        self.cut_btn = widgets.button("Cut", kind="primary", on=self.cut)
        self.stop_btn = widgets.button("Stop", kind="stop", on=self.stop)
        row = QWidget()
        rh = QHBoxLayout(row)
        rh.setContentsMargins(0, 0, 0, 0)
        rh.addWidget(self.trace_btn)
        rh.addWidget(self.cut_btn)
        c.body.addWidget(row)
        c.body.addWidget(self.stop_btn)
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        self.progress_lbl = widgets.hint("")
        self.status = widgets.body("")
        self.photo_after = QCheckBox("Take a photo when it is done")
        self.photo_after.setChecked(True)
        for wdg in (self.photo_after, self.bar, self.progress_lbl, self.status):
            c.body.addWidget(wdg)
        pv.addWidget(c)
        pv.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(panel)
        scroll.setFixedWidth(360)

        left = QVBoxLayout()
        left.addWidget(bar)
        left.addWidget(self.view, 1)
        main = QHBoxLayout()
        main.addLayout(left, 1)
        main.addWidget(scroll)
        outer = QVBoxLayout(self)
        outer.addLayout(main, 1)
        outer.addWidget(sb)

        self._fill_presets(cfg.value("preset", next(iter(BUILTIN_PRESETS))))
        self._build_item()
        self._busy(False)

    # -- the bed picture -------------------------------------------------
    @staticmethod
    def _sep():
        f = QFrame()
        f.setFrameShape(QFrame.VLine)
        f.setStyleSheet("color: rgba(255,255,255,0.15);")
        return f

    @staticmethod
    def _grid_pixmap():
        n = int(_FIELD * _PX_PER_MM)
        img = QImage(n, n, QImage.Format_RGB888)
        img.fill(QColor(62, 62, 62))
        pm = QPixmap.fromImage(img)
        p = QPainter(pm)
        p.setPen(QPen(QColor(88, 88, 88), 1))
        for k in range(0, int(_FIELD) + 1, 10):
            p.drawLine(k * _PX_PER_MM, 0, k * _PX_PER_MM, n)
            p.drawLine(0, k * _PX_PER_MM, n, k * _PX_PER_MM)
        p.end()
        return pm

    def _add_rulers(self):
        pen = QPen(QColor(150, 150, 150))
        pen.setCosmetic(True)
        font = QFont()
        font.setPointSize(8)
        for k in range(0, int(_FIELD) + 1, 10):
            long = k % 50 == 0
            t = 4 if long else 2
            self.scene.addLine(k, -t, k, 0, pen)
            self.scene.addLine(-t, k, 0, k, pen)
            if k % 20 == 0:
                for x, y in ((k, -13), (-13, k)):
                    lbl = QGraphicsSimpleTextItem(str(k))
                    lbl.setFont(font)
                    lbl.setBrush(QColor(170, 170, 170))
                    lbl.setFlag(QGraphicsItem.ItemIgnoresTransformations)
                    lbl.setPos(x, y)
                    self.scene.addItem(lbl)

    def _make_focus_mark(self):
        p = QPainterPath()
        p.moveTo(-3, 0)
        p.lineTo(3, 0)
        p.moveTo(0, -3)
        p.lineTo(0, 3)
        p.addEllipse(QPointF(0, 0), 1.6, 1.6)
        pen = QPen(_FOCUS)
        pen.setCosmetic(True)
        pen.setWidth(2)
        item = self.scene.addPath(p, pen)
        item.setZValue(20)
        item.setToolTip("Autofocus measures here (the factory's 10 mm grid)")
        return item

    def show_bed(self, rgb):
        self._bed_rgb = rgb
        h, w = rgb.shape[:2]
        img = QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888).copy()
        self._bg.setPixmap(QPixmap.fromImage(img))

    # -- the stencil -------------------------------------------------------
    def _build_item(self):
        keep = self.origin()
        if self.item is not None:
            self.scene.removeItem(self.item)
        self.item = _StencilItem(self.art, self._dragged)
        self.item.setZValue(5)
        self.scene.addItem(self.item)
        self._syncing = True
        self.item.setPos(*keep)
        self._syncing = False
        w, h = self.art.size
        self.size_lbl.setText(f"{len(self.art.apertures)} holes · {w:.1f} × {h:.1f} mm")
        self.turn_lbl.setText(f"Turned {90 * self.turns}° clockwise" if self.turns
                              else "As drawn")
        self._paint()
        self._place_focus_mark()

    def rotate(self, step):
        cx, cy = self.centre()
        self.turns = (self.turns + step) % 4
        self.art = xtool.rotated(self.base_art, self.turns)
        self.selected.clear()
        w, h = self.art.size
        self._syncing = True
        self.x.setValue(round(cx - w / 2, 2))
        self.y.setValue(round(cy - h / 2, 2))
        self._syncing = False
        self._build_item()

    def origin(self):
        return self.x.value(), self.y.value()

    def centre(self):
        w, h = self.art.size
        return self.x.value() + w / 2, self.y.value() + h / 2

    def centre_at(self, p):
        w, h = self.art.size
        self.x.setValue(round(p.x() - w / 2, 2))
        self.y.setValue(round(p.y() - h / 2, 2))

    def _dragged(self, pos):
        if self._syncing:
            return
        self._syncing = True
        self.x.setValue(round(pos.x(), 2))
        self.y.setValue(round(pos.y(), 2))
        self._syncing = False
        self._place_focus_mark()

    def _typed(self, *_a):
        if self._syncing or self.item is None:
            return
        self._syncing = True
        self.item.setPos(self.x.value(), self.y.value())
        self._syncing = False
        self._place_focus_mark()

    def _nudge(self, dx, dy):
        if self.item is None or not self.item.flags() & QGraphicsItem.ItemIsMovable:
            return
        self.x.setValue(self.x.value() + dx)
        self.y.setValue(self.y.value() + dy)

    def focus_point(self):
        return xtool.snap_to_grid(self._focus_point or self.centre())

    def _place_focus_mark(self):
        self._focus_mark.setPos(*self.focus_point())

    def _cursor(self, p):
        self.cursor_lbl.setText(f"X {p.x():7.2f}   Y {p.y():7.2f} mm")

    def _context(self, p, global_pos):
        m = QMenu(self)
        a1 = m.addAction("Centre the stencil here")
        a2 = m.addAction("Autofocus here")
        a3 = m.addAction("Focus at the stencil's middle again")
        a3.setEnabled(self._focus_point is not None)
        busy = self._worker is not None and self._worker.isRunning()
        for a in (a1, a2, a3):
            a.setEnabled(a.isEnabled() and not busy)
        got = m.exec(global_pos)
        if got is a1:
            self.centre_at(p)
        elif got is a2:
            self._focus_point = (p.x(), p.y())
            self._place_focus_mark()
            self.autofocus()
        elif got is a3:
            self._focus_point = None
            self._place_focus_mark()

    # -- selection ---------------------------------------------------------
    def _select_mode(self, on):
        self.view.set_select_mode(on)
        if self.item is not None:
            self.item.setFlag(QGraphicsItem.ItemIsMovable, not on)
            self.item.setCursor(Qt.ArrowCursor if on else Qt.OpenHandCursor)
        self._paint()

    def _boxed(self, rect, add):
        if self.item is None:
            return
        if not add:
            self.selected.clear()
        hit = set()
        for hole in self.item.holes:
            r = hole.mapRectToScene(hole.path().boundingRect())
            if rect.width() == 0 and rect.height() == 0:
                if r.contains(rect.topLeft()):
                    hit.add(hole.index)
            elif rect.intersects(r):
                hit.add(hole.index)
        if add and len(hit) == 1 and hit <= self.selected:
            self.selected -= hit                  # a click on a picked hole drops it
        else:
            self.selected |= hit
        self._paint()

    def select_all(self):
        self.selected = set(range(len(self.art.apertures)))
        self._paint()

    def select_none(self):
        self.selected.clear()
        self._paint()

    def _paint(self, active=None):
        if self.item is None:
            return
        self.item.paint_holes(self.selected, active,
                              dim_unselected=bool(self.selected))
        n = len(self.selected)
        self.sel_lbl.setText(f"{n} hole{'' if n == 1 else 's'} selected" if n else "")
        self.cut_btn.setText(f"Cut {n} selected" if n else "Cut")

    # -- recipe and presets ------------------------------------------------
    def _presets(self):
        cfg = QSettings(*_SETTINGS)
        try:
            saved = json.loads(cfg.value("presets", "{}"))
        except (TypeError, ValueError):
            saved = {}
        out = {k: _recipe_dict(v) for k, v in BUILTIN_PRESETS.items()}
        out.update(saved)
        return out, set(saved)

    def _fill_presets(self, choose):
        names, _ = self._presets()
        self.preset.blockSignals(True)
        self.preset.clear()
        self.preset.addItems(list(names))
        self.preset.blockSignals(False)
        i = self.preset.findText(choose)
        self.preset.setCurrentIndex(max(i, 0))
        self._load_preset(self.preset.currentText())

    def _load_preset(self, name):
        presets, saved = self._presets()
        d = presets.get(name)
        if not d:
            return
        self._syncing_recipe = True
        self.power.setValue(d["power"])
        self.speed.setValue(d["speed"])
        self.freq.setValue(d["frequency"])
        self.passes.setValue(d["total_passes"])
        self.burst.setValue(d["passes_per_burst"])
        self.rest.setValue(d["rest_s"])
        self.zones.setValue(d["zones"])
        self.mark.setChecked(bool(d["mark_passes"]))
        self._syncing_recipe = False
        self.del_btn.setEnabled(name in saved)
        QSettings(*_SETTINGS).setValue("preset", name)
        self._recipe_changed()

    def _recipe_changed(self, *_a):
        if getattr(self, "_syncing_recipe", False):
            return
        r = self.recipe()
        self.recipe_lbl.setText(
            f"{r.rounds} rounds of {r.passes_per_burst} pass"
            f"{'' if r.passes_per_burst == 1 else 'es'} per zone"
            + (f", {r.rest_s:g} s rest after each burst" if r.rest_s else ""))

    def recipe(self):
        return xtool.Recipe(power=self.power.value(), speed=self.speed.value(),
                            frequency=self.freq.value(),
                            total_passes=self.passes.value(),
                            passes_per_burst=self.burst.value(),
                            rest_s=self.rest.value(), zones=self.zones.value(),
                            mark_passes=1 if self.mark.isChecked() else 0)

    def save_preset(self):
        name, ok = QInputDialog.getText(self, "Save recipe", "Name:",
                                        text=self.preset.currentText())
        name = name.strip()
        if not ok or not name:
            return
        if name in BUILTIN_PRESETS:
            return self._say(f"“{name}” is built in; pick another name.", warn=True)
        cfg = QSettings(*_SETTINGS)
        _, saved_names = self._presets()
        try:
            saved = json.loads(cfg.value("presets", "{}"))
        except (TypeError, ValueError):
            saved = {}
        saved[name] = _recipe_dict(self.recipe())
        cfg.setValue("presets", json.dumps(saved))
        self._fill_presets(name)
        self._say(f"Saved “{name}”.")

    def delete_preset(self):
        name = self.preset.currentText()
        cfg = QSettings(*_SETTINGS)
        try:
            saved = json.loads(cfg.value("presets", "{}"))
        except (TypeError, ValueError):
            saved = {}
        if saved.pop(name, None) is not None:
            cfg.setValue("presets", json.dumps(saved))
            self._fill_presets(next(iter(BUILTIN_PRESETS)))
            self._say(f"Deleted “{name}”.")

    # -- what the laser gets ---------------------------------------------
    def _holes(self):
        """The bed paths of the holes to cut, and which aperture each is."""
        _, h = self.art.size
        only = self.selected or None
        paths, owner = [], {}
        for k, poly in enumerate(self.art.apertures):
            if only is not None and k not in only:
                continue
            for ring in (poly.exterior, *poly.interiors):
                p = xtool.to_bed(list(ring.coords), self.origin(), h)
                paths.append(p)
                owner[id(p)] = k
        return paths, owner

    def paths(self):
        return xtool.stencil_paths(self.art, self.origin(), only=self.selected or None)

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

    def _photo(self):
        from gerber2rml.engine.xtool_camera import decode_jpeg
        cal = self._calibration()
        self.laser.lights(True)
        return cal.rectify(decode_jpeg(self.laser.snap()), _PX_PER_MM)

    def take_photo(self):
        def shown(rgb):
            self.show_bed(rgb)
            return "Photo taken."
        self._start(lambda _p: self._photo(), "Taking a photo…", shown)

    def autofocus(self, at=None):
        at = at or self.focus_point()

        def work(_p):
            return self.laser.autofocus(self._calibration(), at)

        def done(z):
            self.thickness.setValue(z - xtool.FOCUS_OFFSET)
            self.focus_note.setText(f"Z {z:.2f} · thickness {z - xtool.FOCUS_OFFSET:.2f} "
                                    f"· measured at X{at[0]:g} Y{at[1]:g}")
            self.laser_lbl.setText(f"Laser: focus Z {z:.2f}")
            self._remember()
            return "In focus. Take a new photo to place the stencil."
        self._start(work, f"Autofocus at X{at[0]:g} Y{at[1]:g}…", done)

    def set_thickness(self):
        t = self.thickness.value()

        def done(z):
            self.focus_note.setText(f"Z {z:.2f} · thickness {t:g} (typed)")
            self.laser_lbl.setText(f"Laser: focus Z {z:.2f}")
            self._remember()
            return "Head moved."
        self._start(lambda _p: self.laser.focus(t), "Moving the head…", done)

    def trace(self):
        try:
            _, outline = xtool.stencil_paths(self.art, self.origin())
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
            holes, owner = self._holes()
            _, outline = xtool.stencil_paths(self.art, self.origin())
            recipe = self.recipe()
            if self.selected:            # a re-cut: the outline is marked already
                from dataclasses import replace
                recipe = replace(recipe, mark_passes=0)
            job = xtool.stencil_job(holes, outline, recipe)
        except ValueError as e:
            return self._say(str(e), warn=True)
        self._remember()
        self._job = job
        self._zone_holes = [{owner[id(p)] for p in z if id(p) in owner}
                            for z in job.zone_paths]
        self.bar.setRange(0, max(1, int(job.seconds)))
        self.bar.setValue(0)
        self.bar.setVisible(True)
        take_photo = self.photo_after.isChecked()

        def work(progress):
            z = self.laser.z()
            self.laser.run(job.text)
            self.laser.wait(job.seconds * 2 + 120, progress=progress)
            return z, (self._photo() if take_photo else None)

        def done(res):
            z, rgb = res
            if rgb is not None:
                self.show_bed(rgb)
            self._paint()
            n = sum(job.zones)
            return (f"Cut at Z {z:.2f}: {n} hole{'' if n == 1 else 's'}, "
                    f"{job.passes} passes. Push out any slugs; select any that "
                    f"did not go through and cut them again.")
        what = f"{len(self.selected)} selected holes" if self.selected else "the stencil"
        self._start(work, f"Cutting {what}, about {job.seconds / 60:.1f} min "
                          f"({len(job.zones)} zones)…", done)

    def stop(self):
        try:
            self.laser.stop()
            self._say("Stopped.")
        except xtool.LaserError as e:
            self._say(str(e), warn=True)

    # -- plumbing ----------------------------------------------------------
    def _progress(self, t):
        self.bar.setValue(int(t))
        job = self._job
        if job is None:
            return
        left = max(job.seconds - t, 0)
        where = job.at(t)
        if where is None:
            text = "resting" if t < job.seconds else "finishing"
            self._paint()
        elif where[0] < 0:
            text = "marking the outline"
            self._paint()
        else:
            zone, rnd = where
            text = f"zone {zone + 1} of {len(job.zones)}, round {rnd + 1}"
            self._paint(active=self._zone_holes[zone])
        self.progress_lbl.setText(f"{text} · about {left:.0f} s left")

    def _start(self, fn, text, done=None):
        self._say(text)
        self._busy(True)
        self._worker = _Worker(fn, self)
        self._worker.progress.connect(self._progress)
        self._worker.finished_ok.connect(
            lambda r: self._done((done(r) if done else None) or "Done.", False))
        self._worker.failed.connect(lambda m: self._done(m, True))
        self._worker.start()

    def _done(self, msg, warn):
        self._busy(False)
        self.bar.setVisible(False)
        self.progress_lbl.setText("")
        self._job = None
        self._paint()
        self._say(msg, warn=warn)

    def _busy(self, on):
        for b in (self.photo_btn, self.focus_btn, self.set_focus_btn,
                  self.trace_btn, self.cut_btn, self.rot_l, self.rot_r,
                  self.select_btn, self.x, self.y):
            b.setEnabled(not on)
        if self.item is not None:
            self.item.setFlag(QGraphicsItem.ItemIsMovable,
                              not on and not self.view.select_mode)

    def _say(self, text, warn=False):
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {theme.CAUTION};" if warn else "")

    def closeEvent(self, e):
        if self._worker is not None and self._worker.isRunning():
            self._say("The laser is still running: press Stop first.", warn=True)
            e.ignore()
            return
        super().closeEvent(e)
