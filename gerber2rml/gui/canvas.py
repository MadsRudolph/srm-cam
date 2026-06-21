"""Matplotlib preview canvas: draws cut (solid) and rapid (light) polylines."""
from PySide6.QtWidgets import QWidget, QVBoxLayout
from matplotlib.figure import Figure
from matplotlib.collections import LineCollection
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
