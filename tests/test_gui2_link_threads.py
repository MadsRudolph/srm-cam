"""The link's port belongs to its worker: closed there, written under a lock,
and a STOP drops whatever was still queued."""
import threading
import time

from gerber2rml.engine import spi_probe
from gerber2rml.gui2.machine import MachineLink


class FakeSerial:
    def __init__(self):
        self.closed_by = None
        self.writes = []

    def write(self, data):
        self.writes.append(data)

    def readline(self):
        return b""

    def reset_input_buffer(self):
        pass

    def close(self):
        self.closed_by = threading.current_thread().name


def _linked(qt_app, monkeypatch):
    fake = FakeSerial()
    monkeypatch.setattr(spi_probe, "open_link", lambda port, **k: fake)
    monkeypatch.setattr(spi_probe, "firmware_version", lambda ser: (4, set()))
    link = MachineLink()
    link.connect_to("COM9")
    t0 = time.monotonic()
    while not link.is_connected() and time.monotonic() - t0 < 3:
        time.sleep(0.01)
    assert link.is_connected()
    return link, fake


def test_the_worker_closes_the_port_not_the_caller(qt_app, monkeypatch):
    link, fake = _linked(qt_app, monkeypatch)
    link.disconnect_from("test")
    assert fake.closed_by == "srm-link"


def test_stop_drops_the_commands_still_queued(qt_app, monkeypatch):
    link, fake = _linked(qt_app, monkeypatch)
    gate = threading.Event()
    ran = []
    link.submit("slow", lambda ser: gate.wait(2))
    link.submit("spindle", lambda ser: ran.append("spindle"))
    time.sleep(0.05)
    link.stop_now()
    gate.set()
    time.sleep(0.2)
    assert ran == []                       # the queued spindle start never ran
    link.disconnect_from("test")
