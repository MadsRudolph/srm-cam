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


def test_probe_grid_abort_stops_early_and_lifts():
    sent = []
    class Rec(FakeSerial):
        def write(self, data):
            sent.append(data); super().write(data)
    s = Rec()
    res = probe_grid("COM5", [(0, 0, 0), (1, 10000, 0)],
                     serial_factory=lambda p, b, t: s, startup_wait=0,
                     should_abort=lambda: True)        # abort before the first point
    assert res == []                                   # nothing probed
    assert b"!\n" in sent                              # firmware told to lift
    assert s.closed                                    # port still closed


def test_probe_grid_deep_outlier_aborts_and_lifts():
    # point 1 touches at the surface; point 2 comes back far DEEPER than the
    # surface (the bit punched into the board) -> stop the grid and lift.
    sent = []
    class Deep(FakeSerial):
        def write(self, data):
            sent.append(data)
            s = data.decode().strip()
            if s == "D":
                self._out.append(b"D 0 0 -50000\n")
            elif s.startswith("P"):
                _, pid, x, y = s.split()
                z = -56000 if pid == "0" else -59000   # 3 mm deeper on point 1
                self._out.append(f"R {pid} {x} {y} {z}\n".encode())
    s = Deep()
    res = probe_grid("COM5", [(0, 0, 0), (1, 0, 0), (2, 0, 0)],
                     serial_factory=lambda p, b, t: s, startup_wait=0, outlier_mm=1.5)
    assert len(res) == 2                              # stopped after the deep point
    assert "outlier" in str(res[1].get("error", "")).lower()
    assert res[1]["z"] is None                        # the bad reading is discarded
    assert b"!\n" in sent                             # tool told to lift


def test_probe_grid_missed_point_skips_and_continues():
    # a point that finds no copper (firmware RUNAWAY) is recorded as missing but
    # the grid keeps going (the firmware safely capped that descent).
    sent = []
    class OneMiss(FakeSerial):
        def write(self, data):
            sent.append(data)
            s = data.decode().strip()
            if s == "D":
                self._out.append(b"D 0 0 -50000\n")
            elif s.startswith("P"):
                pid = s.split()[1]
                self._out.append(f"E {pid} RUNAWAY\n".encode() if pid == "1"
                                 else f"R {pid} 0 0 -56000\n".encode())
    s = OneMiss()
    res = probe_grid("COM5", [(0, 0, 0), (1, 0, 0), (2, 0, 0)],
                     serial_factory=lambda p, b, t: s, startup_wait=0)
    assert len(res) == 3                              # ALL points probed (not aborted)
    assert res[1]["z"] is None and res[0]["z"] and res[2]["z"]   # only #1 missed
    assert b"!\n" not in sent                         # no abort -> no lift command


def test_probe_grid_aborts_if_first_point_misses():
    # no surface found yet (point 0 misses) -> can't level -> stop + lift
    sent = []
    class FirstMiss(FakeSerial):
        def write(self, data):
            sent.append(data)
            s = data.decode().strip()
            if s == "D":
                self._out.append(b"D 0 0 -50000\n")
            elif s.startswith("P"):
                self._out.append(f"E {s.split()[1]} RUNAWAY\n".encode())
    s = FirstMiss()
    res = probe_grid("COM5", [(0, 0, 0), (1, 0, 0)],
                     serial_factory=lambda p, b, t: s, startup_wait=0)
    assert len(res) == 1 and b"!\n" in sent           # no reference -> stop + lift


def test_touch_off_abort_lifts_and_returns_none():
    from gerber2rml.engine.spi_probe import touch_off
    sent = []
    class Rec(FakeSerial):
        def write(self, data):
            sent.append(data); super().write(data)
        def readline(self):
            return b""                                 # board never replies
    s = Rec()
    r = touch_off(s, timeout=2.0, should_abort=lambda: True)
    assert r is None and b"!\n" in sent                # aborted -> lift, no contact


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


# ---- firmware v2: drift compensation, version, zero-Z ----------------------

class DriftSerial(FakeSerial):
    """v2 board where the whole machine sinks 30 um per completed probe (warm-up
    drift): both grid touches and the 'B' reference re-touch see it."""
    REF_TRUE = -56000

    def __init__(self):
        super().__init__()
        self.n = 0                    # completed P probes

    def _drift(self, n):
        return -30 * n

    def write(self, data):
        s = data.decode().strip()
        if s == "B":
            self._out.append(f"B {self.REF_TRUE + self._drift(self.n)}\n".encode())
        elif s.startswith("P"):
            _, pid, x, y = s.split()
            z = -56000 - int(x) // 100 + self._drift(self.n)
            self._out.append(f"R {pid} {x} {y} {z}\n".encode())
            self.n += 1
        else:
            super().write(data)


def test_drift_compensation_recovers_true_surface():
    pts = [(0, 0, 0), (1, 10000, 0), (2, 20000, 0), (3, 30000, 0)]
    log = []
    res = probe_grid("COM5", pts, serial_factory=lambda p, b, t: DriftSerial(),
                     startup_wait=0, retouch_every=2, drift_log=log)
    true_z = [-56000, -56100, -56200, -56300]
    raw = [r["z_raw"] for r in res]
    corr = [r["z"] for r in res]
    # raw values are polluted by up to 90 um of drift...
    assert max(abs(r - t) for r, t in zip(raw, true_z)) >= 60
    # ...corrected values sit within half a drift step of the true surface
    assert max(abs(c - t) for c, t in zip(corr, true_z)) <= 20
    assert len(log) >= 2 and log[0]["after"] == 0


def test_no_retouch_means_no_correction():
    res = probe_grid("COM5", [(0, 0, 0), (1, 10000, 0)],
                     serial_factory=_factory(), startup_wait=0)
    assert all("z_raw" not in r for r in res)


def test_firmware_version_v2_and_v1_fallback():
    from gerber2rml.engine.spi_probe import firmware_version

    class V2Serial:
        def __init__(self): self._out = []
        def write(self, data):
            if data.decode().strip() == "V":
                self._out.append(b"V 2 probe,refine,verify,retouch,zeroz\n")
        def readline(self): return self._out.pop(0) if self._out else b""
        def close(self): pass

    ver, feats = firmware_version(V2Serial())
    assert ver == 2 and "retouch" in feats and "zeroz" in feats

    class V1Serial(V2Serial):                 # old sketch: 'V' is ignored
        def write(self, data): pass

    assert firmware_version(V1Serial(), timeout=0.05) == (1, set())


def test_zero_z_parses_new_origin():
    from gerber2rml.engine.spi_probe import zero_z

    class WSerial:
        def __init__(self, reply): self._reply = reply; self._out = []
        def write(self, data):
            if data.decode().strip() == "W":
                self._out.append(self._reply)
        def readline(self): return self._out.pop(0) if self._out else b""
        def close(self): pass

    assert zero_z(WSerial(b"W 0 0 -56290\n")) == (0.0, 0.0, -56.29)
    assert zero_z(WSerial(b"E W NOTOUCH\n"), timeout=0.05) is None


# ---- finding the board ----------------------------------------------------

def test_rank_ports_puts_known_usb_serial_chips_first():
    from gerber2rml.engine.spi_probe import rank_ports
    ranked = rank_ports([
        ("COM3", "PCI VEN_8086 DEV_7AEB"),               # Intel AMT, never a board
        ("COM4", "USB VID:PID=1A86:7523 SER= LOCATION=1-6"),
    ])
    assert ranked[0] == ("COM4", "CH340 (Uno clone)")
    assert ranked[1] == ("COM3", "unknown device")


def test_rank_ports_keeps_unknown_ports_rather_than_dropping_them():
    """A board behind an unrecognised chip must stay selectable - ordering is
    a hint, not a filter."""
    from gerber2rml.engine.spi_probe import rank_ports
    ranked = rank_ports([("COM7", "something odd")])
    assert [d for d, _why in ranked] == ["COM7"]


def test_best_port_prefers_a_real_board():
    from gerber2rml.engine.spi_probe import best_port
    assert best_port([
        ("COM3", "PCI VEN_8086"),
        ("COM4", "USB VID:PID=2341:0043"),
    ]) == "COM4"


def test_best_port_returns_none_when_nothing_looks_like_a_board():
    """None rather than a guess: probing the wrong port just times out
    confusingly, and "no board found" is far more useful than that."""
    from gerber2rml.engine.spi_probe import best_port
    assert best_port([("COM3", "PCI VEN_8086")]) is None
    assert best_port([]) is None


def test_best_port_handles_a_missing_hwid():
    from gerber2rml.engine.spi_probe import best_port, rank_ports
    assert rank_ports([("COM1", None)]) == [("COM1", "unknown device")]
    assert best_port([("COM1", None)]) is None

