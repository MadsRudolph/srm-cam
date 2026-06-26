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

def test_canvas_set_estimate():
    canvas = PreviewCanvas()
    canvas.set_estimate("est ~3m 44s")
    assert canvas.est_lbl.text() == "est ~3m 44s"
    canvas.set_estimate("")                          # clear
    assert canvas.est_lbl.text() == ""

def test_canvas_takes_vertical_stretch():
    # Regression: the plot canvas must get the spare vertical space (stretch 1),
    # so the control row with the estimate label can't balloon into a black box.
    canvas = PreviewCanvas()
    lay = canvas.layout()
    assert lay.itemAt(0).widget() is canvas.canvas    # canvas is the first item
    assert lay.stretch(0) == 1                         # ...and gets the stretch

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

def _trail_artist(canvas):
    return canvas._tool_trail_artist


def test_tool_trail_accumulates_and_fades():
    canvas = PreviewCanvas()
    canvas.show_segments([[(0, 0), (40, 0)]], [])
    for x in (0.0, 10.0, 20.0, 30.0):          # four well-separated samples
        canvas.set_tool_position(x, 5.0)
    art = _trail_artist(canvas)
    assert art is not None and len(art.get_segments()) == 3      # n-1 segments
    cols = art.get_colors()
    assert cols[0][3] < cols[-1][3]            # oldest segment fainter than newest

def test_tool_trail_dedups_tiny_jitter():
    canvas = PreviewCanvas()
    canvas.show_segments([[(0, 0), (1, 1)]], [])
    canvas.set_tool_position(10.0, 10.0)
    canvas.set_tool_position(10.05, 10.0)      # < _TRAIL_MIN_STEP -> ignored
    assert len(canvas._tool_trail) == 1

def test_tool_trail_clear_and_toggle():
    canvas = PreviewCanvas()
    canvas.show_segments([[(0, 0), (1, 1)]], [])
    for x in (0.0, 5.0, 10.0):
        canvas.set_tool_position(x, 0.0)
    canvas.clear_tool_trail()
    assert canvas._tool_trail == [] and _trail_artist(canvas) is None
    canvas.set_tool_trail_visible(False)       # off -> stops recording
    canvas.set_tool_position(20.0, 0.0)
    assert canvas._tool_trail == [] and _trail_artist(canvas) is None

def _simulate_box(canvas, x0, y0, x1, y1):
    """Drive the canvas' press/motion/release handlers with synthetic events."""
    class _Evt:
        def __init__(self, x, y, button=1):
            self.xdata, self.ydata, self.button = x, y, button
            self.inaxes = canvas.ax
    canvas._on_press(_Evt(x0, y0))
    canvas._on_motion(_Evt((x0 + x1) / 2, (y0 + y1) / 2))
    canvas._on_release(_Evt(x1, y1))


def test_region_drag_fires_callback():
    canvas = PreviewCanvas()
    canvas.show_segments([[(0, 0), (10, 0), (10, 10)]], [])
    seen = {}
    canvas.on_region_added = lambda bbox: seen.setdefault("bbox", bbox)
    canvas.set_selecting(True)
    _simulate_box(canvas, 1, 2, 6, 7)
    assert seen["bbox"] == (1, 2, 6, 7)                 # normalised corners reported


def test_region_drag_ignored_when_not_selecting():
    canvas = PreviewCanvas()
    canvas.show_segments([[(0, 0), (10, 0)]], [])
    seen = {}
    canvas.on_region_added = lambda bbox: seen.setdefault("bbox", bbox)
    _simulate_box(canvas, 1, 1, 5, 5)                   # selection mode off
    assert "bbox" not in seen


def test_set_rework_regions_draws_and_persists():
    canvas = PreviewCanvas()
    canvas.show_segments([[(0, 0), (10, 0), (10, 10)]], [])
    canvas.set_rework_regions([
        ((0, 0, 4, 4), "#ff5252", "0.20 mm"),
        ((6, 6, 9, 9), "#42a5f5", "0.40 mm"),
    ])
    rects = [p for p in canvas.ax.patches if p.__class__.__name__ == "Rectangle"]
    assert len(rects) >= 2                              # one per region
    canvas.slider.setValue(400)                         # a redraw must not lose them
    rects = [p for p in canvas.ax.patches if p.__class__.__name__ == "Rectangle"]
    assert len(rects) >= 2


def test_set_rework_regions_empty_clears():
    canvas = PreviewCanvas()
    canvas.show_segments([[(0, 0), (10, 0)]], [])
    canvas.set_rework_regions([((0, 0, 4, 4), "#ff5252", "0.20 mm")])
    canvas.set_rework_regions([])                       # must not raise
    assert canvas._rework_artists == []


def test_slider_frame_stays_fixed_while_scrubbing():
    canvas = PreviewCanvas()
    cuts = [[(0, 0), (10, 0)], [(10, 0), (10, 10)],
            [(10, 10), (0, 10)], [(0, 10), (0, 0)]]
    canvas.show_segments(cuts, [])
    full = canvas.ax.get_xlim()
    canvas.slider.setValue(300)
    assert canvas.ax.get_xlim() == full           # view does not jump/rescale


def test_bed_fit_flag_and_view_includes_bed():
    canvas = PreviewCanvas()
    canvas.set_bed((203.2, 152.4))
    canvas.show_segments([[(10, 10), (20, 20)]], [])   # small -> inside the bed
    assert canvas._bed_fits is True
    x0, x1 = canvas.ax.get_xlim()
    assert x1 >= 203.2                                  # whole bed kept in view
    canvas.show_segments([[(10, 10), (210, 20)]], [])  # pokes past bed width
    assert canvas._bed_fits is False
    canvas.set_bed(None)                                # hidden -> always 'fits'
    canvas.show_segments([[(10, 10), (210, 20)]], [])
    assert canvas._bed_fits is True
