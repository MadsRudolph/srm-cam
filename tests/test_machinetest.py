"""Machine-capability tests against a simulated v3 board (no hardware).

The point of the Machine test panel is to tell the truth about which SPI
commands work. These tests check that it does: that a board which ignores
turnSpindle is reported FAIL rather than PASS, that a machine which ignores the
speed argument is reported UNKNOWN rather than PASS, and that a flaky link
produces a readable result instead of a traceback.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from gerber2rml.engine import spi_probe
from gerber2rml.gui import machinetest as mt

_app = QApplication.instance() or QApplication([])


class FakeV3:
    """Simulates the srm20_spi_probe v3 sketch.

    Knobs let a test build a board that answers correctly, one that ignores a
    command, or one that is simply not v3 — which is the whole question the
    panel exists to answer.
    """

    def __init__(self, version=3, spindle_works=True, speed_scales=True,
                 stop_works=True, system=0x00000001, patched=True):
        self.version = version
        self.spindle_works = spindle_works
        self.speed_scales = speed_scales
        self.stop_works = stop_works
        self.system = system
        self.patched = patched
        # The real board's first SPI transfer after a reset returns zeros;
        # tests set this to reproduce that.
        self.zero_first_reads = 0
        self.pos = [0, 0, -50000]        # um
        self.rpm = 0
        self.frame_us = 5000
        self.out = []
        self.pending = None              # an N move that has not reported yet
        self.hold_ms = 0                 # extra ms from a pause
        self.sent = []
        self.closed = False

    # -- helpers
    def _emit(self, line):
        self.out.append((line + "\n").encode())

    def _resolve(self, interrupted=False):
        if self.pending is None:
            return
        dx, dy, dz, sp, ms = self.pending
        self.pending = None
        stopped = interrupted and self.stop_works
        if stopped:
            dx, dy, dz = (int(v * 0.2) for v in (dx, dy, dz))   # stopped early
            ms = int(ms * 0.2)
        self.pos = [self.pos[0] + dx, self.pos[1] + dy, self.pos[2] + dz]
        if stopped:
            # What the real firmware says when a move is cut short: the N
            # handler's waitForMotorStop returns false, so it reports an abort
            # rather than a completed move. Getting this wrong in the fake would
            # hide a 30 s stall on real hardware.
            self._emit("E N ABORT")
            self.hold_ms = 0
            return
        dist = int(round((dx * dx + dy * dy + dz * dz) ** 0.5))
        self._emit(f"N {ms + self.hold_ms} {dist} {sp} "
                   f"{self.pos[0]} {self.pos[1]} {self.pos[2]}")
        self.hold_ms = 0

    # -- serial API
    def write(self, data):
        s = data.decode().strip()
        self.sent.append(s)
        if not s:
            return
        c = s[0]
        if c == "V":
            feats = "probe,status,spindle,jobctl,view,timedmove"
            self._emit(f"V {self.version} {feats}")
        elif c == "Q":
            self._emit(f"Q {self.pos[0]} {self.pos[1]} {self.pos[2]} 0")
        elif c == "X":
            if self.zero_first_reads > 0:
                self.zero_first_reads -= 1
                self._emit("X 0 0 0")
            else:
                self._emit(f"X {self.system} 0 {self.rpm}")
        elif c == "S":
            rpm = int(s[1:])
            self.rpm = rpm if self.spindle_works else 0
            self._emit(f"S {rpm}")
        elif c == "I":
            self._emit("I 100" if self.patched else "E I NOPATCH")
        elif c == "F":
            if len(s) > 1:
                self.frame_us = int(s[1:])
            self._emit(f"F {self.frame_us}" if self.patched else "E F NOPATCH")
        elif c in "~^":
            if c == "^":
                self.hold_ms += 3000       # the pause showed up as elapsed time
            self._emit(f"{c} ok")
        elif c == "%":
            self._emit("% ok")
            self._resolve(interrupted=True)
        elif c == "K":
            self._emit("K ok")
        elif c == "Y":
            self.pos = [90000, 0, 0]
            self._emit("Y ok")
        elif c == "A":
            self._emit("A 1")
        elif c == "N":
            dx, dy, dz, sp = (int(v) for v in s[1:].split())
            dist = (dx * dx + dy * dy + dz * dz) ** 0.5
            rate = (10.0 if not self.speed_scales
                    else (10.0 if sp < 0 else max(sp, 1) * 2.0))   # um/ms
            self.pending = (dx, dy, dz, sp, max(int(dist / rate), 1))

    def readline(self):
        if not self.out:
            self._resolve()              # a move reports when it finishes
        return self.out.pop(0) if self.out else b""

    def flush(self):
        pass

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """The tests exercise timing-shaped logic, not the clock."""
    monkeypatch.setattr(mt.time, "sleep", lambda _s: None)


def _run(key, ser, **kw):
    return mt.run_test(key, ser, **kw)


# --- status decoding --------------------------------------------------------
def test_decode_status_maps_every_documented_bit():
    # state 1 | paused 0x20 | error 0x40 | moving 0x800 | fatal 0x1000
    #         | spindle 0x10000 | cover 0x20000
    st = spi_probe.decode_status(0x00031861, 0x00000010)
    assert st["state"] == 1
    assert st["paused"] and st["error"] and st["moving"] and st["fatal"]
    assert st["spindle"] and st["cover"] and st["cmderr"]


def test_decode_status_idle_word_sets_nothing():
    st = spi_probe.decode_status(0x00000001, 0)
    assert not any(st[k] for _m, k, _d in spi_probe.SYSTEM_BITS)
    assert not st["cmderr"]


# --- the tests themselves ---------------------------------------------------
def test_firmware_v2_is_a_failure_not_a_pass():
    status, detail = _run("firmware", FakeV3(version=2))
    assert status == mt.FAIL
    assert "reflash" in detail.lower()


def test_firmware_v3_passes():
    status, _ = _run("firmware", FakeV3())
    assert status == mt.PASS


def test_status_word_of_zero_is_unknown_not_pass():
    """All-zero is what a failed SPI transfer looks like; blessing it as PASS
    would be the panel lying about the thing it exists to check."""
    status, detail = _run("status", FakeV3(system=0))
    assert status == mt.UNKNOWN
    assert "FAILED" in detail


def test_status_retries_past_a_garbage_first_read():
    """Measured on the machine: the first SPI transfer after the Uno resets
    comes back all zeros. A single read would report a live machine as dead."""
    ser = FakeV3(system=0x00000082)
    ser.zero_first_reads = 1
    st = spi_probe.machine_status(ser)
    assert st is not None and st["system"] == 0x00000082


def test_status_still_reports_a_genuinely_dead_link():
    ser = FakeV3(system=0)
    ser.zero_first_reads = 99
    st = spi_probe.machine_status(ser)
    assert st is not None and st["system"] == 0      # dead, not None


def test_status_word_with_flags_passes_and_names_them():
    status, detail = _run("status", FakeV3(system=0x00020001))
    assert status == mt.PASS
    assert "cover" in detail


def test_machine_version_unknown_when_library_unpatched():
    status, _ = _run("machine_version", FakeV3(patched=False))
    assert status == mt.UNKNOWN


def test_jobctl_acks_all_four_opcodes():
    status, detail = _run("jobctl", FakeV3())
    assert status == mt.PASS
    for name in ("suspendJob", "resumeJob", "stopMoving", "cancelJob"):
        assert f"{name}=ack" in detail


def test_spindle_that_does_nothing_is_reported_fail():
    ser = FakeV3(spindle_works=False)
    status, detail = mt._t_spindle(ser, {"log": lambda _m: None,
                                         "abort": lambda: False}, seconds=2)
    assert status == mt.FAIL
    # The verdict must stay open about WHICH half broke: turnSpindle being
    # ignored and getActualSpindleSpeed being broken look identical from here,
    # and only a human ear can separate them.
    assert "LISTEN" in detail
    assert "S 0" in ser.sent                   # always stopped afterwards


def test_spindle_that_works_is_reported_pass_and_stopped():
    ser = FakeV3(spindle_works=True)
    status, detail = mt._t_spindle(ser, {"log": lambda _m: None,
                                         "abort": lambda: False}, seconds=2)
    assert status == mt.PASS
    # PASS here means start/stop works — NOT that the RPM argument sets the
    # speed. Measured on the machine it does not, and claiming otherwise once
    # sent the wrong conclusion into the docs.
    assert "STARTS AND STOPS" in detail
    assert "separate question" in detail
    assert ser.sent[-1] == "S 0"               # left off, not spinning


def test_speed_argument_ignored_is_unknown_with_the_consequence_spelled_out():
    status, detail = _run("speed", FakeV3(speed_scales=False))
    assert status == mt.UNKNOWN
    assert "IGNORES the speed argument" in detail


def test_speed_argument_honoured_passes():
    status, _ = _run("speed", FakeV3(speed_scales=True))
    assert status == mt.PASS


def test_stopmoving_that_interrupts_passes_and_restores_position():
    ser = FakeV3(stop_works=True)
    start = list(ser.pos)
    status, detail = _run("stopmoving", ser)
    assert status == mt.PASS
    assert "before stopping" in detail
    assert abs(ser.pos[1] - start[1]) < 100    # head put back (within 0.1 mm)


def test_stopmoving_that_is_ignored_is_reported_fail():
    status, detail = _run("stopmoving", FakeV3(stop_works=False))
    assert status == mt.FAIL
    assert "does nothing on this machine" in detail


def test_pause_resume_detects_the_hold():
    status, detail = _run("pauseresume", FakeV3())
    assert status == mt.PASS
    assert "unpaused" in detail


def test_view_reports_where_the_head_went():
    status, detail = _run("view", FakeV3())
    assert status == mt.PASS
    assert "head moved" in detail


def test_spindlecal_calls_out_an_ignored_rpm_argument():
    """The real machine settled at ~8600 for every setpoint from 500 to 3000.
    Reporting that as PASS would hide the actual finding: on/off only."""
    class FixedSpeed(FakeV3):
        def write(self, data):
            s = data.decode().strip()
            if s.startswith("S"):
                self.rpm = 8600 if int(s[1:]) else 0   # speed ignores the arg
                self._emit(f"S {int(s[1:])}")
                return
            super().write(data)

    status, detail = _run("spindlecal", FixedSpeed())
    assert status == mt.FAIL
    assert "ON/OFF" in detail and "VPanel's spindle slider" in detail


def test_spindlecal_passes_when_the_argument_does_scale():
    class Scales(FakeV3):
        def write(self, data):
            s = data.decode().strip()
            if s.startswith("S"):
                self.rpm = int(s[1:]) * 2
                self._emit(f"S {int(s[1:])}")
                return
            super().write(data)

    status, _ = _run("spindlecal", Scales())
    assert status == mt.PASS


def test_speed_test_halts_the_machine_when_a_move_fails():
    """A failed move must STOP the axis. Abandoning the reply does not: the
    move lives in the Roland controller, and it kept driving Y across the
    table when this was missing."""
    class Refuses(FakeV3):
        def write(self, data):
            if data.decode().strip().startswith("N"):
                self._emit("E N ABORT")
                return
            super().write(data)

    ser = Refuses()
    status, detail = _run("speed", ser)
    assert status == mt.UNKNOWN
    assert "%" in ser.sent                     # stopMoving actually sent
    assert "halted" in detail


# --- serial resync ----------------------------------------------------------
# Observed on the machine: interrupting a move left an unconsumed line in the
# buffer, so every later command read the PREVIOUS command's reply. The failures
# then marched forward one step at a time — the speed test's FIRST move
# "succeeded" and its return "failed", which is the giveaway.

class Stale(FakeV3):
    """A board with a leftover line already queued before the next command."""

    def __init__(self, stale_line, **kw):
        super().__init__(**kw)
        self._emit(stale_line)
        self.flushed = False

    def reset_input_buffer(self):
        self.out.clear()
        self.flushed = True


def test_ack_resyncs_past_a_stale_line():
    ser = Stale("% ok")
    assert spi_probe.machine_status(ser) is not None
    assert ser.flushed


def test_query_position_resyncs_past_a_stale_line():
    """This exact case produced 'the end position could not be read'."""
    ser = Stale("E N ABORT")
    assert spi_probe.query_position(ser) is not None


def test_timed_move_reports_the_boards_reason_for_failing():
    class Refuses(FakeV3):
        def write(self, data):
            if data.decode().strip().startswith("N"):
                self._emit("E N ABORT")
                return
            super().write(data)

    why = []
    assert spi_probe.timed_move(Refuses(), 0, 1000, 0, -1, last_error=why) is None
    assert why == ["E N ABORT"]


def test_pauseresume_failure_names_the_reason_not_just_no_answer():
    class Refuses(FakeV3):
        def write(self, data):
            if data.decode().strip().startswith("N"):
                self._emit("E N ABORT")
                return
            super().write(data)

    status, detail = _run("pauseresume", Refuses())
    assert status == mt.FAIL
    assert "E N ABORT" in detail and "system=" in detail   # says WHY


# --- robustness -------------------------------------------------------------
def test_unknown_key_is_skipped_not_raised():
    status, _ = _run("no-such-test", FakeV3())
    assert status == mt.SKIP


def test_a_dead_link_fails_readably_instead_of_raising():
    class Broken(FakeV3):
        def write(self, data):
            raise OSError("port went away")

    for spec in mt.TESTS:
        status, detail = _run(spec.key, Broken())
        assert status in (mt.FAIL, mt.UNKNOWN, mt.SKIP), spec.key
        assert "Traceback" not in detail


def test_abort_stops_a_sweep_early():
    status, _ = _run("speed", FakeV3(), abort=lambda: True)
    assert status == mt.SKIP


def test_report_text_renders_only_the_tests_that_ran():
    text = mt.report_text({"firmware": (mt.PASS, "v3")}, port="COM5")
    assert "COM5" in text and "| PASS |" in text
    assert "Spindle on/off" not in text        # never ran -> not in the report


def test_every_test_has_a_runner_and_a_known_risk():
    for spec in mt.TESTS:
        assert spec.key in mt._RUNNERS
        assert spec.risk in (mt.SAFE, mt.MOTION, mt.SPINDLE)


# --- the dialog -------------------------------------------------------------
@pytest.fixture
def dialog(monkeypatch):
    """The dialog with its serial worker stubbed out — the port is not the
    thing under test here, the arming rules are."""
    queued = []

    class StubWorker:
        def __init__(self, port):
            self.port = port
        status = result = log = batch_done = failed = None

        def start(self):
            pass

        def stop(self):
            pass

        def request_tests(self, keys):
            queued.extend(keys)

        def request_abort(self):
            queued.clear()

    class _Sig:
        def connect(self, _fn):
            pass

    for name in ("status", "result", "log", "batch_done", "failed"):
        setattr(StubWorker, name, _Sig())
    monkeypatch.setattr(mt, "_TestWorker", StubWorker)
    dlg = mt.MachineTestDialog("COM-TEST")
    dlg._queued = queued
    yield dlg
    dlg._worker.stop()


def test_dialog_lists_every_test(dialog):
    assert dialog.table.rowCount() == len(mt.TESTS)


def test_motion_tests_are_refused_until_armed(dialog):
    dialog.motion_chk.setChecked(False)
    dialog._start(["view"])
    assert dialog._queued == []
    row = next(i for i, t in enumerate(mt.TESTS) if t.key == "view")
    assert dialog.table.item(row, 2).text() == mt.SKIP
    assert "Allow motion" in dialog.table.item(row, 3).text()


def test_motion_tests_run_once_armed(dialog):
    dialog.motion_chk.setChecked(True)
    dialog._start(["view"])
    assert dialog._queued == ["view"]


def test_spindle_needs_its_own_arm_even_with_motion_allowed(dialog):
    dialog.motion_chk.setChecked(True)
    dialog.spindle_chk.setChecked(False)
    dialog._start(["spindle"])
    assert dialog._queued == []


def test_run_safe_queues_only_the_read_only_tests(dialog):
    dialog._run_safe()
    assert dialog._queued == [t.key for t in mt.TESTS if t.risk == mt.SAFE]
    assert "spindle" not in dialog._queued
