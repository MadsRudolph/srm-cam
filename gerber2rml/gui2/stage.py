"""The stage: the machine bed, and the work on it.

This is the one dominant object in the window. Everything else is subordinate
to it, and it is the same object in every context — selecting a step in the
rail changes what is drawn on the stage, it does not change the stage for a
different panel.

Three decisions worth stating, because they are what makes this different from
the first interface's preview rather than merely a restyle of it:

**It is not matplotlib.** The first interface plots into a matplotlib axes,
which brings a plot frame, tick labels, an axis title and a toolbar — the
furniture of a figure in a paper, on a screen where the figure IS the
application. Painting it directly costs about four hundred lines and buys a
canvas with no chrome at all, rulers that sit in the margin instead of a box
around the work, and roughly an order of magnitude more headroom on redraw for
a trace job with tens of thousands of segments.

**Cutting moves are drawn at their real width.** A toolpath drawn as a
one-pixel line tells you where the bit goes. Drawn at the bit's diameter it
tells you what copper survives, which is the question the operator actually
has, and it makes a too-fat bit obvious at a glance instead of at the
multimeter. Below about 1.5 px of real width it falls back to a hairline,
because a sub-pixel stroke is a lie in the other direction.

**One frame, and it is the machine's.** The canvas is always in bed
coordinates — the frame VPanel, the position readout and the operator's hands
are in, and the only frame in which clicking to jog is truthful. The design
frame is available as an explicit X-ray inspection, and when it is on the
whole canvas is tinted and the badge is unmissable, so the two can never be
confused for one another. Every serious scare in this program's history has
been a coordinate-frame presentation problem.
"""
import math

from PySide6.QtCore import Qt, QPointF, QRectF, Signal, QTimer
from PySide6.QtGui import (QPainter, QPen, QBrush, QColor, QPainterPath,
                           QTransform, QCursor, QPolygonF, QFontMetricsF,
                           QPixmap)
from PySide6.QtWidgets import QWidget, QSizePolicy

from gerber2rml.gui2 import theme

BED_MARGIN = 26          # px of margin kept around the bed when fitting
RULER = 22               # px reserved along the left and bottom for the scale


# ---------------------------------------------------------------------------
# shapely -> QPainterPath
# ---------------------------------------------------------------------------

def _ring_to_path(path, coords):
    it = iter(coords)
    try:
        x, y = next(it)[:2]
    except StopIteration:
        return
    path.moveTo(x, y)
    for c in it:
        path.lineTo(c[0], c[1])
    path.closeSubpath()


def geom_to_path(geom):
    """A filled :class:`QPainterPath` for any shapely polygonal geometry.

    Holes come out as holes: Qt's default fill rule is odd-even, so an interior
    ring drawn in the same path is subtracted for free.
    """
    path = QPainterPath()
    if geom is None or geom.is_empty:
        return path
    geoms = getattr(geom, "geoms", None)
    if geoms is not None:
        for g in geoms:
            path.addPath(geom_to_path(g))
        return path
    if geom.geom_type == "Polygon":
        _ring_to_path(path, geom.exterior.coords)
        for interior in geom.interiors:
            _ring_to_path(path, interior.coords)
    elif geom.geom_type in ("LineString", "LinearRing"):
        coords = list(geom.coords)
        if coords:
            path.moveTo(*coords[0][:2])
            for c in coords[1:]:
                path.lineTo(c[0], c[1])
    return path


def polylines_to_path(polylines):
    """One path for a list of ``[(x, y), ...]`` polylines."""
    path = QPainterPath()
    for line in polylines:
        if len(line) < 2:
            continue
        path.moveTo(*line[0])
        for pt in line[1:]:
            path.lineTo(*pt)
    return path


# ---------------------------------------------------------------------------

class Stage(QWidget):
    """The bed, the work, and the toolpaths."""

    placement_changed = Signal(float, float)     # drag finished: total (dx, dy) mm
    placement_dragging = Signal(float, float)    # live during a drag, cheap
    jog_requested = Signal(float, float)         # clicked a target while armed
    hovered = Signal(object)                     # (x, y) mm, or None on leave
    frame_changed = Signal(str)
    region_added = Signal(float, float, float, float)   # a box dragged in mm

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(420, 320)

        self.bed = (203.2, 152.4)
        self.frame = "bed"                # "bed" | "xray"
        self.mode = "place"               # "place" | "jog"

        # content
        self._copper = None
        self._copper_far = None
        self._outline = None
        self._holes = []
        self._align_holes = []
        self._cuts = []
        self._rapids = []
        self._cuts_far = []
        self._shorts = []
        self._probe = []
        self._screws = []
        self._screw_grid = []
        self._regions = []
        self._stock = None                # (x, y, w, h) mm
        self._tool = None                 # (x, y) mm
        self._cut_width = 0.8
        self._show_travel = True
        self._legend = []

        # cached painter paths (mm space)
        self._p_copper = None
        self._p_copper_far = None
        self._p_outline = None
        self._p_cuts = None
        self._p_rapids = None
        self._p_cuts_far = None

        # view
        self._scale = 3.0
        self._origin = QPointF(0, 0)      # px position of bed (0, 0)
        self._fitted = False
        self._panning = False
        self._pan_from = None
        self._pan_start = None
        self._dragging = False
        self._drag_from = None
        self._drag_place0 = None
        self._box_from = None
        self._box_to = None
        # Where the work is drawn RELATIVE to where the geometry says it is.
        # Non-zero only while a drag is in flight: see mouseMoveEvent.
        self._drag_offset = (0.0, 0.0)
        # Rasterised copies of the scene, used only while it is being moved.
        # A trace job for a full-bed board is ~21,000 path elements stroked at
        # true cut width; that is ~180 ms per repaint, which is a slideshow if
        # it happens on every mouse-move. Blitting a pixmap is a memcpy.
        self._drag_raster = None       # the WORK only, for a placement drag
        self._pan_raster = None        # the whole scene, for a pan
        # The drawn scene, kept until something it depends on changes. The
        # overlays that move most often - the live tool position, the hover
        # readout, a rubber box - are NOT in it, so a machine link polling at
        # 3 Hz costs a blit rather than a re-stroke of the whole toolpath.
        self._scene_raster = None

        self._empty_title = "No board loaded"
        self._empty_body = ""
        self._busy = ""

    # -- content -----------------------------------------------------------
    def set_board(self, copper, outline, holes, *, copper_far=None,
                  align_holes=None):
        # Rebuilding a QPainterPath for a full-bed copper pour is not free, and
        # neither is the re-stroke that follows dropping the raster. Selecting
        # a different STEP does not change the board, so recognise that the
        # geometry is the same objects and keep both.
        if (copper is self._copper and outline is self._outline
                and copper_far is self._copper_far
                and holes == self._holes
                and list(align_holes or []) == self._align_holes):
            return
        self._copper, self._outline, self._holes = copper, outline, list(holes or [])
        self._copper_far = copper_far
        self._align_holes = list(align_holes or [])
        self._p_copper = geom_to_path(copper) if copper is not None else None
        self._p_copper_far = (geom_to_path(copper_far)
                              if copper_far is not None else None)
        self._p_outline = geom_to_path(outline) if outline is not None else None
        self._invalidate()
        if not self._fitted:
            self.fit()
        self.update()

    def clear_board(self):
        self._copper = self._outline = self._copper_far = None
        self._p_copper = self._p_outline = self._p_copper_far = None
        self._holes = []
        self._align_holes = []
        self._invalidate()
        self.set_toolpaths([], [])
        self._shorts = []
        self.update()

    def set_toolpaths(self, cuts, rapids, *, far=None, cut_width=None):
        # Same lists AND same width: the built paths and the raster are still
        # valid, so selecting a step we have already drawn is a blit. The empty
        # case needs care - two distinct empty lists are not the same object,
        # and comparing them by identity made every step change re-stroke the
        # whole toolpath for nothing.
        same_far = (far is self._cuts_far) or (not far and not self._cuts_far)
        if (cuts is self._cuts and rapids is self._rapids and same_far
                and (cut_width is None or cut_width == self._cut_width)):
            return
        self._cuts, self._rapids = cuts or [], rapids or []
        self._cuts_far = far or []
        if cut_width:
            self._cut_width = cut_width
        self._p_cuts = polylines_to_path(self._cuts)
        self._p_rapids = polylines_to_path(self._rapids)
        self._p_cuts_far = polylines_to_path(self._cuts_far)
        self._invalidate()
        self.update()

    def set_shorts(self, shorts):
        self._shorts = list(shorts or [])
        self.update()

    def set_probe_points(self, pts):
        pts = list(pts or [])
        if pts == self._probe:
            return
        self._probe = pts
        self._invalidate()
        self.update()

    def set_screws(self, chosen, grid=None):
        chosen = list(chosen or [])
        grid = self._screw_grid if grid is None else list(grid)
        if chosen == self._screws and grid == self._screw_grid:
            return
        self._screws, self._screw_grid = chosen, grid
        self._invalidate()
        self.update()

    def set_regions(self, regions):
        """Rework boxes: ``[(x0, y0, x1, y1, colour), ...]`` in mm."""
        regions = list(regions or [])
        if regions == self._regions:
            return
        self._regions = regions
        self._invalidate()
        self.update()

    def set_stock(self, rect):
        if rect == self._stock:
            return
        self._stock = rect
        self._invalidate()
        self.update()

    def set_tool(self, pos):
        self._tool = pos
        self.update()

    def set_travel_visible(self, on):
        if bool(on) == self._show_travel:
            return
        self._show_travel = bool(on)
        self._invalidate()
        self.update()

    def set_legend(self, entries):
        """``[(colour, text), ...]`` drawn bottom-right. A colour the reader has
        to guess at is a colour that is not carrying anything."""
        self._legend = list(entries or [])
        self.update()

    def set_empty(self, title, body=""):
        self._empty_title, self._empty_body = title, body
        self.update()

    def set_busy(self, text=""):
        self._busy = text
        self.update()

    def set_frame(self, frame):
        if frame != self.frame:
            self.frame = frame
            self._invalidate()
            self.frame_changed.emit(frame)
            self.update()

    def set_mode(self, mode):
        self.mode = mode
        self.setCursor(QCursor(Qt.CrossCursor if mode == "jog"
                               else Qt.ArrowCursor))
        self.update()

    def has_board(self):
        return self._outline is not None or self._copper is not None

    # -- view --------------------------------------------------------------
    def _world(self):
        t = QTransform()
        t.translate(self._origin.x(), self._origin.y())
        t.scale(self._scale, -self._scale)
        return t

    def to_mm(self, pt):
        inv, ok = self._world().inverted()
        return inv.map(QPointF(pt)) if ok else QPointF(0, 0)

    def to_px(self, x, y):
        return self._world().map(QPointF(x, y))

    def to_px_work(self, x, y):
        """Device position of a point that belongs to the WORK, so it follows a
        drag in flight rather than staying behind on the bed."""
        dx, dy = self._drag_offset
        return self._world().map(QPointF(x + dx, y + dy))

    def fit(self, target=None):
        """Frame ``target`` = (x0, y0, x1, y1) mm, or the whole bed."""
        w = max(self.width() - RULER - BED_MARGIN * 2, 60)
        h = max(self.height() - RULER - BED_MARGIN * 2, 60)
        if target is None:
            x0, y0, x1, y1 = 0, 0, self.bed[0], self.bed[1]
        else:
            x0, y0, x1, y1 = target
            pad = max((x1 - x0), (y1 - y0)) * 0.08 + 2
            x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
        span_x, span_y = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
        self._scale = min(w / span_x, h / span_y)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        vx = RULER + (self.width() - RULER) / 2
        vy = (self.height() - RULER) / 2
        self._origin = QPointF(vx - cx * self._scale, vy + cy * self._scale)
        self._fitted = True
        self._invalidate()
        self.update()

    def fit_work(self):
        """Frame the work if there is any, else the bed."""
        b = self._work_bounds()
        self.fit(b)

    def _work_bounds(self):
        boxes = []
        for g in (self._outline, self._copper, self._copper_far):
            if g is not None and not g.is_empty:
                boxes.append(g.bounds)
        if self._stock:
            x, y, w, h = self._stock
            boxes.append((x, y, x + w, y + h))
        for (x, y, d) in self._align_holes:
            boxes.append((x - d, y - d, x + d, y + d))
        if not boxes:
            return None
        return (min(b[0] for b in boxes), min(b[1] for b in boxes),
                max(b[2] for b in boxes), max(b[3] for b in boxes))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._invalidate()
        if not self._fitted:
            self.fit()

    def wheelEvent(self, e):
        d = e.angleDelta().y()
        if not d:
            return
        before = self.to_mm(e.position())
        self._scale *= 1.0015 ** d
        self._scale = max(0.4, min(self._scale, 400.0))
        self._invalidate()        # the raster was rendered at the old scale
        after = self.to_mm(e.position())
        self._origin += QPointF((after.x() - before.x()) * self._scale,
                                -(after.y() - before.y()) * self._scale)
        self._fitted = True
        self.update()

    # -- interaction -------------------------------------------------------
    def mousePressEvent(self, e):
        if e.button() in (Qt.MiddleButton, Qt.RightButton):
            self._panning = True
            self._pan_from = e.position()
            self._pan_start = e.position()
            self._begin_move("pan")
            self.setCursor(QCursor(Qt.ClosedHandCursor))
            return
        if e.button() != Qt.LeftButton:
            return
        p = self.to_mm(e.position())
        if self.mode == "jog":
            self.jog_requested.emit(p.x(), p.y())
            return
        if self.mode == "box":
            self._box_from = p
            self._box_to = p
            return
        if self._over_work(p):
            self._dragging = True
            self._drag_from = p
            self._begin_move("drag")
            self.setCursor(QCursor(Qt.SizeAllCursor))

    def _over_work(self, p):
        b = self._work_bounds()
        if not b:
            return False
        dx, dy = self._drag_offset
        x0, y0, x1, y1 = b
        return (x0 + dx <= p.x() <= x1 + dx) and (y0 + dy <= p.y() <= y1 + dy)

    def mouseMoveEvent(self, e):
        if self._panning:
            d = e.position() - self._pan_from
            self._origin += d
            self._pan_from = e.position()
            self._scene_raster = None
            if self._pan_raster is not None:
                self._pan_raster = (self._pan_raster[0],
                                    e.position() - self._pan_start)
            self.update()
            return
        p = self.to_mm(e.position())
        if self._box_from is not None:
            self._box_to = p
            self.hovered.emit((p.x(), p.y()))
            self.update()
            return
        if self._dragging:
            # A drag does NOT move the geometry — it moves where the geometry
            # is drawn, and nothing is regenerated until the mouse comes up.
            #
            # It used to emit on every mouse-move, and the receiver re-read the
            # Gerbers off disk and re-ran the isolation offsetter each time. On
            # a full-bed double-sided board that is hundreds of milliseconds per
            # mouse event, so the board crawled behind the cursor. Translating
            # cached paths is a transform, and costs nothing.
            self._drag_offset = (p.x() - self._drag_from.x(),
                                 p.y() - self._drag_from.y())
            self.placement_dragging.emit(*self._drag_offset)
            self.update()
            return
        self.hovered.emit((p.x(), p.y()))
        if self.mode == "place":
            self.setCursor(QCursor(Qt.OpenHandCursor if self._over_work(p)
                                   else Qt.ArrowCursor))

    def mouseReleaseEvent(self, e):
        if self._panning or self._dragging:
            self._invalidate()
        if self._box_from is not None and self._box_to is not None:
            a, b = self._box_from, self._box_to
            self._box_from = self._box_to = None
            # A stray click is not a region. Below a millimetre square there is
            # nothing a 0.8 mm cutter could usefully be asked to re-do.
            if abs(a.x() - b.x()) > 1.0 and abs(a.y() - b.y()) > 1.0:
                self.region_added.emit(a.x(), a.y(), b.x(), b.y())
            self.update()
            return
        if self._panning:
            self._panning = False
            self.setCursor(QCursor(Qt.ArrowCursor))
        if self._dragging:
            self._dragging = False
            dx, dy = self._drag_offset
            self._drag_offset = (0.0, 0.0)
            self.setCursor(QCursor(Qt.OpenHandCursor))
            if dx or dy:
                # One commit, at the end. This is the only expensive moment.
                self.placement_changed.emit(dx, dy)

    def leaveEvent(self, e):
        self.hovered.emit(None)
        super().leaveEvent(e)

    # -- painting ----------------------------------------------------------
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QColor(theme.INK))
        if self.frame == "xray":
            # The design frame gets its own ground, not just a badge. Two views
            # that differ only by a label are two views that get confused.
            p.fillRect(self.rect(), theme.alpha(theme.LIVE, 0.045))

        if self._pan_raster is not None:
            # Panning moves everything, so the whole scene is one blit. The
            # rulers are redrawn live below, because their labels belong to the
            # new view rather than the old one.
            p.drawPixmap(self._pan_raster[1], self._pan_raster[0])
        else:
            w = self._world()
            # The machine does not move when you drag the job across it, so the
            # bed, its grid, the copper sheet, the hold-down screws and any
            # rework boxes are painted BEFORE the drag offset is applied. Only
            # the work itself follows the cursor.
            p.save()
            p.setTransform(w, True)
            self._paint_static(p)
            p.restore()
            dx, dy = self._drag_offset
            if self._drag_raster is not None:
                p.drawPixmap(QPointF(dx * self._scale, -dy * self._scale),
                             self._drag_raster)
            elif dx or dy:
                p.save()
                p.setTransform(w, True)
                p.translate(dx, dy)
                self._paint_work(p)
                p.restore()
            else:
                if self._scene_raster is None:
                    self._scene_raster = self._raster(self._paint_work)
                p.drawPixmap(QPointF(0, 0), self._scene_raster)

        self._paint_box(p)
        self._paint_shorts(p)
        self._paint_tool(p)
        self._paint_rulers(p)
        self._paint_frame_badge(p)
        self._paint_legend(p)
        if not self.has_board():
            self._paint_empty(p)
        if self._busy:
            self._paint_busy(p)
        p.end()

    def _paint_static(self, p):
        """What belongs to the machine, and stays put when the job is moved."""
        self._paint_bed(p)
        self._paint_stock(p)
        self._paint_screw_grid(p)
        self._paint_regions(p)

    def _paint_work(self, p):
        """What belongs to the job, and follows the cursor when it is dragged."""
        self._paint_copper(p)
        self._paint_paths(p)
        self._paint_holes(p)
        self._paint_fixtures(p)
        self._paint_probe(p)

    def _raster(self, what):
        """Render ``what(painter)`` under the world transform into a pixmap.

        Transparent ground, so a work raster composites over the bed that is
        painted live underneath it.
        """
        dpr = self.devicePixelRatioF()
        pm = QPixmap(max(int(self.width() * dpr), 1),
                     max(int(self.height() * dpr), 1))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setTransform(self._world(), True)
        what(p)
        p.end()
        return pm

    def _begin_move(self, kind):
        """Freeze the expensive layers before a drag or a pan starts."""
        if kind == "drag":
            # The cached scene IS the work layer, already rendered at this
            # view. Reusing it means the first millimetre of a drag costs
            # nothing; rendering a second copy of the same thing would make
            # the drag feel like it sticks before it lets go.
            self._drag_raster = (self._scene_raster if self._scene_raster
                                 is not None else self._raster(self._paint_work))
        else:
            self._pan_raster = (self._raster(
                lambda p: (self._paint_static(p), self._paint_work(p))),
                QPointF(0, 0))

    def _end_move(self):
        self._drag_raster = None
        self._pan_raster = None

    def _invalidate(self):
        """The drawn scene is stale: the content or the view changed."""
        self._scene_raster = None
        self._drag_raster = None
        self._pan_raster = None

    # bed ------------------------------------------------------------------
    def _paint_bed(self, p):
        bx, by = self.bed
        p.fillRect(QRectF(0, 0, bx, by), QColor(theme.BED))
        step = 10.0
        if self._scale * step < 6:                # too dense to read: 50 mm only
            step = 50.0
        pen = QPen(QColor(theme.GRID), 0)
        pen.setCosmetic(True)
        n = 0
        x = 0.0
        while x <= bx + 1e-6:
            pen.setColor(QColor(theme.GRID_10 if n % 5 == 0 else theme.GRID))
            p.setPen(pen)
            p.drawLine(QPointF(x, 0), QPointF(x, by))
            x += step
            n += 1
        n = 0
        y = 0.0
        while y <= by + 1e-6:
            pen.setColor(QColor(theme.GRID_10 if n % 5 == 0 else theme.GRID))
            p.setPen(pen)
            p.drawLine(QPointF(0, y), QPointF(bx, y))
            y += step
            n += 1
        edge = QPen(QColor(theme.BED_EDGE), 0)
        edge.setCosmetic(True)
        p.setPen(edge)
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(0, 0, bx, by))
        # The machine origin. Everything in this program is measured from here
        # and the origin is never moved in XY, so it is drawn as a datum mark
        # rather than as an axis crossing.
        o = QPen(QColor(theme.FIXTURE), 0)
        o.setCosmetic(True)
        p.setPen(o)
        p.drawLine(QPointF(-3.5, 0), QPointF(3.5, 0))
        p.drawLine(QPointF(0, -3.5), QPointF(0, 3.5))

    def _paint_stock(self, p):
        if not self._stock:
            return
        x, y, w, h = self._stock
        p.fillRect(QRectF(x, y, w, h), QColor(theme.COPPER_FILL))
        pen = QPen(QColor(theme.COPPER_DIM), 0)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(x, y, w, h))

    def _paint_copper(self, p):
        if self._p_copper_far is not None and self.frame == "xray":
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(theme.alpha(theme.PATH_FAR, 0.16)))
            p.drawPath(self._p_copper_far)
        if self._p_copper is not None:
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(theme.alpha(theme.COPPER, 0.22)))
            p.drawPath(self._p_copper)
        if self._p_outline is not None:
            pen = QPen(QColor(theme.OUTLINE), 0)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPath(self._p_outline)

    def _paint_regions(self, p):
        for (x0, y0, x1, y1, colour) in self._regions:
            r = QRectF(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
            p.fillRect(r, theme.alpha(colour, 0.16))
            pen = QPen(QColor(colour), 0)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)

    def _paint_paths(self, p):
        if self._show_travel and self._p_rapids is not None:
            pen = QPen(QColor(theme.TRAVEL), 0)
            pen.setCosmetic(True)
            pen.setStyle(Qt.DotLine)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPath(self._p_rapids)
        for path, colour in ((self._p_cuts_far, theme.PATH_FAR),
                             (self._p_cuts, theme.PATH)):
            if path is None or path.isEmpty():
                continue
            width_px = self._cut_width * self._scale
            pen = QPen(QColor(colour))
            if width_px >= 1.5:
                # True cut width: what you see is the copper that goes away.
                pen.setWidthF(self._cut_width)
                pen.setColor(theme.alpha(colour, 0.85))
            else:
                pen.setCosmetic(True)
                pen.setWidthF(1.0)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)

    def _paint_holes(self, p):
        if not self._holes:
            return
        pen = QPen(QColor(theme.HOLE), 0)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(QBrush(theme.alpha(theme.HOLE, 0.20)))
        for (x, y, d) in self._holes:
            r = max(d, 0.2) / 2.0
            p.drawEllipse(QPointF(x, y), r, r)

    def _paint_screw_grid(self, p):
        """Holes in the spoilboard and the screws in them. Bed furniture: these
        stay put when the job is dragged across them."""
        if self._screw_grid:
            g = QPen(theme.alpha(theme.FIXTURE, 0.18), 0)
            g.setCosmetic(True)
            p.setPen(g)
            p.setBrush(Qt.NoBrush)
            for (x, y) in self._screw_grid:
                p.drawEllipse(QPointF(x, y), 2.0, 2.0)
        pen = QPen(QColor(theme.FIXTURE), 0)
        pen.setCosmetic(True)
        for (x, y) in self._screws:
            # Drawn at true head diameter (8 mm): the question is whether a
            # screw head lands on a track, and the hole is not what collides.
            p.setPen(pen)
            p.setBrush(QBrush(theme.alpha(theme.FIXTURE, 0.30)))
            p.drawEllipse(QPointF(x, y), 4.0, 4.0)

    def _paint_fixtures(self, p):
        """The registration pins, which belong to the job and move with it."""
        pen = QPen(QColor(theme.FIXTURE), 0)
        pen.setCosmetic(True)
        for (x, y, d) in self._align_holes:
            p.setPen(pen)
            p.setBrush(QBrush(theme.alpha(theme.FIXTURE, 0.28)))
            p.drawEllipse(QPointF(x, y), d / 2.0, d / 2.0)

    def _paint_probe(self, p):
        if not self._probe:
            return
        pen = QPen(QColor(theme.PROBE), 0)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        for pt in self._probe:
            x, y = pt[0], pt[1]
            p.drawLine(QPointF(x - 1.2, y), QPointF(x + 1.2, y))
            p.drawLine(QPointF(x, y - 1.2), QPointF(x, y + 1.2))

    # device-space overlays -------------------------------------------------
    def _paint_box(self, p):
        """The rubber box, drawn in device space so the 1 px edge stays 1 px."""
        if self._box_from is None or self._box_to is None:
            return
        a = self.to_px(self._box_from.x(), self._box_from.y())
        b = self.to_px(self._box_to.x(), self._box_to.y())
        r = QRectF(a, b).normalized()
        p.fillRect(r, theme.alpha(theme.PATH, 0.10))
        p.setPen(QPen(QColor(theme.PATH), 1, Qt.DashLine))
        p.setBrush(Qt.NoBrush)
        p.drawRect(r)

    def _paint_shorts(self, p):
        """Marked in device space so a short stays findable at any zoom.

        A short drawn in millimetres disappears when you zoom out to check the
        placement, which is exactly when you most want to know the board has
        thirteen of them.
        """
        if not self._shorts:
            return
        pen = QPen(QColor(theme.DANGER), 1.6)
        p.setBrush(Qt.NoBrush)
        for s in self._shorts:
            c = self.to_px_work(s["x"], s["y"])
            p.setPen(QPen(theme.alpha(theme.DANGER, 0.20), 7))
            p.drawPoint(c)
            p.setPen(pen)
            p.drawLine(c + QPointF(-4, -4), c + QPointF(4, 4))
            p.drawLine(c + QPointF(-4, 4), c + QPointF(4, -4))

    def _paint_tool(self, p):
        if not self._tool:
            return
        c = self.to_px(*self._tool)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(theme.alpha(theme.TOOL, 0.55), 1.0))
        p.drawEllipse(c, 11, 11)
        p.setPen(QPen(QColor(theme.TOOL), 1.4))
        p.drawEllipse(c, 4, 4)
        p.drawLine(c + QPointF(-9, 0), c + QPointF(-6, 0))
        p.drawLine(c + QPointF(6, 0), c + QPointF(9, 0))
        p.drawLine(c + QPointF(0, -9), c + QPointF(0, -6))
        p.drawLine(c + QPointF(0, 6), c + QPointF(0, 9))

    def _paint_rulers(self, p):
        """The scale sits in the margin, not in a box around the work.

        A plot frame says "this is a figure". A pair of edge scales says "this
        is a bed", which is what it is.
        """
        f = theme.font("micro", mono=True)
        p.setFont(f)
        fm = QFontMetricsF(f)
        h, w = self.height(), self.width()
        p.fillRect(QRectF(0, h - RULER, w, RULER), QColor(theme.BASE))
        p.fillRect(QRectF(0, 0, RULER, h - RULER), QColor(theme.BASE))
        p.setPen(QPen(QColor(theme.RULE), 1))
        p.drawLine(QPointF(0, h - RULER + 0.5), QPointF(w, h - RULER + 0.5))
        p.drawLine(QPointF(RULER - 0.5, 0), QPointF(RULER - 0.5, h - RULER))

        step = self._nice_step()
        pen_t = QPen(QColor(theme.TEXT_4), 1)
        x = 0.0
        while x <= self.bed[0] + 1e-6:
            px = self.to_px(x, 0).x()
            if RULER < px < w:
                p.setPen(pen_t)
                p.drawLine(QPointF(px, h - RULER), QPointF(px, h - RULER + 4))
                s = f"{x:g}"
                p.setPen(QPen(QColor(theme.TEXT_3), 1))
                p.drawText(QPointF(px - fm.horizontalAdvance(s) / 2,
                                   h - RULER + 15), s)
            x += step
        y = 0.0
        while y <= self.bed[1] + 1e-6:
            py = self.to_px(0, y).y()
            if 0 < py < h - RULER:
                p.setPen(pen_t)
                p.drawLine(QPointF(RULER - 4, py), QPointF(RULER, py))
                s = f"{y:g}"
                p.setPen(QPen(QColor(theme.TEXT_3), 1))
                p.save()
                p.translate(RULER - 6, py + fm.horizontalAdvance(s) / 2)
                p.rotate(-90)
                p.drawText(QPointF(0, 0), s)
                p.restore()
            y += step
        p.setPen(QPen(QColor(theme.TEXT_4), 1))
        p.setFont(theme.font("micro"))
        p.drawText(QRectF(0, h - RULER, RULER, RULER),
                   Qt.AlignCenter, "mm")

    def _nice_step(self):
        """A ruler step that lands on a round number and stays legible."""
        for candidate in (1, 2, 5, 10, 20, 25, 50, 100):
            if candidate * self._scale >= 46:
                return float(candidate)
        return 100.0

    def _paint_frame_badge(self, p):
        if self.frame != "xray":
            return
        f = theme.font("label")
        p.setFont(f)
        fm = QFontMetricsF(f)
        text = "DESIGN X-RAY — NOT WHAT THE MACHINE CUTS"
        wpx = fm.horizontalAdvance(text) + 22
        r = QRectF(RULER + 12, 12, wpx, 26)
        p.setPen(QPen(QColor(theme.LIVE), 1))
        p.setBrush(QBrush(QColor(theme.LIVE_FILL)))
        p.drawRoundedRect(r, theme.RADIUS_CHIP, theme.RADIUS_CHIP)
        p.setPen(QPen(QColor(theme.LIVE), 1))
        p.drawText(r, Qt.AlignCenter, text)

    def _paint_legend(self, p):
        if not self._legend:
            return
        f = theme.font("micro")
        p.setFont(f)
        fm = QFontMetricsF(f)
        pad, row_h, swatch = 10, 15, 9
        wpx = max(fm.horizontalAdvance(t) for _c, t in self._legend) + swatch + pad * 2 + 8
        hpx = row_h * len(self._legend) + pad * 2 - 3
        x = self.width() - wpx - 12
        y = self.height() - RULER - hpx - 12
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(theme.alpha(theme.BASE, 0.88)))
        p.drawRoundedRect(QRectF(x, y, wpx, hpx), theme.RADIUS, theme.RADIUS)
        p.setPen(QPen(QColor(theme.RULE), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(x, y, wpx, hpx), theme.RADIUS, theme.RADIUS)
        for i, (colour, text) in enumerate(self._legend):
            cy = y + pad + i * row_h
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(colour)))
            p.drawRect(QRectF(x + pad, cy + 2, swatch, 3))
            p.setPen(QPen(QColor(theme.TEXT_3), 1))
            p.drawText(QPointF(x + pad + swatch + 8, cy + 8), text)

    def _paint_empty(self, p):
        """The empty state is a designed state, not an absence.

        It shows the bed at true size with the origin marked, so the first
        thing a person learns is what the machine's work area looks like and
        where its zero is — which is the thing they will be asked about in
        thirty seconds.
        """
        cx = RULER + (self.width() - RULER) / 2
        cy = (self.height() - RULER) / 2
        p.setFont(theme.font("title"))
        fm = QFontMetricsF(p.font())
        p.setPen(QPen(QColor(theme.TEXT_2), 1))
        p.drawText(QPointF(cx - fm.horizontalAdvance(self._empty_title) / 2,
                           cy), self._empty_title)
        if self._empty_body:
            p.setFont(theme.font("body"))
            fm2 = QFontMetricsF(p.font())
            p.setPen(QPen(QColor(theme.TEXT_4), 1))
            p.drawText(QPointF(cx - fm2.horizontalAdvance(self._empty_body) / 2,
                               cy + 26), self._empty_body)

    def _paint_busy(self, p):
        p.fillRect(self.rect(), theme.alpha(theme.INK, 0.55))
        p.setFont(theme.font("head"))
        fm = QFontMetricsF(p.font())
        cx = RULER + (self.width() - RULER) / 2
        cy = (self.height() - RULER) / 2
        p.setPen(QPen(QColor(theme.TEXT_2), 1))
        p.drawText(QPointF(cx - fm.horizontalAdvance(self._busy) / 2, cy),
                   self._busy)
