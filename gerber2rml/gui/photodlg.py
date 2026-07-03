"""Photo anchor dialog: click the known holes in a board photo, in order.

The caller supplies the photo (RGBA numpy array) and the ordered anchor list
[(label, (machine_x, machine_y)), ...]. The operator clicks each anchor's
hole in the photo (scroll to zoom, right-click to undo). ``photo_points()``
returns the clicked (u, v) pixel coordinates in the same order.
"""
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QVBoxLayout)
from PySide6.QtCore import Qt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure


class PhotoAnchorDialog(QDialog):
    _MARK = "#4dd0e1"

    def __init__(self, parent, image, anchors):
        super().__init__(parent)
        self.setWindowTitle("Click the anchor holes in the photo")
        self.resize(980, 760)
        self._img = image
        self._anchors = list(anchors)
        self._points = []                       # [(u, v)] clicked, in order
        self._marks = []

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

        self._canvas.mpl_connect("button_press_event", self._on_click)
        self._canvas.mpl_connect("scroll_event", self._on_scroll)
        self._update_prompt()

    # ---- interaction ----------------------------------------------------
    def _on_click(self, ev):
        if ev.inaxes != self._ax or ev.xdata is None:
            return
        if ev.button == 3:                      # right-click: undo last
            if self._points:
                self._points.pop()
                for a in self._marks.pop():
                    a.remove()
                self._update_prompt()
                self._canvas.draw_idle()
            return
        if ev.button != 1 or len(self._points) >= len(self._anchors):
            return
        u, v = float(ev.xdata), float(ev.ydata)
        label = self._anchors[len(self._points)][0]
        self._points.append((u, v))
        self._marks.append([
            self._ax.scatter([u], [v], s=90, facecolors="none",
                             edgecolors=self._MARK, linewidths=1.6, zorder=5),
            self._ax.annotate(label, (u, v), color=self._MARK, fontsize=9,
                              xytext=(6, 6), textcoords="offset points", zorder=5),
        ])
        self._update_prompt()
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
                "Scroll to zoom, right-click to undo.")
            ok.setEnabled(False)
        else:
            self._prompt.setText("All anchors clicked — OK to fit the overlay.")
            ok.setEnabled(True)

    def photo_points(self):
        return list(self._points)
