"""Machine dock controls: spindle, pause/resume, view and the live status strip.

These wrap SPI commands proven on the machine in the 2026-08 audit. The tests
here are about the RULES around them — the cover interlock, not claiming a
spindle is running when the link is gone, routing pause to whatever actually
owns the serial port — because those are what stop a proven-working command
from doing the wrong thing.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import matplotlib
matplotlib.use("Agg")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from gerber2rml.gui.app import MainWindow

_app = QApplication.instance() or QApplication([])


class _Sig:
    def disconnect(self, _fn=None):
        pass


class FakeDRO:
    """Stands in for the poller: records what the window asked the machine for."""

    def __init__(self):
        self.spindle = []
        self.jobctl = []
        self.stopped = False
        self.position = _Sig()

    def request_spindle(self, rpm):
        self.spindle.append(rpm)

    def request_jobctl(self, what):
        self.jobctl.append(what)

    def request_abort(self):
        pass

    def stop(self):
        self.stopped = True


@pytest.fixture
def win():
    w = MainWindow()
    yield w
    w.close()


@pytest.fixture
def connected(win):
    win._dro = FakeDRO()
    for b in (win.spindle_btn, win.pause_btn, win.resume_btn, win.view_btn):
        b.setEnabled(True)
    return win


def _yes(monkeypatch):
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))


def _no(monkeypatch):
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.No))


# --- the cover interlock ----------------------------------------------------
def test_spindle_refused_while_the_lid_is_open(connected, monkeypatch):
    warned = []
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: warned.append(a)))
    _yes(monkeypatch)
    connected._on_machine_status({"cover": True, "spindle": False})
    connected.spindle_btn.setChecked(True)
    assert connected._dro.spindle == []          # never asked the machine
    assert not connected.spindle_btn.isChecked()
    assert warned


def test_spindle_needs_a_confirmation(connected, monkeypatch):
    _no(monkeypatch)
    connected._on_machine_status({"cover": False, "spindle": False})
    connected.spindle_btn.setChecked(True)
    assert connected._dro.spindle == []
    assert not connected.spindle_btn.isChecked()


def test_spindle_starts_once_confirmed(connected, monkeypatch):
    _yes(monkeypatch)
    connected._on_machine_status({"cover": False, "spindle": False})
    connected.spindle_btn.setChecked(True)
    assert connected._dro.spindle == [connected._SPINDLE_RPM]


def test_stopping_the_spindle_never_asks(connected, monkeypatch):
    _yes(monkeypatch)
    connected._on_machine_status({"cover": False, "spindle": False})
    connected.spindle_btn.setChecked(True)
    _no(monkeypatch)                             # a refusal must not block STOP
    connected.spindle_btn.setChecked(False)
    assert connected._dro.spindle[-1] == 0


def test_spindle_refused_by_the_machine_unticks_the_button(connected, monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    connected.spindle_btn.blockSignals(True)
    connected.spindle_btn.setChecked(True)
    connected.spindle_btn.blockSignals(False)
    connected._on_spindle_done(False, 0)
    assert not connected.spindle_btn.isChecked()


# --- the status strip -------------------------------------------------------
def test_status_strip_names_what_is_wrong(connected):
    connected._on_machine_status({"cover": True, "spindle": False, "rpm": 0})
    assert "LID OPEN" in connected.machine_label.text()
    connected._on_machine_status({"cover": False, "spindle": True, "rpm": 8600})
    assert "8600" in connected.machine_label.text()
    connected._on_machine_status({"cover": False, "spindle": False, "fatal": True})
    assert "FAULT" in connected.machine_label.text()


def test_button_follows_a_spindle_started_elsewhere(connected):
    """The operator also runs the spindle from VPanel; the button must reflect
    the machine, not just what this app asked for."""
    connected._on_machine_status({"cover": False, "spindle": True, "rpm": 8600})
    assert connected.spindle_btn.isChecked()
    assert connected._dro.spindle == []          # ...without commanding anything


def test_disconnect_clears_the_strip_and_unticks_the_spindle(win):
    win._dro = FakeDRO()
    win._on_machine_status({"cover": False, "spindle": True, "rpm": 8600})
    assert win.spindle_btn.isChecked()
    win._stop_dro()
    assert not win.spindle_btn.isChecked()       # the link is gone: claim nothing
    assert win.machine_label.text() == ""
    assert not win.spindle_btn.isEnabled()


# --- transport routing ------------------------------------------------------
def test_pause_goes_to_the_machine_when_idle(connected):
    connected._on_jobctl("pause")
    assert connected._dro.jobctl == ["pause"]


def test_pause_goes_to_the_STREAM_when_one_is_running(connected):
    """During a stream the worker owns the serial port, not the poller — a
    pause sent to the poller would go nowhere."""
    class FakeStream:
        def __init__(self):
            self.paused = None

        def isRunning(self):
            return True

        def set_paused(self, on):
            self.paused = on

    connected._stream_worker = FakeStream()
    connected._on_jobctl("pause")
    assert connected._stream_worker.paused is True
    assert connected._dro.jobctl == []           # not sent twice
    connected._on_jobctl("resume")
    assert connected._stream_worker.paused is False


def test_view_always_goes_to_the_machine(connected):
    connected._on_jobctl("view")
    assert connected._dro.jobctl == ["view"]


def test_controls_do_nothing_without_a_link(win):
    win._dro = None
    win._on_jobctl("pause")                      # must not raise
    win.spindle_btn.setChecked(True)
    assert not win.spindle_btn.isChecked()


# --- Z jog ------------------------------------------------------------------
# Z is the axis you nudge constantly by hand — setting up a touch-off, backing
# off after a probe. Until now the only jog was click-to-jog, which is XY only.

class ZJogDRO(FakeDRO):
    def __init__(self):
        super().__init__()
        self.zjog = []

    def request_jog_z(self, dz_um):
        self.zjog.append(dz_um)


@pytest.fixture
def zwin(win):
    win._dro = ZJogDRO()
    win.zjog_up_btn.setEnabled(True)
    win.zjog_down_btn.setEnabled(True)
    return win


def _set_step(w, mm):
    w.zjog_step.setCurrentIndex(
        [w.zjog_step.itemData(i) for i in range(w.zjog_step.count())].index(mm))


def test_up_moves_positive_by_the_selected_step(zwin):
    _set_step(zwin, 0.5)
    zwin.zjog_up_btn.click()
    assert zwin._dro.zjog == [500]           # microns, away from the work


def test_down_moves_negative(zwin):
    _set_step(zwin, 1.0)
    zwin.zjog_down_btn.click()
    assert zwin._dro.zjog == [-1000]


def test_step_size_is_honoured(zwin):
    for mm, expect in ((0.01, 10), (0.05, 50), (5.0, 5000)):
        zwin._dro.zjog.clear()
        _set_step(zwin, mm)
        zwin.zjog_up_btn.click()
        assert zwin._dro.zjog == [expect], mm


def test_repeated_presses_accumulate_rather_than_replace(zwin):
    """Four presses must be four steps. The poller coalesces them into one
    move, but dropping three would leave the bit somewhere nobody asked for."""
    from gerber2rml.gui.app import _DROPoller
    p = _DROPoller("COM-TEST")
    for _ in range(4):
        p.request_jog_z(-100)
    assert p._pending_zjog == -400


def test_down_is_refused_while_the_bit_is_touching(zwin, monkeypatch):
    warned = []
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: warned.append(a)))
    zwin._touching = True
    _set_step(zwin, 1.0)
    zwin.zjog_down_btn.click()
    assert zwin._dro.zjog == []              # never sent
    assert warned


def test_up_is_allowed_while_touching(zwin):
    """Retreating from contact is the whole point of the button."""
    zwin._touching = True
    _set_step(zwin, 0.1)
    zwin.zjog_up_btn.click()
    assert zwin._dro.zjog == [100]


def test_z_jog_does_nothing_without_a_link(win):
    win._dro = None
    win._on_jog_z(+1)                        # must not raise


def test_z_jog_buttons_track_the_connection(win):
    assert not win.zjog_up_btn.isEnabled()   # nothing to move until connected
    assert not win.zjog_down_btn.isEnabled()
