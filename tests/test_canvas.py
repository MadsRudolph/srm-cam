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

def _simulate_box(canvas, x0, y0, x1, y1):
    """Drive the canvas' press/motion/release handlers with synthetic events."""
    class _Evt:
        def __init__(self, x, y, button=1):
            self.xdata, self.ydata, self.button = x, y, button
            self.inaxes = canvas.ax
    canvas._on_press(_Evt(x0, y0))
    canvas._on_motion(_Evt((x0 + x1) / 2, (y0 + y1) / 2))
    canvas._on_release(_Evt(x1, y1))


def test_box_selection_records_bbox_and_persists():
    canvas = PreviewCanvas()
    canvas.show_segments([[(0, 0), (10, 0), (10, 10)]], [])
    canvas.set_selecting(True)
    _simulate_box(canvas, 1, 2, 6, 7)
    assert canvas.selection_bbox() == (1, 2, 6, 7)     # normalised corners
    canvas.slider.setValue(400)                         # a redraw must not lose it
    assert canvas.selection_bbox() == (1, 2, 6, 7)
    assert any(isinstance(p, type(canvas._rect_artist)) for p in canvas.ax.patches)


def test_box_selection_ignored_when_not_selecting():
    canvas = PreviewCanvas()
    canvas.show_segments([[(0, 0), (10, 0)]], [])
    _simulate_box(canvas, 1, 1, 5, 5)                   # selection mode off
    assert canvas.selection_bbox() is None


def test_clear_selection():
    canvas = PreviewCanvas()
    canvas.show_segments([[(0, 0), (10, 0)]], [])
    canvas.set_selecting(True)
    _simulate_box(canvas, 1, 1, 5, 5)
    canvas.clear_selection()
    assert canvas.selection_bbox() is None


def test_slider_frame_stays_fixed_while_scrubbing():
    canvas = PreviewCanvas()
    cuts = [[(0, 0), (10, 0)], [(10, 0), (10, 10)],
            [(10, 10), (0, 10)], [(0, 10), (0, 0)]]
    canvas.show_segments(cuts, [])
    full = canvas.ax.get_xlim()
    canvas.slider.setValue(300)
    assert canvas.ax.get_xlim() == full           # view does not jump/rescale
