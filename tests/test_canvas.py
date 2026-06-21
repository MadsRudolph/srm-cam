import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import matplotlib
matplotlib.use("Agg")
from PySide6.QtWidgets import QApplication
from gerber2rml.gui.canvas import PreviewCanvas

_app = QApplication.instance() or QApplication([])

def test_canvas_draws_without_error():
    canvas = PreviewCanvas()
    cuts = [[(0, 0), (1, 0), (1, 1)]]
    rapids = [[(1, 1), (0, 0)]]
    canvas.show_segments(cuts, rapids)        # must not raise
    assert len(canvas.ax.collections) >= 1

def test_canvas_clear():
    canvas = PreviewCanvas()
    canvas.show_segments([[(0, 0), (1, 1)]], [])
    canvas.show_segments([], [])              # redraw empty must not raise
