"""The jog pad, keys and link against the simulator: relative, no lift, and
never a queue of moves still running after the key is let go."""
import time
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDoubleSpinBox

from gerber2rml.engine import simmachine as sm
from gerber2rml.engine import spi_probe
from gerber2rml.gui2 import machine as machine_mod
from gerber2rml.gui2.window import MainWindow

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"


@pytest.fixture
def win(qt_app, monkeypatch):
    m = sm.machine(speedup=1e6)
    m.pos = (60000, 50000, -5000)
    w = MainWindow()
    w.resize(1500, 900)
    w.link.connect_to("SIM")
    assert _wait(qt_app, w.link.is_connected, 10)
    w.bar.link.poll()
    assert _wait(qt_app, lambda: w._last_xyz is not None, 5)
    yield w
    w.link.disconnect_from("test")
    if w.link._thread is not None:
        w.link._q.put(None)
        w.link._thread.join(2)
    w.close()


def _wait(qt_app, cond, secs):
    t0 = time.monotonic()
    while not cond() and time.monotonic() - t0 < secs:
        qt_app.processEvents()
        time.sleep(0.005)
    return cond()


def _idle(qt_app, w):
    return _wait(qt_app, lambda: not w.link.is_busy()
                 and not w.link._jog_queued and w.link._q.empty(), 5)


def _head():
    return tuple(v / 1000.0 for v in sm.machine().pos)


def test_the_arrows_step_by_the_chip_and_z_stays_where_it_is(win, qt_app):
    pad = win.bar.pad
    pad.chips[1.0].click()
    x, y, z = _head()
    for _ in range(5):                         # J would have climbed 25 mm
        pad.xy[(1, 0)].click()
        assert _idle(qt_app, win)
    pad.xy[(0, 1)].click()
    assert _idle(qt_app, win)
    nx, ny, nz = _head()
    assert (nx - x, ny - y) == pytest.approx((5.0, 1.0))
    assert nz == pytest.approx(z)


def test_z_buttons_step_and_a_big_chip_only_goes_down_a_little(win, qt_app):
    pad = win.bar.pad
    pad.chips[10.0].click()
    z = _head()[2]
    pad.z_down.click()
    assert _idle(qt_app, win)
    assert _head()[2] == pytest.approx(z - 1.0)    # capped
    pad.z_up.click()
    assert _idle(qt_app, win)
    assert _head()[2] == pytest.approx(min(0.0, z - 1.0 + 10.0))


def test_a_held_key_is_a_couple_of_moves_not_a_queue(win, qt_app, monkeypatch):
    sent = []
    real = spi_probe.timed_move

    def slow(ser, dx=0, dy=0, dz=0, **kw):
        sent.append((dx, dy, dz))
        time.sleep(0.05)
        return real(ser, dx, dy, dz, **kw)
    monkeypatch.setattr(machine_mod.spi_probe, "timed_move", slow)
    x, y, _z = _head()
    for _ in range(30):
        win.link.jog_by(0.1, 0.0)
    assert _idle(qt_app, win)
    assert len(sent) <= 2
    assert _head()[0] - x == pytest.approx(3.0)


def test_stop_drops_steps_not_sent_and_the_next_jog_still_works(win, qt_app,
                                                                monkeypatch):
    real = spi_probe.timed_move

    def slow(ser, dx=0, dy=0, dz=0, **kw):
        time.sleep(0.05)
        return real(ser, dx, dy, dz, **kw)
    monkeypatch.setattr(machine_mod.spi_probe, "timed_move", slow)
    win.bar.pad.keys_btn.setChecked(True)
    for _ in range(5):
        win.link.jog_by(1.0, 0.0)
    win.bar._stop()
    assert not win.bar.pad.keys_on()
    assert win.link._jog_pending == [0.0, 0.0, 0.0]
    assert _idle(qt_app, win)
    x = _head()[0]
    win.link.jog_by(1.0, 0.0)
    assert _idle(qt_app, win)
    assert _head()[0] == pytest.approx(x + 1.0)


def test_keys_lit_the_arrows_drive_the_head_from_anywhere(win, qt_app):
    win.show()
    qt_app.processEvents()
    pad = win.bar.pad
    pad.chips[1.0].click()
    x, y, _z = _head()
    # Off: the machine does not move.
    QTest.keyClick(win.stage, Qt.Key_Right)
    win.stage._nudge_timer.stop()
    assert _idle(qt_app, win) and _head()[0] == pytest.approx(x)
    pad.keys_btn.setChecked(True)
    win.traveller.setFocus()
    QTest.keyClick(QApplication.focusWidget() or win, Qt.Key_Right)
    assert _idle(qt_app, win) and _head()[0] == pytest.approx(x + 1)
    QTest.keyClick(QApplication.focusWidget() or win, Qt.Key_Up,
                   Qt.ShiftModifier)
    assert _idle(qt_app, win) and _head()[1] == pytest.approx(y + 10)
    QTest.keyClick(QApplication.focusWidget() or win, Qt.Key_Left,
                   Qt.ControlModifier)
    assert _idle(qt_app, win) and _head()[0] == pytest.approx(x + 0.9)


def test_a_number_box_keeps_its_arrows(win, qt_app):
    win.show()
    qt_app.processEvents()
    win.bar.pad.keys_btn.setChecked(True)
    box = win.findChildren(QDoubleSpinBox)[0]
    x = _head()[0]
    box.setFocus()
    if QApplication.focusWidget() is not box:
        pytest.skip("the window has no focus on this desktop")
    QTest.keyClick(box, Qt.Key_Right)
    assert _idle(qt_app, win) and _head()[0] == pytest.approx(x)


def test_on_the_copper_a_step_sideways_or_down_is_refused(win, qt_app):
    said = []
    win.say = lambda level, text: said.append((level, text))
    win.link.position.emit(60.0, 50.0, -5.0, True)
    qt_app.processEvents()
    assert win.bar._touching
    head = _head()
    win._on_jog_step(1.0, 0.0)
    assert "touching" in said[-1][1]
    win.bar._jog(-1)
    assert _idle(qt_app, win) and _head() == head


def test_disconnecting_turns_the_keys_off(win, qt_app):
    win.bar.pad.keys_btn.setChecked(True)
    win.link.disconnect_from("test")
    assert _wait(qt_app, lambda: not win.link.is_connected(), 5)
    qt_app.processEvents()
    assert not win.bar.pad.keys_on()
