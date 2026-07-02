import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import matplotlib
matplotlib.use("Agg")
from pathlib import Path
from PySide6.QtWidgets import QApplication
from gerber2rml.gui.app import MainWindow

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"
_app = QApplication.instance() or QApplication([])

def test_stylesheet_parses_without_warning():
    # Qt discards the WHOLE stylesheet on a parse error (and logs "Could not
    # parse application stylesheet"), so guard against malformed QSS slipping in.
    from PySide6.QtCore import qInstallMessageHandler
    from PySide6.QtWidgets import QCheckBox, QPushButton
    from gerber2rml.gui import app
    msgs = []
    qInstallMessageHandler(lambda mode, ctx, m: msgs.append(m))
    try:
        _app.setStyleSheet(app._STYLESHEET)
        for W in (QCheckBox, QPushButton):
            w = W("x"); w.ensurePolished(); w.show(); _app.processEvents()
    finally:
        qInstallMessageHandler(None)
    assert not [m for m in msgs if "parse" in m.lower() and "stylesheet" in m.lower()]


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


def test_arrow_keys_jog_carriage_relative():
    w = MainWindow()
    w.load_folder(str(FIXT)); w.generate_preview()

    class FakeDRO:
        def __init__(self): self.moved = None
        def request_move(self, x, y): self.moved = (x, y)
    w._dro = FakeDRO()
    w._tool_xyz = (50.0, 40.0, -54.0)

    w._on_jog_step(1.0, 0.0)                       # right arrow, 1 mm in +X
    assert w._dro.moved == (51000, 40000)         # absolute target, microns
    assert w._tool_xyz[:2] == (51.0, 40.0)        # optimistic local advance

    w._on_jog_step(0.0, 1.0)                       # next tap reads the advanced XY
    assert w._dro.moved == (51000, 41000)

    # canvas dispatch: while hovering, arrow + modifier -> signed (dx, dy) mm
    seen = {}
    w.preview.on_jog_step = lambda dx, dy: seen.setdefault("d", (dx, dy))
    w.preview._flip_x = False
    w.preview._hover = True
    w.preview._on_key(type("E", (), {"key": "shift+up"})())
    assert seen["d"] == (0.0, 10.0)               # shift = 10 mm coarse

    seen.clear()
    w.preview._on_key(type("E", (), {"key": "ctrl+left"})())
    assert seen["d"] == (-0.1, 0.0)               # ctrl = 0.1 mm fine

    # a flipped ("as designed") view keeps the on-screen direction intuitive
    seen.clear()
    w.preview._flip_x = True
    w.preview._on_key(type("E", (), {"key": "right"})())
    assert seen["d"] == (-1.0, 0.0)               # screen-right -> data -X when flipped

    # keys are ignored unless the mouse is over the preview
    seen.clear()
    w.preview._flip_x = False
    w.preview._hover = False
    w.preview._on_key(type("E", (), {"key": "up"})())
    assert "d" not in seen


def test_arrow_jog_without_connection_is_safe():
    w = MainWindow(); w.load_folder(str(FIXT))
    w._dro = None
    w._on_jog_step(1.0, 0.0)                       # no machine -> hint only, no crash


def test_rotate_button_cycles_and_reorients_board():
    w = MainWindow(); w.load_folder(str(FIXT)); w.generate_preview()
    b0 = w.state.board.outline.bounds
    assert w._rotation == 0 and w.rotate_lbl.text() == "0°"

    w._on_rotate()                                 # 90
    assert w._rotation == 90 and "90" in w.rotate_lbl.text()
    assert w.state.rotate == 90
    b1 = w.state.board.outline.bounds
    # rotation reorients the real geometry: width<->height swap, still positive
    assert abs((b0[2] - b0[0]) - (b1[3] - b1[1])) < 1e-6
    assert b1[0] >= -1e-6 and b1[1] >= -1e-6

    for _ in range(3):                             # 180, 270, back to 0
        w._on_rotate()
    assert w._rotation == 0 and w.state.rotate == 0


def test_double_sided_rotation_reorients_layout():
    w = MainWindow(); w.load_folder(str(FIXT))
    w.double_sided_chk.setChecked(True); w.generate_preview()
    assert w.rotate_btn.isEnabled()                # rotation works in double-sided too
    b0 = w._double_sided_layout().outline.bounds
    w._on_rotate()                                 # 90°
    assert w._rotation == 90 and w.state.rotate == 90
    b1 = w._double_sided_layout().outline.bounds   # cache keyed on rotate -> recomputed
    # width<->height swap (the dowels rotate with the board; counts preserved)
    assert abs((b0[2] - b0[0]) - (b1[3] - b1[1])) < 1e-6
    lay = w._machine_layout()
    assert len(lay.align_holes) == 2 and len(lay.holes) > 0   # dowels rotate too


def test_ruler_snaps_to_board_geometry_and_is_exclusive():
    w = MainWindow(); w.load_folder(str(FIXT)); w.generate_preview()
    # snap targets were pushed to the canvas
    assert w.preview._snap_pts and w.preview._snap_segs

    # enabling the ruler turns off the other drag modes
    w.move_chk.setChecked(True)
    w.measure_chk.setChecked(True)
    assert w.preview._measuring and not w.move_chk.isChecked()

    # a press near a real corner snaps the start point onto it
    corner = w.preview._snap_pts[0]
    near = type("E", (), {"button": 1, "inaxes": w.preview.ax,
                          "xdata": corner[0] + 0.05, "ydata": corner[1] + 0.05})
    w.preview._on_press(near())
    sx, sy = w.preview._measure_start
    assert abs(sx - corner[0]) < 1e-6 and abs(sy - corner[1]) < 1e-6

    # leaving ruler mode clears the drawn line
    w.measure_chk.setChecked(False)
    assert w.preview._measure_line is None


def test_emergency_stop_aborts_workers_and_disconnects():
    from gerber2rml.gui.app import _ProbeWorker, _DROPoller

    w = MainWindow(); w.load_folder(str(FIXT)); w.generate_preview()
    assert w.stop_btn.isEnabled()                 # STOP is always available

    # fake an in-progress grid probe + live link, then hit STOP
    class FakePW:
        def __init__(self): self.aborted = False
        def isRunning(self): return True
        def abort(self): self.aborted = True
    class FakeDRO:
        def __init__(self): self.aborted = False
        def request_abort(self): self.aborted = True
        def stop(self): pass
        position = type("S", (), {"disconnect": lambda *a: None})()
    w._probe_worker = FakePW()
    w._dro = FakeDRO()
    dro = w._dro
    w._on_emergency_stop()
    assert w._probe_worker.aborted and dro.aborted   # both told to lift + stop
    assert w._dro is None and not w._dro_was_on       # link torn down, no auto-resume

    # the worker classes expose the abort hooks the stop relies on
    pw = _ProbeWorker("X", []); pw.abort(); assert pw._abort is True
    d = _DROPoller("X"); d.request_abort(); assert d._abort is True


def test_clear_level_wipes_z_keeps_grid():
    from PySide6.QtWidgets import QTableWidgetItem
    w = MainWindow(); w.load_folder(str(FIXT)); w.generate_preview()
    w.level_nx_spin.setValue(3); w.level_ny_spin.setValue(3)
    w._on_build_level_grid()
    w.level_table.setItem(0, 2, QTableWidgetItem("-0.05"))
    w.level_chk.setChecked(True); w.level_show_chk.setChecked(True)
    w._on_clear_level()
    zs = [w.level_table.item(r, 2).text() for r in range(w.level_table.rowCount())]
    assert all(z == "" for z in zs)               # Z column wiped
    assert w.level_table.item(0, 0) is not None    # X/Y grid kept
    assert not w.level_chk.isChecked() and not w.level_show_chk.isChecked()


def test_probe_grid_lays_over_displayed_outline_double_sided():
    # the grid must follow the outline that's actually shown — for double-sided
    # that's the registered layout, not the single-sided state.board frame.
    w = MainWindow(); w.load_folder(str(FIXT))
    w.double_sided_chk.setChecked(True); w.generate_preview()
    bounds = w._level_bounds()
    lay = w._double_sided_layout().outline.bounds
    assert tuple(round(v, 3) for v in bounds) == tuple(round(v, 3) for v in lay)
    w._on_build_level_grid()
    x0, y0, x1, y1 = lay
    xy, _ = w._table_points()
    assert xy and all(x0 <= x <= x1 and y0 <= y <= y1 for (x, y) in xy)  # all on the board


def test_height_map_overlay_follows_displayed_frame_double_sided():
    # regression: the heatmap mesh must be sampled over the DISPLAYED (mirrored)
    # outline, the same frame as the probe grid/PCB — not state.board.outline,
    # which for a mirrored bottom side is offset and makes the heatmap misalign.
    from PySide6.QtWidgets import QTableWidgetItem
    w = MainWindow(); w.load_folder(str(FIXT))
    w.double_sided_chk.setChecked(True); w.generate_preview()
    w.level_nx_spin.setValue(3); w.level_ny_spin.setValue(3); w._on_build_level_grid()
    for r in range(9):                                  # tilt so the map is non-trivial
        x = float(w.level_table.item(r, 0).text())
        w.level_table.setItem(r, 2, QTableWidgetItem(f"{0.001 * x:.4f}"))
    w.level_show_chk.setChecked(True); w._update_level_overlay()
    X, _Y, _Z, _pts = w.preview._level_overlay
    mesh = (round(float(X.min()), 3), round(float(X.max()), 3))
    disp = w._level_bounds()
    assert mesh == (round(disp[0], 3), round(disp[2], 3))      # mesh spans displayed X
    design = w.state.board.outline.bounds
    assert mesh != (round(design[0], 3), round(design[2], 3))  # NOT the design frame


def test_diagnostics_runs(monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    seen = {}
    monkeypatch.setattr(QMessageBox, "exec", lambda self: seen.update(
        text=self.text(), info=self.informativeText()) or 0)
    w = MainWindow(); w.load_folder(str(FIXT)); w.generate_preview()
    w._z_zero = -58.0                              # pretend we probed a low surface
    w.double_sided_chk.setChecked(True)
    w._on_diagnostics()
    assert "Pre-flight" in seen["text"]
    assert "Z range" in seen["info"] or "reach" in seen["info"].lower()


def test_copper_stock_overlay_and_fit_check():
    w = MainWindow(); w.load_folder(str(FIXT)); w.generate_preview()
    # enter a copper piece and show it
    w.stock_w_spin.setValue(120.0); w.stock_h_spin.setValue(120.0)
    w.stock_x_spin.setValue(0.0); w.stock_y_spin.setValue(0.0)
    w.stock_show_chk.setChecked(True)
    assert w.preview._stock == (0.0, 0.0, 120.0, 120.0)
    w.generate_preview()
    assert w.preview._stock_fits                    # big copper -> design fits

    # tiny copper -> design spills off
    w.stock_w_spin.setValue(5.0); w.stock_h_spin.setValue(5.0)
    w.generate_preview()
    assert not w.preview._stock_fits

    # capture the corner from the live tool position
    w._on_position(40.0, 30.0, -54.0, False)
    w._on_stock_corner_from_tool()
    assert (w.stock_x_spin.value(), w.stock_y_spin.value()) == (40.0, 30.0)

    w.stock_show_chk.setChecked(False)
    assert w.preview._stock is None                 # hidden


def test_center_design_on_stock_moves_placement():
    w = MainWindow(); w.load_folder(str(FIXT)); w.generate_preview()
    w.stock_w_spin.setValue(140.0); w.stock_h_spin.setValue(140.0)
    w.stock_x_spin.setValue(10.0); w.stock_y_spin.setValue(10.0)
    w.stock_show_chk.setChecked(True)
    w._on_center_design_on_stock()
    jb = w._job_bounds()
    cx, cy = (jb[0] + jb[2]) / 2, (jb[1] + jb[3]) / 2
    assert abs(cx - (10 + 70)) < 0.5 and abs(cy - (10 + 70)) < 0.5   # centred on stock


def test_save_load_setup_round_trips(tmp_path):
    from PySide6.QtWidgets import QTableWidgetItem
    w = MainWindow(); w.load_folder(str(FIXT)); w.generate_preview()
    w.place_x_spin.setValue(-2.0); w.place_y_spin.setValue(3.0)
    w._on_rotate()                                 # 90
    w.double_sided_chk.setChecked(True); w.fresh_bed_spin.setValue(4.0)
    w.stock_w_spin.setValue(60.0); w.stock_show_chk.setChecked(True)
    w.level_nx_spin.setValue(3); w.level_ny_spin.setValue(3); w._on_build_level_grid()
    w.level_table.setItem(0, 2, QTableWidgetItem("-0.05"))
    w.level_chk.setChecked(True)

    setup = w._collect_setup()

    w2 = MainWindow()
    w2._apply_setup(setup)                         # fresh window restores everything
    assert w2.place_x_spin.value() == -2.0 and w2._rotation == 90
    assert w2.double_sided_chk.isChecked() and w2.fresh_bed_spin.value() == 4.0
    assert w2.stock_w_spin.value() == 60.0
    assert w2.level_table.item(0, 2).text() == "-0.05" and w2.level_chk.isChecked()
    assert str(w2.state.gerber_dir).endswith("mosfet_test")   # board reloaded


def test_apply_setup_tolerates_missing_board_and_unknown_fields():
    w = MainWindow()
    # board path gone + an unknown job field -> must not raise, just skip them
    w._apply_setup({
        "gerber_dir": "C:/nope/missing", "place_x": 5.0,
        "jobs": {"traces": {"cut_depth": 0.2, "bogus_field": 99}},
    })
    assert w.place_x_spin.value() == 5.0           # other settings still applied


def test_level_csv_save_load_round_trip(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QTableWidgetItem
    w = MainWindow(); w.load_folder(str(FIXT))
    w.level_nx_spin.setValue(3); w.level_ny_spin.setValue(2); w._on_build_level_grid()
    w.level_table.setItem(0, 2, QTableWidgetItem("-0.05"))
    w.level_table.setItem(1, 2, QTableWidgetItem("ERR"))   # a missed point
    w.level_table.setItem(2, 2, QTableWidgetItem("0.10"))

    csv = tmp_path / "hm.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(csv), "")))
    w._on_save_level_grid()
    assert "x_mm,y_mm,dz_mm" in csv.read_text()

    # load it into a fresh window — ERR is preserved but skipped as unmeasured
    w2 = MainWindow(); w2.load_folder(str(FIXT))
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(csv), "")))
    w2._on_load_level_grid()
    assert w2.level_table.rowCount() == 6
    assert w2.level_table.item(0, 2).text() == "-0.05"
    _xy, xyz = w2._table_points()
    assert len(xyz) == 2                            # ERR row skipped, not crashed


def test_probe_resume_skips_filled_points():
    from PySide6.QtWidgets import QTableWidgetItem
    w = MainWindow(); w.load_folder(str(FIXT)); w.generate_preview()
    w.level_nx_spin.setValue(3); w.level_ny_spin.setValue(3)
    w._on_build_level_grid()                       # 9 points; row 0 seeded with "0"
    # mark rows 0..4 measured, leave 5..8 unfilled (one as ERR)
    for r in range(5):
        w.level_table.setItem(r, 2, QTableWidgetItem(f"{-0.01 * r:.4f}"))
    w.level_table.setItem(5, 2, QTableWidgetItem("ERR"))
    filled, unfilled = w._grid_fill_state()
    assert filled == 5 and unfilled == 4

    # resume: anchor (row 0) + the 4 unfilled rows (5 ERR, 6, 7, 8)
    pts, x0, y0 = w._probe_points(resume=True)
    rows = [p[0] for p in pts]
    assert rows[0] == 0                            # anchor first -> re-sets dz ref
    assert set(rows) == {0, 5, 6, 7, 8}            # filled 1..4 are kept, not re-probed
    # offsets are relative to point 0
    assert pts[0][1] == 0 and pts[0][2] == 0

    # re-probe all = every row
    pts_all, _, _ = w._probe_points(resume=False)
    assert len(pts_all) == 9


def test_probe_grid_overlay_toggles_on_preview():
    w = MainWindow(); w.load_folder(str(FIXT)); w.generate_preview()
    w.level_nx_spin.setValue(3); w.level_ny_spin.setValue(3)
    w._on_build_level_grid()                       # build -> auto-shows the grid
    assert w.level_gridshow_chk.isChecked()
    assert len(w.preview._probe_grid) == 9
    w.preview._draw_fraction(1.0)                  # redraw keeps it (no error)
    assert len(w.preview._probe_grid) == 9
    w.level_gridshow_chk.setChecked(False)         # toggle off clears it
    assert w.preview._probe_grid is None


def test_preview_status_shows_run_estimate():
    w = MainWindow(); w.load_folder(str(FIXT))
    w.tabs.setCurrentIndex(2)                       # cutout tab (no gap-warning path)
    w.generate_preview()
    assert "est. run" in w.statusBar().currentMessage()


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

def test_overlay_trim_pick_apply_and_clear():
    w = MainWindow()
    w.load_folder(str(FIXT))
    # simulate a live machine position, then pick where the bit REALLY is
    w._tool_xyz = (50.0, 40.0, -1.0)
    w._on_align_pick(53.5, 38.0, "")
    assert w._overlay_trim == (3.5, -2.0)
    # the live overlay is drawn in the design frame (machine + trim)...
    w._on_position(50.0, 40.0, -1.0, False)
    assert w.preview._tool_pos == (53.5, 38.0)
    # ...while the DRO label keeps the raw machine readout plus the trim tag
    assert "X    50.00" in w.dro_label.text()
    assert "+3.50" in w.dro_label.text()
    # click-to-jog inverts the trim so the bit lands where the user clicked
    sent = {}
    class _FakeDRO:
        def request_move(self, ux, uy): sent["um"] = (ux, uy)
    w._dro = _FakeDRO()
    w._on_jog_to(53.5, 38.0)
    assert sent["um"] == (50000, 40000)          # microns, back in machine frame
    w._dro = None
    # trim survives a session round trip
    d = w._collect_setup()
    w2 = MainWindow()
    w2._apply_setup(d)
    assert w2._overlay_trim == (3.5, -2.0)
    # Ctrl+click clears it
    w._on_align_pick(0.0, 0.0, "ctrl")
    assert w._overlay_trim == (0.0, 0.0)


def test_overlay_trim_zero_is_passthrough():
    w = MainWindow()
    w.load_folder(str(FIXT))
    w._on_position(12.0, 34.0, -0.5, False)
    assert w.preview._tool_pos == (12.0, 34.0)   # no trim -> untouched mapping
    assert "Δ" not in w.dro_label.text()


def test_manual_fiducials_seed_drag_and_persist(tmp_path):
    w = MainWindow()
    w.load_folder(str(FIXT))
    w.double_sided_chk.setChecked(True)
    w.regmethod_combo.setCurrentIndex(1)            # fiducial registration
    w.fid_place_combo.setCurrentIndex(2)            # Manual (drag pins)
    # switching to Manual seeds one point per fiducial from the corner layout
    assert len(w._fid_points) == w.fid_count_spin.value()
    assert w.preview._pin_drag is True              # pins are draggable in X-ray
    assert not w.fid_offset_spin.isEnabled()        # corner offset is moot now
    # drag pin 0 somewhere else on the canvas: the layout must follow it exactly
    lay = w._double_sided_layout()
    tx, ty = lay.frame0[0] - 3.0, lay.frame0[1] + 12.0   # into the left waste
    w._on_fid_pin_moved(0, tx, ty)
    lay2 = w._double_sided_layout()
    assert abs(lay2.align_holes[0][0] - tx) < 1e-6
    assert abs(lay2.align_holes[0][1] - ty) < 1e-6
    assert abs(lay2.flip_pos - lay.flip_pos) < 1e-6      # flip axis unmoved
    # the machine (export) layout drills the same physical hole: mirrored x
    mlay = w._machine_layout()
    px = tx - lay2.frame0[0]                             # board-relative x
    mx = mlay.align_holes[0][0] - mlay.frame0[0]
    bw = ((lay2.align_holes[1][0] - lay2.frame0[0])
          + (mlay.align_holes[1][0] - mlay.frame0[0]))   # box width invariant
    assert abs((px + mx) - bw) < 1e-6
    # settings + points survive a session save/load round trip
    d = w._collect_setup()
    w2 = MainWindow()
    w2._apply_setup(d)
    assert w2.fid_place_combo.currentIndex() == 2
    assert w2.regmethod_combo.currentIndex() == 1
    assert len(w2._fid_points) == len(w._fid_points)
    assert abs(w2._fid_points[0][0] - w._fid_points[0][0]) < 1e-6


def test_pin_drag_disabled_outside_manual_fiducial_mode():
    w = MainWindow()
    w.load_folder(str(FIXT))
    w.double_sided_chk.setChecked(True)
    w.regmethod_combo.setCurrentIndex(1)            # fiducial, corner placement
    w.generate_preview()
    assert w.preview._pin_drag is False
    w.regmethod_combo.setCurrentIndex(0)            # dowels
    w.generate_preview()
    assert w.preview._pin_drag is False
    w.double_sided_chk.setChecked(False)            # single-sided
    w.generate_preview()
    assert w.preview._pin_drag is False


def test_drill_tab_bottom_view_shows_machine_frame_holes():
    # Regression: the drill tab used to always draw the design-frame X-ray, so
    # with View=Bottom the on-screen holes were mirrored versus the physical
    # cut (only the on-axis dowels lined up) and click-to-jog missed them.
    from gerber2rml.doublesided import reflect_holes
    w = MainWindow()
    w.load_folder(str(FIXT))
    w.double_sided_chk.setChecked(True)
    w.tabs.setCurrentIndex(1)                       # drill tab
    w.view_combo.setCurrentText("Bottom")
    w.generate_preview()
    mlay = w._machine_layout()
    assert w.preview._full_holes == mlay.holes      # as physically drilled
    w.view_combo.setCurrentText("Top")
    w.generate_preview()
    exp = reflect_holes(mlay.holes, mlay.axis, mlay.flip_pos)
    assert w.preview._full_holes == exp             # as seen after the flip
    w.view_combo.setCurrentText("Both sides")
    w.generate_preview()
    lay = w._double_sided_layout()
    assert w.preview._full_holes == lay.holes       # X-ray keeps design frame


def test_double_sided_cutout_tab_shows_edge_cut_not_traces():
    # Regression: in double-sided 'Both sides' view the Cutout tab used to keep
    # drawing the trace isolation; it must show the edge-cut path instead.
    w = MainWindow()
    w.load_folder(str(FIXT))
    w.double_sided_chk.setChecked(True)
    w.tabs.setCurrentIndex(2)                       # cutout tab
    w.generate_preview()
    assert len(w.preview._full_cuts) > 0            # the outline cut is drawn
    assert w.preview._full_top_cuts == []           # ...and no top trace isolation
    assert w.preview.est_lbl.text() not in ("", "—")  # cutout got a real estimate
    n_cutout = len(w.preview._full_cuts)
    w.tabs.setCurrentIndex(0)                       # traces op for comparison
    w.generate_preview()
    assert len(w.preview._full_cuts) > n_cutout     # isolation is far denser

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

def test_rework_export_always_enabled_and_explains(monkeypatch):
    # The button used to grey out silently when preconditions were missing (an
    # operator lost time to this). It now stays enabled and clicking explains
    # exactly what to fix.
    from PySide6.QtWidgets import QMessageBox
    from gerber2rml.engine.select import clip_toolpaths_to_bbox
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: warnings.append(a[2])))
    w = MainWindow()
    w.load_folder(str(FIXT))
    w.double_sided_chk.setChecked(True)
    assert w.export_sel_btn.isEnabled()             # enabled from the start
    w._on_export_selected()                         # no regions yet
    assert "boxes" in warnings[-1]
    box = (0, 0, 200, 200)                          # covers the whole placed board
    w._on_region_added(box)
    w.view_combo.setCurrentText("Both sides")
    w.generate_preview()
    assert w.export_sel_btn.isEnabled()             # still enabled...
    w._on_export_selected()
    assert "Bottom or Top" in warnings[-1]          # ...and it says what to fix
    # with a side picked, both sides' MACHINE-frame paths clip as before
    assert clip_toolpaths_to_bbox(w._ds_side_toolpaths("traces", "Bottom"), box)
    assert clip_toolpaths_to_bbox(w._ds_side_toolpaths("traces", "Top"), box)


def test_machine_dock_at_bottom_with_port():
    # GUI 2.0 phase 2: the machine strip + run progress live in a bottom dock,
    # and the serial port selector sits in the dock next to Connect.
    w = MainWindow()
    lay = w.centralWidget().layout()
    names = [lay.itemAt(i).widget().objectName() for i in range(lay.count())]
    assert names[-2:] == ["machineBar", "progressBar"]   # dock is the bottom rows
    bar = w.centralWidget().layout().itemAt(lay.count() - 2).widget()
    assert w.level_port_combo in bar.findChildren(type(w.level_port_combo))
    assert w.connect_btn in bar.findChildren(type(w.connect_btn))

def test_rework_export_uses_custom_depth(tmp_path, monkeypatch):
    # the rework pass cuts at the spin's depth, not the original job's depth.
    from PySide6.QtWidgets import QFileDialog
    import gerber2rml.engine.select as sel
    real = sel.clip_toolpaths_to_bbox
    seen = {}
    def spy(toolpaths, bbox, cut_z=None):
        seen["cut_z"] = cut_z
        return real(toolpaths, bbox, cut_z=cut_z)
    monkeypatch.setattr(sel, "clip_toolpaths_to_bbox", spy)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: str(tmp_path)))
    w = MainWindow(); w.load_folder(str(FIXT)); w.generate_preview()
    w.tabs.setCurrentIndex(0)                          # traces op
    db = w.state.board.outline.bounds
    w.rework_level_chk.setChecked(False)              # flat for this case
    w.rework_depth_spin.setValue(0.42)               # default for the next box
    w._on_region_added((db[0] - 1, db[1] - 1, db[2] + 1, db[3] + 1))
    w._on_export_selected()
    assert seen["cut_z"] == -0.42                      # exported deeper than the 1st pass


def test_rework_follows_height_map_for_uniform_depth():
    from PySide6.QtWidgets import QTableWidgetItem
    w = MainWindow(); w.load_folder(str(FIXT)); w.generate_preview()
    # a tilted surface (dz grows with x), so leveling warps the cut Z per point
    w.level_nx_spin.setValue(3); w.level_ny_spin.setValue(3); w._on_build_level_grid()
    for r in range(9):
        x = float(w.level_table.item(r, 0).text())
        w.level_table.setItem(r, 2, QTableWidgetItem(f"{0.01 * x:.4f}"))
    db = w.state.board.outline.bounds
    box = (db[0] - 1, db[1] - 1, db[2] + 1, db[3] + 1)
    tps = w.state.toolpaths("traces")
    # flat region: every cut at exactly -0.20
    w.rework_depth_spin.setValue(0.20)
    w.rework_level_chk.setChecked(False)
    w._on_region_added(box)
    flat, lv_f = w._rework_clip_regions(tps)
    assert lv_f == 0 and all(abs(m.z + 0.20) < 1e-9 for tp in flat for m in tp if not m.rapid)
    # leveled region: cut Z varies with the surface
    w._clear_rework()
    w.rework_level_chk.setChecked(True)
    w._on_region_added(box)
    lev, lv_t = w._rework_clip_regions(tps)
    zs = [m.z for tp in lev for m in tp if not m.rapid]
    assert lv_t == 1 and max(zs) - min(zs) > 1e-3     # warped, no longer a single flat depth
    assert max(zs) > -0.20 + 1e-3                     # surface-follow lifts some cuts upward


def test_run_progress_tracks_live_position():
    w = MainWindow(); w.load_folder(str(FIXT)); w.generate_preview()
    w.run_op_combo.setCurrentText("Traces")
    w.run_track_btn.setChecked(True)                  # arm
    assert w._run_progress is not None and w._run_progress.total > 0
    end = w._run_progress.pts[-1]                      # last point of the path
    w._on_position(end[0], end[1], end[2], False)      # report the bit at the end
    assert w.run_bar.value() >= 99                      # ~done
    assert "done" in w.run_eta_lbl.text() or "left" in w.run_eta_lbl.text()
    w.run_track_btn.setChecked(False)                  # disarm resets
    assert w._run_progress is None and w.run_bar.value() == 0


def test_run_progress_autostarts_on_motion():
    w = MainWindow(); w.load_folder(str(FIXT)); w.generate_preview()
    w.run_op_combo.setCurrentText("Traces")
    w.run_auto_chk.setChecked(True)
    w._dro = object()                                  # pretend the link is open
    assert w._run_progress is None
    # three consecutive moving reads (>0.25 mm each) -> auto-arm
    w._on_position(10.0, 10.0, -0.15, False)
    w._on_position(11.0, 10.0, -0.15, False)
    w._on_position(12.0, 10.0, -0.15, False)
    w._on_position(13.0, 10.0, -0.15, False)
    assert w._run_progress is not None and w.run_track_btn.isChecked()
    w._dro = None


def test_run_progress_no_autostart_right_after_jog():
    import time as _t
    w = MainWindow(); w.load_folder(str(FIXT)); w.generate_preview()
    w.run_auto_chk.setChecked(True)
    w._dro = object()
    w._last_jog_t = _t.time()                          # we just jogged
    for x in (10.0, 11.0, 12.0, 13.0):                 # motion, but it's our jog
        w._on_position(x, 10.0, -0.15, False)
    assert w._run_progress is None                      # suppressed near a jog
    w._dro = None


def test_run_progress_rework_needs_a_box(monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    w = MainWindow(); w.load_folder(str(FIXT)); w.generate_preview()
    w.run_rework_chk.setChecked(True)                  # selection mode, no box drawn
    w.run_track_btn.setChecked(True)
    assert w._run_progress is None and not w.run_track_btn.isChecked()  # refused


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


def test_fiducial_mode_selectable_and_spec():
    w = MainWindow()
    w._select_registration("fiducial")
    assert w._registration_mode() == "fiducial"
    spec = w._fiducial_spec_from_ui()
    assert spec.count in (2, 3, 4)
    assert spec.placement in ("onboard", "waste")
    w._select_registration("dowel")            # round-trips to the proven default
    assert w._registration_mode() == "dowel"


def test_fiducial_export_writes_align_and_runplan(tmp_path):
    w = MainWindow()
    w.load_folder(str(FIXT))
    w.double_sided_chk.setChecked(True)
    w._select_registration("fiducial")
    written = w.export_to(tmp_path)
    names = {p.name for p in written}
    assert any(n.endswith("_align.nc") for n in names)
    plan = next(p for p in written if p.name.endswith("_runplan.txt"))
    assert "FIDUCIAL" in plan.read_text(encoding="utf-8")


def test_fiducial_preview_shows_four_pins():
    w = MainWindow()
    w.load_folder(str(FIXT))
    w.double_sided_chk.setChecked(True)
    w._select_registration("fiducial")
    w.generate_preview()
    assert len(w.preview._pins) == 4           # 4 corner fiducials drawn


def test_rework_add_and_delete_regions():
    w = MainWindow()
    w.load_folder(str(FIXT)); w.generate_preview()
    w.rework_depth_spin.setValue(0.20)
    w._on_region_added((0.0, 0.0, 4.0, 4.0))
    w.rework_depth_spin.setValue(0.40)
    w._on_region_added((6.0, 6.0, 9.0, 9.0))
    assert len(w._rework_regions) == 2
    assert w.rework_table.rowCount() == 2
    assert abs(w._rework_regions[0]["depth"] - 0.20) < 1e-9
    assert abs(w._rework_regions[1]["depth"] - 0.40) < 1e-9
    w._delete_rework_region(0)
    assert len(w._rework_regions) == 1
    assert abs(w._rework_regions[0]["depth"] - 0.40) < 1e-9


def test_rework_clear_empties_all():
    w = MainWindow()
    w.load_folder(str(FIXT)); w.generate_preview()
    w._on_region_added((0.0, 0.0, 4.0, 4.0))
    w._clear_rework()
    assert w._rework_regions == [] and w.rework_table.rowCount() == 0


def test_rework_edit_region_depth_in_table():
    w = MainWindow()
    w.load_folder(str(FIXT)); w.generate_preview()
    w._on_region_added((0.0, 0.0, 4.0, 4.0))
    w._set_region_depth(0, 0.33)
    assert abs(w._rework_regions[0]["depth"] - 0.33) < 1e-9


def test_rework_export_two_regions_one_file(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    w = MainWindow()
    w.load_folder(str(FIXT)); w.generate_preview()      # traces tab, single-sided
    b = w.state.board.outline.bounds
    cx = (b[0] + b[2]) / 2; cy = (b[1] + b[3]) / 2
    w.rework_level_chk.setChecked(False)
    w.rework_depth_spin.setValue(0.20)
    w._on_region_added((b[0], b[1], cx, cy))            # lower-left quadrant
    w.rework_depth_spin.setValue(0.40)
    w._on_region_added((cx, cy, b[2], b[3]))            # upper-right quadrant
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: str(tmp_path)))
    w._on_export_selected()
    files = list(tmp_path.glob("*_rework.nc"))
    assert len(files) == 1                               # ONE file for all regions
    text = files[0].read_text()
    assert "Z-0.2\n" in text and "Z-0.4\n" in text       # both depths in one program


def test_rework_export_refused_with_no_regions(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    warned = {}
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: warned.setdefault("w", a)))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: str(tmp_path)))
    w = MainWindow()
    w.load_folder(str(FIXT)); w.generate_preview()
    w._on_export_selected()                              # no regions
    assert list(tmp_path.glob("*_rework.nc")) == []     # nothing written
    assert "w" in warned


def test_settings_panel_autofits_per_page():
    # The real bug: fields were pushed off-screen behind a horizontal scrollbar
    # because the panel was narrower than the field content. Pages differ a lot
    # in width, so the panel re-fits to the CURRENT page: Project must fully fit
    # its content, and switching to the much wider Bed-Leveling page must widen
    # the panel. Needs a real (shown) width so the fit isn't capped by Qt's tiny
    # pre-show default geometry.
    w = MainWindow()
    w.resize(1700, 900); w.show(); _app.processEvents()
    project_inner = w.stacked_widget.widget(0).widget()
    project_min = w._settings_container.minimumWidth()      # fitted on show (page 0)
    assert project_min >= w.sidebar.minimumWidth() + project_inner.sizeHint().width()
    w.sidebar.setCurrentRow(2); _app.processEvents()        # Bed Leveling: wider
    assert w._settings_container.minimumWidth() > project_min   # re-fit wider
    w.close()


def test_settings_panel_collapse_toggle():
    # The collapse control lives on the viewer's bar; toggling it hides/shows
    # the settings panel (and never the preview).
    w = MainWindow()
    w.preview.panel_btn.setChecked(True)                    # collapse via viewer button
    assert w._settings_container.isHidden()                 # panel hidden
    assert not w.preview.isHidden()                         # preview never hidden
    assert "Show panel" in w.preview.panel_btn.text()       # label flipped
    w.preview.panel_btn.setChecked(False)                   # restore
    assert not w._settings_container.isHidden()
    assert "Hide panel" in w.preview.panel_btn.text()


def test_move_on_bed_on_by_default():
    w = MainWindow()
    assert w.move_chk.isChecked()                           # drag-to-move enabled
    assert w.preview._moving is True                        # preview in move mode


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


def test_preview_shows_persistent_estimate_per_op():
    w = MainWindow()
    w.load_folder(str(FIXT))
    w.tabs.setCurrentIndex(0); w.generate_preview()       # Traces
    traces_est = w.preview.est_lbl.text()
    assert "~" in traces_est                              # a duration is shown
    w.tabs.setCurrentIndex(1); w.generate_preview()       # Drill
    assert "~" in w.preview.est_lbl.text()
    assert w.preview.est_lbl.text() != traces_est         # differs per op


def test_3d_viewer_tab_exists_with_launchers():
    w = MainWindow()
    titles = [w.sidebar.item(i).text() for i in range(w.sidebar.count())]
    assert "3D Viewer" in titles                          # 5th sidebar entry
    for b in (w.view3d_sim_btn, w.view3d_file_btn, w.view3d_bed_btn):
        assert b is not None


def test_3d_viewer_buttons_call_handlers(monkeypatch):
    # No board / no height map -> the handlers' guards warn instead of opening a
    # GL window, which proves each button is wired to its handler.
    from PySide6.QtWidgets import QMessageBox
    warned = []
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: warned.append(a[1])))
    w = MainWindow()                                       # nothing loaded
    w.view3d_sim_btn.click()                               # -> _on_simulate_3d guard
    w.view3d_bed_btn.click()                               # -> _on_bed_3d guard
    assert len(warned) == 2


def test_double_sided_enable_refits_panel():
    # Enabling double-sided reveals the (wide) registration controls; the panel
    # must re-fit so they aren't clipped.
    w = MainWindow()
    w.resize(1916, 1000); w.show(); _app.processEvents()
    w.sidebar.setCurrentRow(1); _app.processEvents()       # Double-Sided page
    before = w._settings_container.minimumWidth()
    w.double_sided_chk.setChecked(True); _app.processEvents()
    assert w._settings_container.minimumWidth() > before   # re-fit wider


def test_preload_demo_loads_board():
    from gerber2rml.gui.app import _preload_demo
    w = MainWindow()
    assert w.state.board is None                            # empty on construction
    _preload_demo(w)
    assert w.state.board is not None                        # demo loaded
    assert not w.state.board.outline.is_empty


def test_preload_demo_missing_dir_is_safe(monkeypatch):
    from pathlib import Path
    import gerber2rml.gui.app as appmod
    monkeypatch.setattr(appmod, "_DEMO_DIR", Path("does/not/exist"))
    w = MainWindow()
    appmod._preload_demo(w)                                 # must not raise
    assert w.state.board is None                            # stays empty


def test_demo_badge_set_and_cleared_on_user_load(monkeypatch):
    from gerber2rml.gui.app import _preload_demo
    from PySide6.QtWidgets import QFileDialog
    w = MainWindow()
    _preload_demo(w)
    assert w.preview._demo is True                          # badge on for the demo
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: str(FIXT)))
    w._on_load_clicked()                                    # operator loads own board
    assert w.preview._demo is False                         # badge cleared


def test_demo_badge_cleared_by_load_setup():
    # Regression: restoring a saved setup loads the board via load_folder
    # directly (not the Load button), which used to leave the DEMO badge up.
    from gerber2rml.gui.app import _preload_demo
    w = MainWindow()
    _preload_demo(w)
    assert w.preview._demo is True
    donor = MainWindow()
    donor.load_folder(str(FIXT))
    w._apply_setup(donor._collect_setup())                  # "Load setup..."
    assert w.preview._demo is False                         # badge cleared
