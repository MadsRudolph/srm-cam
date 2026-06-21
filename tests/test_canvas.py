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

def test_canvas_show_holes():
    canvas = PreviewCanvas()
    canvas.show_holes([(0, 0, 0.8), (5, 5, 1.0)])   # must not raise
    assert len(canvas.ax.patches) == 2              # one circle per hole

def test_canvas_show_holes_empty():
    canvas = PreviewCanvas()
    canvas.show_holes([])                            # redraw empty must not raise
    assert len(canvas.ax.patches) == 0

def _n_cut_segments(canvas):
    from matplotlib.collections import LineCollection
    for c in canvas.ax.collections:
        if isinstance(c, LineCollection):
            return len(c.get_segments())
    return 0

def test_slider_scrubs_partial_toolpath():
    canvas = PreviewCanvas()
    cuts = [[(0, 0), (1, 0)], [(1, 0), (2, 0)], [(2, 0), (3, 0)], [(3, 0), (4, 0)]]
    canvas.show_segments(cuts, [])
    assert canvas.slider.value() == 1000          # resets to full on new data
    assert _n_cut_segments(canvas) == 4           # full view shows all segments
    canvas.slider.setValue(500)                   # emits valueChanged -> redraw at 0.5
    assert _n_cut_segments(canvas) == 2           # half scrubbed

def test_slider_frame_stays_fixed_while_scrubbing():
    canvas = PreviewCanvas()
    cuts = [[(0, 0), (10, 0)], [(10, 0), (10, 10)],
            [(10, 10), (0, 10)], [(0, 10), (0, 0)]]
    canvas.show_segments(cuts, [])
    full = canvas.ax.get_xlim()
    canvas.slider.setValue(300)
    assert canvas.ax.get_xlim() == full           # view does not jump/rescale
