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
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSettings, Qt, QThread, Signal
from PySide6.QtGui import (QBrush, QColor, QImage, QPainter, QPainterPath, QPen,
                           QPixmap, QPolygonF)
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox,
                               QFrame, QGraphicsItem, QGraphicsPathItem,
                               QGraphicsScene, QGraphicsSimpleTextItem,
                               QGraphicsView, QHBoxLayout, QInputDialog, QLabel,
                               QListWidget, QListWidgetItem, QMenu, QProgressBar, QPushButton, QScrollArea,
                               QSizePolicy, QSpinBox, QVBoxLayout, QWidget)

from gerber2rml.engine import xtool
from gerber2rml.gui2 import theme, widgets

_SETTINGS = ("SRM-CAM", "stencil-laser")
_PX_PER_MM = 8
_FIELD = 220.0          # mm the camera calibration covers
_INSPECTOR_W = 380

BUILTIN_PRESETS = {
    "0.1 mm 304 stainless": xtool.DEFAULT_RECIPE,
    "Marking test (1 pass)": xtool.Recipe(power=30, total_passes=1,
                                          passes_per_burst=1, rest_s=0, zones=1,
                                          mark_passes=0),
}
# Filled jobs: the sphawes/fiber-laser-pcb-fab settings the lab imports into XCS.
FILL_PRESETS = {
    "RemoveSolderMask (sphawes)": xtool.SPHAWES_REMOVE_MASK,
    "Traces (sphawes)": xtool.SPHAWES_TRACES,
}
# Copper trace presets: FlatCAM-style concentric isolation + optional moat / rubout.
TRACES_PRESETS = {
    "FR4 1.6 mm · proven (100 %, 1000 mm/s × 20)": xtool.FR4_TRACES_RECIPE,
    "FlatCAM isolation (concentric; uncalibrated)": xtool.DEFAULT_TRACES_RECIPE,
    "Wide isolation (concentric; uncalibrated)": xtool.WIDE_TRACES_RECIPE,
    "Moat hatch (uncalibrated)": xtool.MOAT_HATCH_RECIPE,
    "Full rubout (XCS reference; uncalibrated)": xtool.RUBOUT_TRACES_RECIPE,
}

# What changes with the job. Everything else on the page is the same.
KINDS = {
    "calibration": dict(window="copper calibration", step="Calibrate native copper vectors",
                        section="The calibration coupon", noun="cell",
                        run="Run one calibration pass", run_selected="Run one calibration pass",
                        busy="Calibrating", presets={"Exploratory single pass — not a production recipe":
                            xtool.FillRecipe(power=10, speed=2000, frequency=30, passes=1,
                                             mark_outline=False)}),
    "traces": dict(window="copper traces", step="Etch the copper traces",
                   section="The copper traces", noun="trench", nouns="trenches",
                   run="Etch the traces", run_selected="Etch {n} selected",
                   busy="Etching the traces", presets=TRACES_PRESETS),
    "stencil": dict(window="solder paste stencil", step="Cut the stencil",
                    section="The stencil", noun="hole", run="Cut the stencil",
                    run_selected="Cut {n} selected", busy="Cutting",
                    presets=BUILTIN_PRESETS),
    "mask": dict(window="solder mask", step="Open the solder mask",
                 section="The solder mask", noun="opening", run="Open the mask",
                 run_selected="Open {n} selected", busy="Opening the mask",
                 presets=FILL_PRESETS),
    "silk": dict(window="silkscreen", step="Mark the silkscreen",
                 section="The silkscreen", noun="shape", run="Mark the silkscreen",
                 run_selected="Mark {n} selected", busy="Marking the silkscreen",
                 presets=FILL_PRESETS),
}
_LEGEND_NOUN = {"traces": "isolation trench", "stencil": "paste hole",
                "mask": "mask opening", "silk": "silkscreen", "calibration": "test vectors"}


def _recipe_dict(r):
    from dataclasses import fields
    return {f.name: getattr(r, f.name) for f in fields(r)}


def as_laser_art(art):
    """A stencil's artwork as the page's :class:`xtool.LaserArt`; anything
    already one passes through."""
    if isinstance(art, xtool.LaserArt):
        return art
    return xtool.LaserArt(kind="stencil", apertures=art.apertures,
                          outline=art.outline, mirrored=art.mirrored,
                          kerf=art.kerf, notes=art.warnings(),
                          note=f"kerf {art.kerf:g} mm")


def _brightness(rgb):
    """Mean brightness of a photo, from a sparse sample (it is 16 Mpx)."""
    import numpy as np
    return float(np.asarray(rgb)[::16, ::16].mean())


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
    reference_clicked = Signal(QPointF)

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
        self.pick_reference = False

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
        if self.pick_reference and e.button() == Qt.LeftButton:
            self.reference_clicked.emit(self.mapToScene(e.position().toPoint()))
            e.accept()
            return
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
        if self.pick_reference and e.button() == Qt.LeftButton:
            e.accept()
            return
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


class _Into:
    """A layout that takes rows the way a Section does."""

    def __init__(self, layout):
        self.add = layout.addWidget


class _Legend(QFrame):
    """The stage's key, in its corner, as the main stage has one."""

    def __init__(self, entries, parent=None):
        super().__init__(parent)
        self.setObjectName("cardQuiet")
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 12, 8)
        v.setSpacing(3)
        self.first_label = None
        for idx, (token, text) in enumerate(entries):
            sw = QLabel()
            sw.setFixedSize(12, 3)
            sw.setStyleSheet(f"background: {token}; border-radius: 1px;")
            t = widgets.micro(text)
            t.setStyleSheet(f"color: {theme.TEXT_3}; background: transparent;")
            if idx == 0:
                self.first_label = t
            r = _row(sw, t, None, gap=7)
            r.setObjectName("legendRow")
            r.setStyleSheet("QWidget#legendRow { background: transparent; }")
            v.addWidget(r)


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------

class StencilLaserDialog(QDialog):
    """``art`` is a :class:`gerber2rml.engine.stencil.StencilArtwork` or an
    :class:`xtool.LaserArt` (traces, solder mask, silkscreen, or stencil)."""

    def __init__(self, art=None, parent=None, laser=None, name="stencil",
                 jobs=None, dxf=None):
        super().__init__(parent)
        self._empty = art is None           # nothing loaded: a calibration area
        if art is None:
            art = xtool.calibration_art()
            name = "No job loaded"
        art = as_laser_art(art)
        self._dxf = Path(dxf) if dxf else None    # traces come from this DXF
        self._dxf_mirror = None             # None: as the copper face has it
        self._dxf_flip = False
        self._mode = "move"
        self.rework_boxes = []              # (x0, y0, x1, y1), bed mm
        self._rework_items = []
        self.kind = art.kind
        self.k = KINDS[self.kind]
        self._jobs = jobs
        self.base_art = art
        self._trace_side = art.side if art.kind == "traces" else None
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
        self._raw_rgb = None
        self._reference_pairs = []  # (unrotated artwork XY, corrected photo XY)
        self._pending_reference = None
        self._reference_markers = []
        self._last_cut_paths = None
        self._last_proof = None
        self._art_warnings = []
        self.setWindowTitle(f"xTool F1 Ultra — {self.k['window']}")
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
        self.view.reference_clicked.connect(self._pick_reference)
        self.legend = _Legend([(theme.PATH, _LEGEND_NOUN[self.kind]),
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
            ("select", "Select", "Click shapes or drag a box; Ctrl or Shift "
                                 "adds. The run then does only those."),
            ("rework", "Rework", "Traces: drag boxes over spots that did not "
                                 "cut through; click a box to remove it. "
                                 "Re-etch runs only inside the boxes.")], "move")
        self.mode.changed.connect(self._set_mode)
        self.photo_btn = widgets.button("Photo", on=self.take_photo,
                                        tip="Take a picture of the bed")
        self.focus_btn = widgets.button(
            "Autofocus", on=lambda: self.autofocus(),
            tip="Measure the height under the focus point with the blue dot "
                "and move the head")
        self.align_btn = widgets.button(
            "Align", on=self.align,
            tip="Take a photo and find the enabled automatic references. "
                "Use Alignment in the side panel to choose references or match points.")
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

        self.job_switch = widgets.Segmented([
            ("traces", "Traces", "Etch the copper traces"),
            ("mask", "Mask", "Open the solder mask over the pads"),
            ("silk", "Silk", "Mark the component silkscreen"),
            ("stencil", "Stencil", "Cut the solder paste stencil")], self.kind)
        for b in self.job_switch.findChildren(QPushButton):
            b.setSizePolicy(QSizePolicy.Ignored, b.sizePolicy().verticalPolicy())
        self.job_switch.changed.connect(self.switch_kind)
        pv.addWidget(self.job_switch)

        head = QWidget()
        hv = QVBoxLayout(head)
        hv.setContentsMargins(0, 0, 0, 0)
        hv.setSpacing(2)
        hv.addWidget(widgets.eyebrow("Step"))
        self.step_lbl = QLabel(self.k["step"])
        self.step_lbl.setFont(theme.font("sub"))
        hv.addWidget(self.step_lbl)
        pv.addWidget(head)

        s = widgets.Section(self.k["section"])
        self.art_section = s
        self.name_lbl = QLabel(name)
        self.name_lbl.setFont(theme.font("sub"))
        s.add(self.name_lbl)
        self.size_lbl = widgets.hint("")
        s.add(self.size_lbl)
        self.dxf_btn = widgets.button(
            "Open DXF…", kind="ghost", on=self.open_dxf,
            tip="Copper traces from a DXF drawing instead of the Gerber folder: "
                "closed shapes are copper, circles in pads are drills, the edge "
                "goes on a layer named Edge.Cuts or Outline")
        self.gerber_btn = widgets.button(
            "Open Gerber folder…", kind="ghost", on=self.open_gerber,
            tip="A KiCad Gerber folder: traces, mask, silkscreen and stencil")
        s.add(_row(self.gerber_btn, self.dxf_btn))
        self.empty_hint = widgets.hint(
            "Nothing loaded. Open a Gerber folder or a DXF to etch, or drag the "
            "calibration area onto the material and run Calibrate the camera "
            "(Alignment) or the copper calibration.")
        s.add(self.empty_hint)
        self.empty_cal_btn = widgets.button(
            "Copper calibration…", on=self.open_copper_calibration,
            tip="Find the power, speed and passes that clear copper, a coupon "
                "at a time")
        s.add(self.empty_cal_btn)
        self.empty_hint.setVisible(self._empty)
        self.empty_cal_btn.setVisible(self._empty)
        self.copper_side = QComboBox()
        self.copper_side.addItem("B.Cu — bottom copper", "bottom")
        self.copper_side.addItem("F.Cu — top copper", "top")
        self.copper_side.setCurrentIndex(self.copper_side.findData(self._trace_side or "bottom"))
        self.copper_side.currentIndexChanged.connect(self._switch_copper_side)
        self.copper_side_field = widgets.Field("Copper face", self.copper_side)
        s.add(self.copper_side_field)
        self.dxf_mirror = QCheckBox("Mirror left–right")
        self.dxf_mirror.setToolTip("A DXF follows the copper face (B.Cu mirrored, "
                                   "F.Cu as drawn); tick or untick to choose")
        self.dxf_flip = QCheckBox("Flip top–bottom")
        self.dxf_flip.setToolTip("Turn the drawing over top to bottom. With the "
                                 "quarter turns this gives every way round")
        self.dxf_mirror.toggled.connect(self._dxf_orientation)
        self.dxf_flip.toggled.connect(self._dxf_orientation)
        self.dxf_orient = _row(self.dxf_mirror, self.dxf_flip)
        s.add(self.dxf_orient)
        self._warn_box = QWidget()
        self._warn_layout = QVBoxLayout(self._warn_box)
        self._warn_layout.setContentsMargins(0, 0, 0, 0)
        self._warn_layout.setSpacing(theme.GAP_S)
        s.add(self._warn_box)
        self._sync_warnings()
        self.x = _spin(float(cfg.value("x", 60.0)), -50, _FIELD, 0.1, 3, suffix=" mm")
        self.y = _spin(float(cfg.value("y", 60.0)), -50, _FIELD, 0.1, 3, suffix=" mm")
        self.x.valueChanged.connect(self._typed)
        self.y.valueChanged.connect(self._typed)
        place = widgets.Disclosure("Position in numbers", key="laser-position")
        place.body.addWidget(widgets.Field("X", self.x))
        place.body.addWidget(widgets.Field(
            "Y", self.y, help="The outline's top-left corner, in the laser's mm. "
                              "Drag it, use the arrow keys, or right-click the bed."))
        s.add(place)
        pv.addWidget(s)

        s = widgets.Section("Rework")
        self.rework_section = s
        s.add(widgets.hint(
            "Spots that did not cut through: choose Rework above the bed and "
            "drag a box over each one. Re-etch runs the isolation again only "
            "inside the boxes; click a box to remove it."))
        self.rework_count = widgets.hint("No boxes yet.")
        s.add(self.rework_count)
        self.rework_passes = _ispin(int(QSettings(*_SETTINGS).value(
            "rework_passes", 5)), 1, 200)
        self.rework_passes.valueChanged.connect(
            lambda v: QSettings(*_SETTINGS).setValue("rework_passes", v))
        s.add(widgets.Field(
            "Rework passes", self.rework_passes,
            help="Passes over the boxes, on top of the job's. Power and speed "
                 "are the recipe's."))
        self.rework_btn = widgets.button(
            "Re-etch the boxes", kind="primary", on=self.rework, enabled=False)
        self.rework_clear_btn = widgets.button(
            "Clear boxes", kind="ghost", on=self.clear_rework, enabled=False)
        s.add(_row(self.rework_btn, self.rework_clear_btn))
        pv.addWidget(s)

        s = widgets.Section("Alignment")
        self.proof_hint = widgets.hint("")
        s.add(self.proof_hint)
        self.proof_btn = widgets.button(
            "Calibrate the camera", on=self.proof,
            tip="Marks the waste beside the board if there is any, otherwise the "
                "isolation the job removes anyway")
        s.add(self.proof_btn)
        self.proof_note = widgets.hint("")
        self.proof_note.setVisible(False)
        s.add(self.proof_note)
        self.proof_more = widgets.Disclosure("Proof options", key="laser-proof")
        self.proof_where = QComboBox()
        self.proof_where.addItem("Automatic: waste if there is any", "auto")
        self.proof_where.addItem("On the isolation the job removes", "isolation")
        self.proof_where.addItem("In the waste beside the board", "waste")
        self.proof_more.body.addWidget(widgets.Field("Marks", self.proof_where))
        self.proof_passes = _ispin(xtool.PROOF_PASSES, 1, 20)
        self.proof_more.body.addWidget(widgets.Field(
            "Mark passes", self.proof_passes,
            help="Enough for the camera to see the mark, far fewer than the job."))
        s.add(self.proof_more)
        manual = widgets.Disclosure("Match points by hand", key="laser-manual-points")
        s.add(manual)
        s_manual, s = s, _Into(manual.body)     # the next rows go under the fold
        s.add(widgets.hint("Pick the same holes, pad centres, corners or marks in the "
                           "drawing and photo. Use 2 distant points; 3 or more let "
                           "the fit check your picks. No mounting holes needed."))
        self.reference_snap = QComboBox()
        self.reference_snap.addItem("Snap to hole centres", "holes")
        self.reference_snap.addItem("Snap to artwork centres", "artwork")
        self.reference_snap.addItem("Free points / corners / marks", "free")
        self.reference_snap.currentIndexChanged.connect(self._draw_references)
        s.add(self.reference_snap)
        self.pick_refs_btn = widgets.button("Pick matching points", on=self._toggle_reference_pick)
        self.pick_refs_btn.setCheckable(True)
        s.add(self.pick_refs_btn)
        self.reference_list = QListWidget()
        self.reference_list.setMaximumHeight(110)
        s.add(self.reference_list)
        self.reference_note = widgets.hint("Take a photo, then pick matching points.")
        s.add(self.reference_note)
        self.apply_refs_btn = widgets.button("Apply point alignment", on=self.apply_reference_alignment)
        self.remove_ref_btn = widgets.button("Remove", kind="ghost", on=self._remove_reference)
        self.clear_refs_btn = widgets.button("Clear", kind="ghost", on=self._clear_references)
        s.add(self.apply_refs_btn)
        s.add(_row(self.remove_ref_btn, self.clear_refs_btn, None))
        s = s_manual
        auto = widgets.Disclosure("Automatic alignment references", key="alignment-references")
        auto.body.addWidget(widgets.hint("Tick only holes or shapes that already exist "
                                        "on the material. These picks do not change what gets etched."))
        self.auto_reference_source = QComboBox()
        self.auto_reference_source.addItem("Drilled holes", "holes")
        self.auto_reference_source.addItem("Artwork shapes", "artwork")
        self.auto_reference_source.setCurrentIndex(1 if self.kind == "stencil" else 0)
        self.auto_reference_source.currentIndexChanged.connect(self._populate_auto_references)
        auto.body.addWidget(self.auto_reference_source)
        self.auto_contrast = QComboBox()
        self.auto_contrast.addItem("Dark holes / marks on light material", "dark")
        self.auto_contrast.addItem("Bright pads / marks on dark material", "bright")
        auto.body.addWidget(self.auto_contrast)
        self.auto_reference_list = QListWidget()
        self.auto_reference_list.setMaximumHeight(140)
        self.auto_reference_list.itemSelectionChanged.connect(self._draw_references)
        auto.body.addWidget(self.auto_reference_list)
        self.auto_all_btn = widgets.button("All", kind="ghost", on=lambda: self._check_auto_references(True))
        self.auto_none_btn = widgets.button("None", kind="ghost", on=lambda: self._check_auto_references(False))
        auto.body.addWidget(_row(self.auto_all_btn, self.auto_none_btn, None))
        s.add(auto)
        pv.addWidget(s)
        self._populate_auto_references()

        s = widgets.Section("Focus")
        self.z_read = widgets.Readout("Head Z", "—")
        self.t_read = widgets.Readout("Thickness", "—")
        s.add(_row(self.z_read, self.t_read, None, gap=theme.GAP_L))
        self.focus_note = widgets.hint("Autofocus measures at the cross: the "
                                       "stencil's middle, on the factory's 10 mm "
                                       "grid. Right-click the bed to measure "
                                       "somewhere else.")
        focus_more = widgets.Disclosure("Set the height by hand", key="laser-focus")
        focus_more.body.addWidget(self.focus_note)
        self.thickness = _spin(float(cfg.value("thickness", 4.1)), 0, 137, 0.1,
                               suffix=" mm")
        self.set_focus_btn = widgets.button("Set", on=self.set_thickness,
                                            tip="Move the head to this thickness + 8 mm, "
                                                "as XCS does")
        focus_more.body.addWidget(
            _row((widgets.Field("By hand", self.thickness), 1), self.set_focus_btn))
        s.add(focus_more)
        pv.addWidget(s)

        s = widgets.Section("Camera")
        self.off_x = widgets.Readout("Photo offset X", "")
        self.off_y = widgets.Readout("Photo offset Y", "")
        s.add(_row(self.off_x, self.off_y, None, gap=theme.GAP_L))
        self.offset_x = _spin(self.cam_offset[0], -10, 10, 0.01, 3, suffix=" mm")
        self.offset_y = _spin(self.cam_offset[1], -10, 10, 0.01, 3, suffix=" mm")
        self.offset_x.valueChanged.connect(self._edit_offset)
        self.offset_y.valueChanged.connect(self._edit_offset)
        self.learn_btn = widgets.button("Learn from this cut", on=self.learn_offset)
        self.reset_off_btn = widgets.button("Reset", kind="ghost",
                                            on=self.reset_offset)
        s.add(self.learn_btn)
        cam_more = widgets.Disclosure("Correct by hand", key="laser-camera")
        cam_more.body.addWidget(widgets.Field("Correction X", self.offset_x))
        cam_more.body.addWidget(widgets.Field("Correction Y", self.offset_y))
        cam_more.body.addWidget(widgets.hint(
            "The photo is moved by this much so it lands on what the fiber really "
            "cuts. A proof on the drilled holes measures it; so does Learn, right "
            "after a stencil cut with the stencil still where it was cut."))
        cam_more.body.addWidget(_row(self.reset_off_btn, None))
        s.add(cam_more)
        # Learning needs holes the laser itself cut; the offset is shared, so a
        # stencil job teaches it for the mask and silkscreen too.
        self.learn_btn.setVisible(self.kind == "stencil")
        pv.addWidget(s)
        self._show_offset()

        s = widgets.Section("Recipe")
        self.preset = QComboBox()
        self.preset.currentTextChanged.connect(self._load_preset)
        s.add(self.preset)
        self.strategy = QComboBox()
        self.strategy.addItem("Concentric passes (FlatCAM, fast)", "concentric")
        self.strategy.addItem("Moat hatch (cross-hatched band)", "moat")
        self.strategy.addItem("Full rubout (clear all non-copper)", "rubout")
        self.strategy_field = widgets.Field("Method", self.strategy)
        self.strategy.currentIndexChanged.connect(self._on_trace_geometry_changed)
        s.add(self.strategy_field)
        self.recipe_lbl = widgets.hint("")
        s.add(self.recipe_lbl)
        # The numbers live under a fold: pick a preset and cut; open it only
        # to tweak one, and save the tweak as a preset of its own.
        self.recipe_more = widgets.Disclosure("Adjust the numbers",
                                              key=f"{self.kind}-recipe")
        r = xtool.DEFAULT_RECIPE
        f = xtool.SPHAWES_REMOVE_MASK
        t = xtool.DEFAULT_TRACES_RECIPE
        self.power = _spin(r.power, 1, 100, 1, 0)
        self.speed = _spin(r.speed, 10, 5000, 10, 0)
        self.freq = _spin(r.frequency, 1, 60, 1, 0)
        self.passes = _ispin(r.total_passes, 1, 300)
        self.offsets = _ispin(t.offsets, 1, 50)
        self.trace_kerf = _spin(t.kerf, 0.0, 0.2, 0.001, 3)
        self.density = _spin(f.lines_per_cm, 10, 1000, 10, 0)
        self.burst = _ispin(r.passes_per_burst, 1, 50)
        self.rest = _spin(r.rest_s, 0, 120, 1, 0)
        self.zones = _ispin(r.zones, 1, 12)
        self.spot_drills = QCheckBox("Etch drill hole centres inside pads")
        self.spot_drills.setChecked(True)
        self.cross = QCheckBox("Cross hatch: each pass at right angles to the last")
        self.one_way = QCheckBox("One way: every line drawn the same direction")
        self.mark = QCheckBox("Mark the board outline afterwards")
        self.mark.setChecked(True)

        self.power_field = widgets.Field("Power", self.power, unit="%")
        self.speed_field = widgets.Field("Speed", self.speed, unit="mm/s")
        self.freq_field = widgets.Field("Frequency", self.freq, unit="kHz")
        self.passes_field = widgets.Field("Passes", self.passes)
        self.offsets_field = widgets.Field("Isolation passes", self.offsets, unit="rings")
        self.trace_kerf_field = widgets.Field("Cleared line width", self.trace_kerf, unit="mm")
        self.density_field = widgets.Field("Line density", self.density, unit="lines/cm")
        self.burst_field = widgets.Field("Per burst", self.burst, unit="passes")
        self.rest_field = widgets.Field("Rest", self.rest, unit="s")
        self.zones_field = widgets.Field("Zones", self.zones)

        for field_w, wdg in (
            (self.power_field, self.power),
            (self.speed_field, self.speed),
            (self.freq_field, self.freq),
            (self.passes_field, self.passes),
            (self.offsets_field, self.offsets),
            (self.trace_kerf_field, self.trace_kerf),
            (self.density_field, self.density),
            (self.burst_field, self.burst),
            (self.rest_field, self.rest),
            (self.zones_field, self.zones),
        ):
            self.recipe_more.body.addWidget(field_w)
            if wdg in (self.offsets, self.trace_kerf, self.density):
                wdg.valueChanged.connect(self._on_trace_geometry_changed)
            else:
                wdg.valueChanged.connect(self._recipe_changed)

        for c in (self.spot_drills, self.cross, self.one_way, self.mark):
            self.recipe_more.body.addWidget(c)
            if c is self.spot_drills:
                c.toggled.connect(self._on_trace_geometry_changed)
            else:
                c.toggled.connect(self._recipe_changed)

        self.save_btn = widgets.button("Save as preset…", on=self.save_preset)
        self.del_btn = widgets.button("Delete preset", kind="ghost",
                                      on=self.delete_preset)
        self.recipe_more.body.addWidget(_row(None, self.save_btn, self.del_btn))
        self.calibrate_btn = widgets.button("Calibrate copper vectors…", on=self.open_copper_calibration)
        self.calibrate_btn.setVisible(self.kind == "traces")
        self.recipe_more.body.addWidget(self.calibrate_btn)
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
        for b in self.findChildren(QPushButton):
            b.setAutoDefault(False)
            b.setDefault(False)
        self._sync_recipe_widgets()
        self._fill_presets(cfg.value(self._key("preset"), next(iter(self.k["presets"]))))
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
    def _noun(self, n):
        return self.k["noun"] if n == 1 else self.k.get("nouns", self.k["noun"] + "s")

    def _sync_warnings(self):
        for w in self._art_warnings:
            w.setParent(None)
            w.deleteLater()
        self._art_warnings = []
        for msg in self.base_art.warnings():
            n = widgets.hint(msg)
            n.setStyleSheet(f"color: {theme.CAUTION};")
            self._warn_layout.addWidget(n)
            self._art_warnings.append(n)
        self._warn_box.setVisible(bool(self._art_warnings))

    def _sync_recipe_widgets(self):
        is_stencil = self.kind == "stencil"
        is_traces = self.kind == "traces"
        self.density.setMaximum(10000 if is_traces else 1000)
        self.density.setDecimals(2 if is_traces else 0)
        if hasattr(self, "calibrate_btn"):
            self.calibrate_btn.setVisible(is_traces)
        strat = self.strategy.currentData() or "concentric"
        is_hatch = is_traces and strat in ("moat", "rubout")
        self.copper_side_field.setVisible(is_traces)
        self.strategy_field.setVisible(is_traces)
        self.offsets_field.setVisible(is_traces and strat != "rubout")
        self.trace_kerf_field.setVisible(is_traces)
        self.density_field.setVisible(self.kind in ("mask", "silk") or is_traces)
        self.burst_field.setVisible(is_stencil)
        self.rest_field.setVisible(is_stencil or (is_traces and strat == "concentric"))
        self.zones_field.setVisible(is_stencil)
        self.spot_drills.setVisible(is_traces and bool(self.base_art.drills))
        self.cross.setVisible(self.kind in ("mask", "silk") or is_hatch)
        self.one_way.setVisible(self.kind in ("mask", "silk") or is_hatch)
        self.mark.setText("Mark the board outline afterwards"
                          if is_stencil else
                          "Score the board outline afterwards, faintly")

    def _trace_art_for(self, side):
        if self._dxf is not None:
            from gerber2rml.engine import dxf_traces
            mirror = (side == "bottom") if self._dxf_mirror is None else self._dxf_mirror
            return dxf_traces.build_dxf_traces(self._dxf, side=side, mirror=mirror,
                                               flip=self._dxf_flip)
        if callable(self._jobs):
            return self._jobs("traces", side=side)
        if self.parent() is not None and hasattr(self.parent(), "_laser_art_for"):
            return self.parent()._laser_art_for("traces", side=side)
        raise ValueError("Load this Gerber folder in the main window to change copper faces.")

    def _switch_copper_side(self, *_a):
        side = self.copper_side.currentData()
        if self.kind != "traces" or side == self.base_art.side:
            return
        self._dxf_mirror = None             # the face's own mirroring again
        try:
            art = self._trace_art_for(side)
        except Exception as e:
            self.copper_side.blockSignals(True)
            self.copper_side.setCurrentIndex(self.copper_side.findData(self.base_art.side))
            self.copper_side.blockSignals(False)
            self._say(str(e), warn=True)
            return
        self._take_traces_art(art)
        self._say(f"Showing {'F.Cu (top)' if side == 'top' else 'B.Cu (bottom)'}. "
                  "Place that copper face upwards on the laser bed.")

    def _dxf_orientation(self, *_a):
        """Mirror or flip the DXF: rebuilt the way round the boxes say."""
        if self._dxf is None or self.kind != "traces":
            return
        self._dxf_mirror = self.dxf_mirror.isChecked()
        self._dxf_flip = self.dxf_flip.isChecked()
        try:
            art = self._trace_art_for(self._trace_side or self.base_art.side)
        except Exception as e:                  # noqa: BLE001 - shown in status bar
            return self._say(str(e), warn=True)
        self._take_traces_art(art)
        self._say(f"{self._dxf.name}: "
                  + ("mirrored" if self.base_art.mirrored else "not mirrored")
                  + (", flipped top to bottom" if self.base_art.flipped else "") + ".")

    def _sync_dxf_orientation(self):
        on = self._dxf is not None and self.kind == "traces"
        self.dxf_orient.setVisible(on)
        if on:
            for box, value in ((self.dxf_mirror, self.base_art.mirrored),
                               (self.dxf_flip, getattr(self.base_art, "flipped", False))):
                box.blockSignals(True)
                box.setChecked(bool(value))
                box.blockSignals(False)

    def _take_traces_art(self, art):
        """A new traces drawing on the page, the recipe as it is."""
        self.base_art = as_laser_art(art)
        self._trace_side = self.base_art.side
        self.copper_side.blockSignals(True)
        self.copper_side.setCurrentIndex(self.copper_side.findData(self._trace_side))
        self.copper_side.blockSignals(False)
        self._clear_references()
        self._populate_auto_references()
        self.selected.clear()
        self._refresh_traces_art()
        self._sync_warnings()
        self._sync_recipe_widgets()
        self._sync_dxf_orientation()

    def open_gerber(self):
        """A Gerber folder's jobs on the page, as srm-cam-laser opens them."""
        from PySide6.QtWidgets import QFileDialog
        from gerber2rml.gui2.laser_app import first_job, job_builder
        cfg = QSettings(*_SETTINGS)
        picked = QFileDialog.getExistingDirectory(
            self, "Gerber folder for the laser", str(cfg.value("gerber_dir", "")))
        if not picked:
            return
        folder = Path(picked)
        cfg.setValue("gerber_dir", str(folder))
        try:
            kind, _art = first_job(folder, "traces")
        except ValueError as e:
            return self._say(str(e), warn=True)
        self._jobs = job_builder(folder)
        self._dxf = None
        self._trace_side = None             # the face with the most copper
        self._empty = False
        self.name_lbl.setText(folder.name)
        self.switch_kind(kind, force=True)
        self._sync_empty()
        self._say(f"Opened {folder.name}: {self.k['window']}.")

    def _sync_empty(self):
        for w in (self.empty_hint, self.empty_cal_btn):
            w.setVisible(self._empty)

    def open_dxf(self):
        """Copper traces from a DXF: the drawing as seen from above, F.Cu."""
        from PySide6.QtWidgets import QFileDialog
        from gerber2rml.engine import dxf_traces
        cfg = QSettings(*_SETTINGS)
        picked, _ = QFileDialog.getOpenFileName(
            self, "Copper traces DXF", str(cfg.value("dxf_dir", "")),
            "DXF drawings (*.dxf);;All files (*)")
        if not picked:
            return
        path = Path(picked)
        cfg.setValue("dxf_dir", str(path.parent))
        try:
            art = dxf_traces.build_dxf_traces(path)
        except xtool.TracesError as e:
            return self._say(str(e), warn=True)
        self.load_dxf_art(art, path)

    def load_dxf_art(self, art, path):
        """Show ``art``, read from the DXF at ``path``, as the traces job."""
        self._dxf = Path(path)
        self._dxf_mirror, self._dxf_flip = None, False
        self._empty = False
        self._sync_empty()
        self.name_lbl.setText(self._dxf.name)
        self._trace_side = as_laser_art(art).side
        if self.kind != "traces":
            self.switch_kind("traces")
        else:
            self._take_traces_art(art)
        n = len(self.base_art.drills or [])
        face = ("B.Cu, mirrored for the bottom face" if self.base_art.side == "bottom"
                else "F.Cu, as drawn")
        self._say(f"Opened {self._dxf.name}: {face}, {n} drilled "
                  f"hole{'' if n == 1 else 's'}. The copper face switch "
                  f"changes it.")

    def switch_kind(self, kind, force=False):
        if kind == self.kind and not force:
            return
        try:
            if kind == "traces" and (self._trace_side is not None
                                     or self._dxf is not None):
                new_art = self._trace_art_for(self._trace_side or "top")
            elif callable(self._jobs):
                new_art = self._jobs(kind)
            elif isinstance(self._jobs, dict) and kind in self._jobs:
                new_art = self._jobs[kind]
            elif self.parent() is not None and hasattr(self.parent(), "_laser_art_for"):
                new_art = self.parent()._laser_art_for(kind)
            else:
                raise RuntimeError(f"No {KINDS[kind]['window']} job is loaded: "
                                   f"open a Gerber folder first.")
        except Exception as e:                  # noqa: BLE001 - shown in status bar
            self.job_switch.set_current(self.kind)
            self._say(str(e), warn=True)
            return
        self.kind = kind
        self.k = KINDS[kind]
        self.base_art = as_laser_art(new_art)
        self._clear_references()
        self.auto_reference_source.setCurrentIndex(1 if kind == "stencil" else 0)
        self._populate_auto_references()
        self.art = xtool.rotated(self.base_art, self.turns, self.fine)
        if kind == "traces":
            self._trace_side = self.base_art.side
            self.copper_side.blockSignals(True)
            self.copper_side.setCurrentIndex(self.copper_side.findData(self._trace_side))
            self.copper_side.blockSignals(False)
        self.selected.clear()
        self.job_switch.set_current(kind)
        self.setWindowTitle(f"xTool F1 Ultra — {self.k['window']}")
        self.step_lbl.setText(self.k["step"])
        self.art_section.label.setText(self.k["section"])
        if self.legend.first_label is not None:
            self.legend.first_label.setText(_LEGEND_NOUN[kind])
        self.legend.adjustSize()
        self._place_legend()
        self._sync_warnings()
        self.learn_btn.setVisible(self.kind == "stencil")
        self._sync_recipe_widgets()
        cfg = QSettings(*_SETTINGS)
        self._fill_presets(cfg.value(self._key("preset"),
                                     next(iter(self.k["presets"]))))
        self._build_item()
        self._say(f"Switched to {self.k['window']}.")

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
        n = len(self.art.apertures)
        self.size_lbl.setText(
            (f"{'F.Cu (top)' if self.art.side == 'top' else 'B.Cu (bottom)'} · "
             if self.kind == "traces" else "")
            + f"{n} {self._noun(n)} · {w:.1f} × {h:.1f} mm · "
            f"{'mirrored' if self.art.mirrored else 'not mirrored'}"
            + (" · flipped" if getattr(self.art, "flipped", False) else "")
            + (f" · {self.art.note}" if self.art.note else "") + turned)
        self._paint()
        self._place_focus_mark()

    def rotate(self, step):
        self._turn_to(self.turns + step, self.fine)

    def _turn_to(self, turns, fine, *, preserve_selection=False):
        """Turn the stencil about its middle, keeping the middle where it is."""
        cx, cy = self.centre()
        self.turns = turns % 4
        self.fine = fine
        self.art = xtool.rotated(self.base_art, self.turns, self.fine)
        if not preserve_selection:
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
        self._draw_references()

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
    def _set_mode(self, mode):
        """Move, Select, or Rework (boxes on the bed for a second pass)."""
        if mode == "rework" and self.kind != "traces":
            self.mode.set_current(self._mode)
            return self._say("Rework is for copper traces: switch to Traces.",
                             warn=True)
        self._mode = mode
        self._select_mode(mode != "move")
        if mode == "rework":
            self._say("Rework: drag a box over each spot that did not cut "
                      "through. Click a box to remove it.")

    def _rework_boxed(self, rect):
        """A box dragged in Rework mode is added; a click inside one drops it."""
        if rect.width() == 0 and rect.height() == 0:
            p = rect.topLeft()
            for i in range(len(self.rework_boxes) - 1, -1, -1):
                x0, y0, x1, y1 = self.rework_boxes[i]
                if x0 <= p.x() <= x1 and y0 <= p.y() <= y1:
                    del self.rework_boxes[i]
                    break
        elif rect.width() >= 0.3 and rect.height() >= 0.3:
            r = rect.normalized()
            self.rework_boxes.append((r.left(), r.top(), r.right(), r.bottom()))
        self._draw_rework()

    def _draw_rework(self):
        for it in self._rework_items:
            self.scene.removeItem(it)
        self._rework_items = []
        for i, (x0, y0, x1, y1) in enumerate(self.rework_boxes):
            it = self.scene.addRect(QRectF(x0, y0, x1 - x0, y1 - y0),
                                    _pen(theme.CAUTION, 1.6),
                                    QBrush(_c(theme.CAUTION, 0.14)))
            it.setZValue(8)
            label = QGraphicsSimpleTextItem(str(i + 1))
            label.setBrush(QBrush(_c(theme.CAUTION)))
            label.setFlag(QGraphicsItem.ItemIgnoresTransformations)
            label.setPos(x0, y0)
            label.setZValue(9)
            self.scene.addItem(label)
            self._rework_items += [it, label]
        n = len(self.rework_boxes)
        self.rework_count.setText(f"{n} box{'' if n == 1 else 'es'} on the bed."
                                  if n else "No boxes yet.")
        self.rework_btn.setEnabled(bool(n))
        self.rework_clear_btn.setEnabled(bool(n))
        self.rework_btn.setText(f"Re-etch {n} box{'' if n == 1 else 'es'}"
                                if n else "Re-etch the boxes")

    def clear_rework(self):
        self.rework_boxes = []
        self._draw_rework()

    def _sync_rework(self):
        on = self.kind == "traces"
        self.rework_section.setVisible(on)
        if not on and self._mode == "rework":
            self.mode.set_current("move")
            self._set_mode("move")

    def rework(self):
        """The traces again, only inside the rework boxes: the CNC's rework
        on the laser. The recipe's power and speed, Rework passes deep."""
        if self.kind != "traces" or not self.rework_boxes:
            return
        r = replace(self._run_recipe(), passes=self.rework_passes.value())
        try:
            job = xtool.traces_job(self.art, self.origin(), r,
                                   boxes=self.rework_boxes)
        except ValueError as e:
            return self._say(str(e), warn=True)
        self._remember()
        self._job = job
        self._zone_holes = [set()]
        self.bar.setRange(0, max(1, int(job.seconds)))
        self.bar.setValue(0)
        self.bar.setVisible(True)
        take_photo = self.photo_after.isChecked()
        n = len(self.rework_boxes)
        before = self._raw_rgb

        def work(progress):
            z = self.laser.z()
            self.laser.run(job.text)
            self.laser.wait(job.seconds * 2 + 120, progress=progress)
            return z, (self._photo_after_job(before) if take_photo else None)

        def done(res):
            z, rgb = res
            if rgb is not None:
                self.show_bed(rgb)
            return (f"Reworked at Z {z:.2f}: {n} box{'' if n == 1 else 'es'}, "
                    f"{job.passes} passes. Check them on the photo; clear the "
                    f"boxes that are through and run the rest again.")
        self._start(work, f"Rework: {n} box{'' if n == 1 else 'es'}, "
                          f"{job.passes} passes…", done)

    def _select_mode(self, on):
        self.view.set_select_mode(on)
        if self.item is not None:
            self.item.setFlag(QGraphicsItem.ItemIsMovable, not on)
            self.item.setCursor(Qt.CrossCursor if on else Qt.OpenHandCursor)
        self._paint()

    def _boxed(self, rect, add):
        if self._mode == "rework":
            return self._rework_boxed(rect)
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
        if e.key() == Qt.Key_Escape and self.view.pick_reference:
            self.pick_refs_btn.setChecked(False)
            self._toggle_reference_pick()
            return
        if e.key() == Qt.Key_H and not e.modifiers():
            self.set_look("filled" if self.look == "hidden" else "hidden")
            return
        super().keyPressEvent(e)

    def _paint(self, active=None, *, estimate=True):
        if self.item is None:
            return
        self.item.paint_holes(self.selected, active, "outlines" if self.view.pick_reference else self.look)
        if self.view.pick_reference:
            self.item.setVisible(self._pending_reference is None)
        n, total = len(self.selected), len(self.art.apertures)
        self.sel_read.set(f"{n} / {total}" if n else f"{total}")
        self.sel_read.set_label("Selected" if n else self._noun(2))
        self.cut_btn.setText(self.k["run_selected"].format(n=n) if n else self.k["run"])
        if estimate:
            self._estimate()

    # -- recipe and presets ------------------------------------------------
    def _key(self, name):
        """Settings per kind; the stencil keeps the names it always had."""
        return name if self.kind == "stencil" else f"{name}_{self.kind}"

    def _saved_presets(self):
        try:
            return json.loads(QSettings(*_SETTINGS).value(self._key("presets"), "{}"))
        except (TypeError, ValueError):
            return {}

    def _presets(self):
        saved = self._saved_presets()
        out = {k: _recipe_dict(v) for k, v in self.k["presets"].items()}
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
        if self.kind == "stencil":
            self.passes.setValue(d["total_passes"])
            self.burst.setValue(d["passes_per_burst"])
            self.rest.setValue(d["rest_s"])
            self.zones.setValue(d["zones"])
            self.mark.setChecked(bool(d["mark_passes"]))
        elif self.kind == "traces":
            idx = self.strategy.findData(d.get("strategy", "concentric"))
            if idx >= 0:
                self.strategy.setCurrentIndex(idx)
            self.passes.setValue(d["passes"])
            self.offsets.setValue(d.get("offsets", xtool.DEFAULT_TRACE_OFFSETS))
            self.trace_kerf.setValue(d.get("kerf", xtool.DEFAULT_TRACE_KERF))
            self.density.setValue(d["lines_per_cm"])
            self.rest.setValue(d.get("rest_s", 0.0))
            self.spot_drills.setChecked(bool(d.get("spot_drills", True)))
            self.cross.setChecked(bool(d["cross_hatch"]))
            self.one_way.setChecked(bool(d["one_way"]))
            self.mark.setChecked(bool(d["mark_outline"]))
        else:
            self.passes.setValue(d["passes"])
            self.density.setValue(d["lines_per_cm"])
            self.cross.setChecked(bool(d["cross_hatch"]))
            self.one_way.setChecked(bool(d["one_way"]))
            self.mark.setChecked(bool(d["mark_outline"]))
        self._syncing_recipe = False
        self.del_btn.setEnabled(name in saved)
        QSettings(*_SETTINGS).setValue(self._key("preset"), name)
        if self.kind == "traces":
            self._sync_recipe_widgets()
            self._refresh_traces_art()
        self._recipe_changed()

    def _on_trace_geometry_changed(self, *_a):
        if self._syncing_recipe:
            return
        if self.kind == "traces":
            self._sync_recipe_widgets()
            self._refresh_traces_art()
        self._recipe_changed()

    def _refresh_traces_art(self):
        if self.kind != "traces" or self.base_art.copper is None:
            return
        r = self.recipe()
        apertures = xtool.traces_apertures(
            self.base_art.copper, self.base_art.outline,
            self.base_art.drills or (), strategy=r.strategy, offsets=r.offsets,
            kerf=r.kerf, lines_per_cm=r.lines_per_cm, spot_drills=r.spot_drills)
        note = ("full rubout" if r.strategy == "rubout"
                else f"{r.offsets} passes ({r.isolation_mm:.2f} mm gap)")
        self.base_art = replace(self.base_art, apertures=apertures, kerf=r.kerf,
                                note=note, _ring_cache=None)
        if self.auto_reference_source.currentData() == "artwork":
            self._populate_auto_references()
        self.art = xtool.rotated(self.base_art, self.turns, self.fine)
        self.selected.clear()
        if self.item is not None:
            self._build_item()

    def _recipe_changed(self, *_a):
        if self._syncing_recipe:
            return
        r = self.recipe()
        presets, _ = self._presets()
        chosen = presets.get(self.preset.currentText())
        now = _recipe_dict(r)
        changed = chosen is not None and any(
            float(chosen.get(f, v)) != float(v)
            for f, v in now.items()
            if f != "mark_power" and isinstance(v, (int, float, bool))
        ) or (chosen is not None and chosen.get("strategy") != getattr(r, "strategy", None)
              if self.kind == "traces" else False)
        if self.kind == "stencil":
            what = (f"{r.rounds} round{'' if r.rounds == 1 else 's'} of "
                    f"{r.passes_per_burst} pass{'' if r.passes_per_burst == 1 else 'es'} "
                    f"per zone" + (f", {r.rest_s:g} s laser-off after each"
                                   if r.rest_s else ""))
        elif self.kind == "traces":
            if r.strategy == "concentric":
                what = (f"Concentric · {r.offsets} ring{'' if r.offsets == 1 else 's'} "
                        f"({r.isolation_mm:.2f} mm gap) · {r.passes} depth passes · "
                        f"{r.power:g} % @ {r.speed:g} mm/s")
            else:
                mode = "Moat hatch" if r.strategy == "moat" else "Full rubout"
                what = (f"{mode} · {r.power:g} % · {r.speed:g} mm/s · {r.passes} passes · "
                        f"{r.lines_per_cm:g} lines/cm")
        else:
            what = (f"{r.power:g} % · {r.speed:g} mm/s · {r.passes} pass"
                    f"{'' if r.passes == 1 else 'es'}"
                    f"{', cross-hatched' if r.cross_hatch else ''} · "
                    f"{r.lines_per_cm:g} lines/cm ({r.interval:.3f} mm)")
        uncalibrated = (self.kind == "traces" and self.preset.currentText() in TRACES_PRESETS
                        and "proven" not in self.preset.currentText())
        self.recipe_lbl.setText(("Uncalibrated starting values · " if uncalibrated else "")
                               + ("Changed from the preset · " if changed else "") + what)
        self._estimate()

    def _estimate(self):
        if not hasattr(self, "time_read") or self.item is None:
            return
        try:
            if self.kind == "traces":
                secs = xtool.traces_job(
                    self.art, (1.0, 1.0), self._run_recipe(),
                    only=self.selected or None).seconds
                self.time_read.set(f"{int(secs // 60)}:{int(secs % 60):02d}")
                return
            if self.kind != "stencil":
                from shapely.affinity import translate
                shapes = [translate(p, -self.x.value() + 1, -self.y.value() + 1)
                          for p in self._shapes()]
                secs = xtool.fill_job(shapes, [], self._run_recipe()).seconds
                self.time_read.set(f"{int(secs // 60)}:{int(secs % 60):02d}")
                return
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
        if self.kind == "traces":
            return xtool.TracesRecipe(
                strategy=self.strategy.currentData() or "concentric",
                power=self.power.value(),
                speed=self.speed.value(),
                frequency=self.freq.value(),
                passes=self.passes.value(),
                offsets=self.offsets.value(),
                kerf=self.trace_kerf.value(),
                lines_per_cm=self.density.value(),
                rest_s=self.rest.value(),
                spot_drills=self.spot_drills.isChecked(),
                cross_hatch=self.cross.isChecked(),
                one_way=self.one_way.isChecked(),
                mark_outline=self.mark.isChecked())
        if self.kind != "stencil":
            return xtool.FillRecipe(power=self.power.value(), speed=self.speed.value(),
                                    frequency=self.freq.value(),
                                    passes=self.passes.value(),
                                    lines_per_cm=self.density.value(),
                                    cross_hatch=self.cross.isChecked(),
                                    one_way=self.one_way.isChecked(),
                                    mark_outline=self.mark.isChecked())
        return xtool.Recipe(power=self.power.value(), speed=self.speed.value(),
                            frequency=self.freq.value(),
                            total_passes=self.passes.value(),
                            passes_per_burst=self.burst.value(),
                            rest_s=self.rest.value(), zones=self.zones.value(),
                            mark_passes=1 if self.mark.isChecked() else 0)

    def _run_recipe(self):
        """A re-cut leaves the outline alone: it is marked already."""
        r = self.recipe()
        if not self.selected:
            return r
        return replace(r, mark_passes=0) if self.kind == "stencil" else \
            replace(r, mark_outline=False)

    def save_preset(self):
        name, ok = QInputDialog.getText(self, "Save the recipe", "Name:",
                                        text=self.preset.currentText())
        name = name.strip()
        if not ok or not name:
            return
        if name in self.k["presets"]:
            return self._say(f"“{name}” is built in; pick another name.", warn=True)
        saved = self._saved_presets()
        saved[name] = _recipe_dict(self.recipe())
        QSettings(*_SETTINGS).setValue(self._key("presets"), json.dumps(saved))
        self._fill_presets(name)
        self._say(f"Saved “{name}”.")

    def delete_preset(self):
        name = self.preset.currentText()
        saved = self._saved_presets()
        if saved.pop(name, None) is not None:
            QSettings(*_SETTINGS).setValue(self._key("presets"), json.dumps(saved))
            self._fill_presets(next(iter(self.k["presets"])))
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

    def _shapes(self, art=None, origin=None, only="selected"):
        """The job's shapes as shapely Polygons on the bed (filled jobs)."""
        from shapely.geometry import Polygon
        art = art or self.art
        origin = origin or self.origin()
        pick = (self.selected or None) if only == "selected" else None
        _, h = art.size
        out = []
        for k, poly in enumerate(art.apertures):
            if pick is not None and k not in pick:
                continue
            out.append(Polygon(xtool.to_bed(list(poly.exterior.coords), origin, h),
                               [xtool.to_bed(list(r.coords), origin, h)
                                for r in poly.interiors]))
        return out

    def _auto_polys(self, art):
        return (art.apertures if self.auto_reference_source.currentData() == "artwork"
                else (art.features or []))

    def _populate_auto_references(self, *_a):
        self.auto_reference_list.clear()
        for i, poly in enumerate(self._auto_polys(self.base_art)):
            c = poly.centroid
            item = QListWidgetItem(f"{i + 1} · X {c.x:.2f}  Y {c.y:.2f} mm")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.auto_reference_list.addItem(item)
        self._sync_proof()

    def _check_auto_references(self, checked):
        for i in range(self.auto_reference_list.count()):
            self.auto_reference_list.item(i).setCheckState(Qt.Checked if checked else Qt.Unchecked)

    def _features(self, art, origin):
        """Only the explicitly enabled automatic alignment references."""
        _, h = art.size
        return [xtool.to_bed(list(p.exterior.coords), origin, h)
                for i, p in enumerate(self._auto_polys(art))
                if i < self.auto_reference_list.count()
                and self.auto_reference_list.item(i).checkState() == Qt.Checked]

    # -- picked references: base artwork XY <-> corrected bed/photo XY -------
    def _reference_to_bed(self, point):
        from shapely.affinity import rotate
        from shapely.geometry import Point
        angle = 90 * self.turns + self.fine
        outline = rotate(self.base_art.outline, -angle, origin=(0, 0))
        x0, _, _, y1 = outline.bounds
        p = rotate(Point(*point), -angle, origin=(0, 0))
        ox, oy = self.origin()
        return p.x - x0 + ox, y1 - p.y + oy

    def _reference_from_bed(self, point):
        from shapely.affinity import rotate
        from shapely.geometry import Point
        angle = 90 * self.turns + self.fine
        x0, _, _, y1 = rotate(self.base_art.outline, -angle, origin=(0, 0)).bounds
        ox, oy = self.origin()
        p = rotate(Point(point[0] - ox + x0, y1 - point[1] + oy),
                   angle, origin=(0, 0))
        return p.x, p.y

    def _toggle_reference_pick(self):
        if self.pick_refs_btn.isChecked() and self._bed_rgb is None:
            self.pick_refs_btn.setChecked(False)
            return self._say("Take a photo first, then pick matching points.", warn=True)
        self._pending_reference = None
        self.view.pick_reference = self.pick_refs_btn.isChecked()
        self.view.setCursor(Qt.CrossCursor if self.view.pick_reference else Qt.ArrowCursor)
        self.item.setFlag(QGraphicsItem.ItemIsMovable,
                          not self.view.pick_reference and not self.view.select_mode)
        self._reference_prompt()
        self._draw_references()
        self._paint(estimate=False)

    def _reference_prompt(self):
        if self.view.pick_reference:
            text = ("Now click the SAME point in the photo (drawing hidden)."
                    if self._pending_reference is not None else
                    "Click a reference in the drawing. Zoom in for a precise pick.")
        else:
            text = f"{len(self._reference_pairs)} matching points · use widely spaced references."
        self.reference_note.setText(text)

    def _pick_reference(self, point):
        if not self.view.pick_reference:
            return
        xy = (point.x(), point.y())
        if not (0 <= xy[0] <= _FIELD and 0 <= xy[1] <= _FIELD):
            return self._say("Pick a point inside the camera's bed area.", warn=True)
        if self._pending_reference is None:
            mode = self.reference_snap.currentData()
            if mode != "free":
                polys = ((self.art.features or []) if mode == "holes" else self.art.apertures)
                centres = [xtool.to_bed([(p.centroid.x, p.centroid.y)], self.origin(),
                                       self.art.size[1])[0] for p in polys]
                if not centres:
                    return self._say("No centres available. Choose Free points / corners / marks.", warn=True)
                xy = min(centres, key=lambda q: (q[0] - xy[0]) ** 2 + (q[1] - xy[1]) ** 2)
                if (xy[0] - point.x()) ** 2 + (xy[1] - point.y()) ** 2 > 16:
                    return self._say("Click closer to a reference centre, or choose Free points.", warn=True)
            self._pending_reference = self._reference_from_bed(xy)
        else:
            self._reference_pairs.append((self._pending_reference, xy))
            self._pending_reference = None
        self._update_reference_list()
        self._paint(estimate=False)

    def _update_reference_list(self):
        self.reference_list.clear()
        for i, (_, target) in enumerate(self._reference_pairs):
            self.reference_list.addItem(f"{i + 1} · photo X {target[0]:.2f}  Y {target[1]:.2f} mm")
        self._reference_prompt()
        self._draw_references()

    def _clear_references(self):
        self._reference_pairs.clear()
        self._pending_reference = None
        self.pick_refs_btn.setChecked(False)
        self.view.pick_reference = False
        self.view.setCursor(Qt.ArrowCursor)
        self._update_reference_list()
        if self.item is not None:
            self.item.setFlag(QGraphicsItem.ItemIsMovable, not self.view.select_mode)
            self._paint(estimate=False)

    def _remove_reference(self):
        row = self.reference_list.currentRow()
        if row >= 0:
            self._reference_pairs.pop(row)
        self._pending_reference = None
        self._update_reference_list()
        self._paint(estimate=False)

    def _draw_references(self):
        for item in self._reference_markers:
            self.scene.removeItem(item)
        self._reference_markers.clear()
        if self.view.pick_reference and self._pending_reference is None:
            mode = self.reference_snap.currentData()
            polys = ((self.art.features or []) if mode == "holes" else
                     self.art.apertures if mode == "artwork" else [])
            for poly in polys:
                centre = poly.centroid
                x, y = xtool.to_bed([(centre.x, centre.y)], self.origin(), self.art.size[1])[0]
                path = QPainterPath()
                path.addEllipse(QPointF(x, y), 0.5, 0.5)
                marker = self.scene.addPath(path, _pen(theme.PROBE, 1.5))
                marker.setZValue(24)
                marker.setAcceptedMouseButtons(Qt.NoButton)
                self._reference_markers.append(marker)
        if hasattr(self, "auto_reference_list"):
            row = self.auto_reference_list.currentRow()
            polys = self._auto_polys(self.art)
            if 0 <= row < len(polys):
                points = xtool.to_bed(list(polys[row].exterior.coords), self.origin(), self.art.size[1])
                path = QPainterPath()
                path.addPolygon(QPolygonF([QPointF(*p) for p in points]))
                marker = self.scene.addPath(path, _pen(theme.PROBE, 3.0))
                marker.setZValue(24)
                marker.setAcceptedMouseButtons(Qt.NoButton)
                self._reference_markers.append(marker)
        pairs = list(self._reference_pairs)
        if self._pending_reference is not None:
            pairs.append((self._pending_reference, None))
        for i, (source, target) in enumerate(pairs):
            for xy, token, suffix in ((self._reference_to_bed(source), theme.PATH, "D"),
                                      (target, theme.PROBE, "P")):
                if xy is None:
                    continue
                x, y = xy
                path = QPainterPath()
                path.addEllipse(QPointF(x, y), 0.6, 0.6)
                path.moveTo(x - 1, y)
                path.lineTo(x + 1, y)
                path.moveTo(x, y - 1)
                path.lineTo(x, y + 1)
                marker = self.scene.addPath(path, _pen(token, 1.5))
                label = self.scene.addSimpleText(f"{i + 1}{suffix}")
                label.setBrush(QBrush(_c(token)))
                label.setFlag(QGraphicsItem.ItemIgnoresTransformations)
                label.setPos(x + 0.8, y + 0.8)
                for item in (marker, label):
                    item.setZValue(25)
                    item.setAcceptedMouseButtons(Qt.NoButton)
                    self._reference_markers.append(item)

    def apply_reference_alignment(self):
        from math import degrees
        from gerber2rml.engine import xtool_camera as cam
        source = [self._reference_to_bed(p) for p, _ in self._reference_pairs]
        target = [q for _, q in self._reference_pairs]
        try:
            fit = cam.fit_reference_points(source, target)
        except (ValueError, cam.CameraError) as e:
            return self._say(str(e), warn=True)
        # Rotating about the board centre changes its bounding box. Recover
        # translation from the same physical reference after the turn.
        self._turn_to(self.turns, self.fine + degrees(fit.transform.theta), preserve_selection=True)
        now = [self._reference_to_bed(p) for p, _ in self._reference_pairs]
        self.x.setValue(round(self.x.value() + sum(q[0] - p[0] for p, q in zip(now, target)) / len(now), 3))
        self.y.setValue(round(self.y.value() + sum(q[1] - p[1] for p, q in zip(now, target)) / len(now), 3))
        self.pick_refs_btn.setChecked(False)
        self._toggle_reference_pick()
        msg = f"Aligned on {len(source)} points · RMS {fit.rms:.3f} mm · worst {max(fit.errors):.3f} mm."
        if len(source) == 2:
            msg += " Add a third point to independently check the fit."
        self.reference_note.setText(msg)
        self._remember()
        self._say(msg)

    def _remember(self):
        cfg = QSettings(*_SETTINGS)
        cfg.setValue("x", self.x.value())
        cfg.setValue("y", self.y.value())
        cfg.setValue("thickness", self.thickness.value())

    # -- actions -----------------------------------------------------------
    def open_copper_calibration(self):
        from gerber2rml.gui2.copper_calibration import CopperCalibrationDialog
        dialog = CopperCalibrationDialog(self, laser=self.laser)
        dialog._cal = self._cal
        if self._raw_rgb is not None:
            dialog._raw_rgb = self._raw_rgb
            dialog.show_bed(dialog._photo(_PX_PER_MM, dialog._raw_rgb))
        dialog.exec()
        self._cal = dialog._cal
        self._raw_rgb = dialog._raw_rgb
        self._set_offset(dialog.cam_offset)
        self.thickness.setValue(dialog.thickness.value())
        if dialog.saved_recipe_name:
            self._fill_presets(dialog.saved_recipe_name)

    def _calibration(self):
        if self._cal is None:
            self._cal = self.laser.calibration()
        return self._cal

    PHOTO_TRIES = 6
    PHOTO_DARK = 0.85           # of the photo before: darker is not lit yet

    def _raw_photo(self, like=None):
        """The camera's picture. ``like``: a photo of the same bed taken
        before a job. Straight after a job the light and the exposure take a
        moment to come back; a photo clearly darker than ``like`` is taken
        again, a second apart, until it is not."""
        import time
        from gerber2rml.engine.xtool_camera import decode_jpeg
        self._calibration()
        self.laser.lights(True)
        raw = decode_jpeg(self.laser.snap())
        if like is not None:
            want = self.PHOTO_DARK * _brightness(like)
            for _ in range(self.PHOTO_TRIES - 1):
                if _brightness(raw) >= want:
                    break
                time.sleep(1.0)
                raw = decode_jpeg(self.laser.snap())
        self._raw_rgb = raw
        return raw

    def _photo_after_job(self, before):
        """The bed straightened, after a job: lit like ``before`` was."""
        return self._photo(_PX_PER_MM, self._raw_photo(like=before))

    def _photo(self, px_per_mm=_PX_PER_MM, raw=None, offset=None):
        raw = self._raw_photo() if raw is None else raw
        return self._calibration().rectify(
            raw, px_per_mm, self.cam_offset if offset is None else offset)

    # -- the camera's offset -------------------------------------------------
    def _show_offset(self):
        ex, ey = self.cam_offset
        self.off_x.set(f"{ex:+.2f} mm")
        self.off_y.set(f"{ey:+.2f} mm")

    def _set_offset(self, off):
        old = self.cam_offset
        self.cam_offset = (round(float(off[0]), 3), round(float(off[1]), 3))
        cfg = QSettings(*_SETTINGS)
        cfg.setValue("camera_offset_x", self.cam_offset[0])
        cfg.setValue("camera_offset_y", self.cam_offset[1])
        # A correction changes photo coordinates, never the laser artwork.
        dx, dy = old[0] - self.cam_offset[0], old[1] - self.cam_offset[1]
        self._reference_pairs = [(p, (q[0] + dx, q[1] + dy))
                                 for p, q in self._reference_pairs]
        for spin, value in ((self.offset_x, self.cam_offset[0]),
                            (self.offset_y, self.cam_offset[1])):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)
        if self._raw_rgb is not None:
            self.show_bed(self._photo(_PX_PER_MM, self._raw_rgb))
        self._update_reference_list()
        self._show_offset()

    def _edit_offset(self, *_a):
        self._set_offset((self.offset_x.value(), self.offset_y.value()))
        self._say("Photo correction updated. The drawing and laser position have not moved.")

    def reset_offset(self):
        self._set_offset((0.0, 0.0))
        self._say("Photo offset reset; the current photo has been updated.")

    def _residual(self, rgb_hi, hi, holes=None):
        """Where the holes of the stencil, as placed now, show up in a photo:
        the alignment over a small search, or None if they cannot be found."""
        from gerber2rml.engine import xtool_camera as cam
        holes = self._last_cut_paths if holes is None else holes
        if not holes or len(holes) < 2:
            return None
        a = cam.align(rgb_hi, hi, holes, search_mm=4.0, max_turn=1.5)
        # In steel a clean hole shows the bright plate under it, so not every
        # hole reads dark: half of them is plenty to measure a small offset
        # with the stencil already in place.
        return a if a.found >= max(2, min(5, 0.5 * a.total)) and a.score > 0.15 else None

    def learn_offset(self):
        """The stencil is where it was cut: whatever offset the photo shows
        between the overlay and the real holes is the camera's error."""
        hi = 8
        if not self._last_cut_paths:
            return self._say("Cut a stencil in this window first. Camera learning uses "
                             "the actual cut position; matching board points only moves the drawing.", warn=True)

        def work(_p):
            raw = self._raw_photo()
            a = self._residual(self._photo(hi, raw), hi)
            return raw, a

        def done(res):
            raw, a = res
            if a is None or abs(a.turn) > 0.3:
                self.show_bed(self._photo(_PX_PER_MM, raw))
                return ("Could not find the cut holes under the stencil. Leave it "
                        "where it was cut, take a photo to check, and try again.")
            self._set_offset((self.cam_offset[0] + a.dx, self.cam_offset[1] + a.dy))
            self.show_bed(self._photo(_PX_PER_MM, raw))
            return (f"Learned from {a.found} holes: the photo was {a.dx:+.2f}, "
                    f"{a.dy:+.2f} mm off. Photos now land on the cut.")
        self._start(work, "Learning the camera's offset from the cut…", done)

    def _sync_proof(self):
        """The camera calibration, on every traces job; with drilled holes it
        also puts the job on them."""
        if hasattr(self, "rework_section"):
            self._sync_rework()             # traces only, like the proof
        if hasattr(self, "dxf_orient"):
            self._sync_dxf_orientation()
        on = self.kind == "traces"
        holes = len(self.base_art.drills or []) >= 2
        self.proof_btn.setText("Calibrate and lock onto the holes" if holes
                               else "Calibrate the camera")
        if getattr(self, "_empty", False):
            self.proof_hint.setText(
                "The laser makes a few faint marks inside the calibration area "
                "and photographs them: where they land corrects the camera. Drag "
                "the area onto the material first.")
            for w in (self.proof_hint, self.proof_btn):
                w.setVisible(True)
            self.proof_more.setVisible(False)       # the marks go in the area
            if hasattr(self, "rework_section"):
                self.rework_section.setVisible(False)
            return
        self.proof_hint.setText(
            "The laser makes a few faint marks and photographs them: where they "
            "land corrects the camera, so the photo shows where it really fires. "
            + ("The drilled holes in the same photo then move the job onto "
               "them. Drag the drawing roughly onto the board first."
               if holes else
               "Works on a blank. Drag the drawing onto the blank first; the "
               "marks go beside it or on copper the job removes anyway."))
        for w in (self.proof_hint, self.proof_btn, self.proof_more):
            w.setVisible(on)
        if not on:
            self.proof_note.setVisible(False)

    def _hole_paths(self, art=None, origin=None):
        """Every drilled hole as a bed path, wherever the job is now."""
        art = art or self.art
        _, h = art.size
        return [xtool.to_bed(list(p.exterior.coords), origin or self.origin(), h)
                for p in (art.features or [])]

    def _proof_plans(self):
        """The marks to try, best first, for the choice under Proof options."""
        if self._empty:
            return [xtool.proof_in_area(self.art, self.origin(), self.recipe())], False
        want = self.proof_where.currentData()
        recipe, plans, errors = self.recipe(), [], []
        for where, build in (("waste", xtool.proof_in_waste),
                             ("isolation", xtool.proof_on_isolation)):
            if want not in ("auto", where):
                continue
            try:
                plans.append(build(self.art, self.origin(), recipe))
            except ValueError as e:
                errors.append(str(e))
        if not plans:
            raise ValueError(errors[0] if errors else "Nothing to mark.")
        return plans, want == "auto"

    def proof(self):
        """Tie the laser to the drilled holes. A photo, a few faint marks, a
        second photo: what changed is where the laser really fires, and the
        holes are in the same pictures. The camera's correction is set from the
        marks and the job is moved onto the holes."""
        from gerber2rml.engine import xtool_camera as cam
        if self.kind != "traces":
            return self._say("The camera calibration runs on a traces job.",
                             warn=True)
        try:
            plans, auto = self._proof_plans()
        except ValueError as e:
            return self._say(str(e), warn=True)
        recipe, passes = self.recipe(), self.proof_passes.value()
        holes = (self._hole_paths() if len(self.art.drills or []) >= 2
                 else [])                   # a blank: the camera only
        old = self.cam_offset
        hi = 8
        self._remember()

        def work(_p):
            raw_a = self._raw_photo()
            before = self._photo(hi, raw_a)
            plan = plans[-1]
            if plans[0].where == "waste" and (
                    not auto or cam.sheet_continues(before, hi, plans[0].spots,
                                                    plans[0].inside)):
                plan = plans[0]
            text, secs = xtool.proof_job(plan, recipe, passes)
            self.laser.run(text)
            self.laser.wait(secs * 2 + 60)
            raw_b = self._raw_photo(like=raw_a)
            m = cam.locate_change(before, self._photo(hi, raw_b), hi, plan.marks)
            if not m.ok:
                return plan, raw_b, m, None, old
            new = (old[0] + m.dx, old[1] + m.dy)
            if not holes:
                return plan, raw_b, m, None, new
            # The holes, in the photo from before the marks, seen through the
            # corrected camera: what is left is the job being off the board.
            try:
                a = cam.align(self._photo(hi, raw_a, new), hi, holes,
                              search_mm=4.0, max_turn=1.5, need=cam.DRILLED_NEED)
            except cam.CameraError:
                a = None
            return plan, raw_b, m, a, new

        def done(res):
            plan, raw_b, m, a, new = res
            where = {"waste": "the waste beside the board",
                     "area": "the calibration area"}.get(plan.where, "the isolation")
            self._last_proof = None
            if not m.ok:
                self.show_bed(self._photo(_PX_PER_MM, raw_b))
                msg = (f"The proof marks in {where} did not show in the photo "
                       f"({m.found} of {m.total}). Nothing was moved. Raise Mark "
                       f"passes under Proof options"
                       + (", or mark the isolation instead." if plan.where == "waste"
                          else "."))
                self.proof_note.setText(msg)
                self.proof_note.setVisible(True)
                return msg
            self._set_offset(new)
            self.show_bed(self._photo(_PX_PER_MM, raw_b))
            cam_mm = (m.dx ** 2 + m.dy ** 2) ** 0.5
            said = (f"Proof on {m.found} marks in {where}: the camera was "
                    f"{cam_mm:.2f} mm off and is corrected.")
            if not holes:
                msg = said + (" Open a Gerber folder or DXF and place it on the "
                          "photo." if self._empty else
                          " No drilled holes, so the job stays where it is: "
                          "check it on the photo, then etch.")
                self._last_proof = {"where": plan.where, "camera": (m.dx, m.dy)}
                self.proof_note.setText(msg)
                self.proof_note.setVisible(True)
                return msg
            if a is None or not a.ok:
                seen = (f" (found {a.found} of {a.total})" if a is not None else "")
                msg = (said + f" The drilled holes could not be found{seen}, so "
                       "the job was not moved: drag it closer and press Align.")
                self.proof_note.setText(msg)
                self.proof_note.setVisible(True)
                return msg
            target = self._middle(holes) + (a.dx, a.dy)
            self._turn_to(self.turns, self.fine + a.turn, preserve_selection=True)
            dx, dy = target - self._middle(self._hole_paths())
            self.x.setValue(round(self.x.value() + dx, 3))
            self.y.setValue(round(self.y.value() + dy, 3))
            self._clear_references()
            self._remember()
            off = (a.dx ** 2 + a.dy ** 2) ** 0.5
            self._last_proof = {"where": plan.where, "camera": (m.dx, m.dy),
                                "job": (a.dx, a.dy), "turn": a.turn,
                                "holes": (a.found, a.total)}
            msg = (said + f" The job was {off:.2f} mm off the holes"
                   + (f" and {a.turn:+.1f}° round" if abs(a.turn) > 0.05 else "")
                   + f"; it now sits on {a.found} of {a.total}. Ready to cut.")
            self.proof_note.setText(msg)
            self.proof_note.setVisible(True)
            return msg
        self._start(work, "Calibrating the camera: photo, marks, photo…", done)

    def align(self):
        """Find the holes already cut and put the stencil back on them. Tries the
        stencil as it is, then the other three quarter turns, in case the board
        went back the other way round."""
        from gerber2rml.engine import xtool_camera as cam
        cx, cy = self.centre()
        if len(self._features(self.art, self.origin())) < 2:
            return self._say("Choose at least two existing features under Automatic "
                             "alignment references, or use Pick matching points for "
                             "pads, corners or marks.", warn=True)
        candidates = []
        for k in range(4):
            art = xtool.rotated(self.base_art, self.turns + k, self.fine)
            w, h = art.size
            candidates.append((k, self._features(art, (cx - w / 2, cy - h / 2))))
        hi = 8
        contrast = self.auto_contrast.currentData()
        # Drilled holes over the bed's slats do not all read dark: see
        # xtool_camera.DRILLED_NEED. Holes cut in a stencil keep 85 %.
        need = (cam.DRILLED_NEED if self.kind != "stencil"
                and self.auto_reference_source.currentData() == "holes" else 0.85)

        def work(_p):
            rgb = self._photo(hi)
            tried = []
            for k, holes in candidates:
                a = cam.align(rgb, hi, holes, polarity=contrast, need=need)
                tried.append((k, holes, a))
                if a.ok and k == 0:
                    break
            good = [t for t in tried if t[2].ok]
            pick = max(good or tried, key=lambda t: (t[2].found / max(t[2].total, 1), t[2].score))
            return rgb, pick, bool(good)

        def done(res):
            rgb, (k, holes, a), good = res
            self.show_bed(rgb[::hi // _PX_PER_MM, ::hi // _PX_PER_MM].copy())
            if not good:
                return (f"Could not match the references: at best {a.found} of {a.total} "
                        f"(needs {int(-(-a.need * a.total // 1))}). "
                        "Drag the drawing closer, choose clearer references, or pick matching points.")
            target = self._middle(holes) + (a.dx, a.dy)
            self._turn_to(self.turns + k, self.fine + a.turn, preserve_selection=True)
            now = self._features(self.art, self.origin())
            dx, dy = target - self._middle(now)
            self.x.setValue(round(self.x.value() + dx, 3))
            self.y.setValue(round(self.y.value() + dy, 3))
            moved = (a.dx ** 2 + a.dy ** 2) ** 0.5
            turned = (90 * k + a.turn + 180) % 360 - 180
            self._clear_references()
            what = "references"
            return (f"Aligned on {a.found} of {a.total} {what}: moved {moved:.2f} mm "
                    f"(X {a.dx:+.2f}, Y {a.dy:+.2f}), turned {turned:+.1f}°. Check "
                    f"with Show where before cutting.")
        self._start(work, "Aligning: photo, then looking for the chosen references…", done)

    def _focused(self, z, how):
        self.z_read.set(f"{z:.2f}")
        self.t_read.set(f"{z - xtool.FOCUS_OFFSET:.2f}")
        self.link.set(f"Laser · focus Z {z:.2f}", "live")
        self.focus_note.setText(how)

    def take_photo(self):
        def shown(rgb):
            self._clear_references()
            self.show_bed(rgb)
            self.link.set("Laser connected", "live")
            return "Photo taken."
        self._start(lambda _p: self._photo(), "Taking a photo…", shown)

    def autofocus(self, at=None):
        at = at or self.focus_point()

        def work(_p):
            z = self.laser.autofocus(self._calibration(), at)
            return z, self._photo()

        def done(result):
            z, rgb = result
            self._clear_references()
            self.show_bed(rgb)
            self.thickness.setValue(z - xtool.FOCUS_OFFSET)
            self._focused(z, f"Measured at X{at[0]:g} Y{at[1]:g} with the blue dot.")
            self._remember()
            return "In focus. Photo refreshed at the new head height; ready to align."
        self._start(work, f"Autofocus at X{at[0]:g} Y{at[1]:g}…", done)

    def set_thickness(self):
        t = self.thickness.value()

        def work(_p):
            z = self.laser.focus(t)
            return z, self._photo()

        def done(result):
            z, rgb = result
            self._clear_references()
            self.show_bed(rgb)
            self._focused(z, f"Set by hand to thickness {t:g}.")
            self._remember()
            return "Head moved; photo refreshed for alignment."
        self._start(work, "Moving the head and refreshing the photo…", done)

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
        if self.kind != "stencil":
            return self._fill()
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
        before = self._raw_rgb
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
            raw = self._raw_photo(like=before)
            try:
                a = self._residual(self._photo(8, raw), 8, holes)
            except Exception:           # noqa: BLE001 - a check, never a failure
                a = None
            return z, self._photo(_PX_PER_MM, raw), a

        def done(res):
            z, rgb, a = res
            self._last_cut_paths = holes
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

    def _fill(self):
        """A traces, solder mask, or silkscreen job."""
        if self._empty:
            return self._say("Nothing loaded to etch: open a Gerber folder or a "
                             "DXF first.", warn=True)
        try:
            if self.kind == "traces":
                job = xtool.traces_job(
                    self.art, self.origin(), self._run_recipe(),
                    only=self.selected or None)
            else:
                _, outline = xtool.stencil_paths(self.art, self.origin())
                job = xtool.fill_job(self._shapes(), outline, self._run_recipe())
        except ValueError as e:
            return self._say(str(e), warn=True)
        self._remember()
        self._job = job
        picked = self.selected or set(range(len(self.art.apertures)))
        self._zone_holes = [picked]
        self.bar.setRange(0, max(1, int(job.seconds)))
        self.bar.setValue(0)
        self.bar.setVisible(True)
        take_photo = self.photo_after.isChecked()
        before = self._raw_rgb

        def work(progress):
            z = self.laser.z()
            self.laser.run(job.text)
            self.laser.wait(job.seconds * 2 + 120, progress=progress)
            return z, (self._photo_after_job(before) if take_photo else None)

        def done(res):
            z, rgb = res
            if rgb is not None:
                self.show_bed(rgb)
            n = len(picked)
            return (f"Done at Z {z:.2f}: {n} {self._noun(n)}, "
                    f"{job.passes} passes. Switch to Outlines to check them on the "
                    f"photo; select any that need more and run those again.")
        what = (f"{len(self.selected)} selected" if self.selected
                else f"{len(picked)} {self._noun(len(picked))}")
        self._start(work, f"{self.k['busy']}: {what}, {job.passes} passes…", done)

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
            text = (f"Pass {rnd + 1} of {rounds}" if self.kind != "stencil" else
                    f"Zone {zone + 1} of {len(job.zones)} · round {rnd + 1} of {rounds}")
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
                  self.mode, self.job_switch, self.strategy,
                  self.rework_btn, self.rework_clear_btn, self.rework_passes,
                  self.all_btn, self.none_btn, self.x, self.y,
                  self.preset, self.save_btn, self.copper_side,
                  self.pick_refs_btn, self.apply_refs_btn, self.remove_ref_btn,
                  self.clear_refs_btn, self.reference_snap, self.auto_reference_source,
                  self.auto_reference_list, self.auto_all_btn, self.auto_none_btn, self.auto_contrast,
                  self.offset_x, self.offset_y, self.calibrate_btn,
                  self.proof_btn, self.proof_where, self.proof_passes):
            b.setEnabled(not on)
        if self.item is not None:
            self.item.setFlag(QGraphicsItem.ItemIsMovable,
                              not on and not self.view.select_mode and not self.view.pick_reference)
        self.view.setEnabled(not on)

    def _say(self, text, warn=False):
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {theme.CAUTION if warn else theme.TEXT_2};")

    def closeEvent(self, e):
        if self._worker is not None and self._worker.isRunning():
            self._say("The laser is still running: press STOP first.", warn=True)
            e.ignore()
            return
        super().closeEvent(e)
