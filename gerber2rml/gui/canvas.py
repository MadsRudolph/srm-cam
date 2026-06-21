"""Matplotlib preview canvas: draws cut/rapid polylines, or drill holes as circles."""
from PySide6.QtWidgets import QWidget, QVBoxLayout
from matplotlib.figure import Figure
from matplotlib.collections import LineCollection
from matplotlib.patches import Circle
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg


class PreviewCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.figure = Figure(figsize=(5, 5))
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.ax = self.figure.add_subplot(111)
        self.ax.set_aspect("equal")
        layout = QVBoxLayout(self)
        layout.addWidget(self.canvas)

    def show_segments(self, cuts, rapids):
        self.ax.clear()
        self.ax.set_aspect("equal")
        if rapids:
            lc = LineCollection(rapids, colors="0.8", linewidths=0.4)
            self.ax.add_collection(lc, autolim=True)
        if cuts:
            lc = LineCollection(cuts, colors="tab:blue", linewidths=0.8)
            self.ax.add_collection(lc, autolim=True)
        self.ax.relim()
        self.ax.autoscale_view()
        self.ax.margins(0.05)
        self.canvas.draw_idle()

    def show_holes(self, holes):
        """Draw drill holes as true-size circles plus centre marks. Drill
        toolpaths are vertical pecks (no XY extent), so they can't be shown as
        lines — holes are the meaningful preview for the drill operation."""
        self.ax.clear()
        self.ax.set_aspect("equal")
        for (x, y, d) in holes:
            self.ax.add_patch(Circle((x, y), max(d, 0.1) / 2.0, fill=False,
                                     edgecolor="tab:red", linewidth=0.8))
        if holes:
            xs = [h[0] for h in holes]
            ys = [h[1] for h in holes]
            self.ax.scatter(xs, ys, s=8, c="tab:red", marker="+")
            m = 3.0
            self.ax.set_xlim(min(xs) - m, max(xs) + m)
            self.ax.set_ylim(min(ys) - m, max(ys) + m)
        self.canvas.draw_idle()
