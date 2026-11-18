"""The second interface's Machine test window lets go of the port however it
is closed.

Its worker holds the serial port, and the main window reconnects to the same
port the moment the window's exec() returns. Close and Escape went through
reject(), which raises no closeEvent, so the worker was never stopped: two
owners of one port.
"""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton

from gerber2rml.gui2 import machinetest as mt2


@pytest.fixture
def stops(qt_app, monkeypatch):
    """MachineTestDialog with a worker that counts how often it is stopped."""
    stopped = []

    class _Sig:
        def connect(self, _fn):
            pass

    class StubWorker:
        status = result = log = batch_done = failed = _Sig()

        def __init__(self, port, should_abort=None):
            self.port = port

        def start(self):
            pass

        def stop(self):
            stopped.append(self.port)

        def request_tests(self, keys):
            pass

        def request_abort(self):
            pass

    monkeypatch.setattr(mt2, "_TestWorker", StubWorker)
    return stopped


def _close_button(dlg):
    return next(b for b in dlg.findChildren(QPushButton) if b.text() == "Close")


def test_the_close_button_stops_the_worker(stops):
    dlg = mt2.MachineTestDialog("COM-TEST")
    dlg.show()
    _close_button(dlg).click()
    assert stops == ["COM-TEST"]
    assert not dlg.isVisible()


def test_escape_stops_the_worker(stops):
    dlg = mt2.MachineTestDialog("COM-TEST")
    dlg.show()
    QTest.keyClick(dlg, Qt.Key_Escape)
    assert stops and stops[0] == "COM-TEST"
    assert not dlg.isVisible()


def test_the_window_x_stops_the_worker(stops):
    dlg = mt2.MachineTestDialog("COM-TEST")
    dlg.show()
    dlg.close()
    assert stops and stops[0] == "COM-TEST"
    assert not dlg.isVisible()
