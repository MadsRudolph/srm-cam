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
