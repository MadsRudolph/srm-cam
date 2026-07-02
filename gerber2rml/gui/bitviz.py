"""Tool-profile graphic: a live cross-section of the active trace tool.

For a V-bit it draws the V dipped to its (width-derived) cut depth through the
copper into the stock, with the effective width W, depth D and angle annotated —
making the W = T + 2*D*tan(theta/2) relationship visible at a glance. Hovering
moves an "explore" depth line so the operator can read off how wide the cut
would be at ANY depth, not just the active one. For a flat endmill it draws the
rectangular profile (width is depth-independent).

Pure display: reads a TraceJob, never writes one.
"""
import math

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QPolygonF

_BG = QColor("#1e1e1e")
_STOCK = QColor(115, 78, 45, 120)       # FR substrate
_COPPER = QColor("#b87333")             # copper band at the surface
_BIT_FILL = QColor(205, 205, 215, 100)
_BIT_EDGE = QColor("#dcdcdc")
_CUT = QColor("#00ffff")                # width annotation (matches the preview)
_DEPTH = QColor("#ffb000")              # depth annotation (amber)
_EXPLORE = QColor("#ff79c6")            # hover explore line
_TEXT = QColor("#d4d4d4")

_COPPER_MM = 0.035                      # drawn (exaggerated to a minimum px) band


class BitProfileWidget(QWidget):
    """Cross-section of the active trace tool at its cutting depth."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._job = None
        self._explore_depth = None      # hover depth (mm below surface), or None
        self.setMinimumHeight(150)
        self.setMouseTracking(True)
        self.setToolTip(
            "Cross-section of the active trace tool (from the preset).\n"
            "V-bit: the cut width W grows with depth D as W = tip + 2·D·tan(θ/2).\n"
            "Hover up/down to read the width at any depth; the solid markers show "
            "the actual job depth derived from the target width.")

    # ---- data ----------------------------------------------------------
    def set_job(self, job):
        """Show ``job`` (a TraceJob). Cheap; call on any parameter change."""
        self._job = job
        self.update()

    def width_at(self, depth):
        """Cut width (mm) at ``depth`` for the active tool — the number the
        hover label shows. Flat bits are depth-independent."""
        if self._job is None:
            return 0.0
        if self._job.tool_type == "vbit":
            return self._job.width_at_depth(depth)
        return self._job.bit_diameter

    # ---- geometry helpers ------------------------------------------------
    def _view(self):
        """(surface_y_px, scale_px_per_mm, centre_x_px, depth_span_mm)."""
        j = self._job
        d_job = j.effective_cut_depth()
        span = max(d_job * 1.8, 0.45)               # always show some headroom
        y_surf = 46.0
        scale = (self.height() - y_surf - 30.0) / span
        return y_surf, scale, self.width() / 2.0, span

    # ---- interaction -----------------------------------------------------
    def mouseMoveEvent(self, event):
        if self._job is None:
            return
        y_surf, scale, _cx, span = self._view()
        d = (event.position().y() - y_surf) / scale
        self._explore_depth = min(max(d, 0.0), span) if d > 0.02 else None
        self.update()

    def leaveEvent(self, event):
        self._explore_depth = None
        self.update()

    # ---- painting --------------------------------------------------------
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), _BG)
        if self._job is None:
            p.setPen(_TEXT)
            p.drawText(self.rect(), Qt.AlignCenter, "no tool")
            return
        j = self._job
        y_surf, scale, cx, span = self._view()
        w_px = self.width()

        # stock + copper band (copper exaggerated to stay visible)
        copper_px = max(_COPPER_MM * scale, 3.0)
        p.fillRect(0, int(y_surf), w_px, self.height() - int(y_surf), QBrush(_STOCK))
        p.fillRect(0, int(y_surf - copper_px), w_px, int(copper_px), QBrush(_COPPER))

        d_job = j.effective_cut_depth()
        y_tip = y_surf + d_job * scale

        if j.tool_type == "vbit":
            # V silhouette: flat tip at the bottom, flanks at the half angle,
            # extended up to the top of the widget as the shank direction.
            half = math.radians(j.included_angle) / 2.0
            t2 = j.tip_diameter / 2.0 * scale
            y_top = 6.0
            flank = lambda y: t2 + (y_tip - y) * math.tan(half)  # halfwidth at y px
            poly = QPolygonF([
                QPointF(cx - flank(y_top), y_top),
                QPointF(cx - t2, y_tip),
                QPointF(cx + t2, y_tip),
                QPointF(cx + flank(y_top), y_top),
            ])
            p.setPen(QPen(_BIT_EDGE, 1.4))
            p.setBrush(QBrush(_BIT_FILL))
            p.drawPolygon(poly)
            # angle label beside the upper flank
            p.setPen(_TEXT)
            p.drawText(QPointF(cx + flank(y_top) + 8, y_top + 14),
                       f"{j.included_angle:g}°")
            p.drawText(QPointF(cx + t2 + 6, y_tip + 4),
                       f"tip {j.tip_diameter:g}")
            w_eff = j.effective_diameter()
        else:
            # flat endmill: plain rectangle, width == bit diameter
            b2 = j.bit_diameter / 2.0 * scale
            p.setPen(QPen(_BIT_EDGE, 1.4))
            p.setBrush(QBrush(_BIT_FILL))
            p.drawRect(int(cx - b2), 6, int(2 * b2), int(y_tip - 6))
            w_eff = j.bit_diameter

        # W: double arrow across the cut at the surface (for a V-bit the cut's
        # width at the surface of a D-deep pass IS the effective width)
        hw = w_eff / 2.0 * scale
        yW = y_surf - copper_px - 10
        p.setPen(QPen(_CUT, 1.4))
        p.drawLine(QPointF(cx - hw, yW), QPointF(cx + hw, yW))
        for sx in (cx - hw, cx + hw):
            p.drawLine(QPointF(sx, yW - 4), QPointF(sx, yW + 4))
        p.drawText(QPointF(cx + hw + 8, yW + 4), f"W {w_eff:.2f} mm")

        # D: depth marker from the surface down to the tip
        xD = cx - hw - 14
        p.setPen(QPen(_DEPTH, 1.2))
        p.drawLine(QPointF(xD, y_surf), QPointF(xD, y_tip))
        p.drawLine(QPointF(xD - 4, y_surf), QPointF(xD + 4, y_surf))
        p.drawLine(QPointF(xD - 4, y_tip), QPointF(xD + 4, y_tip))
        p.drawText(QPointF(8, (y_surf + y_tip) / 2 + 4), f"D {d_job:.2f}")

        # hover explore: dashed line + width readout at the chosen depth
        if self._explore_depth is not None and j.tool_type == "vbit":
            de = self._explore_depth
            we = self.width_at(de)
            ye = y_surf + de * scale
            he = we / 2.0 * scale
            pen = QPen(_EXPLORE, 1.2, Qt.DashLine)
            p.setPen(pen)
            p.drawLine(QPointF(cx - max(he, 4) - 20, ye),
                       QPointF(cx + max(he, 4) + 20, ye))
            p.drawText(QPointF(cx + max(he, 4) + 26, ye + 4),
                       f"@ {de:.2f} mm deep: W {we:.2f} mm")
        elif j.tool_type == "vbit":
            p.setPen(QColor("#777777"))
            p.drawText(QPointF(8, self.height() - 8),
                       "hover to read the width at any depth")
        else:
            p.setPen(QColor("#777777"))
            p.drawText(QPointF(8, self.height() - 8),
                       "flat endmill - width is constant with depth")
