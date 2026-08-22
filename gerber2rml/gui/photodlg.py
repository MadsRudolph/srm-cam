"""Photo registration dialogs: choose the anchor holes, then click them.

Two dialogs share one click/zoom/pan canvas:

``HolePickDialog``  — pick WHICH drilled holes anchor the photo. Fiducial /
dowel holes only exist on double-sided jobs; on a single-sided board any 4
ordinary drill holes do the job just as well, so this dialog lets the operator
choose them off the design.

``PhotoAnchorDialog`` — click those anchors in the board photo, in order.
``photo_points()`` returns the clicked (u, v) pixel coordinates in the same
order as the anchor list.
"""
import math

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QVBoxLayout)
from PySide6.QtCore import Qt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from gerber2rml.gui import theme

_PICK = theme.ACCENT       # placed anchor
_DIM = theme.AXIS_LABEL        # hover ring / map labels


def _draw_board(ax, holes, outline=None, hole_color=theme.HOLE):
    """Draw the design context (outline + drill holes) into ``ax``, machine
    frame, y-up. Returns nothing — the caller owns the axes."""
    if outline:
        xs = [p[0] for p in outline] + [outline[0][0]]
        ys = [p[1] for p in outline] + [outline[0][1]]
        ax.plot(xs, ys, color=theme.TEXT_2, linewidth=1.0, zorder=2)
    if holes:
        from matplotlib.patches import Circle
        for (x, y, d) in holes:
            ax.add_patch(Circle((x, y), max(d, 0.1) / 2.0, fill=False,
                                edgecolor=hole_color, linewidth=1.1, zorder=3))
        ax.scatter([h[0] for h in holes], [h[1] for h in holes], s=12,
                   c=hole_color, marker="+", zorder=3)
    ax.set_aspect("equal")
    ax.set_facecolor(theme.BG)


class _PickDialog(QDialog):
    """Prompt + matplotlib canvas + OK/Cancel, with the click/pan/zoom rules
    both anchor dialogs use.

    Left button does double duty: press-and-drag pans, while a plain click
    (release within a few pixels of the press) places the next point.
    Placement happens on RELEASE so a pan never drops a stray mark.
    Right-click undoes the last point, scroll zooms about the cursor.
    """
    _CLICK_SLOP_PX = 4

    def _build(self, title, size=(980, 760), map_panel=False):
        self.setWindowTitle(title)
        self.resize(*size)
        self._points = []                       # placed points, in order
        self._marks = []                        # [artists] per placed point
        self._drag = None                       # left-button pan in progress

        lay = QVBoxLayout(self)
        self._prompt = QLabel()
        self._prompt.setWordWrap(True)
        lay.addWidget(self._prompt)

        fig = Figure(facecolor=theme.BG)
        self._fig = fig
        self._canvas = FigureCanvasQTAgg(fig)
        if map_panel:
            # a small "which hole is it" map of the design beside the photo
            gs = fig.add_gridspec(1, 3)
            self._map_ax = fig.add_subplot(gs[0, 0])
            self._ax = fig.add_subplot(gs[0, 1:])
        else:
            self._map_ax = None
            self._ax = fig.add_subplot(111)
        lay.addWidget(self._canvas, 1)

        self._buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                         | QDialogButtonBox.Cancel)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        lay.addWidget(self._buttons)

        self._canvas.mpl_connect("button_press_event", self._on_press)
        self._canvas.mpl_connect("button_release_event", self._on_release)
        self._canvas.mpl_connect("scroll_event", self._on_scroll)
        self._canvas.mpl_connect("motion_notify_event", self._on_motion)

    # ---- interaction ----------------------------------------------------
    def _on_press(self, ev):
        if ev.inaxes != self._ax:
            return
        if ev.button == 3:                      # right-click: undo last
            self._undo()
            return
        if ev.button == 1:
            self._drag = {"px": (ev.x, ev.y),
                          "xlim": self._ax.get_xlim(),
                          "ylim": self._ax.get_ylim(),
                          "moved": False}

    def _on_release(self, ev):
        drag, self._drag = self._drag, None
        if (ev.button != 1 or drag is None or drag["moved"]
                or ev.inaxes != self._ax or ev.xdata is None
                or not self._can_place()):
            return
        if self._place(float(ev.xdata), float(ev.ydata)) is False:
            return                              # nothing near enough to place
        self._update_prompt()
        self._canvas.draw_idle()

    def _undo(self):
        if not self._points:
            return
        self._points.pop()
        for a in self._marks.pop():
            a.remove()
        self._after_change()
        self._update_prompt()
        self._canvas.draw_idle()

    def _on_motion(self, ev):
        if self._drag is not None:              # left-drag: pan the view
            dx = ev.x - self._drag["px"][0]
            dy = ev.y - self._drag["px"][1]
            if self._drag["moved"] or dx * dx + dy * dy > self._CLICK_SLOP_PX ** 2:
                self._drag["moved"] = True
                x0, x1 = self._drag["xlim"]
                y0, y1 = self._drag["ylim"]
                bb = self._ax.get_window_extent()
                # keep the grabbed point under the cursor; the linear map works
                # unchanged for imshow's inverted y-axis
                kx = (x1 - x0) / max(bb.width, 1)
                ky = (y1 - y0) / max(bb.height, 1)
                self._ax.set_xlim(x0 - dx * kx, x1 - dx * kx)
                self._ax.set_ylim(y0 - dy * ky, y1 - dy * ky)
                self._canvas.draw_idle()
            return
        self._on_hover(ev)

    def _on_scroll(self, ev):
        if ev.inaxes != self._ax or ev.xdata is None:
            return
        s = 1 / 1.3 if ev.button == "up" else 1.3
        x0, x1 = self._ax.get_xlim()
        y0, y1 = self._ax.get_ylim()
        cx, cy = ev.xdata, ev.ydata
        self._ax.set_xlim(cx + (x0 - cx) * s, cx + (x1 - cx) * s)
        self._ax.set_ylim(cy + (y0 - cy) * s, cy + (y1 - cy) * s)
        self._canvas.draw_idle()

    def _view_span(self):
        x0, x1 = sorted(self._ax.get_xlim())
        y0, y1 = sorted(self._ax.get_ylim())
        return max(x1 - x0, y1 - y0, 1e-6)

    # ---- subclass hooks --------------------------------------------------
    def _can_place(self):
        return True

    def _place(self, x, y):
        raise NotImplementedError

    def _after_change(self):
        """Called after an undo, before the prompt refresh."""

    def _on_hover(self, ev):
        """Called on plain mouse motion (no pan in progress)."""

    def _update_prompt(self):
        raise NotImplementedError


class HolePickDialog(_PickDialog):
    """Choose the drilled holes that anchor a board photo.

    Fiducial/dowel holes exist only on double-sided jobs. For single-sided
    rework any 4+ ordinary drill holes anchor the photo just as well — as long
    as they are ones the operator can recognise again in the photo and they
    are spread out rather than bunched in one corner. Click them here in the
    order they will be clicked in the photo; ``anchors()`` returns them as
    ``[(label, (x, y)), ...]`` ready for :class:`PhotoAnchorDialog`.
    """
    MIN_ANCHORS = 4
    _MIN_SPREAD_MM = 3.0        # minor axis of the picked set: kills collinear

    def __init__(self, parent, holes, outline=None, preset=None):
        super().__init__(parent)
        self._holes = [(float(x), float(y), float(d)) for (x, y, d) in holes]
        self._build("Pick the anchor holes")
        _draw_board(self._ax, self._holes, outline)
        self._ax.set_axis_off()
        self._ax.autoscale_view()
        self._fig.tight_layout(pad=0.5)
        self._hover = []
        for p in (preset or []):                # re-open with the last picks
            snap = self._snap(p[0], p[1], tol=0.25)
            if snap is not None and snap not in self._points:
                self._place(snap[0], snap[1])
        self._update_prompt()

    # ---- picking ---------------------------------------------------------
    def _snap(self, x, y, tol=None):
        """Nearest hole center to (x, y) within ``tol`` mm (default: a
        view-relative grab radius, so holes stay clickable zoomed out)."""
        if tol is None:
            tol = 0.03 * self._view_span()
        best, bestd = None, tol
        for (hx, hy, _d) in self._holes:
            d = math.hypot(x - hx, y - hy)
            if d < bestd:
                bestd, best = d, (hx, hy)
        return best

    def _hole_at(self, pt):
        for (hx, hy, d) in self._holes:
            if (hx, hy) == pt:
                return d
        return 0.0

    def _place(self, x, y):
        pt = self._snap(x, y)
        if pt is None or pt in self._points:
            return False                        # empty space / already used
        n = len(self._points) + 1
        self._points.append(pt)
        self._marks.append([
            self._ax.scatter([pt[0]], [pt[1]], s=140, facecolors="none",
                             edgecolors=_PICK, linewidths=1.8, zorder=6),
            self._ax.annotate(str(n), pt, color=_PICK, fontsize=11,
                              fontweight="bold", xytext=(7, 5),
                              textcoords="offset points", zorder=6),
        ])
        return True

    def _clear_hover(self):
        removed = bool(self._hover)
        for a in self._hover:
            a.remove()
        self._hover = []
        return removed

    def _on_hover(self, ev):
        """Ring the hole a click would snap to, so a pick is never a guess."""
        removed = self._clear_hover()
        pt = (self._snap(float(ev.xdata), float(ev.ydata))
              if ev.inaxes == self._ax and ev.xdata is not None else None)
        if pt is not None and pt not in self._points:
            self._hover = [self._ax.scatter([pt[0]], [pt[1]], s=200,
                                            facecolors="none", edgecolors=_DIM,
                                            linewidths=1.2, zorder=5)]
        if removed or self._hover:
            self._canvas.draw_idle()

    def _after_change(self):
        self._renumber()

    def _renumber(self):
        """Undo can leave the labels out of step — rewrite them in place."""
        for i, arts in enumerate(self._marks, 1):
            for a in arts:
                if hasattr(a, "set_text"):
                    a.set_text(str(i))

    # ---- fit sanity ------------------------------------------------------
    def _spread_mm(self):
        """Extent of the picked set along its MINOR axis (mm). Near zero means
        the holes are in a line, which no homography can resolve."""
        if len(self._points) < 3:
            return 0.0
        cx = sum(p[0] for p in self._points) / len(self._points)
        cy = sum(p[1] for p in self._points) / len(self._points)
        # 2x2 scatter matrix -> smaller eigenvalue -> RMS extent across the line
        sxx = sum((p[0] - cx) ** 2 for p in self._points) / len(self._points)
        syy = sum((p[1] - cy) ** 2 for p in self._points) / len(self._points)
        sxy = sum((p[0] - cx) * (p[1] - cy) for p in self._points) / len(self._points)
        tr, det = sxx + syy, sxx * syy - sxy * sxy
        disc = max(tr * tr / 4.0 - det, 0.0)
        return 2.0 * math.sqrt(max(tr / 2.0 - math.sqrt(disc), 0.0))

    def _update_prompt(self):
        n = len(self._points)
        ok = self._buttons.button(QDialogButtonBox.Ok)
        span = self._spread_mm()
        if n < self.MIN_ANCHORS:
            self._prompt.setText(
                f"Click at least <b>{self.MIN_ANCHORS}</b> drill holes to "
                f"anchor the photo — {n} picked. Choose holes you can "
                "recognise again in the photo (big ones, board corners) and "
                "spread them as wide as possible. Scroll to zoom, drag to "
                "pan, right-click to undo.")
            ok.setEnabled(False)
        elif span < self._MIN_SPREAD_MM:
            self._prompt.setText(
                f"<b>{n} holes picked, but they are nearly in a straight "
                f"line</b> ({span:.1f} mm across). A photo fit needs holes "
                "spread in two directions — add one well off that line.")
            ok.setEnabled(False)
        else:
            self._prompt.setText(
                f"<b>{n} anchor holes picked</b> ({span:.0f} mm across the "
                "narrow way). OK, then click these same holes in the photo "
                "in this order. Right-click to undo.")
            ok.setEnabled(True)

    def anchors(self):
        """``[(label, (x, y)), ...]`` in click order. The label is what the
        photo dialog asks for, so it names the hole's size and position."""
        out = []
        for i, (x, y) in enumerate(self._points, 1):
            d = self._hole_at((x, y))
            out.append((f"hole {i} (\N{LATIN CAPITAL LETTER O WITH STROKE}"
                        f"{d:.2f} mm)", (x, y)))
        return out


class PhotoAnchorDialog(_PickDialog):
    """Click the known holes in a board photo, in order.

    The caller supplies the photo (RGBA numpy array) and the ordered anchor
    list ``[(label, (machine_x, machine_y)), ...]``. Pass ``board`` (a dict
    with ``holes`` and optional ``outline``) to show a map of the design
    beside the photo with the wanted hole flagged — with ordinary drill holes
    as anchors, "machine X 43.2 Y 18.7" alone is not something an operator can
    find on a board.
    """
    _MARK = _PICK

    def __init__(self, parent, image, anchors, board=None):
        super().__init__(parent)
        self._img = image
        self._anchors = list(anchors)
        self._guide = []                        # rubber-band line + angle text
        self._build("Click the anchor holes in the photo",
                    map_panel=bool(board))
        self._ax.imshow(image)                  # row 0 on top: photo as shot
        self._ax.set_axis_off()
        self._board = board or {}
        self._map_marks = []
        if self._map_ax is not None:
            _draw_board(self._map_ax, self._board.get("holes") or [],
                        self._board.get("outline"))
            self._map_ax.set_axis_off()
            self._map_ax.set_title("design", color=_DIM, fontsize=9)
            for i, (_lbl, (mx, my)) in enumerate(self._anchors, 1):
                self._map_ax.annotate(str(i), (mx, my), color=_DIM, fontsize=9,
                                      xytext=(6, 4), textcoords="offset points",
                                      zorder=6)
        self._fig.tight_layout(pad=0.5)
        self._update_prompt()

    # ---- placing ---------------------------------------------------------
    def _can_place(self):
        return len(self._points) < len(self._anchors)

    def _place(self, u, v):
        label = self._anchors[len(self._points)][0]
        self._clear_guide()                     # next motion re-aims it
        self._points.append((u, v))
        self._marks.append([
            self._ax.scatter([u], [v], s=90, facecolors="none",
                             edgecolors=self._MARK, linewidths=1.6, zorder=5),
            self._ax.annotate(label, (u, v), color=self._MARK, fontsize=9,
                              xytext=(6, 6), textcoords="offset points", zorder=5),
        ])
        return True

    def _after_change(self):
        self._clear_guide()                     # re-aims from the new last point

    # ---- angle guide -----------------------------------------------------
    # Consecutive anchors form edges whose directions are KNOWN from their
    # machine coordinates. A dotted rubber-band from the last click to the
    # cursor shows the live edge angle against the one the design says to
    # expect; aiming at the wrong hole shows up as a big deviation before the
    # click happens. (For the classic 4 rectangle corners this is the old
    # 0 / +90 / +180 rule, derived instead of assumed.)
    _EXPECT = (0.0, 90.0, 180.0)

    @staticmethod
    def _seg_angle(p0, p1):
        """Direction of p0->p1 in degrees, photo frame: 0 = right, 90 = up
        (image v runs downward, hence the sign flip)."""
        return math.degrees(math.atan2(-(p1[1] - p0[1]), p1[0] - p0[0]))

    def _turn_expected(self, n):
        """Turn (deg) of anchor edge ``n`` (points n-1 -> n) away from edge 1,
        from the anchors' machine coordinates. None when the design can't say
        (missing/coincident anchors), which falls back to the square rule."""
        if n < 2 or len(self._anchors) <= n:
            return None
        (x0, y0), (x1, y1) = self._anchors[0][1], self._anchors[1][1]
        (xa, ya), (xb, yb) = self._anchors[n - 1][1], self._anchors[n][1]
        if math.hypot(x1 - x0, y1 - y0) < 1e-9 or math.hypot(xb - xa, yb - ya) < 1e-9:
            return None
        base = math.degrees(math.atan2(y1 - y0, x1 - x0))
        edge = math.degrees(math.atan2(yb - ya, xb - xa))
        return (edge - base) % 360.0      # 0..360, like the square rule's 90/180

    def _guide_expected(self, n):
        """Expected direction (deg) of edge ``n``. The first edge assumes a
        roughly level photo (~0); later edges are turned off the first edge as
        it was actually clicked, by the angle the design says."""
        if n <= 1 or len(self._points) < 2:
            return self._EXPECT[0]
        base = self._seg_angle(self._points[0], self._points[1])
        turn = self._turn_expected(n)
        if turn is None:
            turn = self._EXPECT[min(n, len(self._EXPECT)) - 1]
        return base + turn

    def _clear_guide(self):
        removed = bool(self._guide)
        for a in self._guide:
            a.remove()
        self._guide = []
        return removed

    def _on_hover(self, ev):
        removed = self._clear_guide()
        n = len(self._points)
        if (ev.inaxes != self._ax or ev.xdata is None
                or n < 1 or n >= len(self._anchors)):
            if removed:
                self._canvas.draw_idle()
            return
        u0, v0 = self._points[-1]
        u, v = float(ev.xdata), float(ev.ydata)
        ang = self._seg_angle((u0, v0), (u, v))
        dev = (ang - self._guide_expected(n) + 180.0) % 360.0 - 180.0
        col = (theme.OK if abs(dev) <= 3.0 else
               theme.STATUS_SPIN if abs(dev) <= 10.0 else theme.DANGER_TEXT)
        line, = self._ax.plot([u0, u], [v0, v], linestyle=":", color=col,
                              linewidth=1.4, zorder=4)
        note = (f"{ang:+.1f}\N{DEGREE SIGN}" if n == 1 else
                f"{ang:+.1f}\N{DEGREE SIGN}  "
                f"(\N{GREEK CAPITAL LETTER DELTA}{dev:+.1f}\N{DEGREE SIGN} "
                f"from the design)")
        text = self._ax.annotate(note, (u, v), color=col, fontsize=9,
                                 xytext=(12, -14), textcoords="offset points",
                                 zorder=4)
        self._guide = [line, text]
        self._canvas.draw_idle()

    # ---- prompt / map ----------------------------------------------------
    def _flag_on_map(self):
        """Ring the anchor being asked for on the design map."""
        if self._map_ax is None:
            return
        for a in self._map_marks:
            a.remove()
        self._map_marks = []
        n = len(self._points)
        for i, (_lbl, (mx, my)) in enumerate(self._anchors):
            col = _PICK if i < n else (theme.STATUS_SPIN if i == n else None)
            if col is None:
                continue
            self._map_marks.append(self._map_ax.scatter(
                [mx], [my], s=200 if i == n else 120, facecolors="none",
                edgecolors=col, linewidths=2.0 if i == n else 1.4, zorder=7))

    def _update_prompt(self):
        n, total = len(self._points), len(self._anchors)
        ok = self._buttons.button(QDialogButtonBox.Ok)
        if n < total:
            label, (mx, my) = self._anchors[n]
            self._prompt.setText(
                f"Click anchor {n + 1}/{total}: <b>{label}</b> "
                f"(machine X {mx:.2f}, Y {my:.2f}). "
                "Scroll to zoom, drag to pan, right-click to undo.")
            ok.setEnabled(False)
        else:
            self._prompt.setText("All anchors clicked — OK to fit the overlay.")
            ok.setEnabled(True)
        self._flag_on_map()

    def photo_points(self):
        return list(self._points)
