"""Serial-protocol tests for the SPI grid prober driver (fake serial, no hardware)."""
from gerber2rml.engine.spi_probe import probe_grid, deviations_mm, ProbeError
import pytest


class FakeSerial:
    """Simulates the srm20_spi_probe.ino board: 'D' -> datum ack, 'P id x y' ->
    'R id x y z' with z from a synthetic tilted plane (z = -56000 - x//100)."""
    def __init__(self, drop_ids=()):
        self._out = []        # queued reply lines (bytes)
        self.drop_ids = set(drop_ids)
        self.closed = False

    def reset_input_buffer(self):
        self._out.clear()

    def write(self, data):
        s = data.decode().strip()
        if s == "D":
            self._out.append(b"# datum log\n")
            self._out.append(b"D 120000 26000 -54260\n")
        elif s.startswith("P"):
            _, pid, x, y = s.split()
            pid, x, y = int(pid), int(x), int(y)
            if pid in self.drop_ids:
                self._out.append(f"E {pid} NOTOUCH\n".encode())
            else:
                z = -56000 - x // 100          # tilt in +X: deeper as x grows
                self._out.append(f"R {pid} {x} {y} {z}\n".encode())

    def readline(self):
        return self._out.pop(0) if self._out else b""

    def close(self):
        self.closed = True


def _factory(drop_ids=()):
    return lambda port, baud, timeout: FakeSerial(drop_ids)


def test_probe_grid_parses_results_and_closes():
    pts = [(0, 0, 0), (1, 10000, 0), (2, 20000, 0)]
    fake = {}
    def factory(port, baud, timeout):
        fake["s"] = FakeSerial()
        return fake["s"]
    res = probe_grid("COM5", pts, serial_factory=factory, startup_wait=0)
    assert [r["z"] for r in res] == [-56000, -56100, -56200]   # tilt: -1 um per 100 um x
    assert fake["s"].closed                                     # serial always closed


def test_probe_grid_raises_without_datum_ack():
    class NoAck(FakeSerial):
        def write(self, data):
            if data.decode().strip() == "D":
                self._out.append(b"# nothing useful\n")   # never sends 'D ...'
    with pytest.raises(ProbeError):
        probe_grid("COM5", [(0, 0, 0)], serial_factory=lambda p, b, t: NoAck(),
                   startup_wait=0, ack_timeout=0.1, ack_tries=2)


def test_deviations_relative_to_reference():
    res = probe_grid("COM5", [(0, 0, 0), (1, 10000, 0), (2, 20000, 0)],
                     serial_factory=_factory(), startup_wait=0)
    dz = deviations_mm(res, ref_id=0)
    assert dz[0] == 0.0
    assert abs(dz[1] - (-0.1)) < 1e-9     # 100 um lower over 10 mm
    assert abs(dz[2] - (-0.2)) < 1e-9


def test_query_position_parses_microns_to_mm():
    from gerber2rml.engine.spi_probe import open_link, query_position

    class QSerial:
        def __init__(self, touch): self._out = []; self._t = touch
        def reset_input_buffer(self): self._out.clear()
        def write(self, data):
            if data.decode().strip() == "Q":
                self._out.append(f"Q 120000 26000 -54260 {self._t}\n".encode())
        def readline(self): return self._out.pop(0) if self._out else b""
        def close(self): pass

    ser = open_link("COM5", startup_wait=0, serial_factory=lambda p, b, t: QSerial(0))
    assert query_position(ser) == (120.0, 26.0, -54.26, False)
    ser2 = open_link("COM5", startup_wait=0, serial_factory=lambda p, b, t: QSerial(1))
    assert query_position(ser2) == (120.0, 26.0, -54.26, True)


def test_touch_off_parses_contact_and_handles_notouch():
    from gerber2rml.engine.spi_probe import touch_off

    class TSerial:
        def __init__(self, reply): self._reply = reply; self._out = []
        def write(self, data):
            if data.decode().strip() == "T":
                self._out.append(self._reply)
        def readline(self): return self._out.pop(0) if self._out else b""
        def close(self): pass

    assert touch_off(TSerial(b"T 50000 40000 -56290\n")) == (50.0, 40.0, -56.29)
    assert touch_off(TSerial(b"E T NOTOUCH\n")) is None


def test_jog_to_sends_command_and_reads_ack():
    from gerber2rml.engine.spi_probe import jog_to

    class JSerial:
        def __init__(self): self.sent = None; self._out = []
        def write(self, data):
            self.sent = data.decode().strip()
            if self.sent.startswith("J"):
                _, x, y = self.sent.split()
                self._out.append(f"J {x} {y}\n".encode())
        def readline(self): return self._out.pop(0) if self._out else b""
        def close(self): pass

    s = JSerial()
    assert jog_to(s, 120000, 26000) is True
    assert s.sent == "J 120000 26000"


def test_failed_point_recorded_and_skipped_in_deviations():
    res = probe_grid("COM5", [(0, 0, 0), (1, 10000, 0)],
                     serial_factory=_factory(drop_ids={1}), startup_wait=0)
    assert res[1]["z"] is None and "error" in res[1]
    dz = deviations_mm(res)
    assert set(dz) == {0}                  # only the contacted point survives
