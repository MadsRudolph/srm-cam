"""The Run-it-all page, end to end against the simulator: connect to SIM,
click the stock, Start, and the board comes out cut where the design is."""
import time
from pathlib import Path

import pytest

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
    w.action_autorun(True)
    # These runs find the stock by its edges; the bracket has its own test.
    w.autorun_page.where.setCurrentIndex(
        w.autorun_page.where.findData("click"))
    # Straight through; the check before the cut-out has its own test.
    w.autorun_page.check_chk.setChecked(False)
    yield w
    w.action_autorun(False)                   # opt-in: leave it as found
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

def test_automatic_mode_is_off_until_chosen_and_adds_only_its_step(qt_app):
    from gerber2rml.gui2 import machine
    w = MainWindow()
    w.load_folder(str(FIXT))
    assert not w.autorun_act.isChecked()
    before = [s.key for s in w.plan.steps]
    assert "autorun" not in before and not machine.SHOW_SIM
    w.action_autorun(True)
    after = [s.key for s in w.plan.steps]
    assert [k for k in after if k != "autorun"] == before
    assert machine.SHOW_SIM
    w.action_autorun(False)
    assert [s.key for s in w.plan.steps] == before and not machine.SHOW_SIM
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
    assert win.stock == pytest.approx((32.52, 28.24, 160, 100))
    page.h_spin.setValue(60)                   # a smaller sheet, same bracket
    assert win.stock == pytest.approx((32.52, 68.24, 160, 60))


def test_the_standard_bracket_cuts_inside_its_outline(win, qt_app):
    # Back-right, a sheet tall enough for the demo board's margins.
    sm.machine(speedup=1e6, corner=(32520, 8240), angle_deg=0.0,
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
    assert min(p[0] for p in pts) > 32.52 and max(p[0] for p in pts) < 192.52
    assert min(p[1] for p in pts) > 8.24 and max(p[1] for p in pts) < 128.24


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
    # Put the board in the stock's back-left corner, 4 mm in.
    b = win.work_bounds()
    st = win.state
    win.action_place(st.place_x + 42.49 + 4 - b[0],
                     st.place_y + 129.47 - 4 - b[3])
    before = win.work_bounds()
    done = []
    page.finished.connect(lambda ok, msg: done.append((ok, msg)))
    page.start()
    assert _wait(qt_app, lambda: bool(done), 120), "the run never finished"
    assert done[0][0], done[0][1]
    after = win.work_bounds()
    assert after == pytest.approx(before, abs=0.01)


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
