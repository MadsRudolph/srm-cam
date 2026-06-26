"""3D bed visualizer (OctoPrint-style) — builds offscreen via pyqtgraph GL."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import matplotlib
matplotlib.use("Agg")
import numpy as np
from pathlib import Path
from PySide6.QtWidgets import QApplication, QTableWidgetItem, QMessageBox
from gerber2rml.gui.bedviz import BedVisualizerWindow
from gerber2rml.gui.app import MainWindow

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"
_app = QApplication.instance() or QApplication([])


def test_pyqtgraph_uses_pyside6():
    # Regression: pyqtgraph must use the app's Qt binding (PySide6); a stray
    # PyQt6/PyQt5 in the env loads a second Qt runtime and crashes the 3D views.
    from pyqtgraph.Qt import QT_LIB
    assert QT_LIB == "PySide6"


def _bowl():
    xs = np.linspace(0, 80, 30); ys = np.linspace(0, 60, 30)
    Z = np.array([[-3e-5 * ((x - 40) ** 2 + (y - 30) ** 2) for y in ys] for x in xs])
    pts = [(10, 10, 0.0), (40, 30, -0.08), (70, 50, 0.01)]
    return xs, ys, Z, pts


def test_bedviz_builds_surface_and_points():
    xs, ys, Z, pts = _bowl()
    w = BedVisualizerWindow(xs, ys, Z, pts, title="t")
    assert w._surface is not None and w._scatter is not None
    assert "um" in w.range_lbl.text()


def test_bedviz_exaggeration_rebuilds():
    xs, ys, Z, pts = _bowl()
    w = BedVisualizerWindow(xs, ys, Z, pts, exaggeration=100)
    w._on_exag(600)
    assert w._exag == 600 and w._surface is not None


def test_main_window_opens_bed_3d():
    w = MainWindow()
    w.load_folder(str(FIXT))
    w.level_nx_spin.setValue(3); w.level_ny_spin.setValue(3); w._on_build_level_grid()
    for r in range(9):
        x = float(w.level_table.item(r, 0).text())
        w.level_table.setItem(r, 2, QTableWidgetItem(f"{0.001 * x:.4f}"))
    w._on_bed_3d()
    assert isinstance(w._bedviz, BedVisualizerWindow)


def test_hover_text_reports_value_and_band():
    from gerber2rml.gui.bedviz import _hover_text
    pts = [(10, 10, 0.0), (40, 30, -0.08), (70, 50, 0.02)]
    t = _hover_text(pts, zmin=-0.08, zmax=0.02, i=1)
    assert "Probe #2 of 3" in t
    assert "X 40.000" in t and "Y 30.000" in t
    assert "-80 µm" in t and "-0.0800 mm" in t
    assert "0% of range" in t                 # the minimum sits at the band bottom


def test_nearest_index_within_radius():
    from gerber2rml.gui.bedviz import _nearest_index
    screen = [(100, 100), None, (300, 300)]   # a clipped point is skipped
    assert _nearest_index(screen, 104, 97, max_px=18) == 0
    assert _nearest_index(screen, 305, 296, max_px=18) == 2
    assert _nearest_index(screen, 200, 200, max_px=18) is None   # nothing in range


def test_bedviz_pick_round_trips_a_marker():
    # project a marker to the screen, then pick at that pixel -> same point.
    xs, ys, Z, pts = _bowl()
    w = BedVisualizerWindow(xs, ys, Z, pts, title="pick")
    w.view.resize(800, 600)                   # give the offscreen view a real size
    x, y, dz = w._points[1]                    # the centre point — always on-screen
    scr = w._project(x, y, dz * w._exag)
    assert scr is not None
    assert w._pick(scr[0], scr[1]) == 1
    assert w._pick(-999, -999) is None         # empty space picks nothing


def test_bed_3d_warns_without_data(monkeypatch):
    w = MainWindow()
    w.load_folder(str(FIXT))
    w._on_build_level_grid()          # grid built but no Z values
    called = {}
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: called.setdefault("w", True)))
    w._on_bed_3d()
    assert called.get("w")            # warned instead of opening
    assert getattr(w, "_bedviz", None) is None
