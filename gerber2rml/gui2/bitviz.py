"""What a V-bit actually cuts, drawn to scale.

A flat endmill cuts its own diameter no matter how deep it goes, so its width
is a number and a number is enough. A V-bit does not: the width IS the depth,
through ``W = T + 2 D tan(theta/2)``, and a tenth of a millimetre of Z is the
difference between separating two 0.2 mm tracks and merging them.

That relationship is the one thing an operator has to hold in their head when
they pick a depth, and prose does not carry it. So this draws the tool in the
copper at the depth it will actually run, and lets the pointer walk the depth
so the width can be read off anywhere - the same question the flex margin now
asks silently every time it deepens a cut.

Shown only for a V-bit, because for a flat bit there is nothing to see: the
picture would be a rectangle whose width never changes, which is exactly what
the text already says.

Pure display. It reads a TraceJob and never writes one.
"""
import math

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QPolygonF
from PySide6.QtWidgets import QWidget

from gerber2rml.gui2 import theme

FOIL_MM = 0.035          # copper on FR-4; drawn with a floor so it stays visible


class BitProfile(QWidget):
    """A cross-section of the trace tool, at the depth it will cut."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._job = None
        self._explore = None          # depth the pointer is asking about
        self.setMinimumHeight(148)
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)

    # -- state -------------------------------------------------------------
    def set_job(self, job):
        self._job = job
        self.setVisible(job is not None and job.tool_type == "vbit")
        self.update()

    def _width_at(self, depth):
        j = self._job
        if j is None:
            return 0.0
        return (j.width_at_depth(depth) if j.tool_type == "vbit"
                else j.bit_diameter)

    def _view(self):
        """(surface y, px per mm vertically, centre x, depth shown)."""
        d = max(self._job.effective_cut_depth(), 1e-4)
        span = max(d * 1.9, 0.45)                   # headroom below the cut
        y_surf = 56.0                               # room for the width call-out
        return y_surf, (self.height() - y_surf - 30.0) / span, self.width() / 2.0, span

    # -- interaction -------------------------------------------------------
    def mouseMoveEvent(self, e):
        if self._job is None:
            return
        y_surf, scale, _cx, span = self._view()
        d = (e.position().y() - y_surf) / scale
        self._explore = min(max(d, 0.0), span) if d > 0.02 else None
        self.update()

    def leaveEvent(self, _e):
        self._explore = None
        self.update()

    # -- painting ----------------------------------------------------------
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QColor(theme.INK))
        if self._job is None or self._job.tool_type != "vbit":
            p.end()
            return
        j = self._job
        y_surf, scale, cx, span = self._view()
        w = self.width()
        depth = j.effective_cut_depth()
        # Horizontal scale is its own: the widths involved are a few tenths of
        # a millimetre against a depth of one, and drawing both at the same
        # scale makes a needle nobody can read.
        widest = max(self._width_at(span), j.tip_diameter * 3, 0.3)
        hx = (w * 0.42) / widest

        # --- the stock, and the copper skin on top of it ------------------
        p.fillRect(QRectF(0, y_surf, w, self.height() - y_surf),
                   QColor(theme.COPPER_FILL))
        p.setPen(QPen(theme.alpha(theme.COPPER_DIM, 0.5), 1))
        p.setBrush(Qt.NoBrush)
        for k in range(1, 6):                        # a little laminate hatch
            yy = y_surf + (self.height() - y_surf) * k / 6.0
            p.drawLine(QPointF(0, yy), QPointF(w, yy))
        foil = max(FOIL_MM * scale, 3.0)             # a floor, or it vanishes
        half = self._width_at(depth) / 2.0

        # --- the tool itself, sitting in that cut -------------------------
        # Drawn from the top of the widget down to the tip, so the flanks run
        # off the top edge the way a real bit disappears into the collet
        # rather than stopping in mid-air at an arbitrary height.
        tip_y = y_surf + depth * scale
        rise = tip_y                                # px from the tip to y=0
        half_at_top = (j.tip_diameter / 2.0) + (rise / scale) * math.tan(
            math.radians(j.included_angle) / 2.0)
        body = QPolygonF([QPointF(cx - (j.tip_diameter / 2.0) * hx, tip_y),
                          QPointF(cx - half_at_top * hx, 0.0),
                          QPointF(cx + half_at_top * hx, 0.0),
                          QPointF(cx + (j.tip_diameter / 2.0) * hx, tip_y)])
        p.setBrush(QBrush(theme.alpha(theme.TEXT_2, 0.22)))
        pen = QPen(theme.alpha(theme.TEXT_3, 0.9), 1)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.drawPolygon(body)

        # --- the copper, LAST and interrupted by the cut -------------------
        # Painted over the tool and stopping either side of it, so the gap in
        # the band is the cut width itself. That gap is the whole subject: it
        # is what separates one track from the next, and drawing the band
        # unbroken under a tool that is removing it says the opposite.
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(theme.COPPER)))
        p.drawRect(QRectF(0, y_surf, cx - half * hx, foil))
        p.drawRect(QRectF(cx + half * hx, y_surf, w - (cx + half * hx), foil))

        # --- the width it makes, called out just above the copper ---------
        y_w = y_surf - 13
        p.setPen(QPen(QColor(theme.PATH), 2))
        p.drawLine(QPointF(cx - half * hx, y_w), QPointF(cx + half * hx, y_w))
        for sx in (cx - half * hx, cx + half * hx):   # end ticks, so the span
            p.drawLine(QPointF(sx, y_w - 4), QPointF(sx, y_w + 4))
        p.setFont(theme.font("label"))
        p.setPen(QPen(QColor(theme.PATH)))
        p.drawText(QRectF(0, y_w - 22, w, 18), Qt.AlignHCenter,
                   "%.3f mm wide" % self._width_at(depth))

        # --- and the depth that bought it ---------------------------------
        p.setPen(QPen(theme.alpha(theme.CAUTION, 0.9), 1, Qt.DashLine))
        p.drawLine(QPointF(0, tip_y), QPointF(w, tip_y))
        p.setPen(QPen(QColor(theme.CAUTION)))
        p.drawText(QRectF(6, tip_y + 2, w - 12, 16), Qt.AlignLeft,
                   "%.3f mm deep" % depth)

        # --- what it WOULD be, wherever the pointer is --------------------
        if self._explore is not None:
            ey = y_surf + self._explore * scale
            ew = self._width_at(self._explore)
            p.setPen(QPen(QColor(theme.LIVE), 1, Qt.DotLine))
            p.drawLine(QPointF(0, ey), QPointF(w, ey))
            p.setPen(QPen(QColor(theme.LIVE), 2))
            p.drawLine(QPointF(cx - (ew / 2.0) * hx, ey),
                       QPointF(cx + (ew / 2.0) * hx, ey))
            p.setPen(QPen(QColor(theme.LIVE)))
            p.drawText(QRectF(6, ey - 18, w - 12, 16), Qt.AlignRight,
                       "%.3f mm deep -> %.3f mm wide" % (self._explore, ew))
        else:
            p.setPen(QPen(QColor(theme.TEXT_3)))
            p.setFont(theme.font("label"))
            p.drawText(QRectF(6, self.height() - 20, w - 12, 16),
                       Qt.AlignHCenter,
                       "%.0f° included, %.2f mm tip · point at it to "
                       "read any depth" % (j.included_angle, j.tip_diameter))
        p.end()
