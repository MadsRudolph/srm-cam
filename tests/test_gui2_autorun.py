"""The Run-it-all page, end to end against the simulator: connect to SIM,
click the stock, Start, and the board comes out cut where the design is."""
import math
import re
import time
from pathlib import Path

import pytest

from gerber2rml.engine import autorun as ar
from gerber2rml.engine import bracket as br
from gerber2rml.engine import simmachine as sm
from gerber2rml.gui2.window import MainWindow

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"


@pytest.fixture
def win(qt_app, monkeypatch, tmp_path):
    from gerber2rml import platform as plat
    monkeypatch.setattr(plat, "documents_dir", lambda *a, **k: tmp_path)
    # The fixture board is 104 mm square: a 150 x 120 sheet holds it.
    sm.machine(speedup=1e6, corner=(41300, 27800), angle_deg=1.2,
               size=(150000, 120000))
    w = MainWindow()
    w.resize(1400, 900)
    w.load_folder(str(FIXT))
    # These runs find the stock by its edges; the bracket has its own test.
    w.autorun_page.where.setCurrentIndex(
        w.autorun_page.where.findData("click"))
    # Straight through; the check before the cut-out has its own test.
    w.autorun_page.check_chk.setChecked(False)
    yield w
    w.link.disconnect_from("test")
    if w.link._thread is not None:            # end its worker thread
        w.link._q.put(None)
        w.link._thread.join(2)
    w.close()


def _wait(qt_app, cond, secs):
    t0 = time.monotonic()
    while not cond() and time.monotonic() - t0 < secs:
        qt_app.processEvents()
        time.sleep(0.01)
    return cond()


def test_run_it_all_cuts_a_single_sided_board_on_the_simulator(win, qt_app):
    win.link.connect_to("SIM")
    assert _wait(qt_app, win.link.is_connected, 10)
    win.select_step("autorun")
    page = win.autorun_page
    assert win.inspector.stack.currentWidget() is page
    page.w_spin.setValue(150)
    page.h_spin.setValue(120)
    page.on_stock_click(110.0, 80.0)
    done = []
    page.finished.connect(lambda ok, msg: done.append((ok, msg)))
    page.start()
    assert _wait(qt_app, lambda: bool(done), 120), "the run never finished"
    assert done[0][0], done[0][1]
    m = sm.machine()
    assert m.lines, "nothing was cut"
    # Every cut lies on the stock, and the board sits on it, turned with it.
    view = m.view()
    xs = [p[0] for line in view["cuts"] for p in line]
    ys = [p[1] for line in view["cuts"] for p in line]
    assert min(xs) > 41.3 and min(ys) > 27.8
    # Everything it measured and sent can be looked at afterwards.
    assert len(win.level_page.points(side="bottom")) == 12
    assert win.level_page.height_map(side="bottom") is not None
    sent = sorted(p.name for p in page.run_dir.glob("*.nc"))
    assert len(sent) == 3 and (page.run_dir / "run.log").exists()
    # The design on the stage is turned with the stock, like the cuts.
    import math
    assert abs(math.degrees(win._stock_turn.theta) - 1.2) < 0.05
    # And the link is back, for the next thing the operator does.
    assert _wait(qt_app, win.link.is_connected, 10)


def test_a_board_bigger_than_the_stock_stops_before_anything_is_cut(win, qt_app):
    win.link.connect_to("SIM")
    assert _wait(qt_app, win.link.is_connected, 10)
    sm.machine(speedup=1e6, corner=(41300, 27800), size=(100000, 80000))
    win.select_step("autorun")
    page = win.autorun_page
    page.w_spin.setValue(100)
    page.h_spin.setValue(80)
    page.on_stock_click(90.0, 70.0)
    done = []
    page.finished.connect(lambda ok, msg: done.append((ok, msg)))
    page.start()
    assert _wait(qt_app, lambda: bool(done), 120)
    assert not done[0][0] and "bigger piece" in done[0][1]
    assert not sm.machine().lines

def test_run_it_all_flips_and_fits_a_double_sided_board(win, qt_app):
    win.action_double_sided(True)
    win.link.connect_to("SIM")
    assert _wait(qt_app, win.link.is_connected, 10)
    win.select_step("autorun")
    page = win.autorun_page
    page.w_spin.setValue(150)
    page.h_spin.setValue(120)
    page.on_stock_click(110.0, 80.0)
    done = []
    page.finished.connect(lambda ok, msg: done.append((ok, msg)))
    page.start()
    # The run waits at the flip: the operator presses Continue.
    assert _wait(qt_app, lambda: not page.flip_btn.isHidden(), 120), \
        page.status.text()
    page._flipped()
    assert _wait(qt_app, lambda: bool(done), 180), "the run never finished"
    assert done[0][0], done[0][1]
    assert win._top_fit is not None
    assert sum(m is not None for m in win._fid_measured) == 4
    assert win.level_page.points(side="top")
    assert sm.machine().face == 1

def test_the_standard_bracket_runs_double_sided(win, qt_app):
    # Back-right, from the bracket, flipped and pushed back slightly off.
    sm.machine(speedup=1e6, corner=(31790, 4430), angle_deg=0.0,
               size=(160000, 124000))
    win.inspector.setup.double.setChecked(True)
    win.link.connect_to("SIM")
    assert _wait(qt_app, win.link.is_connected, 10)
    win.select_step("autorun")
    page = win.autorun_page
    page.where.setCurrentIndex(page.where.findData("bracket"))
    page.set_bracket(br.DEFAULT)
    page.w_spin.setValue(160)
    page.h_spin.setValue(124)
    page.level_chk.setChecked(False)
    done = []
    page.finished.connect(lambda ok, msg: done.append((ok, msg)))
    page.start()

    def step():
        if not page.flip_btn.isHidden():
            page._flipped()
        if not page.check_box.isHidden():
            page.cut_btn.click()
        return bool(done)
    assert _wait(qt_app, step, 240), "the run never finished"
    assert done[0][0], done[0][1]
    assert sm.machine().face == 1
    assert sum(m is not None for m in win._fid_measured) == 4
    # The holes are outside the design, and on the sheet.
    lay = win._ds_layout()
    x0, y0, x1, y1 = lay.outline.bounds
    sx, sy, sw, sh = win.stock
    for x, y, _d in lay.align_holes:
        assert not (x0 < x < x1 and y0 < y < y1)
        assert sx < x < sx + sw and sy < y < sy + sh


def test_a_flip_that_lands_under_the_tongue_stops_before_anything_is_cut(
        win, qt_app):
    # Clear of the tongue as placed; mirrored across the sheet it is not.
    sm.machine(speedup=1e6, corner=(31790, 8430), angle_deg=0.0,
               size=(160000, 120000))
    win.inspector.setup.double.setChecked(True)
    keep = (win.state.place_x, win.state.place_y)
    win.link.connect_to("SIM")
    assert _wait(qt_app, win.link.is_connected, 10)
    win.select_step("autorun")
    page = win.autorun_page
    page.where.setCurrentIndex(page.where.findData("bracket"))
    page.set_bracket(br.DEFAULT)
    page.w_spin.setValue(160)
    page.h_spin.setValue(120)
    page.level_chk.setChecked(False)
    # Put where the operator put it - as a drag would - not in the corner.
    win.action_place(*keep)
    page.board_dragged()
    done = []
    page.finished.connect(lambda ok, msg: done.append((ok, msg)))
    page.start()
    assert _wait(qt_app, lambda: bool(done), 60), "the run never finished"
    assert not done[0][0] and "once the board is flipped" in done[0][1]
    assert not sm.machine().view()["cuts"]


def test_a_sheet_with_no_room_for_the_holes_stops_before_anything_is_cut(
        win, qt_app):
    # The 104 mm board fits 112 x 112 with its margins, but not with its holes.
    sm.machine(speedup=1e6, corner=(79790, 16430), angle_deg=0.0,
               size=(112000, 112000))
    win.inspector.setup.double.setChecked(True)
    win.link.connect_to("SIM")
    assert _wait(qt_app, win.link.is_connected, 10)
    win.select_step("autorun")
    page = win.autorun_page
    page.where.setCurrentIndex(page.where.findData("bracket"))
    page.set_bracket(br.DEFAULT)
    page.w_spin.setValue(112)
    page.h_spin.setValue(112)
    done = []
    page.finished.connect(lambda ok, msg: done.append((ok, msg)))
    page.start()
    assert _wait(qt_app, lambda: bool(done), 60), "the run never finished"
    assert not done[0][0] and "bigger piece" in done[0][1]
    assert not sm.machine().view()["cuts"]


def test_the_click_is_armed_shown_and_taken_back(win, qt_app):
    win.select_step("autorun")
    page = win.autorun_page
    page.pick_btn.setChecked(True)
    assert win.stage.mode == "stock"
    win.stage.stock_picked.emit(80.0, 60.0)
    assert page._click == (80.0, 60.0)
    assert not page.pick_btn.isChecked() and win.stage.mode == "place"
    assert win.stage._target == (80.0, 60.0)
    page.pick_btn.setChecked(True)            # armed again, then cancelled
    page.pick_btn.setChecked(False)
    assert win.stage.mode == "place" and page._click == (80.0, 60.0)
    page.pick_btn.setChecked(True)
    win.set_stage_mode("jog")                 # another control takes the stage
    assert not page.pick_btn.isChecked()

def test_the_run_is_on_the_rail_in_pro_too(qt_app):
    """No tick to find: Pro runs the same smart run as Novice, and the
    simulated mill is there to try it on."""
    from gerber2rml.gui2 import machine
    w = MainWindow()
    w.load_folder(str(FIXT))
    assert "autorun" in [s.key for s in w.plan.steps]
    assert machine.SHOW_SIM
    w.close()

def test_in_the_bracket_any_size_of_stock_needs_one_touch(win, qt_app):
    # A 150 x 120 sheet pushed into a back-left bracket, corner at
    # (42.49, 129.47):
    # the outline comes from the bracket and the size, the copper's height
    # from one touch, and the board is cut on it.
    sm.machine(speedup=1e6, corner=(42490, 9470), angle_deg=0.0,
               size=(150000, 120000))
    win.link.connect_to("SIM")
    assert _wait(qt_app, win.link.is_connected, 10)
    win.select_step("autorun")
    page = win.autorun_page
    page.where.setCurrentIndex(page.where.findData("bracket"))
    assert page.pick_btn.isHidden() and not page.datum_box.isHidden()
    page.set_bracket(br.Bracket(3, 12, "back-left"))
    page.corner_box.setCurrentIndex(page.corner_box.findData("back-left"))
    page.w_spin.setValue(150)
    page.h_spin.setValue(120)
    page.level_chk.setChecked(False)
    done = []
    page.finished.connect(lambda ok, msg: done.append((ok, msg)))
    page.start()
    assert _wait(qt_app, lambda: bool(done), 120), "the run never finished"
    assert done[0][0], done[0][1]
    m = sm.machine()
    xs = [p[0] for line in m.view()["cuts"] for p in line]
    ys = [p[1] for line in m.view()["cuts"] for p in line]
    assert xs and min(xs) > 42.49 and min(ys) > 9.47
    from gerber2rml.gui2 import workspace
    assert workspace.setting("autorun/bracket") == "3,12,back-left"


def test_the_outline_follows_the_size_and_the_bracket(win, qt_app):
    win.select_step("autorun")
    page = win.autorun_page
    qt_app.processEvents()
    page.where.setCurrentIndex(page.where.findData("bracket"))
    page.set_bracket(br.DEFAULT)
    page.w_spin.setValue(160)
    page.h_spin.setValue(100)
    assert win.stock == pytest.approx((31.79, 28.43, 160, 100))
    page.h_spin.setValue(60)                   # a smaller sheet, same bracket
    assert win.stock == pytest.approx((31.79, 68.43, 160, 60))


def test_the_standard_bracket_cuts_inside_its_outline(win, qt_app):
    # Back-right, a sheet tall enough for the demo board's margins.
    sm.machine(speedup=1e6, corner=(31790, 8430), angle_deg=0.0,
               size=(160000, 120000))
    win.link.connect_to("SIM")
    assert _wait(qt_app, win.link.is_connected, 10)
    win.select_step("autorun")
    page = win.autorun_page
    page.where.setCurrentIndex(page.where.findData("bracket"))
    page.set_bracket(br.DEFAULT)
    page.w_spin.setValue(160)
    page.h_spin.setValue(120)
    page.level_chk.setChecked(False)
    done = []
    page.finished.connect(lambda ok, msg: done.append((ok, msg)))
    page.start()
    assert _wait(qt_app, lambda: bool(done), 120), "the run never finished"
    assert done[0][0], done[0][1]
    pts = [p for line in sm.machine().view()["cuts"] for p in line]
    assert pts
    assert min(p[0] for p in pts) > 31.79 and max(p[0] for p in pts) < 191.79
    assert min(p[1] for p in pts) > 8.43 and max(p[1] for p in pts) < 128.43


def test_a_board_under_the_probe_tongue_stops_before_anything_is_cut(
        win, qt_app):
    sm.machine(speedup=1e6, corner=(31790, 8430), angle_deg=0.0,
               size=(160000, 120000))
    win.link.connect_to("SIM")
    assert _wait(qt_app, win.link.is_connected, 10)
    win.select_step("autorun")
    page = win.autorun_page
    page.where.setCurrentIndex(page.where.findData("bracket"))
    page.set_bracket(br.DEFAULT)
    page.w_spin.setValue(160)
    page.h_spin.setValue(120)
    page.level_chk.setChecked(False)
    qt_app.processEvents()
    # On the stock, its margins kept, but its back-right corner by the tongue.
    x, y = br.DEFAULT.inside_corner()
    b = win.work_bounds()
    st = win.state
    win.action_place(st.place_x + x - 3 - b[2], st.place_y + y - 3 - b[3])
    done = []
    page.finished.connect(lambda ok, msg: done.append((ok, msg)))
    page.start()
    assert _wait(qt_app, lambda: bool(done), 60), "the run never finished"
    assert not done[0][0] and "probe tongue" in done[0][1]
    assert not sm.machine().view()["cuts"]


def test_the_run_waits_before_the_cut_out_and_can_cut_the_traces_again(
        win, qt_app):
    sm.machine(speedup=1e6, corner=(42490, 9470), angle_deg=0.0,
               size=(150000, 120000))
    win.link.connect_to("SIM")
    assert _wait(qt_app, win.link.is_connected, 10)
    win.select_step("autorun")
    page = win.autorun_page
    page.where.setCurrentIndex(page.where.findData("bracket"))
    page.set_bracket(br.Bracket(3, 12, "back-left"))
    page.w_spin.setValue(150)
    page.h_spin.setValue(120)
    page.level_chk.setChecked(False)
    page.check_chk.setChecked(True)
    done = []
    page.finished.connect(lambda ok, msg: done.append((ok, msg)))
    page.start()
    assert _wait(qt_app, lambda: not page.check_box.isHidden(), 60)
    # Brought out to be looked at, at the top, and told so.
    m = sm.machine()
    assert m.pos == [0, 150000, 0]
    assert "view position" in page.check_lbl.text()
    page.deeper_spin.setValue(0.05)
    page.again_btn.click()                     # traces once more, deeper
    assert _wait(qt_app, lambda: not page.check_box.isHidden(), 60)
    assert "0.05 mm deeper" in page.check_lbl.text()
    page.cut_btn.click()
    assert _wait(qt_app, lambda: bool(done), 60), "the run never finished"
    assert done[0][0], done[0][1]
    sent = sorted(p.name for p in page.run_dir.glob("*.nc"))
    assert len(sent) == 4                      # drill, traces x2, cut-out
    assert not (page.run_dir / "height_map_bottom.csv").exists()


def test_ticked_a_run_leaves_the_laser_file_in_its_folder(win, qt_app):
    """Novice has no export, so Start is where the solder mask file gets made."""
    win.action_solder_mask(True)
    win.link.connect_to("SIM")
    assert _wait(qt_app, win.link.is_connected, 10)
    win.select_step("autorun")
    page = win.autorun_page
    page.w_spin.setValue(150)
    page.h_spin.setValue(120)
    page.on_stock_click(110.0, 80.0)
    done = []
    page.finished.connect(lambda ok, msg: done.append((ok, msg)))
    page.start()
    assert (page.run_dir / "buck_mask_mirrored.dxf").exists()
    assert _wait(qt_app, lambda: bool(done), 120), "the run never finished"
    assert done[0][0], done[0][1]


def test_ticked_a_run_leaves_the_silkscreen_file_in_its_folder(win, qt_app):
    """Like the solder mask: Start writes it, for Novice, which has no export."""
    win.action_silkscreen(True)
    win.link.connect_to("SIM")
    assert _wait(qt_app, win.link.is_connected, 10)
    win.select_step("autorun")
    page = win.autorun_page
    page.w_spin.setValue(150)
    page.h_spin.setValue(120)
    page.on_stock_click(110.0, 80.0)
    done = []
    page.finished.connect(lambda ok, msg: done.append((ok, msg)))
    page.start()
    assert (page.run_dir / "buck_silk_top_not_mirrored.dxf").exists()
    assert _wait(qt_app, lambda: bool(done), 120), "the run never finished"
    assert done[0][0], done[0][1]


def test_start_at_lists_the_jobs(win, qt_app):
    win.select_step("autorun")
    page = win.autorun_page
    page._fill_rows()
    keys = [page.start_box.itemData(i) for i in range(page.start_box.count())]
    assert keys[0] is None and "cutout_run" in keys and "traces_run" in keys


def test_a_board_placed_on_the_stock_stays_where_it_was_put(win, qt_app):
    sm.machine(speedup=1e6, corner=(42490, 9470), angle_deg=0.0,
               size=(150000, 120000))
    win.link.connect_to("SIM")
    assert _wait(qt_app, win.link.is_connected, 10)
    win.select_step("autorun")
    page = win.autorun_page
    page.where.setCurrentIndex(page.where.findData("bracket"))
    page.set_bracket(br.Bracket(3, 12, "back-left"))
    page.w_spin.setValue(150)
    page.h_spin.setValue(120)
    page.level_chk.setChecked(False)
    qt_app.processEvents()
    # Put the board in the stock's back-left corner, clear of the tongue.
    b = win.work_bounds()
    st = win.state
    win.action_place(st.place_x + 42.49 + 7 - b[0],
                     st.place_y + 129.47 - 7 - b[3])
    before = win.work_bounds()
    done = []
    page.finished.connect(lambda ok, msg: done.append((ok, msg)))
    page.start()
    assert _wait(qt_app, lambda: bool(done), 120), "the run never finished"
    assert done[0][0], done[0][1]
    after = win.work_bounds()
    assert after == pytest.approx(before, abs=0.01)


def test_dragging_the_board_turns_centring_off_and_it_stays_put(win, qt_app):
    win.select_step("autorun")
    page = win.autorun_page
    page.where.setCurrentIndex(page.where.findData("bracket"))
    page.set_bracket(br.DEFAULT)
    page.w_spin.setValue(160)
    page.h_spin.setValue(120)
    try:
        page.centre_chk.setChecked(True)
        qt_app.processEvents()
        before = win.work_bounds()
        win._on_drag(10.0, -5.0)
        assert not page.centre_chk.isChecked()
        after = win.work_bounds()
        assert after[0] == pytest.approx(before[0] + 10.0)
        assert after[1] == pytest.approx(before[1] - 5.0)
        page._sync_outline()                # what Start does, and any edit
        assert win.work_bounds() == pytest.approx(after)
    finally:
        page.centre_chk.setChecked(False)   # remembered: leave it as found


def test_centred_the_board_lands_in_the_middle_of_the_stock_found(win,
                                                                 qt_app):
    """Found by its edges, not where the outline was typed: the run centres
    the board on the stock the probe measured, and the cuts follow it."""
    sm.machine(speedup=1e6, corner=(30000, 20000), angle_deg=0.0,
               size=(150000, 120000))
    win.link.connect_to("SIM")
    assert _wait(qt_app, win.link.is_connected, 10)
    win.select_step("autorun")
    page = win.autorun_page
    page.w_spin.setValue(150)
    page.h_spin.setValue(120)
    page.level_chk.setChecked(False)
    page.centre_chk.setChecked(True)
    try:
        page.on_stock_click(100.0, 80.0)
        done = []
        page.finished.connect(lambda ok, msg: done.append((ok, msg)))
        page.start()
        assert _wait(qt_app, lambda: bool(done), 120), "the run never finished"
        assert done[0][0], done[0][1]
        sx, sy, sw, sh = win.stock
        b = win.work_bounds()
        assert b[0] - sx == pytest.approx(sx + sw - b[2], abs=0.05)
        assert b[1] - sy == pytest.approx(sy + sh - b[3], abs=0.05)
        # The stock the probe found, not a typed one: 30, 20 to 180, 140.
        assert (sx + sw / 2, sy + sh / 2) == pytest.approx((105, 80), abs=0.3)
        xs = [p[0] for line in sm.machine().view()["cuts"] for p in line]
        ys = [p[1] for line in sm.machine().view()["cuts"] for p in line]
        assert (min(xs) + max(xs)) / 2 == pytest.approx(105, abs=0.6)
        assert (min(ys) + max(ys)) / 2 == pytest.approx(80, abs=0.6)
    finally:
        page.centre_chk.setChecked(False)     # remembered: leave it as found


def test_centring_moves_the_board_to_the_middle_of_the_outline(win, qt_app):
    """In the bracket, what is on the screen is where it is cut, so ticking
    the box centres the board on the outline there and then."""
    win.select_step("autorun")
    page = win.autorun_page
    page.where.setCurrentIndex(page.where.findData("bracket"))
    page.set_bracket(br.Bracket(3, 12, "back-left"))
    page.w_spin.setValue(150)
    page.h_spin.setValue(120)
    try:
        page.centre_chk.setChecked(True)
        qt_app.processEvents()
        sx, sy, sw, sh = win.stock
        b = win.work_bounds()
        assert b[0] - sx == pytest.approx(sx + sw - b[2], abs=0.01)
        assert b[1] - sy == pytest.approx(sy + sh - b[3], abs=0.01)
    finally:
        page.centre_chk.setChecked(False)


def test_at_the_check_a_box_recuts_only_the_traces_inside_it(win, qt_app):
    sm.machine(speedup=1e6, corner=(42490, 9470), angle_deg=0.0,
               size=(150000, 120000))
    win.link.connect_to("SIM")
    assert _wait(qt_app, win.link.is_connected, 10)
    win.select_step("autorun")
    page = win.autorun_page
    page.where.setCurrentIndex(page.where.findData("bracket"))
    page.set_bracket(br.Bracket(3, 12, "back-left"))
    page.w_spin.setValue(150)
    page.h_spin.setValue(120)
    page.level_chk.setChecked(False)
    page.check_chk.setChecked(True)
    done = []
    page.finished.connect(lambda ok, msg: done.append((ok, msg)))
    page.start()
    assert _wait(qt_app, lambda: not page.check_box.isHidden(), 60)
    page.box_btn.setChecked(True)
    assert win.stage.mode == "box"
    b = win.work_bounds()
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    win._on_region(cx - 10, cy - 10, cx + 10, cy + 10)   # as a drag would
    assert page.again_btn.text() == "Recut 1 box"
    assert not win.rework_page._regions                   # not Rework's
    page.again_btn.click()
    assert _wait(qt_app, lambda: not page.check_box.isHidden(), 60)
    page.cut_btn.click()
    assert _wait(qt_app, lambda: bool(done), 60), "the run never finished"
    assert done[0][0], done[0][1]
    files = sorted(page.run_dir.glob("*.nc"))
    full, redo = files[1].read_text(), files[2].read_text()
    assert len(redo) < len(full) / 2                       # only the box


def test_a_loaded_setup_brings_its_stock_size_and_the_board_stays(
        win, qt_app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    win.select_step("autorun")
    page = win.autorun_page
    page.where.setCurrentIndex(page.where.findData("bracket"))
    page.set_bracket(br.DEFAULT)
    page.w_spin.setValue(120)
    page.h_spin.setValue(110)
    qt_app.processEvents()
    b = win.work_bounds()
    st = win.state
    win.action_place(st.place_x + win.stock[0] + 8 - b[0],
                     st.place_y + win.stock[1] + 3 - b[1])
    path = tmp_path / "job.srmcam"
    before = win.work_bounds()
    stock = win.stock
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *a, **k: (str(path), ""))
    win.action_save_setup()
    page.w_spin.setValue(160)
    page.h_spin.setValue(100)
    win.load_setup(path)
    qt_app.processEvents()
    assert (page.w_spin.value(), page.h_spin.value()) == (120, 110)
    assert win.stock == pytest.approx(stock)
    assert win.work_bounds() == pytest.approx(before)
    page._sync_outline()                     # the next edit, or opening the page
    assert win.stock == pytest.approx(stock)
    assert win.work_bounds() == pytest.approx(before)


def test_a_double_sided_job_can_start_at_the_fiducials(win, qt_app):
    win.action_double_sided(True)
    win.select_step("autorun")
    page = win.autorun_page
    page._fill_rows()
    keys = [page.start_box.itemData(i) for i in range(page.start_box.count())]
    at = keys.index(ar.START_AT_FIDUCIALS)
    assert at > 0 and keys[at + 1:] and at < keys.index("cutout_run")


def test_a_fit_with_a_hole_not_found_is_shown_and_logged(win, qt_app, tmp_path):
    from gerber2rml.engine.fiducial import Transform
    win.action_double_sided(True)
    win.select_step("autorun")
    page = win.autorun_page
    logged = []
    page._log = logged.append
    nominal = [(10.0, 10.0), (60.0, 10.0), (60.0, 40.0), (10.0, 40.0)]
    measured = [(10.0, 10.0), (60.0, 10.0), None, (10.0, 40.0)]
    page._on_fit(nominal, measured, Transform(theta=0.0, scale=1.0, tx=0.0, ty=0.0))
    assert "fiducial 3 not found" in logged
    assert sum("off by" in s for s in logged) == 3
    assert win._fid_measured[2] is None
    qt_app.processEvents()


def _to_the_check(win, qt_app, double, start_at=None, flip=True):
    sm.machine(speedup=1e6, corner=(31790, 4430), angle_deg=0.0,
               size=(160000, 124000))
    if double:
        win.inspector.setup.double.setChecked(True)
    win.link.connect_to("SIM")
    assert _wait(qt_app, win.link.is_connected, 10)
    win.select_step("autorun")
    page = win.autorun_page
    page.where.setCurrentIndex(page.where.findData("bracket"))
    page.set_bracket(br.DEFAULT)
    page.w_spin.setValue(160)
    page.h_spin.setValue(124)
    page.level_chk.setChecked(False)
    page.check_chk.setChecked(True)
    done = []
    page.finished.connect(lambda ok, msg: done.append((ok, msg)))
    page.start()

    def step():
        if not page.flip_btn.isHidden():
            page._flipped()
        return not page.check_box.isHidden() or bool(done)
    assert _wait(qt_app, step, 240)
    assert not done, done
    return page, done


def test_at_the_check_the_holes_can_be_drilled_again_from_this_side(win, qt_app):
    page, done = _to_the_check(win, qt_app, True)
    sent = []
    page._events.job_sig.connect(lambda key, label, prog: sent.append((key, prog)))
    page.holes_spin.setValue(0.3)
    page.holes_btn.click()
    assert _wait(qt_app, lambda: bool(sent) and not page.check_box.isHidden(), 60)
    key, prog = sent[0]
    assert key == ar.HOLES_AGAIN
    # Where the fit says the board's holes came through, on this face.
    lay = win._ds_layout()
    from gerber2rml.doublesided import reflect_holes
    want = win._fit_holes(reflect_holes(lay.holes, lay.axis, lay.flip_pos))
    first = re.search(r"G0 X([-0-9.]+) Y([-0-9.]+)", prog)
    x, y = float(first[1]), float(first[2])
    assert min(math.hypot(x - h[0], y - h[1]) for h in want) < 1.0
    page.cut_btn.click()
    assert _wait(qt_app, lambda: bool(done), 60)
    assert done[0][0], done[0][1]


def test_a_board_with_its_traces_cut_can_start_at_the_check(win, qt_app):
    win.select_step("autorun")
    page = win.autorun_page
    page._fill_rows()
    keys = [page.start_box.itemData(i) for i in range(page.start_box.count())]
    assert ar.START_AT_CHECK in keys


def test_once_turned_over_the_bed_shows_the_top_and_drops_the_old_map(
        win, qt_app, monkeypatch):
    win.action_double_sided(True)
    win.select_step("autorun")
    page = win.autorun_page
    page._fill_rows()
    qt_app.processEvents()
    drawn, meshes, points = [], [], []
    real = win.stage.set_board

    def set_board(copper, outline, *a, **k):
        drawn.append(outline)
        return real(copper, outline, *a, **k)
    monkeypatch.setattr(win.stage, "set_board", set_board)
    monkeypatch.setattr(win.stage, "set_level_mesh",
                        lambda *a: meshes.append(a))
    monkeypatch.setattr(win.stage, "set_probe_points", points.append)
    lay = win._ds_layout()
    page._set_row("stock_top", "running")
    wait = time.monotonic() + 5
    while not drawn and time.monotonic() < wait:
        qt_app.processEvents()
    assert win._auto_top
    assert drawn[-1].equals(lay.top_outline)
    assert meshes[-1] == (None, None, 0.0) and points[-1] == []
    # A new start, and it is the first side again.
    del drawn[:]
    win.show_auto_face(False)
    wait = time.monotonic() + 5
    while not drawn and time.monotonic() < wait:
        qt_app.processEvents()
    assert drawn[-1].equals(lay.outline)



def test_the_boards_own_holes_are_the_reference_holes_through_a_flip(
        win, qt_app, monkeypatch):
    """Mounting holes instead of drilled fiducials: nothing extra is cut,
    and the top is still found from them after the flip. The fixture's
    widest far-apart holes are 1.52 mm, so the room asked for the bit is
    eased a hair for this run."""
    from gerber2rml.engine import mountfid
    monkeypatch.setattr(mountfid, "ROOM_FOR_BIT", 0.7)
    win.action_double_sided(True)
    assert win.use_mounting_holes()
    assert win.reference_holes() == "mounting" and win._fid_count == 2
    assert win._fid_diameter == pytest.approx(1.52)
    lay = win._ds_layout()
    at = {(round(x, 2), round(y, 2)) for x, y, _d in lay.holes}
    for x, y, d in lay.align_holes:              # each IS one of its holes
        assert (round(x, 2), round(y, 2)) in at and d == pytest.approx(1.52)
    assert not win._pins_draggable()             # not pins to pull about
    win.link.connect_to("SIM")
    assert _wait(qt_app, win.link.is_connected, 10)
    win.select_step("autorun")
    page = win.autorun_page
    page._sync_outline()               # what showing the page does
    assert page.ref_box.currentData() == "mounting"
    page.w_spin.setValue(150)
    page.h_spin.setValue(120)
    page.on_stock_click(110.0, 80.0)
    done = []
    page.finished.connect(lambda ok, msg: done.append((ok, msg)))
    page.start()
    assert win._fid_diameter == pytest.approx(1.52)   # Start kept their size
    assert _wait(qt_app, lambda: not page.flip_btn.isHidden(), 120), \
        page.status.text()
    page._flipped()
    assert _wait(qt_app, lambda: bool(done), 180), "the run never finished"
    assert done[0][0], done[0][1]
    assert win._top_fit is not None
    assert sum(m is not None for m in win._fid_measured) == 2


def test_a_board_without_mounting_holes_keeps_its_reference_holes(win):
    win.action_double_sided(True)
    before = (win._fid_placement, win._fid_count, win._fid_diameter)
    said = []
    win.say = lambda level, text: said.append((level, text))
    assert win.use_mounting_holes() is False     # 2.0 mm pair is 28 mm apart
    assert (win._fid_placement, win._fid_count, win._fid_diameter) == before
    assert said and said[-1][0] == "warn"
    win.action_fiducial_layout(4, "mounting", 4.0)
    assert win.reference_holes() == "waste"


def test_leaving_mounting_holes_restores_drilled_ones(win, monkeypatch):
    from gerber2rml.engine import mountfid
    monkeypatch.setattr(mountfid, "ROOM_FOR_BIT", 0.7)
    win.action_double_sided(True)
    assert win.use_mounting_holes()
    win.action_fiducial_layout(win._fid_count, "waste", 4.0)
    assert win.reference_holes() == "waste" and win._fid_count == 4
    assert win._fid_diameter == pytest.approx(1.6)
    assert len(win._ds_layout().align_holes) == 4


def _tight_sheet(win, qt_app):
    """The 104 mm fixture board on a 106 mm sheet in the lab's bracket: no
    room for margins, a cut-out, or to keep clear of the tongue."""
    x, y = br.DEFAULT.inside_corner()
    sm.machine(speedup=1e6, angle_deg=0.0, size=(106000, 106000),
               corner=(int(round((x - 106) * 1000)),
                       int(round((y - 106) * 1000))))
    win.link.connect_to("SIM")
    assert _wait(qt_app, win.link.is_connected, 10)
    win.select_step("autorun")
    page = win.autorun_page
    page.where.setCurrentIndex(page.where.findData("bracket"))
    page.set_bracket(br.DEFAULT)
    page.centre_chk.setChecked(False)
    page.w_spin.setValue(106)
    page.h_spin.setValue(106)
    page.level_chk.setChecked(False)
    page._sync_outline()
    return page


def test_cut_out_as_usual_a_sheet_the_boards_size_is_refused(win, qt_app):
    page = _tight_sheet(win, qt_app)
    done = []
    page.finished.connect(lambda ok, msg: done.append((ok, msg)))
    page.start()
    assert _wait(qt_app, lambda: bool(done), 120)
    assert not done[0][0]
    assert "stock" in done[0][1]


def test_left_in_the_sheet_it_runs_with_no_cut_out_right_up_to_the_bracket(
        win, qt_app, monkeypatch):
    page = _tight_sheet(win, qt_app)
    page.nocut_chk.setChecked(True)
    assert win._no_cutout and not page.check_chk.isEnabled()
    assert not any("cutout" in k for k, _t in page._plan_rows())
    b, (sx, sy, sw, sh) = win.work_extent(), win.stock
    assert (b[0], b[1]) == pytest.approx((sx, sy))     # the far corner
    kx0, ky0, kx1, ky1 = br.DEFAULT.keepout()
    assert b[3] > ky0 and b[2] > kx0                   # it IS under the tongue
    jobs = []
    real = ar.AutoRun._job

    def spy(self, key, *a, **k):
        jobs.append(key)
        return real(self, key, *a, **k)
    monkeypatch.setattr(ar.AutoRun, "_job", spy)
    done = []
    page.finished.connect(lambda ok, msg: done.append((ok, msg)))
    page.start()
    assert _wait(qt_app, lambda: bool(done), 180), "the run never finished"
    assert done[0][0], done[0][1]
    assert jobs and not any("cutout" in k for k in jobs)
    page.nocut_chk.setChecked(False)                   # as it was found
    assert not win._no_cutout
    assert any("cutout" in k for k, _t in page._plan_rows())


def test_the_box_is_there_with_the_bracket_either_number_of_faces(win):
    page = win.autorun_page
    page.nocut_chk.setChecked(True)
    assert page.no_cutout() is False                   # found by its edges
    page.where.setCurrentIndex(page.where.findData("bracket"))
    assert page.no_cutout() is True
    win.action_double_sided(True)
    page._sync_nocut()
    assert page.no_cutout() is True                    # two faces as well
    assert not page.nocut_chk.isHidden() and page.nocut_chk.isEnabled()
    assert not any("cutout" in k for k, _t in page._plan_rows())
    win.action_double_sided(False)
    page.nocut_chk.setChecked(False)


def test_left_in_the_sheet_a_double_sided_board_is_flipped_and_finished(
        win, qt_app, monkeypatch):
    """Both faces, no cut-out: 1 mm of sheet each side of the 104 mm board,
    its reference holes inside its corners."""
    x, y = br.DEFAULT.inside_corner()
    sm.machine(speedup=1e6, angle_deg=0.0, size=(106000, 114000),
               corner=(int(round((x - 106) * 1000)),
                       int(round((y - 114) * 1000))))
    win.action_double_sided(True)
    win.action_fiducial_layout(4, "onboard", 4.0)
    win.link.connect_to("SIM")
    assert _wait(qt_app, win.link.is_connected, 10)
    win.select_step("autorun")
    page = win.autorun_page
    page.where.setCurrentIndex(page.where.findData("bracket"))
    page.set_bracket(br.DEFAULT)
    page.centre_chk.setChecked(False)
    page.w_spin.setValue(106)
    page.h_spin.setValue(114)
    page.level_chk.setChecked(False)
    page._sync_outline()
    page.nocut_chk.setChecked(True)
    b, (sx, sy, sw, sh) = win.work_extent(), win.stock
    assert b[0] - sx == pytest.approx(sx + sw - b[2])  # centred across it
    assert b[1] == pytest.approx(sy)                   # and at the front
    jobs = []
    real = ar.AutoRun._job

    def spy(self, key, *a, **k):
        jobs.append(key)
        return real(self, key, *a, **k)
    monkeypatch.setattr(ar.AutoRun, "_job", spy)
    done = []
    page.finished.connect(lambda ok, msg: done.append((ok, msg)))
    page.start()
    assert _wait(qt_app, lambda: not page.flip_btn.isHidden() or bool(done),
                 120), page.status.text()
    assert not done, done
    page._flipped()
    assert _wait(qt_app, lambda: bool(done), 180), "the run never finished"
    assert done[0][0], done[0][1]
    assert win._top_fit is not None
    assert any("top" in k for k in jobs)
    assert not any("cutout" in k for k in jobs)
    page.nocut_chk.setChecked(False)


def test_a_laser_board_is_drilled_and_cut_out_only(win, qt_app):
    from gerber2rml.engine import method as fab
    win.link.connect_to("SIM")
    assert _wait(qt_app, win.link.is_connected, 10)
    win.select_step("autorun")
    page = win.autorun_page
    page.w_spin.setValue(150)
    page.h_spin.setValue(120)
    page.on_stock_click(110.0, 80.0)
    assert any("traces" in k for k, _t in page._plan_rows())
    page.level_chk.setChecked(True)
    win.action_method(fab.LASER)
    keys = [k for k, _t in page._plan_rows()]
    assert not any("traces" in k for k in keys)
    assert any("drill" in k for k in keys) and any("cutout" in k for k in keys)
    assert not page.level_chk.isChecked() and not page.check_chk.isEnabled()
    assert all("traces" not in str(page.start_box.itemData(i))
               for i in range(page.start_box.count()))
    done = []
    page.finished.connect(lambda ok, msg: done.append((ok, msg)))
    page.start()
    assert _wait(qt_app, lambda: bool(done), 120), "the run never finished"
    assert done[0][0], done[0][1]
    sent = sorted(p.name for p in page.run_dir.glob("*.nc"))
    assert len(sent) == 2 and not any("trace" in n for n in sent), sent
    win.action_method(fab.FLAT)                        # as it was found
    assert page.level_chk.isChecked() and not win._traces_on_laser
    assert any("traces" in k for k, _t in page._plan_rows())


def test_a_laser_board_needs_no_flip_on_the_mill(win, qt_app):
    from gerber2rml.engine import method as fab
    win.inspector.setup.double.setChecked(True)
    assert win._double
    win.select_step("autorun")
    page = win.autorun_page
    win.action_method(fab.LASER)
    assert not win._double and not win.inspector.setup.double.isChecked()
    keys = [k for k, _t in page._plan_rows()]
    assert "flip" not in keys and not any("traces" in k for k in keys)
    # Both faces are still there for the laser.
    assert win._laser_art_for("traces", side="top").side == "top"
    win.action_method(fab.FLAT)
    assert win._double
