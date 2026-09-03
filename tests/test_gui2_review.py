"""What a review of the second interface found, pinned down.

Each test names something that was wrong in the code as reviewed on
2026-09-03 and would have drawn, written or cut the wrong thing: a preview
that did not follow an edit, an export that depended on which row of the
rail was lit, a button that took the wrong board off, a pre-flight that
passed a dowel hanging off the bed.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
import re
import threading
import time
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QAction, QImage, QKeySequence, QMouseEvent

from gerber2rml.gui2.window import FOIL_MM, MainWindow

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"


@pytest.fixture
def win(qt_app):
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    yield w
    w.close()


@pytest.fixture
def loaded(win):
    win.load_folder(str(FIXT))
    return win


def _rows(z):
    """Nine probe points over the fixture board, heights from ``z(x, y)``."""
    return [[f"{x:.3f}", f"{y:.3f}", f"{z(x, y):.4f}"]
            for y in (10.0, 55.0, 100.0) for x in (10.0, 55.0, 100.0)]


def _tilted():
    return _rows(lambda x, y: 0.008 * x)


def _domed():
    return _rows(lambda x, y: 0.008 * x + (0.25 if (x, y) == (55.0, 55.0)
                                           else 0.0))


def _mouse(kind, pt, button, buttons):
    return QMouseEvent(kind, pt, button, buttons, Qt.NoModifier)


def _press(stage, pt, button=Qt.LeftButton):
    stage.mousePressEvent(_mouse(QMouseEvent.MouseButtonPress, pt, button, button))


def _move(stage, pt, buttons=Qt.LeftButton):
    stage.mouseMoveEvent(_mouse(QMouseEvent.MouseMove, pt, Qt.NoButton, buttons))


def _release(stage, pt, button=Qt.LeftButton):
    stage.mouseReleaseEvent(_mouse(QMouseEvent.MouseButtonRelease, pt, button,
                                   Qt.NoButton))


def _zs_below_zero(path):
    text = Path(path).read_text(encoding="utf-8")
    return {round(float(v), 3) for v in re.findall(r"Z(-?\d+\.?\d*)", text)
            if float(v) < 0}


# ---------------------------------------------------- the preview is honest
def test_editing_a_cutting_parameter_rebuilds_the_preview(loaded):
    """The cache is keyed by step, and a step's key survives an edit to its
    bit; the picture showed one pass at 0.8 mm for a job set to four at 2."""
    loaded.select_step("traces_run")
    n0 = len(loaded.stage._cuts)
    loaded.inspector.step._set(loaded.state.trace, "offsets", 4)
    loaded.inspector.step._set(loaded.state.trace, "bit_diameter", 2.0)
    loaded._refresh_preview_now()
    assert len(loaded.stage._cuts) != n0
    assert loaded.stage._cut_width == 2.0


def test_selecting_a_step_that_draws_no_toolpath_keeps_the_scene(loaded):
    loaded.select_step("setup")
    loaded.stage.grab()
    r = loaded.stage._scene_raster
    assert r is not None
    loaded.select_step("checks")
    assert loaded.stage._scene_raster is r


# ------------------------------------------------ the export does not care
def test_the_export_does_not_depend_on_which_step_is_selected(loaded, tmp_path):
    """Exporting with "Top traces" lit handed the writer no map - or the
    top's - for the bottom-frame files, and a flex margin read off whatever
    table was on screen."""
    loaded.action_double_sided(True)
    loaded.action_hold("points")
    loaded.level_page.follow_step("bottom")
    loaded.level_page._load_table({"rows": _domed(), "apply": True,
                                   "show": False})
    assert loaded.level_page.height_map(side="bottom") is not None

    def export_from(key, d):
        loaded.select_step(key)
        written = loaded.export_to(d)
        return {Path(p).name: Path(p).read_bytes()
                for p in written if str(p).endswith(".nc")}
    assert export_from("bottom_traces", tmp_path / "a") == \
        export_from("top_traces", tmp_path / "b")


def test_the_flex_margin_reads_the_bottom_face_whatever_is_shown(loaded):
    loaded.action_double_sided(True)
    loaded.action_hold("points")
    lp = loaded.level_page
    lp.follow_step("bottom")
    lp._load_table({"rows": _domed(), "apply": True, "show": False})
    m = loaded._flex_margin()
    assert m > FOIL_MM + 0.1
    lp.follow_step("top")
    assert loaded._flex_margin() == pytest.approx(m)


def test_an_unapplied_map_charges_the_whole_range(loaded):
    """With the warp off nothing cancels the tilt, so the residual alone
    would leave the cut short by the slope."""
    loaded.action_hold("points")
    loaded.level_page._load_table({"rows": _tilted(), "apply": False,
                                   "show": False})
    zs = [float(r[2]) for r in _tilted()]
    assert loaded._flex_margin() == pytest.approx(max(zs) - min(zs) + FOIL_MM)


def test_the_other_faces_map_is_read_with_its_own_apply_flag(loaded):
    """The visible face's checkbox gated the OTHER face's map, so the flip-fit
    page got no top map whenever the bottom was being looked at."""
    loaded.action_double_sided(True)
    lp = loaded.level_page
    lp.follow_step("top")
    lp._load_table({"rows": _tilted(), "apply": True, "show": False})
    lp.follow_step("bottom")
    lp._load_table({"rows": [], "apply": False, "show": False})
    assert lp.height_map(side="top") is not None
    assert lp.height_map(side="bottom") is None


def test_the_flex_margin_reaches_a_vbit(loaded):
    """A V-bit's depth is back-solved from its width, so deepening cut_depth
    alone changed nothing while the page said the cut was deepened."""
    from gerber2rml.app import presets as pm
    table = pm.load_presets()
    pm.apply_preset(loaded.state, table[next(k for k in table if "V-bit" in k)])
    loaded.action_hold("points")
    loaded.level_page._load_table({"rows": _domed(), "apply": True,
                                   "show": False})
    m = loaded._flex_margin()
    assert m > 0.1
    t = loaded.cutting_trace()
    assert t.effective_cut_depth() == pytest.approx(
        loaded.state.trace.effective_cut_depth() + m, abs=1e-6)


def test_the_flat_profile_undoes_the_vbit_profile(loaded):
    from gerber2rml.app import presets as pm
    table = pm.load_presets()
    vbit = next(k for k in table if "V-bit" in k)
    flat = next(k for k in table if "flat" in k)
    pm.apply_preset(loaded.state, table[vbit])
    assert loaded.state.trace.tool_type == "vbit"
    pm.apply_preset(loaded.state, table[flat])
    assert loaded.state.trace.tool_type == "flat"
    assert loaded.state.trace.effective_diameter() == 0.8


# ------------------------------------------------------------- the panel
def test_the_remove_button_takes_the_picked_board_off(loaded):
    """A button's clicked carries its checked flag, and False is index 0."""
    loaded.add_folder(str(FIXT))
    assert loaded.state.current == 1
    loaded.inspector.setup.remove_board_btn.click()
    assert [m.name for m in loaded.state.boards] == ["buck"]


def test_a_panel_setup_claiming_double_sided_loads_single_sided(
        loaded, tmp_path, monkeypatch):
    loaded.add_folder(str(FIXT))
    path = tmp_path / "p.srmcam"
    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getSaveFileName",
                        lambda *a, **k: (str(path), ""))
    loaded.action_save_setup()
    data = json.loads(path.read_text(encoding="utf-8"))
    data["double_sided"] = True
    path.write_text(json.dumps(data), encoding="utf-8")
    fresh = MainWindow()
    try:
        monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getOpenFileName",
                            lambda *a, **k: (str(path), ""))
        said = []
        monkeypatch.setattr(fresh, "say", lambda l, t: said.append((l, t)))
        fresh.action_load_setup()
        assert fresh.state.is_panel
        assert not fresh._double
        assert not fresh.inspector.setup.double.isChecked()
        assert "flip" not in [s.key for s in fresh.plan]
        assert said[-1][0] == "warn"
    finally:
        fresh.close()


# ----------------------------------------------------------- the checks
def test_a_dowel_off_the_bed_fails_the_fit_check(loaded):
    """The bed-fit check saw the plain board; the dowels sit outside it."""
    loaded.action_double_sided(True)
    loaded.action_place(0.0, 30.0)
    loaded.refresh_checks()
    _x0, _y0, _x1, y1 = loaded.job_extent()
    assert y1 > 152.4, "the pin is meant to hang off the back for this test"
    assert [c for c in loaded._checks if c.title == "Off the bed"]


# ------------------------------------------------------------- setups
def test_a_setup_whose_folder_is_gone_does_not_pretend(loaded, tmp_path,
                                                        monkeypatch):
    data = {"version": 1, "name": "ghost",
            "gerber_dir": str(tmp_path / "nowhere"),
            "place": [30.0, 40.0], "rotate": 0}
    path = tmp_path / "g.srmcam"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getOpenFileName",
                        lambda *a, **k: (str(path), ""))
    said = []
    monkeypatch.setattr(loaded, "say", lambda l, t: said.append((l, t)))
    loaded.action_load_setup()
    assert loaded.state.name == "buck"
    assert (loaded.state.place_x, loaded.state.place_y) == (0.0, 0.0)
    assert said[-1][0] == "warn" and "gone" in said[-1][1]


def test_a_restored_thickness_keeps_the_restored_depths(loaded, tmp_path,
                                                        monkeypatch):
    """Setting the thickness spinbox fired the auto-depth handler, which
    overwrote the depths the file had just restored."""
    setup = loaded.inspector.setup
    setup.auto_depth.setChecked(False)
    loaded.state.drill.total_depth = 1.90
    loaded.state.cutout.total_depth = 1.95
    setup.thickness.setValue(1.55)
    path = tmp_path / "t.srmcam"
    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getSaveFileName",
                        lambda *a, **k: (str(path), ""))
    loaded.action_save_setup()
    fresh = MainWindow()                     # thickness 1.6, auto-depth on
    try:
        monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getOpenFileName",
                            lambda *a, **k: (str(path), ""))
        fresh.action_load_setup()
        assert fresh.state.drill.total_depth == pytest.approx(1.90)
        assert fresh.state.cutout.total_depth == pytest.approx(1.95)
        assert not fresh.inspector.setup.auto_depth.isChecked()
        assert fresh.inspector.setup.thickness.value() == pytest.approx(1.55)
    finally:
        fresh.close()


def test_the_setup_widgets_follow_the_loaded_state(loaded, tmp_path,
                                                   monkeypatch):
    loaded.action_double_sided(True)
    loaded.action_registration("fiducial")
    loaded.action_mirror(False)
    path = tmp_path / "w.srmcam"
    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getSaveFileName",
                        lambda *a, **k: (str(path), ""))
    loaded.action_save_setup()
    fresh = MainWindow()
    try:
        monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getOpenFileName",
                            lambda *a, **k: (str(path), ""))
        fresh.action_load_setup()
        s = fresh.inspector.setup
        assert s.registration.currentData() == "fiducial"
        assert not s.mirror.isChecked()
        assert s.double.isChecked()
        assert fresh._registration == "fiducial" and not fresh.state.mirror
    finally:
        fresh.close()


def test_the_file_format_box_offers_every_backend(loaded):
    from gerber2rml.backends import BACKENDS
    combo = loaded.inspector.setup.machine
    assert [combo.itemText(i) for i in range(combo.count())] == list(BACKENDS)
    assert combo.currentText() == loaded.state.machine


def test_dropping_the_selected_step_moves_the_inspector_with_the_rail(loaded):
    loaded.action_double_sided(True)
    loaded.select_step("top_traces")
    loaded.action_double_sided(False)
    cur = loaded._current_step
    assert cur is not None and loaded.plan.by_key(cur.key) is not None
    assert loaded.traveller.current() == cur.key


# ------------------------------------------------------------- the stage
def test_a_pan_repaints_when_it_ends(loaded):
    stage = loaded.stage
    calls = []
    orig = stage.update
    stage.update = lambda *a: (calls.append(1), orig(*a))
    a = QPointF(300, 300)
    _press(stage, a, Qt.RightButton)
    _move(stage, a + QPointF(60, 20), Qt.RightButton)
    del calls[:]
    _release(stage, a + QPointF(60, 20), Qt.RightButton)
    assert stage._pan_raster is None and not stage._panning
    assert calls, "no repaint after the pan"
    assert stage.cursor().shape() == Qt.ArrowCursor


def test_a_right_click_during_a_box_drag_does_not_commit_the_box(loaded):
    stage = loaded.stage
    loaded.set_stage_mode("box")
    regions = []
    stage.region_added.connect(lambda *a: regions.append(a))
    a, b = QPointF(300, 300), QPointF(380, 360)
    _press(stage, a)
    _move(stage, b)
    _press(stage, b, Qt.RightButton)
    _release(stage, b, Qt.RightButton)
    assert regions == [] and stage._box_from is not None
    assert not stage._panning
    _release(stage, b)
    assert len(regions) == 1
    loaded.set_stage_mode("place")


def test_a_press_on_bare_sheet_does_not_drag_the_board(loaded):
    loaded.action_stock(203.2, 152.4, 0.0, 0.0)
    stage = loaded.stage
    x1 = loaded.state.board.outline.bounds[2]
    pt = stage.to_px(x1 + 30.0, 20.0)            # on the sheet, off the board
    before = (loaded.state.place_x, loaded.state.place_y)
    _press(stage, pt)
    _move(stage, pt + QPointF(40, 0))
    _release(stage, pt + QPointF(40, 0))
    assert (loaded.state.place_x, loaded.state.place_y) == before


def test_one_stage_mode_at_a_time(loaded):
    loaded.rework_page.add_chk.setChecked(True)
    assert loaded.stage.mode == "box"
    loaded.set_stage_mode("jog")
    assert loaded.stage.mode == "jog"
    assert not loaded.rework_page.add_chk.isChecked()
    loaded.inspector.setup.pick_screws.setChecked(True)
    assert loaded.stage.mode == "screws"
    loaded.set_stage_mode("place")
    assert not loaded.inspector.setup.pick_screws.isChecked()


def test_the_xray_is_offered_only_where_there_is_a_far_face(loaded):
    assert not loaded.xray_act.isEnabled()
    loaded.action_double_sided(True)
    assert loaded.xray_act.isEnabled()
    loaded._on_frame("xray")
    loaded.action_double_sided(False)
    assert loaded.stage.frame == "bed" and not loaded.xray_act.isEnabled()


# ------------------------------------------------------- the machine link
def test_a_failed_connect_does_not_leak_a_worker(qt_app, monkeypatch):
    from gerber2rml.gui2 import machine
    from gerber2rml.engine import spi_probe

    def refuse(*a, **k):
        raise OSError("no such port")
    monkeypatch.setattr(spi_probe, "open_link", refuse)
    link = machine.MachineLink()
    for _ in range(3):
        link.connect_to("COM99")
        time.sleep(0.15)
    workers = [t for t in threading.enumerate() if t.name == "srm-link"]
    assert len(workers) == 1


def test_the_z_keys_cannot_run_away(loaded):
    acts = [a for a in loaded.findChildren(QAction)
            if a.shortcut() == QKeySequence(Qt.Key_PageDown)]
    assert acts and not acts[0].autoRepeat()
    assert acts[0].shortcutContext() == Qt.ApplicationShortcut


def test_the_stop_moving_test_actually_sends_the_stop(monkeypatch):
    """The second interface's copy of the machine test had no `import time`:
    it commanded a 20 mm move and died before sending the stop."""
    from gerber2rml.gui2 import machinetest as mt2
    from test_machinetest import FakeV3
    monkeypatch.setattr(mt2.time, "sleep", lambda s: None)
    ser = FakeV3()
    st, detail = mt2.run_test("stopmoving", ser)
    assert "NameError" not in detail, detail
    assert "%" in ser.sent


def test_stop_reaches_a_running_machine_test(monkeypatch):
    from gerber2rml.gui2 import machinetest as mt2
    from test_machinetest import FakeV3
    monkeypatch.setattr(mt2.time, "sleep", lambda s: None)
    ser = FakeV3()
    st, detail = mt2.run_test("stopmoving", ser, abort=lambda: True)
    assert st == mt2.FAIL and "stopped" in detail
    assert "%" in ser.sent


# ----------------------------------------------------------- the photo
def test_the_photo_overlay_has_a_rectangle_on_the_bed(loaded):
    """warp_photo returns matplotlib's (x0, x1, y0, y1); the stage was
    given it as corners, and the rectangle had no width."""
    img = np.zeros((40, 60, 3), dtype=np.uint8)
    x0, y0, x1, y1 = loaded.work_bounds()
    photo_pts = [(0, 0), (60, 0), (60, 40), (0, 40)]
    machine_pts = [(x0, y1), (x1, y1), (x1, y0), (x0, y0)]
    loaded._apply_photo(img, photo_pts, machine_pts)
    _img, (px0, py0, px1, py1) = loaded.stage._photo
    assert px1 > px0 and py1 > py0
    assert px0 <= x0 and px1 >= x1 and py0 <= y0 and py1 >= y1


def test_rework_boxes_and_the_photo_do_not_survive_a_new_board(loaded):
    loaded.rework_page.add_region(10, 10, 20, 20)
    loaded.stage.set_photo(QImage(4, 4, QImage.Format_RGB32), (0, 0, 10, 10))
    loaded.photo_clear_act.setEnabled(True)
    loaded.load_folder(str(FIXT))
    assert loaded.rework_page._regions == []
    assert not loaded.stage.has_photo()
    assert not loaded.photo_clear_act.isEnabled()


# ------------------------------------------------------------ the rework
def test_a_cut_out_rework_is_ramped_not_copied(loaded, tmp_path, monkeypatch):
    x0, y0, x1, y1 = loaded.state.board.outline.bounds
    page = loaded.rework_page
    page.refresh_sources()
    page.source.setCurrentIndex(page.source.findData("cutout"))
    page.depth.setValue(1.2)
    page.add_region(x0 - 2, y0 - 2, (x0 + x1) / 2, y0 + 10)
    out = tmp_path / "r.nc"
    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getSaveFileName",
                        lambda *a, **k: (str(out), ""))
    page._export()
    assert _zs_below_zero(out) == {-0.6, -1.2}


# ---------------------------------------------------------- the 3D view
def test_the_3d_view_follows_the_link(loaded):
    loaded.select_step("traces_run")
    loaded.action_sim3d()
    sim = loaded._sim_window
    assert not sim.live_btn.isEnabled()
    loaded._on_linked({})
    assert sim.live_btn.isEnabled()
    loaded._on_machine_position(10.0, 10.0, 0.0, False)
    loaded._on_unlinked("test")
    assert not sim.live_btn.isEnabled()
    loaded.action_sim3d()
    assert loaded._sim_window is not sim
    loaded._sim_window.close()
