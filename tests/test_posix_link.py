"""The machine link on POSIX, through pyserial's real POSIX code.

A pseudo-terminal stands in for the Arduino's USB-serial port: what opens it is
the same ``serial.Serial`` that opens ``/dev/ttyACM0``, with the same select,
write timeout and error paths, and a thread on the other end speaks enough of
the firmware's protocol to connect, read a position and take a move. This is as
close as a machine with no mill gets, and it is what the STOP timings, the lost
link and the second-program refusal below are measured against.
"""
import errno
import functools
import os
import threading
import time

import pytest

pty = pytest.importorskip("pty")
serial = pytest.importorskip("serial")

from gerber2rml import platform as plat                 # noqa: E402
from gerber2rml.engine import spi_probe                 # noqa: E402
from gerber2rml.engine.runner import JobRunner, RunStopped  # noqa: E402
from gerber2rml.engine import rmlspool                  # noqa: E402
from gerber2rml.gui2 import machine                     # noqa: E402

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX ports")


class FakeFirmware(threading.Thread):
    """The sketch's side of the wire, on the pty's master end.

    A move (``N``) holds until a ``%`` or ``!`` arrives, the way the real one
    scans for them mid-move, and every line is timestamped as it lands, so a
    test can say how long a stop took to get here.
    """

    def __init__(self):
        super().__init__(daemon=True, name="fake-firmware")
        self.master, self.slave = pty.openpty()
        self.device = os.ttyname(self.slave)
        self.lines = []              # (monotonic, text)
        self.moving = threading.Event()
        self.mute = False
        self._halted = threading.Event()

    def _say(self, text):
        os.write(self.master, (text + "\n").encode())

    def run(self):
        buf = b""
        while True:
            try:
                got = os.read(self.master, 256)
            except OSError:
                return
            if not got:
                return
            buf += got
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                line = raw.decode("ascii", "replace").strip()
                if line:
                    self.lines.append((time.monotonic(), line))
                    threading.Thread(target=self._answer, args=(line,),
                                     daemon=True).start()

    def _answer(self, line):
        if self.mute:
            return
        try:
            c = line[0]
            if c == "V":
                self._say("V 5 retouch,zeroz,stream")
            elif c == "Q":
                self._say("Q 12340 56780 -1000 0")
            elif c == "X":
                self._say("X 130 4 0")
            elif c == "F":
                self._say("F 500")
            elif c == "N":
                self._halted.clear()
                self.moving.set()
                self._halted.wait(5)
                self.moving.clear()
                self._say("E N ABORT")
            elif c in "%!":
                self._halted.set()
                self._say(c + " ok")
            elif c == "S":
                self._say("S 0")
        except OSError:
            pass

    def unplug(self):
        """What a pulled USB lead looks like from the host: the other end of
        the port is gone, and reads and writes on it now fail."""
        os.close(self.master)
        self.master = -1

    def seen(self, text):
        return [t for t, line in self.lines if line.startswith(text)]


@pytest.fixture
def firmware(monkeypatch):
    fw = FakeFirmware()
    fw.start()
    # The real two-second wait is for an Uno rebooting. This one does not.
    monkeypatch.setattr(spi_probe, "open_link",
                        functools.partial(spi_probe.open_link, startup_wait=0))
    yield fw
    if fw.master >= 0:
        os.close(fw.master)
    os.close(fw.slave)


def _wait(qt_app, cond, secs):
    t0 = time.monotonic()
    while not cond() and time.monotonic() - t0 < secs:
        qt_app.processEvents()
        time.sleep(0.005)
    return cond()


@pytest.fixture
def bar(qt_app):
    link = machine.MachineLink()
    b = machine.MachineBar(link)
    b.said = []
    b.message.connect(lambda level, text: b.said.append((level, text)))
    yield b
    if link.is_connected():
        link.disconnect_from("test")
    if link._thread is not None:
        link._q.put(None)
        link._thread.join(2)
    b.close()


def _connect(qt_app, bar, device):
    bar.link.connect_to(device)
    # The chip, not is_connected: the worker is connected before the signal
    # that tells the bar so has been delivered.
    assert _wait(qt_app, lambda: bar.chip.label.text() == "Linked", 5), bar.said


# ---------------------------------------------------- connect, DRO, jogging
def test_connect_reads_the_position_and_a_jog_reaches_the_firmware(
        qt_app, bar, firmware):
    _connect(qt_app, bar, firmware.device)
    assert bar.chip.label.text() == "Linked"
    assert _wait(qt_app, lambda: bar.dro_x._value.text().strip() == "12.34", 3), \
        "the DRO never showed the position"
    bar._jog(+1)
    assert _wait(qt_app, lambda: firmware.seen("N "), 3)
    bar.link.stop_now()                   # the fake's move holds until told


def test_a_real_port_gets_the_not_yet_proven_warning_and_the_simulator_does_not(
        qt_app, bar, firmware, monkeypatch):
    monkeypatch.setattr(plat, "capabilities",
                        lambda p=None: plat.Capabilities(
                            machine_link=True, vpanel=False, link_proven=False))
    _connect(qt_app, bar, firmware.device)
    assert _wait(qt_app, lambda: bar.said, 2)
    assert plat.UNPROVEN_LINK_NOTE in [t for _l, t in bar.said]
    bar.said.clear()
    bar.link.disconnect_from("test")
    _connect(qt_app, bar, "SIM")
    assert _wait(qt_app, lambda: bar.said, 2)
    assert plat.UNPROVEN_LINK_NOTE not in [t for _l, t in bar.said]


# ---------------------------------------------------------------- the port
def test_a_second_program_cannot_have_the_port(firmware):
    """Windows refuses this by itself. POSIX does not, and two programs on one
    port would each read half the other's replies with the head moving."""
    first = spi_probe._open_serial(firmware.device, 115200, 0.1)
    try:
        with pytest.raises(spi_probe.PortAccessError, match="another program"):
            spi_probe._open_serial(firmware.device, 115200, 0.1)
    finally:
        first.close()
    spi_probe._open_serial(firmware.device, 115200, 0.1).close()


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0,
                    reason="root opens anything")
def test_a_refused_port_says_what_to_do_instead_of_blaming_the_cable(
        qt_app, bar, firmware):
    os.chmod(firmware.device, 0)
    try:
        bar.port_combo.addItem(firmware.device, firmware.device)
        bar.port_combo.setCurrentIndex(bar.port_combo.count() - 1)
        bar.link.connect_to(firmware.device)
        assert _wait(qt_app, lambda: any(l == "fail" for l, _t in bar.said), 5)
    finally:
        os.chmod(firmware.device, 0o620)
    level, text = bar.said[-1]
    assert level == "fail"
    assert bar.chip.label.text() == "Link failed"
    assert "PortAccessError" not in text
    assert "USB lead" not in text
    assert firmware.device in text


def test_a_failure_that_is_not_about_access_is_reported_as_it_always_was(tmp_path):
    with pytest.raises(serial.SerialException) as e:
        spi_probe._open_serial(str(tmp_path / "gone"), 115200, 0.1)
    assert not isinstance(e.value, spi_probe.PortAccessError)
    assert e.value.errno == errno.ENOENT


def test_flush_gives_up_on_a_port_that_never_drains():
    """pyserial's POSIX flush is tcdrain, which has no timeout, and STOP calls
    it from the GUI thread."""
    class Wedged:
        out_waiting = 5
    t0 = time.monotonic()
    spi_probe._BoundedFlushPort(Wedged()).flush()
    took = time.monotonic() - t0
    assert spi_probe.FLUSH_LIMIT_S <= took < spi_probe.FLUSH_LIMIT_S + 0.2


def test_only_posix_wraps_the_port_or_asks_for_exclusivity():
    assert plat.serial_open_options("win32") == {}
    assert plat.serial_open_options("linux") == {"exclusive": True}
    assert plat.serial_open_options("darwin") == {"exclusive": True}
    assert not plat.serial_flush_can_hang("win32")
    assert plat.serial_flush_can_hang("linux")


# --------------------------------------------------------------------- STOP
def test_stop_reaches_the_firmware_while_a_long_move_holds_the_worker(
        qt_app, bar, firmware, record_property):
    """The case the button exists for: the worker is inside a move, waiting for
    its reply. The stop must not queue behind it."""
    _connect(qt_app, bar, firmware.device)
    bar._timer.stop()
    bar.link.jog_by(dz_mm=-1.0)
    assert _wait(qt_app, firmware.moving.is_set, 3), "the move never started"
    assert bar.link.is_busy()

    t0 = time.monotonic()
    bar._stop()
    returned = time.monotonic() - t0
    assert returned < 0.5
    assert _wait(qt_app, lambda: (firmware.seen("%") and firmware.seen("!")
                                  and firmware.seen("S 0")), 1)
    landed = max(firmware.seen("%")[0], firmware.seen("S 0")[0],
                 firmware.seen("!")[0]) - t0
    record_property("stop_returned_s", returned)
    record_property("stop_landed_s", landed)
    print(f"\nSTOP: button returned in {returned * 1000:.1f} ms, all three "
          f"commands at the firmware after {landed * 1000:.1f} ms")
    assert landed < 0.2
    assert [l for l, _t in bar.said if l == "warn"]
    # The order is the point: halt first, because the lift would otherwise wait
    # for the move to finish.
    assert firmware.seen("%")[0] <= firmware.seen("!")[0]
    assert _wait(qt_app, lambda: not firmware.moving.is_set(), 2)


def test_stop_does_not_claim_to_have_stopped_a_port_that_takes_nothing(
        qt_app, bar):
    """A wedged port: nothing reads the other end and its buffer is full. The
    write times out, and the button must come back, in about the time the write
    timeouts add up to, and must say the stop did not get there."""
    master, slave = pty.openpty()
    port = spi_probe._open_serial(os.ttyname(slave), 115200, 0.1)
    try:
        with pytest.raises(serial.SerialTimeoutException):
            port.write(b"x" * 1_000_000)
        bar.link._ser = machine._SerialGuard(port)
        t0 = time.monotonic()
        bar._stop()
        took = time.monotonic() - t0
        print(f"\nSTOP on a wedged port: returned in {took:.2f} s")
        assert took < 2.5
        assert bar.said[-1][0] == "fail"
        assert "did not reach" in bar.said[-1][1]
    finally:
        bar.link._ser = None
        port.close()
        os.close(master)
        os.close(slave)


# ----------------------------------------------------------------- lost link
def test_a_pulled_lead_is_noticed_and_said_in_about_a_second(qt_app, bar, firmware):
    _connect(qt_app, bar, firmware.device)
    assert _wait(qt_app, lambda: bar.dro_x._value.text().strip() == "12.34", 3)
    firmware.unplug()
    t0 = time.monotonic()
    assert _wait(qt_app, lambda: not bar.link.is_connected(), 5), \
        "the bar still says Linked with no lead in"
    took = time.monotonic() - t0
    print(f"\nlost link noticed after {took:.2f} s")
    assert took < 2.0
    assert bar.chip.label.text() == "Link lost"
    level, text = bar.said[-1]
    assert level == "fail" and "lost" in text and "power switch" in text
    # And STOP is honest afterwards: it points at the machine's own controls.
    bar._stop()
    assert "emergency" in bar.said[-1][1]


def test_a_board_that_stops_answering_counts_as_gone(qt_app, monkeypatch):
    """No exception to catch: the port is fine, the Arduino has hung."""
    monkeypatch.setattr(spi_probe, "query_position", lambda ser: None)
    monkeypatch.setattr(spi_probe, "machine_status", lambda ser: None)
    link = machine.MachineLink()
    link._ser = object()
    gone = []
    link.link_lost.connect(gone.append)
    link._do_poll(link._ser)
    assert gone == []                      # one could be noise
    link._do_poll(link._ser)
    qt_app.processEvents()
    assert gone == ["the Arduino stopped answering"]
    assert link.should_abort()


def test_one_good_answer_clears_the_count(qt_app, monkeypatch):
    answers = iter([None, (1.0, 2.0, 3.0, False), None])
    monkeypatch.setattr(spi_probe, "query_position", lambda ser: next(answers))
    monkeypatch.setattr(spi_probe, "machine_status", lambda ser: None)
    link = machine.MachineLink()
    link._ser = object()
    gone = []
    link.link_lost.connect(gone.append)
    for _ in range(3):
        link._do_poll(link._ser)
    qt_app.processEvents()
    assert gone == []


# ------------------------------------------------------------ a running job
class _Printer:
    def __init__(self, pending=None):
        self.sent, self.purged = [], 0
        self._pending = pending or (lambda: 1)

    def send(self, data, name):
        self.sent.append(name)

    def pending(self):
        return self._pending()

    def purge(self):
        self.purged += 1
        return True


class _DeadPort:
    """Reads fail as a pulled lead makes them fail; writes are recorded."""
    def __init__(self):
        self.writes = []

    def write(self, data):
        self.writes.append(data)

    def flush(self):
        pass

    def reset_input_buffer(self):
        pass

    def readline(self):
        raise serial.SerialException("device reports readiness to read but "
                                     "returned no data")


def test_losing_the_arduino_during_a_job_stops_the_job():
    """Two leads. Without this the printer goes on feeding a mill nobody is
    watching, and the run reports a failure while the head keeps cutting."""
    printer, port = _Printer(), _DeadPort()
    runner = JobRunner(port, printer, lambda: False, poll_s=0.01)
    with pytest.raises(RunStopped, match="connection to the mill failed"):
        runner.run("G0 X1\n", "traces")
    assert printer.sent == ["traces"] and printer.purged == 1
    assert b"%\n" in port.writes and b"S 0\n" in port.writes


def test_losing_the_mills_usb_lead_during_a_job_stops_the_spindle():
    """The other lead: the job cannot finish now, and the link can still say
    so to the machine."""
    def gone():
        raise rmlspool.SpoolError("the mill's USB lead failed")
    printer = _Printer(pending=gone)

    class Answers(_DeadPort):
        def readline(self):
            return b"X 130 4 0\n"
    port = Answers()
    runner = JobRunner(port, printer, lambda: False, poll_s=0.01)
    with pytest.raises(RunStopped, match="USB lead failed"):
        runner.run("G0 X1\n", "traces")
    assert printer.purged == 1
    assert b"S 0\n" in port.writes


def test_stop_reaches_the_printer_first_as_it_does_on_windows():
    printer, port = _Printer(), _DeadPort()
    stopped = []
    runner = JobRunner(port, printer, lambda: True, poll_s=0.01)
    with pytest.raises(RunStopped, match="stopped"):
        runner.run("G0 X1\n", "traces")
    stopped.append(printer.purged)
    assert stopped == [1]
    assert port.writes[0] == b"%\n"
