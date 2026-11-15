"""The laser page: the bed as the F1 Ultra's camera sees it, the stencil on it,
and everything needed to place, focus and cut it. What XCS's canvas does for a
stencil, without XCS.

It is built like the main window, from the same parts: a header with the view
controls and the link chip, the stage in the middle, an inspector of eyebrow
sections on the right, and a bar along the bottom with the readouts, the run
buttons and STOP. Colour on the stage follows ``theme``'s roles: the holes are
PATH (metal comes off here), the zone being cut is TOOL, the focus point is
PROBE (the surface gets measured here), the board edge is OUTLINE.

* **Photo** takes the camera's picture and straightens it with the machine's own
  calibration (``engine/xtool_camera.py``): a millimetre on the stage is a
  millimetre of the laser's coordinates.
* **Move** mode: drag the stencil, nudge it with the arrow keys (Shift x10,
  Ctrl x100), turn it a quarter at a time, right-click to centre it where you
  click. X and Y are its outline's top-left corner.
* **Autofocus** measures under the focus point (on the factory's 10 mm grid, at
  the stencil's middle unless you right-click "Autofocus here").
* **Select** mode picks holes by click or box; **Cut** then cuts only those.
* **Cut** lights the zone being cut, counts the time down, and takes a photo when
  it is done. **STOP** always works.

Every laser call runs on a worker thread; the page only shows what comes back.
"""
import json
from dataclasses import replace

from PySide6.QtCore import QPointF, QRectF, QSettings, Qt, QThread, Signal
from PySide6.QtGui import (QBrush, QColor, QImage, QPainter, QPainterPath, QPen,
                           QPixmap, QPolygonF)
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox,
                               QFrame, QGraphicsItem, QGraphicsPathItem,
                               QGraphicsScene, QGraphicsSimpleTextItem,
                               QGraphicsView, QHBoxLayout, QInputDialog, QLabel,
                               QMenu, QProgressBar, QScrollArea, QSpinBox,
                               QVBoxLayout, QWidget)

from gerber2rml.engine import xtool
from gerber2rml.gui2 import theme, widgets

_SETTINGS = ("SRM-CAM", "stencil-laser")
_PX_PER_MM = 4
_FIELD = 220.0          # mm the camera calibration covers
_INSPECTOR_W = 380

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


def _c(token, a=1.0):
    """A theme colour as a QColor, at ``a`` opacity."""
    c = QColor(token)
    c.setAlphaF(a)
    return c


def _pen(token, width=1.5, a=1.0):
    p = QPen(_c(token, a))
    p.setCosmetic(True)
    p.setWidthF(width)
    return p


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
# The stencil on the stage
# ---------------------------------------------------------------------------

class _Hole(QGraphicsPathItem):
    def __init__(self, index, path, parent):
        super().__init__(path, parent)
        self.index = index
        self.setAcceptHoverEvents(True)
        r = path.boundingRect()
        self.setToolTip(f"Hole {index + 1} · {r.width():.2f} × {r.height():.2f} mm")


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
        self.setPen(_pen(theme.OUTLINE, 2.2))
        self.setBrush(QBrush(_c(theme.INK, 0.62)))
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

    def paint_holes(self, selected, active=None, look="filled"):
        """``look``: "filled" (the stencil as it will be), "outlines" (thin
        lines only, so the photo shows through every hole), "hidden"."""
        self.setVisible(look != "hidden")
        self.setBrush(QBrush(_c(theme.INK, 0.62 if look == "filled" else 0.0)))
        if look == "outlines":
            for hole in self.holes:
                if active is not None and hole.index in active:
                    edge, w = _c(theme.TOOL), 2.0
                elif hole.index in selected:
                    edge, w = _c(theme.PATH_FAR), 2.0
                else:
                    edge, w = _c(theme.PATH, 0.95), 1.2
                hole.setBrush(QBrush(Qt.NoBrush))
                pen = QPen(edge)
                pen.setCosmetic(True)
                pen.setWidthF(w)
                hole.setPen(pen)
            return
        dim = bool(selected) or active is not None
        for hole in self.holes:
            if active is not None and hole.index in active:
                fill, edge = _c(theme.TOOL), _c(theme.TOOL)
            elif hole.index in selected:
                fill, edge = _c(theme.PATH_FAR, 0.85), _c(theme.PATH_FAR)
            elif dim:
                fill, edge = _c(theme.GHOST, 0.9), _c(theme.OUTLINE, 0.7)
            else:
                fill, edge = _c(theme.PATH), _c(theme.PATH)
            hole.setBrush(QBrush(fill))
            pen = QPen(edge)
            pen.setCosmetic(True)
            pen.setWidthF(1.0)
            hole.setPen(pen)

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
        self.setBackgroundBrush(QColor(theme.INK))
        self.setFrameShape(QFrame.NoFrame)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._fitted = True
        self.select_mode = False
        self.rubberBandChanged.connect(self._band)
        self._last_band = QRectF()
        self._pan = None

    def fit(self):
        self._fitted = True
        self.resetTransform()
        self.fitInView(QRectF(-16, -16, _FIELD + 26, _FIELD + 26), Qt.KeepAspectRatio)

    def zoom(self, f):
        self._fitted = False
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.scale(f, f)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._fitted:
            self.fit()

    def wheelEvent(self, e):
        self.zoom(1.2 if e.angleDelta().y() > 0 else 1 / 1.2)

    def mouseDoubleClickEvent(self, e):
        self.fit()

    def mousePressEvent(self, e):
        if e.button() == Qt.MiddleButton:     # middle drag pans
            self._pan = e.position()
            self.setCursor(Qt.ClosedHandCursor)
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._pan is not None:
            d = e.position() - self._pan
            self._pan = e.position()
            self._fitted = False
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - d.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - d.y())
            return
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
        if e.key() == Qt.Key_H:
            e.ignore()                  # the page's: show or hide the stencil
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
        if self._pan is not None and e.button() == Qt.MiddleButton:
            self._pan = None
            self.unsetCursor()
            return
        band = self._last_band
        self._last_band = QRectF()
        super().mouseReleaseEvent(e)
        if self.select_mode and e.button() == Qt.LeftButton:
            add = bool(e.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier))
            if band.width() > 0.3 or band.height() > 0.3:
                self.boxed.emit(band, add)
            else:
                p = self.mapToScene(e.position().toPoint())
                self.boxed.emit(QRectF(p, p), add)


# ---------------------------------------------------------------------------
# Small parts
# ---------------------------------------------------------------------------

def _spin(value, lo, hi, step, decimals=2, suffix=""):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setSingleStep(step)
    s.setValue(value)
    s.setKeyboardTracking(False)
    if suffix:
        s.setSuffix(suffix)
    return s


def _ispin(value, lo, hi):
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setValue(value)
    return s


def _row(*items, gap=None):
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(theme.GAP_S if gap is None else gap)
    for it in items:
        if it is None:
            h.addStretch(1)
        elif isinstance(it, tuple):
            h.addWidget(it[0], it[1])
        else:
            h.addWidget(it)
    return w


class _Legend(QFrame):
    """The stage's key, in its corner, as the main stage has one."""

    def __init__(self, entries, parent=None):
        super().__init__(parent)
        self.setObjectName("cardQuiet")
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 12, 8)
        v.setSpacing(3)
        for token, text in entries:
            sw = QLabel()
            sw.setFixedSize(12, 3)
            sw.setStyleSheet(f"background: {token}; border-radius: 1px;")
            t = widgets.micro(text)
            t.setStyleSheet(f"color: {theme.TEXT_3}; background: transparent;")
            r = _row(sw, t, None, gap=7)
            r.setObjectName("legendRow")
            r.setStyleSheet("QWidget#legendRow { background: transparent; }")
            v.addWidget(r)


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------

class StencilLaserDialog(QDialog):
    """``art`` is a :class:`gerber2rml.engine.stencil.StencilArtwork`."""

    def __init__(self, art, parent=None, laser=None, name="stencil"):
        super().__init__(parent)
        self.base_art = art
        self.turns = 0
        self.fine = 0.0                     # degrees on top of the quarter turns
        self.look = "filled"
        self.art = art
        self.laser = laser or xtool.F1Ultra()
        self._cal = None
        self._worker = None
        self._syncing = False
        self._syncing_recipe = False
        self.selected = set()
        self._job = None
        self._zone_holes = []
        self._focus_point = None            # None: follow the stencil's middle
        self._bed_rgb = None
        self.setWindowTitle("xTool F1 Ultra — solder paste stencil")
        self.resize(1400, 900)
        self.setStyleSheet(f"QDialog {{ background: {theme.BASE}; }}")
        cfg = QSettings(*_SETTINGS)
        # The camera's own error, learned from a real cut; see engine rectify().
        self.cam_offset = (float(cfg.value("camera_offset_x", 0.0)),
                           float(cfg.value("camera_offset_y", 0.0)))

        # -- the stage ---------------------------------------------------
        self.scene = QGraphicsScene(-18, -18, _FIELD + 30, _FIELD + 30)
        self._bg = self.scene.addPixmap(self._grid_pixmap())
        self._bg.setScale(1 / _PX_PER_MM)
        self._bg.setZValue(-10)
        edge = self.scene.addRect(QRectF(0, 0, _FIELD, _FIELD), _pen(theme.BED_EDGE, 1))
        edge.setZValue(-9)
        self._add_rulers()
        self._focus_mark = self._make_focus_mark()
        self.item = None
        self.view = _BedView(self.scene)
        self.view.moved.connect(self._cursor)
        self.view.nudge.connect(self._nudge)
        self.view.context.connect(self._context)
        self.view.boxed.connect(self._boxed)
        self.legend = _Legend([(theme.PATH, "paste hole"),
                               (theme.PATH_FAR, "selected"),
                               (theme.TOOL, "cutting now"),
                               (theme.PROBE, "focus point"),
                               (theme.OUTLINE, "board edge")], self.view)

        # -- header --------------------------------------------------------
        header = QFrame()
        header.setObjectName("header")
        header.setStyleSheet(f"QFrame#header {{ background: {theme.PANEL};"
                             f" border-bottom: 1px solid {theme.RULE}; }}")
        hh = QHBoxLayout(header)
        hh.setContentsMargins(theme.GAP_M, theme.GAP_S, theme.GAP_M, theme.GAP_S)
        hh.setSpacing(theme.GAP_S)
        brand = QLabel("XTOOL F1 ULTRA")
        brand.setFont(theme.font("label"))
        brand.setStyleSheet(f"color: {theme.TEXT_3};")
        self.mode = widgets.Segmented([
            ("move", "Move", "Drag, nudge with the arrow keys, turn"),
            ("select", "Select holes", "Click holes or drag a box; Ctrl or Shift "
                                       "adds. Cut then cuts only those.")], "move")
        self.mode.changed.connect(lambda k: self._select_mode(k == "select"))
        self.photo_btn = widgets.button("Photo", on=self.take_photo,
                                        tip="Take a picture of the bed")
        self.focus_btn = widgets.button(
            "Autofocus", on=lambda: self.autofocus(),
            tip="Measure the height under the focus point with the blue dot "
                "and move the head")
        self.align_btn = widgets.button(
            "Align", on=self.align,
            tip="Photo, then find the holes already cut and put the stencil "
                "back on them: after the foil or board has been moved")
        self.rot_l = widgets.button("Turn left", on=lambda: self.rotate(-1),
                                    tip="A quarter turn anticlockwise")
        self.rot_r = widgets.button("Turn right", on=lambda: self.rotate(1),
                                    tip="A quarter turn clockwise")
        self.all_btn = widgets.button("All", kind="ghost", on=self.select_all)
        self.none_btn = widgets.button("None", kind="ghost", on=self.select_none)
        fit = widgets.button("Fit", on=self.view.fit, tip="Show the whole bed")
        self.look_switch = widgets.Segmented([
            ("filled", "Filled", "The stencil as it will be cut"),
            ("outlines", "Outlines", "Thin outlines only: see the photo through "
                                     "every hole, to spot pads that need more"),
            ("hidden", "Hidden", "Only the photo (H)")], "filled")
        self.look_switch.changed.connect(self.set_look)
        self.link = widgets.Chip("Laser not asked yet", "idle")
        for w in (brand, widgets.vrule(), self.photo_btn, self.focus_btn,
                  self.align_btn,
                  widgets.vrule(), self.mode, self.all_btn, self.none_btn,
                  widgets.vrule(), self.rot_l, self.rot_r, fit,
                  widgets.vrule(), self.look_switch):
            hh.addWidget(w)
        hh.addStretch(1)
        hh.addWidget(self.link)

        # -- inspector -----------------------------------------------------
        panel = QWidget()
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(theme.GAP_L, theme.GAP_M, theme.GAP_L, theme.GAP_L)
        pv.setSpacing(theme.GAP_L)

        head = QWidget()
        hv = QVBoxLayout(head)
        hv.setContentsMargins(0, 0, 0, 0)
        hv.setSpacing(2)
        hv.addWidget(widgets.eyebrow("Step"))
        t = QLabel("Cut the stencil")
        t.setFont(theme.font("sub"))
        hv.addWidget(t)
        pv.addWidget(head)

        s = widgets.Section("The stencil")
        self.name_lbl = QLabel(name)
        self.name_lbl.setFont(theme.font("sub"))
        s.add(self.name_lbl)
        self.size_lbl = widgets.hint("")
        s.add(self.size_lbl)
        for msg in art.warnings():
            n = widgets.hint(msg)
            n.setStyleSheet(f"color: {theme.CAUTION};")
            s.add(n)
        self.x = _spin(float(cfg.value("x", 60.0)), -50, _FIELD, 0.1, suffix=" mm")
        self.y = _spin(float(cfg.value("y", 60.0)), -50, _FIELD, 0.1, suffix=" mm")
        self.x.valueChanged.connect(self._typed)
        self.y.valueChanged.connect(self._typed)
        s.add(widgets.Field("X", self.x))
        s.add(widgets.Field("Y", self.y, help="The outline's top-left corner, in "
                                              "the laser's mm. Drag it, use the "
                                              "arrow keys, or right-click the bed."))
        pv.addWidget(s)

        s = widgets.Section("Focus")
        self.z_read = widgets.Readout("Head Z", "—")
        self.t_read = widgets.Readout("Thickness", "—")
        s.add(_row(self.z_read, self.t_read, None, gap=theme.GAP_L))
        self.focus_note = widgets.hint("Autofocus measures at the cross: the "
                                       "stencil's middle, on the factory's 10 mm "
                                       "grid. Right-click the bed to measure "
                                       "somewhere else.")
        s.add(self.focus_note)
        self.thickness = _spin(float(cfg.value("thickness", 4.1)), 0, 137, 0.1,
                               suffix=" mm")
        self.set_focus_btn = widgets.button("Set", on=self.set_thickness,
                                            tip="Move the head to this thickness + 8 mm, "
                                                "as XCS does")
        s.add(_row((widgets.Field("By hand", self.thickness), 1), self.set_focus_btn))
        pv.addWidget(s)

        s = widgets.Section("Camera")
        self.off_x = widgets.Readout("Photo offset X", "")
        self.off_y = widgets.Readout("Photo offset Y", "")
        s.add(_row(self.off_x, self.off_y, None, gap=theme.GAP_L))
        s.add(widgets.hint(
            "The photo is moved by this much so it lands on what the fiber really "
            "cuts. Right after a cut, with the stencil still where it was cut, "
            "press Learn: it finds the holes in a photo and measures the "
            "difference."))
        self.learn_btn = widgets.button("Learn from this cut", on=self.learn_offset)
        self.reset_off_btn = widgets.button("Reset", kind="ghost",
                                            on=self.reset_offset)
        s.add(_row(self.learn_btn, self.reset_off_btn, None))
        pv.addWidget(s)
        self._show_offset()

        s = widgets.Section("Recipe")
        self.preset = QComboBox()
        self.preset.currentTextChanged.connect(self._load_preset)
        s.add(self.preset)
        self.recipe_lbl = widgets.hint("")
        s.add(self.recipe_lbl)
        # The numbers live under a fold: pick a preset and cut; open it only
        # to tweak one, and save the tweak as a preset of its own.
        self.recipe_more = widgets.Disclosure("Adjust the numbers", key="stencil-recipe")
        r = xtool.DEFAULT_RECIPE
        self.power = _spin(r.power, 1, 100, 1, 0)
        self.speed = _spin(r.speed, 10, 5000, 10, 0)
        self.freq = _spin(r.frequency, 1, 60, 1, 0)
        self.passes = _ispin(r.total_passes, 1, 300)
        self.burst = _ispin(r.passes_per_burst, 1, 50)
        self.rest = _spin(r.rest_s, 0, 120, 1, 0)
        self.zones = _ispin(r.zones, 1, 12)
        self.mark = QCheckBox("Mark the board outline afterwards")
        self.mark.setChecked(True)
        for label, wdg, unit in (("Power", self.power, "%"),
                                 ("Speed", self.speed, "mm/s"),
                                 ("Frequency", self.freq, "kHz"),
                                 ("Passes", self.passes, "per hole"),
                                 ("Per burst", self.burst, "passes"),
                                 ("Rest", self.rest, "s"),
                                 ("Zones", self.zones, "")):
            self.recipe_more.body.addWidget(widgets.Field(label, wdg, unit=unit))
            wdg.valueChanged.connect(self._recipe_changed)
        self.recipe_more.body.addWidget(self.mark)
        self.mark.toggled.connect(self._recipe_changed)
        self.save_btn = widgets.button("Save as preset…", on=self.save_preset)
        self.del_btn = widgets.button("Delete preset", kind="ghost",
                                      on=self.delete_preset)
        self.recipe_more.body.addWidget(_row(None, self.save_btn, self.del_btn))
        s.add(self.recipe_more)
        pv.addWidget(s)
        pv.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(panel)
        scroll.setFixedWidth(_INSPECTOR_W)
        scroll.setObjectName("inspector")
        scroll.setStyleSheet(f"QScrollArea#inspector {{ background: {theme.PANEL};"
                             f" border-left: 1px solid {theme.RULE}; }}")
        panel.setStyleSheet(f"background: {theme.PANEL};")

        # -- the bar along the bottom ----------------------------------------
        foot = QFrame()
        foot.setObjectName("foot")
        foot.setStyleSheet(f"QFrame#foot {{ background: {theme.PANEL};"
                           f" border-top: 1px solid {theme.RULE}; }}")
        fh = QHBoxLayout(foot)
        fh.setContentsMargins(theme.GAP_M, theme.GAP_S + 2, theme.GAP_M, theme.GAP_S + 2)
        fh.setSpacing(theme.GAP_L)
        self.cursor_read = widgets.Readout("Cursor", "—", width=170)
        self.sel_read = widgets.Readout("Holes", "—", width=110)
        self.time_read = widgets.Readout("Estimate", "—", width=110)
        mid = QWidget()
        mid.setStyleSheet("background: transparent;")
        mv = QVBoxLayout(mid)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.setSpacing(4)
        self.status = QLabel("")
        self.status.setFont(theme.font("small"))
        self.status.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(4)
        self.bar.setVisible(False)
        mv.addWidget(self.status)
        mv.addWidget(self.bar)
        self.photo_after = QCheckBox("Photo when done")
        self.photo_after.setChecked(True)
        self.trace_btn = widgets.button(
            "Show where", on=self.trace,
            tip="The blue diode round the outline, faint enough not to mark steel")
        self.cut_btn = widgets.button("Cut", kind="primary", on=self.cut)
        self.cut_btn.setMinimumWidth(170)
        self.stop_btn = widgets.button("STOP", kind="stop", on=self.stop)
        self.stop_btn.setMinimumWidth(112)
        for w in (self.cursor_read, self.sel_read, self.time_read, widgets.vrule()):
            fh.addWidget(w)
        fh.addWidget(mid, 1)
        for w in (self.photo_after, self.trace_btn, self.cut_btn, self.stop_btn):
            fh.addWidget(w)

        # -- assemble --------------------------------------------------------
        middle = QHBoxLayout()
        middle.setContentsMargins(0, 0, 0, 0)
        middle.setSpacing(0)
        middle.addWidget(self.view, 1)
        middle.addWidget(scroll)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(header)
        outer.addLayout(middle, 1)
        outer.addWidget(foot)

        # A dialog makes its first button the default and rings it; nothing on
        # this page should fire on Enter.
        from PySide6.QtWidgets import QPushButton
        for b in self.findChildren(QPushButton):
            b.setAutoDefault(False)
            b.setDefault(False)
        self._fill_presets(cfg.value("preset", next(iter(BUILTIN_PRESETS))))
        self._build_item()
        self._busy(False)

    # -- the bed picture -------------------------------------------------
    @staticmethod
    def _grid_pixmap():
        n = int(_FIELD * _PX_PER_MM)
        img = QImage(n, n, QImage.Format_RGB888)
        img.fill(QColor(theme.BED))
        pm = QPixmap.fromImage(img)
        p = QPainter(pm)
        for k in range(0, int(_FIELD) + 1, 10):
            p.setPen(QPen(QColor(theme.GRID_10 if k % 50 == 0 else theme.GRID), 1))
            p.drawLine(k * _PX_PER_MM, 0, k * _PX_PER_MM, n)
            p.drawLine(0, k * _PX_PER_MM, n, k * _PX_PER_MM)
        p.end()
        return pm

    def _add_rulers(self):
        pen = _pen(theme.TEXT_4, 1)
        font = theme.font("micro", mono=True)
        for k in range(0, int(_FIELD) + 1, 10):
            t = 3.5 if k % 50 == 0 else 2
            self.scene.addLine(k, -t, k, 0, pen)
            self.scene.addLine(-t, k, 0, k, pen)
            if k % 20 == 0:
                for x, y in ((k - 2, -11), (-14, k - 2)):
                    lbl = QGraphicsSimpleTextItem(str(k))
                    lbl.setFont(font)
                    lbl.setBrush(QColor(theme.TEXT_3))
                    lbl.setFlag(QGraphicsItem.ItemIgnoresTransformations)
                    lbl.setPos(x, y)
                    self.scene.addItem(lbl)

    def _make_focus_mark(self):
        p = QPainterPath()
        p.moveTo(-3.5, 0)
        p.lineTo(-1.2, 0)
        p.moveTo(1.2, 0)
        p.lineTo(3.5, 0)
        p.moveTo(0, -3.5)
        p.lineTo(0, -1.2)
        p.moveTo(0, 1.2)
        p.lineTo(0, 3.5)
        p.addEllipse(QPointF(0, 0), 2.0, 2.0)
        halo = self.scene.addPath(p, _pen(theme.INK, 5.0, 0.7))
        item = self.scene.addPath(p, _pen(theme.PROBE, 2.4))
        halo.setParentItem(item)
        halo.setPos(0, 0)
        halo.setFlag(QGraphicsItem.ItemStacksBehindParent)
        item.setZValue(20)
        item.setToolTip("Autofocus measures here (the factory's 10 mm grid)")
        return item

    def show_bed(self, rgb):
        self._bed_rgb = rgb
        h, w = rgb.shape[:2]
        img = QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888).copy()
        self._bg.setPixmap(QPixmap.fromImage(img))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_legend()

    def showEvent(self, e):
        super().showEvent(e)
        self._place_legend()
        self.view.setFocus()            # the arrow keys move the stencil at once

    def _place_legend(self):
        self.legend.adjustSize()
        vw, vh = self.view.width(), self.view.height()
        self.legend.move(vw - self.legend.width() - 14, vh - self.legend.height() - 14)

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
        angle = (90 * self.turns + self.fine) % 360
        turned = f" · turned {angle:.1f}°".replace(".0°", "°") if abs(angle) > 1e-6 else ""
        self.size_lbl.setText(
            f"{len(self.art.apertures)} holes · {w:.1f} × {h:.1f} mm · "
            f"{'mirrored' if self.art.mirrored else 'not mirrored'} · kerf "
            f"{self.art.kerf:g} mm{turned}")
        self._paint()
        self._place_focus_mark()

    def rotate(self, step):
        self._turn_to(self.turns + step, self.fine)

    def _turn_to(self, turns, fine):
        """Turn the stencil about its middle, keeping the middle where it is."""
        cx, cy = self.centre()
        self.turns = turns % 4
        self.fine = fine
        self.art = xtool.rotated(self.base_art, self.turns, self.fine)
        self.selected.clear()
        w, h = self.art.size
        self._syncing = True
        self.x.setValue(round(cx - w / 2, 3))
        self.y.setValue(round(cy - h / 2, 3))
        self._syncing = False
        self._build_item()

    @staticmethod
    def _middle(paths):
        import numpy as np
        return np.array([q for p in paths for q in p], float).mean(axis=0)

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
        self.cursor_read.set(f"{p.x():6.1f}  {p.y():6.1f}")

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
            self.item.setCursor(Qt.CrossCursor if on else Qt.OpenHandCursor)
        self._paint()

    def _boxed(self, rect, add):
        if self.item is None:
            return
        if not add:
            self.selected.clear()
        hit = set()
        point = rect.width() == 0 and rect.height() == 0
        for hole in self.item.holes:
            r = hole.mapRectToScene(hole.path().boundingRect())
            if (r.adjusted(-0.3, -0.3, 0.3, 0.3).contains(rect.topLeft()) if point
                    else rect.intersects(r)):
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

    def set_look(self, look):
        self.look = look
        self.look_switch.set_current(look)
        self._focus_mark.setVisible(look != "hidden")
        self._paint()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_H and not e.modifiers():
            self.set_look("filled" if self.look == "hidden" else "hidden")
            return
        super().keyPressEvent(e)

    def _paint(self, active=None):
        if self.item is None:
            return
        self.item.paint_holes(self.selected, active, self.look)
        n, total = len(self.selected), len(self.art.apertures)
        self.sel_read.set(f"{n} / {total}" if n else f"{total}")
        self.sel_read.set_label("Selected" if n else "Holes")
        self.cut_btn.setText(f"Cut {n} selected" if n else "Cut the stencil")
        self._estimate()

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
        if self._syncing_recipe:
            return
        r = self.recipe()
        presets, _ = self._presets()
        chosen = presets.get(self.preset.currentText())
        changed = chosen is not None and any(
            float(chosen[f]) != float(getattr(r, f)) for f in _RECIPE_FIELDS
            if f not in ("mark_power",))
        self.recipe_lbl.setText(("Changed from the preset · " if changed else "") +
            f"{r.rounds} round{'' if r.rounds == 1 else 's'} of "
            f"{r.passes_per_burst} pass{'' if r.passes_per_burst == 1 else 'es'} "
            f"per zone" + (f", {r.rest_s:g} s laser-off after each" if r.rest_s else ""))
        self._estimate()

    def _estimate(self):
        if not hasattr(self, "time_read") or self.item is None:
            return
        try:
            holes, _ = self._holes()
            _, outline = xtool.stencil_paths(self.art, (0, 0))
            outline = [[(x + 1, y + 1) for x, y in p] for p in outline]
            holes = [[(x - self.x.value() + 1, y - self.y.value() + 1) for x, y in p]
                     for p in holes]
            secs = xtool.stencil_job(holes, outline, self._run_recipe()).seconds
            self.time_read.set(f"{int(secs // 60)}:{int(secs % 60):02d}")
        except ValueError:
            self.time_read.set("—")

    def recipe(self):
        return xtool.Recipe(power=self.power.value(), speed=self.speed.value(),
                            frequency=self.freq.value(),
                            total_passes=self.passes.value(),
                            passes_per_burst=self.burst.value(),
                            rest_s=self.rest.value(), zones=self.zones.value(),
                            mark_passes=1 if self.mark.isChecked() else 0)

    def _run_recipe(self):
        """A re-cut leaves the outline alone: it is marked already."""
        r = self.recipe()
        return replace(r, mark_passes=0) if self.selected else r

    def save_preset(self):
        name, ok = QInputDialog.getText(self, "Save the recipe", "Name:",
                                        text=self.preset.currentText())
        name = name.strip()
        if not ok or not name:
            return
        if name in BUILTIN_PRESETS:
            return self._say(f"“{name}” is built in; pick another name.", warn=True)
        cfg = QSettings(*_SETTINGS)
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

    def _raw_photo(self):
        from gerber2rml.engine.xtool_camera import decode_jpeg
        self._calibration()
        self.laser.lights(True)
        return decode_jpeg(self.laser.snap())

    def _photo(self, px_per_mm=_PX_PER_MM, raw=None):
        raw = self._raw_photo() if raw is None else raw
        return self._calibration().rectify(raw, px_per_mm, self.cam_offset)

    # -- the camera's offset -------------------------------------------------
    def _show_offset(self):
        ex, ey = self.cam_offset
        self.off_x.set(f"{ex:+.2f} mm")
        self.off_y.set(f"{ey:+.2f} mm")

    def _set_offset(self, off):
        self.cam_offset = (round(float(off[0]), 3), round(float(off[1]), 3))
        cfg = QSettings(*_SETTINGS)
        cfg.setValue("camera_offset_x", self.cam_offset[0])
        cfg.setValue("camera_offset_y", self.cam_offset[1])
        self._show_offset()

    def reset_offset(self):
        self._set_offset((0.0, 0.0))
        self._say("Photo offset reset. Take a new photo to see it.")

    def _residual(self, rgb_hi, hi):
        """Where the holes of the stencil, as placed now, show up in a photo:
        the alignment over a small search, or None if they cannot be found."""
        from gerber2rml.engine import xtool_camera as cam
        holes, _ = xtool.stencil_paths(self.art, self.origin())
        a = cam.align(rgb_hi, hi, holes, search_mm=4.0, max_turn=1.5)
        # In steel a clean hole shows the bright plate under it, so not every
        # hole reads dark: half of them is plenty to measure a small offset
        # with the stencil already in place.
        return a if a.found >= max(5, 0.5 * a.total) and a.score > 0.15 else None

    def learn_offset(self):
        """The stencil is where it was cut: whatever offset the photo shows
        between the overlay and the real holes is the camera's error."""
        hi = 8

        def work(_p):
            raw = self._raw_photo()
            a = self._residual(self._photo(hi, raw), hi)
            return raw, a

        def done(res):
            raw, a = res
            if a is None:
                self.show_bed(self._photo(_PX_PER_MM, raw))
                return ("Could not find the cut holes under the stencil. Leave it "
                        "where it was cut, take a photo to check, and try again.")
            self._set_offset((self.cam_offset[0] + a.dx, self.cam_offset[1] + a.dy))
            self.show_bed(self._photo(_PX_PER_MM, raw))
            return (f"Learned from {a.found} holes: the photo was {a.dx:+.2f}, "
                    f"{a.dy:+.2f} mm off. Photos now land on the cut.")
        self._start(work, "Learning the camera's offset from the cut…", done)

    def align(self):
        """Find the holes already cut and put the stencil back on them. Tries the
        stencil as it is, then the other three quarter turns, in case the board
        went back the other way round."""
        from gerber2rml.engine import xtool_camera as cam
        cx, cy = self.centre()
        candidates = []
        for k in range(4):
            art = xtool.rotated(self.base_art, self.turns + k, self.fine)
            w, h = art.size
            holes, _ = xtool.stencil_paths(art, (cx - w / 2, cy - h / 2))
            candidates.append((k, holes))
        hi = 8

        def work(_p):
            rgb = self._photo(hi)
            tried = []
            for k, holes in candidates:
                a = cam.align(rgb, hi, holes)
                tried.append((k, holes, a))
                if a.ok and k == 0:
                    break
            good = [t for t in tried if t[2].ok]
            pick = max(good or tried, key=lambda t: t[2].found / max(t[2].total, 1))
            return rgb, pick, bool(good)

        def done(res):
            rgb, (k, holes, a), good = res
            self.show_bed(rgb[::hi // _PX_PER_MM, ::hi // _PX_PER_MM].copy())
            if not good:
                return (f"Could not find the holes: at best {a.found} of {a.total}. "
                        f"Drag the stencil close to them and try again.")
            target = self._middle(holes) + (a.dx, a.dy)
            self._turn_to(self.turns + k, self.fine + a.turn)
            now, _ = xtool.stencil_paths(self.art, self.origin())
            dx, dy = target - self._middle(now)
            self.x.setValue(round(self.x.value() + dx, 3))
            self.y.setValue(round(self.y.value() + dy, 3))
            moved = (a.dx ** 2 + a.dy ** 2) ** 0.5
            turned = (90 * k + a.turn + 180) % 360 - 180
            return (f"Aligned on {a.found} of {a.total} holes: moved {moved:.1f} mm, "
                    f"turned {turned:+.1f}°. Check with Show where before cutting.")
        self._start(work, "Aligning: photo, then looking for the holes…", done)

    def _focused(self, z, how):
        self.z_read.set(f"{z:.2f}")
        self.t_read.set(f"{z - xtool.FOCUS_OFFSET:.2f}")
        self.link.set(f"Laser · focus Z {z:.2f}", "live")
        self.focus_note.setText(how)

    def take_photo(self):
        def shown(rgb):
            self.show_bed(rgb)
            self.link.set("Laser connected", "live")
            return "Photo taken."
        self._start(lambda _p: self._photo(), "Taking a photo…", shown)

    def autofocus(self, at=None):
        at = at or self.focus_point()

        def work(_p):
            return self.laser.autofocus(self._calibration(), at)

        def done(z):
            self.thickness.setValue(z - xtool.FOCUS_OFFSET)
            self._focused(z, f"Measured at X{at[0]:g} Y{at[1]:g} with the blue dot.")
            self._remember()
            return "In focus. Take a new photo to place the stencil."
        self._start(work, f"Autofocus at X{at[0]:g} Y{at[1]:g}…", done)

    def set_thickness(self):
        t = self.thickness.value()

        def done(z):
            self._focused(z, f"Set by hand to thickness {t:g}.")
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
                    lambda _r: "Traced. Move the stencil if it was off.")

    def cut(self):
        try:
            holes, owner = self._holes()
            _, outline = xtool.stencil_paths(self.art, self.origin())
            job = xtool.stencil_job(holes, outline, self._run_recipe())
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
            if not take_photo:
                return z, None, None
            raw = self._raw_photo()
            try:
                a = self._residual(self._photo(8, raw), 8)
            except Exception:           # noqa: BLE001 - a check, never a failure
                a = None
            return z, self._photo(_PX_PER_MM, raw), a

        def done(res):
            z, rgb, a = res
            if rgb is not None:
                self.show_bed(rgb)
            n = sum(job.zones)
            msg = (f"Cut at Z {z:.2f}: {n} hole{'' if n == 1 else 's'}, "
                   f"{job.passes} passes. Push out any slugs; select the ones "
                   f"that did not go through and cut them again.")
            if a is not None and (a.dx ** 2 + a.dy ** 2) ** 0.5 > 0.3:
                msg += (f" The photo shows the holes {a.dx:+.2f}, {a.dy:+.2f} mm "
                        f"from where they were cut: press Learn from this cut.")
            return msg
        what = f"{len(self.selected)} selected holes" if self.selected else "the stencil"
        self._start(work, f"Cutting {what} in {len(job.zones)} zones…", done)

    def stop(self):
        try:
            self.laser.stop()
            self._say("Stopped.", warn=True)
        except xtool.LaserError as e:
            self._say(str(e), warn=True)

    # -- plumbing ----------------------------------------------------------
    def _progress(self, t):
        self.bar.setValue(int(t))
        job = self._job
        if job is None:
            return
        left = max(job.seconds - t, 0)
        self.time_read.set(f"{int(left // 60)}:{int(left % 60):02d}")
        self.time_read.set_label("Left")
        where = job.at(t)
        if where is None:
            text = "Resting, laser off" if t < job.seconds else "Finishing"
            self._paint_active(None)
        elif where[0] < 0:
            text = "Marking the outline"
            self._paint_active(None)
        else:
            zone, rnd = where
            rounds = 1 + max((r for _a, _b, z, r in job.timeline if z >= 0), default=0)
            text = f"Zone {zone + 1} of {len(job.zones)} · round {rnd + 1} of {rounds}"
            self._paint_active(self._zone_holes[zone])
        self.status.setText(text)

    def _paint_active(self, active):
        if self.item is not None:
            self.item.paint_holes(self.selected, active, self.look)

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
        self._job = None
        self.time_read.set_label("Estimate")
        if warn:
            self.link.set("Laser: no answer" if "answer" in msg else "Laser", "fail"
                          if "answer" in msg else "warn")
        self._paint()
        self._say(msg, warn=warn)

    def _busy(self, on):
        for b in (self.photo_btn, self.focus_btn, self.align_btn, self.set_focus_btn,
                  self.learn_btn, self.reset_off_btn,
                  self.trace_btn, self.cut_btn, self.rot_l, self.rot_r,
                  self.mode, self.all_btn, self.none_btn, self.x, self.y,
                  self.preset, self.save_btn):
            b.setEnabled(not on)
        if self.item is not None:
            self.item.setFlag(QGraphicsItem.ItemIsMovable,
                              not on and not self.view.select_mode)

    def _say(self, text, warn=False):
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {theme.CAUTION if warn else theme.TEXT_2};")

    def closeEvent(self, e):
        if self._worker is not None and self._worker.isRunning():
            self._say("The laser is still running: press STOP first.", warn=True)
            e.ignore()
            return
        super().closeEvent(e)
