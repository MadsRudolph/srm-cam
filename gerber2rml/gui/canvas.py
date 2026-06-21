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

    def show_segments(self, cuts, rapids, holes=None):
        """Draw cut (solid blue) and rapid (light) polylines, and optionally
        overlay drill holes as true-size red circles with centre marks. Drill
        toolpaths are vertical pecks (no XY extent), so holes are shown as
        circles overlaid on the trace context rather than as lines."""
        self.ax.clear()
        self.ax.set_aspect("equal")
        if rapids:
            self.ax.add_collection(
                LineCollection(rapids, colors="0.8", linewidths=0.4), autolim=True)
        if cuts:
            self.ax.add_collection(
                LineCollection(cuts, colors="tab:blue", linewidths=0.8), autolim=True)
        if holes:
            for (x, y, d) in holes:
                self.ax.add_patch(Circle((x, y), max(d, 0.1) / 2.0, fill=False,
                                         edgecolor="tab:red", linewidth=0.8))
            self.ax.scatter([h[0] for h in holes], [h[1] for h in holes],
                            s=8, c="tab:red", marker="+")
        self.ax.relim()
        self.ax.autoscale_view()
        self.ax.margins(0.05)
        self.canvas.draw_idle()

    def show_holes(self, holes):
        """Draw drill holes alone (circles + centre marks), no trace context."""
        self.show_segments([], [], holes=holes)
