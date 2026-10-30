"""The Run-it-all page, end to end against the simulator: connect to SIM,
click the stock, Start, and the board comes out cut where the design is."""
import time
from pathlib import Path

import pytest

from gerber2rml.engine import simmachine as sm
from gerber2rml.gui2.window import MainWindow

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"


@pytest.fixture
def win(qt_app):
    # The fixture board is 104 mm square: a 150 x 120 sheet holds it.
    sm.machine(speedup=1e6, corner=(41300, 27800), angle_deg=1.2,
               size=(150000, 120000))
    w = MainWindow()
    w.resize(1400, 900)
    w.load_folder(str(FIXT))
    yield w
    w.link.disconnect_from("test")
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
    assert sm.machine().face == 1