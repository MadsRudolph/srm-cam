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
    assert any(p.suffix == ".nc" for p in written)   # GUI defaults to G-code now

def test_bed_leveling_grid_and_warped_export(tmp_path):
    from PySide6.QtWidgets import QTableWidgetItem
    w = MainWindow()
    w.load_folder(str(FIXT))
    # build a 3x3 probe grid over the placed board
    w.level_nx_spin.setValue(3); w.level_ny_spin.setValue(3)
    w._on_build_level_grid()
    assert w.level_table.rowCount() == 9
    # fill measured Z = a tilt in X (so the warp is non-trivial and checkable)
    for r in range(9):
        x = float(w.level_table.item(r, 0).text())
        w.level_table.setItem(r, 2, QTableWidgetItem(f"{0.01 * x:.4f}"))
    w.level_chk.setChecked(True)
    hmap = w._height_map()
    assert hmap is not None and abs(hmap(100, 0) - 1.0) < 1e-6   # 0.01 * 100

    plain = tmp_path / "plain"; warped = tmp_path / "warped"
    w.level_chk.setChecked(False); w.export_to(plain)
    w.level_chk.setChecked(True);  w.export_to(warped)
    pt = (plain / "board_traces.nc").read_text()
    wt = (warped / "board_traces.nc").read_text()
    assert pt != wt                                   # leveling changed the Z

def test_probe_results_fill_table_as_deviations():
    w = MainWindow()
    w.load_folder(str(FIXT))
    w.level_nx_spin.setValue(3); w.level_ny_spin.setValue(3)
    w._on_build_level_grid()
    w._probe_z0 = None
    # simulate the worker streaming touch heights (microns): a tilt in id order
    for i in range(9):
        w._on_probe_result({"id": i, "x": 0, "y": 0, "z": -56000 - i * 10})
    assert w.level_table.item(0, 2).text() == "0.0000"          # reference point
    assert w.level_table.item(1, 2).text() == "-0.0100"         # 10 um lower
    assert w.level_table.item(8, 2).text() == "-0.0800"
    # and that Z column now feeds a usable height map
    w.level_chk.setChecked(True)
    assert w._height_map() is not None


def test_height_map_overlay_toggles():
    from PySide6.QtWidgets import QTableWidgetItem
    w = MainWindow()
    w.load_folder(str(FIXT)); w.generate_preview()
    w.level_nx_spin.setValue(3); w.level_ny_spin.setValue(3); w._on_build_level_grid()
    for r in range(9):                       # a tilt so the map is non-trivial
        x = float(w.level_table.item(r, 0).text())
        w.level_table.setItem(r, 2, QTableWidgetItem(f"{0.001 * x:.4f}"))
    w.level_show_chk.setChecked(True)
    ov = w.preview._level_overlay
    assert ov is not None and len(ov[3]) == 9      # X,Y,Z meshes + 9 points
    w.level_show_chk.setChecked(False)
    assert w.preview._level_overlay is None


def test_save_level_grid_csv(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QTableWidgetItem, QFileDialog
    w = MainWindow()
    w.load_folder(str(FIXT))
    w.level_nx_spin.setValue(2); w.level_ny_spin.setValue(2); w._on_build_level_grid()
    for r in range(4):
        w.level_table.setItem(r, 2, QTableWidgetItem(f"{0.01 * r:.4f}"))
    out = tmp_path / "hm.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(out), "")))
    w._on_save_level_grid()
    text = out.read_text()
    assert text.splitlines()[0] == "x_mm,y_mm,dz_mm"
    assert len(text.strip().splitlines()) == 5            # header + 4 points


def test_probe_error_point_marked():
    w = MainWindow()
    w.load_folder(str(FIXT))
    w._on_build_level_grid()
    w._probe_z0 = None
    w._on_probe_result({"id": 0, "x": 0, "y": 0, "z": -56000})
    w._on_probe_result({"id": 1, "x": 0, "y": 0, "z": None, "error": "E 1 NOTOUCH"})
    assert w.level_table.item(1, 2).text() == "ERR"


def test_click_to_jog_sends_machine_move():
    w = MainWindow()
    w.load_folder(str(FIXT)); w.generate_preview()
    assert not w.jog_chk.isEnabled()             # disabled until connected

    class FakeDRO:
        def __init__(self): self.moved = None
        def request_move(self, x, y): self.moved = (x, y)
    w._dro = FakeDRO()
    w._on_jog_to(120.0, 26.0)                     # a click at (120, 26) mm
    assert w._dro.moved == (120000, 26000)        # converted to microns

    # the canvas reports clicks only in jog mode
    seen = {}
    w.preview.on_jog_to = lambda x, y: seen.setdefault("xy", (x, y))
    w.preview.set_jogging(True)
    ev = type("E", (), {"button": 1, "inaxes": w.preview.ax, "xdata": 50.0, "ydata": 40.0})
    w.preview._on_press(ev())
    assert seen["xy"] == (50.0, 40.0)


def test_probe_z_requests_touchoff_and_zeros_on_contact():
    w = MainWindow()
    w.load_folder(str(FIXT)); w.generate_preview()

    class FakeDRO:
        def __init__(self): self.touchoff = False
        def request_touchoff(self): self.touchoff = True
    w._dro = FakeDRO()
    w._touching = False
    w._on_probe_z()                              # not touching -> requests a touch-off
    assert w._dro.touchoff is True

    w._on_touch_done(True, 50.0, 40.0, -56.29)   # surface found
    assert abs(w._z_zero - (-56.29)) < 1e-9
    assert "surf" in w.dro_label.text()
    # now 0.15 mm deeper reads as -0.15 below the surface
    w._on_position(50.0, 40.0, -56.44, True)
    assert "surf -0.15" in w.dro_label.text()


def test_probe_z_no_contact_warns(monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    w = MainWindow(); w.load_folder(str(FIXT))
    seen = {}
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: seen.setdefault("w", True)))
    w._on_touch_done(False, 0.0, 0.0, 0.0)
    assert seen.get("w") and w._z_zero is None


def test_dro_updates_banner_and_tool_marker():
    w = MainWindow()
    w.load_folder(str(FIXT)); w.generate_preview()
    w._on_position(120.0, 26.0, -54.26, False)
    assert "120.00" in w.dro_label.text() and "-54.26" in w.dro_label.text()
    assert w.preview._tool_pos == (120.0, 26.0)
    # garbage spike is rejected (keeps last), then re-syncs after a few in a row
    w._on_position(0.0, 0.0, 0.0, False)
    assert w._tool_xyz[:2] == (120.0, 26.0)
    w._on_position(0.0, 0.0, 0.0, False); w._on_position(0.0, 0.0, 0.0, False)
    assert w._tool_xyz[:2] == (0.0, 0.0)


def test_touch_indicator_reflects_contact():
    w = MainWindow()
    w.load_folder(str(FIXT)); w.generate_preview()
    w._on_position(50.0, 40.0, -55.0, True)
    assert "TOUCHING" in w.touch_label.text() and w.preview._tool_touch is True
    w._on_position(50.0, 40.0, -50.0, False)
    assert "clear" in w.touch_label.text() and w.preview._tool_touch is False


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
    assert w.forms["traces"].value().bit_diameter == 0.8
    assert w.forms["cutout"].value().tabs == 4

def test_window_opens_with_srm20_preset_applied():
    w = MainWindow()
    assert w.preset_combo.currentText().startswith("SRM-20")
    assert w.forms["traces"].value().xy_feed == 4.0   # SRM-20 0.8 mm preset

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
    # GUI now defaults to the G-code backend (.nc)
    assert any(p.name.endswith("_top_traces.nc") for p in written)

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

def test_double_sided_view_toggle_bottom_and_top():
    w = MainWindow()
    w.load_folder(str(FIXT))
    w.double_sided_chk.setChecked(True)
    w.view_combo.setCurrentText("Bottom")
    w.generate_preview()
    assert len(w.preview._full_cuts) > 0 and w.preview._full_top_cuts == []
    assert len(w.preview._pins) == 2          # dowels stay visible in both views
    w.view_combo.setCurrentText("Top")
    w.generate_preview()
    assert w.preview._full_cuts == [] and len(w.preview._full_top_cuts) > 0
    assert len(w.preview._pins) == 2

def test_double_sided_rework_export_enabled_per_side():
    from gerber2rml.engine.select import clip_toolpaths_to_bbox
    w = MainWindow()
    w.load_folder(str(FIXT))
    w.double_sided_chk.setChecked(True)
    box = (0, 0, 200, 200)                         # covers the whole placed board
    # Both sides: can't rework two sides at once -> export stays disabled
    w.view_combo.setCurrentText("Both sides")
    w._on_selection_changed(box)
    assert w._ds_side() is None and not w.export_sel_btn.isEnabled()
    # Bottom: export enabled, and the bottom side's MACHINE-frame paths clip
    w.view_combo.setCurrentText("Bottom")
    w._on_selection_changed(box)
    assert w._ds_side() == "Bottom" and w.export_sel_btn.isEnabled()
    assert clip_toolpaths_to_bbox(w._ds_side_toolpaths("traces", "Bottom"), box)
    # Top: its own side paths (reflected) also clip
    w.view_combo.setCurrentText("Top")
    w._on_selection_changed(box)
    assert w._ds_side() == "Top" and w.export_sel_btn.isEnabled()
    assert clip_toolpaths_to_bbox(w._ds_side_toolpaths("traces", "Top"), box)

def test_preview_orientation_badge_and_flip():
    w = MainWindow()
    w.load_folder(str(FIXT))
    # single-sided, mirror on, default -> as-milled badge, no view flip
    w.generate_preview()
    assert "AS MILLED" in w.preview._frame_label and w.preview._flip_x is False
    assert w.frame_combo.isEnabled()
    # 'As designed' -> badge flips wording AND flips the view (export unchanged)
    w.frame_combo.setCurrentIndex(1)
    w.generate_preview()
    assert "AS DESIGNED" in w.preview._frame_label and w.preview._flip_x is True
    # mirror off -> design == milled, the toggle is disabled, no flip
    w.frame_combo.setCurrentIndex(0)
    w.mirror_chk.setChecked(False)          # reloads + regenerates
    assert not w.frame_combo.isEnabled() and w.preview._flip_x is False
    # double-sided: badge follows the View, toggle disabled, never flips
    w.mirror_chk.setChecked(True)
    w.double_sided_chk.setChecked(True)
    w.view_combo.setCurrentText("Both sides"); w.generate_preview()
    assert "AS DESIGNED" in w.preview._frame_label and not w.frame_combo.isEnabled()
    assert w.preview._flip_x is False
    w.view_combo.setCurrentText("Bottom"); w.generate_preview()
    assert "AS MILLED" in w.preview._frame_label and w.preview._flip_x is False

def test_bed_shown_by_default_and_fixture_fits():
    w = MainWindow()
    w.load_folder(str(FIXT))
    w.generate_preview()
    assert w.preview._bed == (203.2, 152.4)   # bed drawn by default
    assert w.preview._bed_fits is True         # the small fixture fits the bed
    w.show_bed_chk.setChecked(False)           # toggling off hides the bed
    assert w.preview._bed is None

def test_placement_moves_design_and_can_exceed_bed():
    w = MainWindow()
    w.load_folder(str(FIXT))
    w.generate_preview()
    assert w.preview._bed_fits is True
    base = w.preview._design_bounds()
    w.place_x_spin.setValue(400.0)             # shove the job far to the right
    moved = w.preview._design_bounds()
    assert moved[0] > base[0] + 300            # design shifted right by ~400 mm
    assert w.preview._bed_fits is False        # now off the 203 mm-wide bed


class _Evt:
    def __init__(self, ax, x, y, button=1):
        self.xdata, self.ydata, self.button, self.inaxes = x, y, button, ax


def test_drag_move_folds_into_placement_and_is_exclusive_with_select():
    w = MainWindow()
    w.load_folder(str(FIXT))
    w.generate_preview()
    w.move_chk.setChecked(True)
    assert w.preview._moving is True and not w.select_chk.isChecked()
    # drag by (+15, +25) on the bed -> placement grows by that
    w.preview._on_press(_Evt(w.preview.ax, 50, 50))
    w.preview._on_release(_Evt(w.preview.ax, 65, 75))
    assert abs(w.place_x_spin.value() - 15.0) < 1e-6
    assert abs(w.place_y_spin.value() - 25.0) < 1e-6
    # turning rework-select on turns move off
    w.select_chk.setChecked(True)
    assert not w.move_chk.isChecked()


def test_stock_thickness_default():
    w = MainWindow()
    assert abs(w.thickness_spin.value() - 1.6) < 1e-6


def test_advanced_options_hidden_until_toggled():
    w = MainWindow()
    assert w._advanced_box.isHidden() is True          # advanced collapsed by default
    w.advanced_chk.setChecked(True)
    assert w._advanced_box.isHidden() is False
    # double-sided sub-controls stay hidden until double-sided is enabled
    assert w._ds_controls.isHidden() is True
    w.double_sided_chk.setChecked(True)
    assert w._ds_controls.isHidden() is False


def test_auto_depth_follows_stock_thickness():
    w = MainWindow()
    w.load_folder(str(FIXT))
    # default: auto on, 1.6 mm stock + 0.1 breakthrough -> 1.7 mm
    assert abs(w.forms["drill"].value().total_depth - 1.7) < 1e-6
    assert abs(w.forms["cutout"].value().total_depth - 1.7) < 1e-6
    assert not w.forms["drill"]._editors["total_depth"].isEnabled()  # locked
    # measure a thicker board -> drill + cut-out depth follow
    w.thickness_spin.setValue(2.0)
    assert abs(w.forms["drill"].value().total_depth - 2.1) < 1e-6
    assert abs(w.forms["cutout"].value().total_depth - 2.1) < 1e-6
    # turning auto off unlocks the fields for manual control
    w.auto_depth_chk.setChecked(False)
    assert w.forms["drill"]._editors["total_depth"].isEnabled()

def test_drill_tab_shows_diameter_summary():
    w = MainWindow()
    w.load_folder(str(FIXT))
    w.tabs.setCurrentIndex(1)             # drill tab
    w.generate_preview()
    msg = w.statusBar().currentMessage()
    # single-bit is the default now -> one file, diameters still listed
    assert "0.8mm" in msg and "1 file" in msg

def test_drill_summary_single_bit_mode():
    w = MainWindow()
    w.load_folder(str(FIXT))
    w.state.drill = type(w.state.drill)(single_bit=True, bit_diameter=0.8)
    w.forms["drill"].set_instance(w.state.drill)
    w.tabs.setCurrentIndex(1)
    w.generate_preview()
    msg = w.statusBar().currentMessage()
    assert "1 file" in msg and "interpolated" in msg

def test_single_sided_preview_has_no_pins():
    w = MainWindow()
    w.load_folder(str(FIXT))
    w.generate_preview()                  # double-sided unchecked
    assert w.preview._pins == []
    assert w.preview._full_top_cuts == []
