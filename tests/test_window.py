import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import matplotlib
matplotlib.use("Agg")
from pathlib import Path
from PySide6.QtWidgets import QApplication
from gerber2rml.gui.app import MainWindow

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"
_app = QApplication.instance() or QApplication([])

def test_window_builds():
    w = MainWindow()
    assert w.machine_combo.count() >= 1          # SRM-20 present
    assert w.preview is not None

def test_load_and_preview_and_export(tmp_path):
    w = MainWindow()
    w.load_folder(str(FIXT))                      # programmatic load (no dialog)
    w.generate_preview()                          # default op (traces)
    assert len(w.preview.ax.collections) >= 1
    written = w.export_to(tmp_path)
    assert any(p.suffix == ".rml" for p in written)

def test_mirror_toggle_reloads_board():
    w = MainWindow()
    w.load_folder(str(FIXT))
    first = w.state.board
    w.mirror_chk.setChecked(False)        # emits toggled -> reload
    assert w.state.board is not first     # a fresh board was loaded
    assert w.state.mirror is False        # state tracks the new flag

def test_drill_tab_preview_overlays_holes_on_traces():
    from matplotlib.collections import LineCollection
    w = MainWindow()
    w.load_folder(str(FIXT))
    w.tabs.setCurrentIndex(1)             # drill tab
    w.generate_preview()
    assert len(w.preview.ax.patches) > 0  # holes drawn as circles, not blank
    assert any(isinstance(c, LineCollection)
               for c in w.preview.ax.collections)  # trace context overlaid behind

def test_apply_preset_updates_forms():
    from gerber2rml.app.presets import BUILTIN_PRESETS
    w = MainWindow()
    name = next(iter(BUILTIN_PRESETS))
    w.preset_combo.setCurrentText(name)
    w.apply_selected_preset()
    assert w.forms["traces"].value().bit_diameter == 0.4
    assert w.forms["cutout"].value().tabs == 4

def test_window_opens_with_fr4_preset_applied():
    w = MainWindow()
    assert w.preset_combo.currentText().startswith("FR-4")
    assert w.forms["traces"].value().xy_feed == 1.5   # FR-4 conservative feed

def test_export_image_writes_png(tmp_path):
    w = MainWindow()
    w.load_folder(str(FIXT))
    w.generate_preview()
    out = w.export_image_to(tmp_path)
    assert out.exists() and out.suffix == ".png"
    assert (tmp_path / (out.stem + "_summary.md")).exists()

def test_double_sided_export(tmp_path):
    w = MainWindow()
    w.load_folder(str(FIXT))
    w.double_sided_chk.setChecked(True)
    written = w.export_to(tmp_path)
    assert any(p.name.endswith("_top_traces.rml") for p in written)

def test_double_sided_preview_shows_both_sides_and_dowels():
    w = MainWindow()
    w.load_folder(str(FIXT))
    w.double_sided_chk.setChecked(True)
    w.generate_preview()
    # both copper sides produced isolation toolpaths (bottom + reflected top)
    assert len(w.preview._full_cuts) > 0
    assert len(w.preview._full_top_cuts) > 0
    # the two dowel/alignment holes are shown as distinct markers
    assert len(w.preview._pins) == 2
    # the view frame autoscales to include the pins (they sit beyond the board)
    x0, x1, y0, y1 = w.preview._limits
    for (px, py, _d) in w.preview._pins:
        assert x0 <= px <= x1 and y0 <= py <= y1

def test_single_sided_preview_has_no_pins():
    w = MainWindow()
    w.load_folder(str(FIXT))
    w.generate_preview()                  # double-sided unchecked
    assert w.preview._pins == []
    assert w.preview._full_top_cuts == []
