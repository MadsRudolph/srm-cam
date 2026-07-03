"""Photo anchor dialog: click the known holes in a board photo, in order.

The caller supplies the photo (RGBA numpy array) and the ordered anchor list
[(label, (machine_x, machine_y)), ...]. The operator clicks each anchor's
hole in the photo (scroll to zoom, right-click to undo). ``photo_points()``
returns the clicked (u, v) pixel coordinates in the same order.
"""
import math

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QVBoxLayout)
from PySide6.QtCore import Qt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure


class PhotoAnchorDialog(QDialog):
    _MARK = "#4dd0e1"
    # Expected direction of each clicked edge, relative to the first one
    # (anchors run bottom-left -> bottom-right -> top-right -> top-left, so
    # the edges of the square turn 0, +90, +180 degrees).
    _EXPECT = (0.0, 90.0, 180.0)

    def __init__(self, parent, image, anchors):
        super().__init__(parent)
        self.setWindowTitle("Click the anchor holes in the photo")
        self.resize(980, 760)
        self._img = image
        self._anchors = list(anchors)
        self._points = []                       # [(u, v)] clicked, in order
        self._marks = []
        self._guide = []                        # rubber-band line + angle text
        self._drag = None                       # left-button pan in progress

        lay = QVBoxLayout(self)
        self._prompt = QLabel()
        self._prompt.setWordWrap(True)
        lay.addWidget(self._prompt)

        fig = Figure(facecolor="#14171c")
        self._canvas = FigureCanvasQTAgg(fig)
        self._ax = fig.add_subplot(111)
        self._ax.imshow(image)                  # row 0 on top: photo as shot
        self._ax.set_axis_off()
        fig.tight_layout(pad=0.5)
        lay.addWidget(self._canvas, 1)

        self._buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        lay.addWidget(self._buttons)

        self._canvas.mpl_connect("button_press_event", self._on_press)
        self._canvas.mpl_connect("button_release_event", self._on_release)
        self._canvas.mpl_connect("scroll_event", self._on_scroll)
        self._canvas.mpl_connect("motion_notify_event", self._on_motion)
        self._update_prompt()

    # ---- interaction ----------------------------------------------------
    # Left button does double duty: press-and-drag pans the photo, while a
    # plain click (release within a few pixels of the press) places the next
    # anchor. Placement happens on RELEASE so a pan never drops a stray mark.
    _CLICK_SLOP_PX = 4

    def _on_press(self, ev):
        if ev.inaxes != self._ax:
            return
        if ev.button == 3:                      # right-click: undo last
            if self._points:
                self._points.pop()
                for a in self._marks.pop():
                    a.remove()
                self._clear_guide()             # re-aims from the new last point
                self._update_prompt()
                self._canvas.draw_idle()
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
                or len(self._points) >= len(self._anchors)):
            return
        u, v = float(ev.xdata), float(ev.ydata)
        label = self._anchors[len(self._points)][0]
        self._clear_guide()                     # next motion re-aims it
        self._points.append((u, v))
        self._marks.append([
            self._ax.scatter([u], [v], s=90, facecolors="none",
                             edgecolors=self._MARK, linewidths=1.6, zorder=5),
            self._ax.annotate(label, (u, v), color=self._MARK, fontsize=9,
                              xytext=(6, 6), textcoords="offset points", zorder=5),
        ])
        self._update_prompt()
        self._canvas.draw_idle()

    # ---- angle guide -----------------------------------------------------
    # The 4 anchors are the corners of a rectangle on the board, so each edge
    # the operator "draws" by clicking should turn exactly 90 degrees from the
    # previous one. A dotted rubber-band from the last click to the cursor
    # shows the live edge angle; aiming at the wrong hole shows up as a big
    # deviation before the click happens.

    @staticmethod
    def _seg_angle(p0, p1):
        """Direction of p0->p1 in degrees, photo frame: 0 = right, 90 = up
        (image v runs downward, hence the sign flip)."""
        return math.degrees(math.atan2(-(p1[1] - p0[1]), p1[0] - p0[0]))

    def _guide_expected(self, n):
        """Expected direction (deg) of edge ``n`` (points n-1 -> n). The first
        edge assumes a roughly level photo (~0); later edges are squared off
        the first edge as it was actually clicked."""
        if n <= 1 or len(self._points) < 2:
            return self._EXPECT[0]
        base = self._seg_angle(self._points[0], self._points[1])
        return base + self._EXPECT[min(n, len(self._EXPECT)) - 1]

    def _clear_guide(self):
        removed = bool(self._guide)
        for a in self._guide:
            a.remove()
        self._guide = []
        return removed

    def _on_motion(self, ev):
        if self._drag is not None:              # left-drag: pan the photo
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
        col = ("#7bd88f" if abs(dev) <= 3.0 else
               "#ffb454" if abs(dev) <= 10.0 else "#ff6666")
        line, = self._ax.plot([u0, u], [v0, v], linestyle=":", color=col,
                              linewidth=1.4, zorder=4)
        note = (f"{ang:+.1f}\N{DEGREE SIGN}" if n == 1 else
                f"{ang:+.1f}\N{DEGREE SIGN}  "
                f"(\N{GREEK CAPITAL LETTER DELTA}{dev:+.1f}\N{DEGREE SIGN} "
                f"from square)")
        text = self._ax.annotate(note, (u, v), color=col, fontsize=9,
                                 xytext=(12, -14), textcoords="offset points",
                                 zorder=4)
        self._guide = [line, text]
        self._canvas.draw_idle()

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

    def photo_points(self):
        return list(self._points)
