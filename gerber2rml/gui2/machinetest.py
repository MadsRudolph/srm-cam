"""Machine test panel — which SPI commands does this machine actually obey?

The SRM-20's SPI remote exposes a dozen commands the project never called
(spindle control, the full status word, pause/resume/stop, jumpToView, timed
moves). Whether each one *works* is an empirical question about this specific
machine, so this panel runs them one at a time, says PASS / FAIL / UNKNOWN,
and produces a report that can be pasted back.

Two layers, deliberately:

* :func:`run_test` and :data:`TESTS` are plain functions over a serial object
  with no Qt anywhere. That keeps the interesting logic testable against a
  fake serial rather than only against hardware.
* The dialog is a thin shell around them.

Safety model — the panel never surprises anyone:

* **safe** tests only read; they run on request with no ceremony.
* **motion** tests move the head and are refused unless *Allow motion* is
  ticked. Each one returns the head to where it started.
* **spindle** tests spin the tool and need *Allow spindle* plus a
  confirmation. The firmware's deadman stops the spindle if this panel dies
  mid-test.

The hardware half below is a verbatim copy of the first interface's module,
for the same reason ``gui2.workspace`` is a copy: this package does not import
from ``gerber2rml.gui``, so either interface can be deleted without breaking
the other. It is kept verbatim on purpose — it answers questions about the
machine, not about the interface, and the two copies must not drift on that.
Only the Qt shell at the bottom is this interface's own.
"""
from collections import namedtuple

from PySide6.QtCore import QMutex, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QHBoxLayout, QHeaderView, QLabel,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from gerber2rml.engine import spi_probe
from gerber2rml.gui2 import theme, widgets, dialogs

PASS, FAIL, UNKNOWN, SKIP = "PASS", "FAIL", "UNKNOWN", "SKIP"

TestSpec = namedtuple("TestSpec", "key label risk blurb")

# Risk levels gate what a test is allowed to do.
SAFE, MOTION, SPINDLE = "safe", "motion", "spindle"

TESTS = (
    TestSpec("firmware", "Firmware version", SAFE,
             "Does the board run the v3 sketch? Everything else needs it."),
    TestSpec("machine_version", "Machine command version", SAFE,
             "getCommandVersion — the machine's own remote-protocol version. "
             "Never called before; the library kept it private."),
    TestSpec("status", "Status word", SAFE,
             "getStatus — reads all 64 bits. v2 firmware used exactly one."),
    TestSpec("cover", "Cover-open bit (interactive)", SAFE,
             "Open and close the lid while this runs. If the bit follows, the "
             "status bits are real and the firmware's safety guard works."),
    TestSpec("frame", "SPI framing delay", SAFE,
             "Reads the per-byte delay and times a position read. Roland's "
             "5 ms/byte is the ceiling on move streaming."),
    TestSpec("framesweep", "Framing-delay sweep", SAFE,
             "Walks the delay down, measuring speed AND read corruption. Finds "
             "how much faster the link can safely go."),
    TestSpec("jobctl", "Job control (idle acks)", SAFE,
             "suspend / resume / stopMoving / cancelJob. An ack only proves the "
             "opcode went out — the motion tests prove they do something."),
    TestSpec("view", "Move to View position", MOTION,
             "jumpToView — VPanel's View button, for bit changes and flips."),
    TestSpec("stopmoving", "Interrupt a move (stopMoving)", MOTION,
             "Starts a 20 mm move and cuts it short. If travel is well under "
             "20 mm, STOP can interrupt a long move instead of waiting it out."),
    TestSpec("pauseresume", "Pause and resume a move", MOTION,
             "Times a 20 mm move, then repeats it with a 3 s pause. The pause "
             "should show up as ~3 s of extra elapsed time."),
    TestSpec("speed", "Speed-unit calibration", MOTION,
             "Timed moves at different raw speed values. If mm/s does not "
             "change, the machine ignores the speed argument and streamed "
             "feeds cannot be controlled."),
    TestSpec("spindle", "Spindle on/off + RPM", SPINDLE,
             "turnSpindle — the big one. If this works, RPM stops being a "
             "VPanel-only setting."),
    TestSpec("spindlecal", "Spindle: what do the numbers mean?", SPINDLE,
             "Commanding 3000 read back 8487 and still climbing — past the "
             "SRM-20's 7000 rating. So the command units, the readback units, "
             "or both are not RPM. This holds each setpoint until the reading "
             "settles and reports the actual relationship. Starts LOW."),
)

TEST_BY_KEY = {t.key: t for t in TESTS}

# Sweep points shared with scripts/srm20_bench.py's reasoning: 5000 is Roland's
# shipped delay, and the bottom of the range is where transfers plausibly fail.
FRAME_STEPS = (5000, 2000, 1000, 500, 200, 100, 50)
SPEED_STEPS = (-1, 2, 10, 30)
MOVE_UM = 20000          # 20 mm — long enough to time, short enough to be safe


# A move ends EITHER with its own reply or with an error line — an interrupted
# move reports 'E N ABORT', not 'N ...'. Waiting only for the happy prefix would
# stall until the timeout every time the interrupt actually worked.
MOVE_DONE = ("N ", "E ")


def _drain_until(ser, prefixes, timeout):
    """Read lines until one starts with any of ``prefixes``; returns it, or None.

    Needed because the transport acks ('~ ok', '% ok') arrive interleaved with
    the reply to a move that is still running.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        line = spi_probe._read_line(ser, deadline)
        if line is None:
            return None
        if line.startswith(prefixes):
            return line
    return None


# --- individual tests -------------------------------------------------------
# Each returns (status, detail). They never raise: a dead link is a FAIL with a
# readable reason, not a traceback in the middle of a test run.

def _t_firmware(ser, ctx):
    ver, feats = spi_probe.firmware_version(ser)
    if ver >= 3:
        return PASS, f"v{ver} — features: {','.join(sorted(feats))}"
    return FAIL, (f"v{ver} — this is the old sketch. Reflash "
                  f"hardware/srm20_spi_probe; the v3 commands do not exist yet.")


def _t_machine_version(ser, ctx):
    v = spi_probe.command_version(ser)
    if v is None:
        return UNKNOWN, ("no answer — either the vendored library is not "
                         "patched, or the machine does not implement it")
    return PASS, f"machine remote-command version {v}"


def _t_status(ser, ctx):
    st = spi_probe.machine_status(ser)
    if st is None:
        return FAIL, "no answer to 'X' — getStatus is not reaching the machine"
    flags = [k for _m, k, _d in spi_probe.SYSTEM_BITS if st.get(k)] or ["none"]
    detail = (f"system=0x{st['system']:08x} remote=0x{st['remote']:08x} "
              f"state={st['state']} flags={','.join(flags)} rpm={st['rpm']}")
    if st["system"] in (0, 0xFFFFFFFF):
        # An all-zero or all-ones word is what a failed SPI transfer looks like,
        # not an idle machine. Reporting PASS here would bless garbage.
        return UNKNOWN, (detail + "  — an all-0/all-1 word is what a FAILED "
                         "transfer looks like. Run the cover test before "
                         "trusting any of these bits.")
    return PASS, detail


def _t_cover(ser, ctx, timeout=25.0):
    """Watch the cover bit while the operator works the lid.

    This is the test that decides whether ANY status bit can be trusted: it is
    the one bit whose true value the operator controls directly.
    """
    st = spi_probe.machine_status(ser)
    if st is None:
        return FAIL, "no status to watch"
    start = st["cover"]
    ctx["log"](f"cover bit is {start} — now OPEN or CLOSE the lid…")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ctx["abort"]():
            return SKIP, "stopped"
        st = spi_probe.machine_status(ser)
        if st is not None and st["cover"] != start:
            return PASS, (f"cover bit changed {start} -> {st['cover']} — the "
                          f"status bits are REAL on this machine")
        time.sleep(0.3)
    return UNKNOWN, (f"bit never changed from {start} in {timeout:.0f}s. Either "
                     f"the lid was not moved, or this bit does not work here — "
                     f"in which case disarm the firmware guard ('A 0').")


def _t_frame(ser, ctx, samples=10):
    us = spi_probe.frame_delay(ser)
    if us is None:
        return UNKNOWN, ("no answer to 'F' — the vendored library is not "
                         "patched, so the delay cannot be tuned")
    t0 = time.monotonic()
    got = sum(1 for _ in range(samples) if spi_probe.query_position(ser))
    ms = (time.monotonic() - t0) * 1000.0 / samples
    return PASS, (f"delay {us} us/byte, {ms:.0f} ms per position read "
                  f"({got}/{samples} answered). A jumpTo is 18 bytes ~ "
                  f"{18 * us / 1000.0:.0f} ms of framing alone.")


def _t_framesweep(ser, ctx, samples=12):
    """Speed vs corruption at each delay. Corruption is the point: a faster
    delay that garbles one read in ten is worse than no speed-up at all,
    because the probe moves on those reads."""
    original = spi_probe.frame_delay(ser)
    if original is None:
        return UNKNOWN, "library not patched — cannot change the framing delay"
    rows, best = [], None
    try:
        for us in FRAME_STEPS:
            if ctx["abort"]():
                return SKIP, "stopped"
            if spi_probe.frame_delay(ser, us) is None:
                continue
            t0 = time.monotonic()
            reads = [spi_probe.query_position(ser) for _ in range(samples)]
            ms = (time.monotonic() - t0) * 1000.0 / samples
            good = [r[:3] for r in reads if r is not None]
            if not good:
                rows.append(f"{us}us DEAD")
                continue
            med = [sorted(v[i] for v in good)[len(good) // 2] for i in range(3)]
            bad = sum(1 for v in good
                      if any(abs(v[i] - med[i]) > 0.003 for i in range(3)))
            lost = samples - len(good)
            clean = bad == 0 and lost == 0
            rows.append(f"{us}us {ms:.0f}ms {'clean' if clean else f'BAD({bad + lost})'}")
            ctx["log"](rows[-1])
            if clean:
                best = us
    finally:
        spi_probe.frame_delay(ser, original)
    if best is None:
        return UNKNOWN, "  |  ".join(rows) or "no usable readings"
    return PASS, (f"lowest clean delay {best} us (stock 5000) — "
                  f"{18 * best / 1000.0:.1f} ms framing per move vs 90 ms.  "
                  + "  |  ".join(rows))


def _t_jobctl(ser, ctx):
    acks = {
        "suspendJob": spi_probe.suspend_job(ser),
        "resumeJob": spi_probe.resume_job(ser),
        "stopMoving": spi_probe.stop_moving(ser),
        "cancelJob": spi_probe.cancel_job(ser),
    }
    detail = ", ".join(f"{k}={'ack' if v else 'NO ANSWER'}" for k, v in acks.items())
    if all(acks.values()):
        return PASS, detail + " — all four opcodes go out; run the motion tests " \
                              "to see whether the machine acts on them"
    return FAIL, detail


def _t_view(ser, ctx):
    before = spi_probe.query_position(ser)
    if not spi_probe.jump_to_view(ser):
        return FAIL, "no answer to 'Y' — jumpToView did not complete"
    after = spi_probe.query_position(ser)
    if before is None or after is None:
        return UNKNOWN, "acked, but the position could not be read to confirm"
    moved = max(abs(a - b) for a, b in zip(after[:3], before[:3]))
    if moved < 0.5:
        return UNKNOWN, (f"acked but the head moved {moved:.2f} mm — either it "
                         f"was already at the view position, or the command is "
                         f"ignored")
    return PASS, (f"head moved to X {after[0]:.1f} Y {after[1]:.1f} Z {after[2]:.1f} "
                  f"(was X {before[0]:.1f} Y {before[1]:.1f} Z {before[2]:.1f})")


def _t_stopmoving(ser, ctx):
    before = spi_probe.query_position(ser)
    if before is None:
        return FAIL, "no position read — refusing to move"
    ser.write(f"N 0 {MOVE_UM} 0 -1\n".encode())
    time.sleep(0.4)                      # let it get going...
    ser.write(b"%\n")                    # ...then cut it short mid-flight
    ended = _drain_until(ser, MOVE_DONE, 30.0)   # 'E N ABORT' if it worked
    after = spi_probe.query_position(ser)
    if after is None:
        # Always put the head back, even when the check itself failed — a test
        # that bails leaving the machine 20 mm from where it started makes
        # every later test start from the wrong place.
        spi_probe.timed_move(ser, 0, -MOVE_UM, 0, -1)
        return UNKNOWN, (f"interrupted (board said {ended!r}) but the end "
                         f"position could not be read; head returned blind")
    moved = abs(after[1] - before[1])
    if moved > 0.01:
        spi_probe.timed_move(ser, 0, -int(round(moved * 1000)), 0, -1)
    if moved < 0.05:
        return UNKNOWN, (f"the head barely moved ({moved:.2f} mm) — the move "
                         f"may have been rejected before it started, so this "
                         f"says nothing about stopMoving. Board said {ended!r}")
    if moved < MOVE_UM / 1000.0 * 0.75:
        return PASS, (f"travelled {moved:.2f} mm of 20.00 before stopping "
                      f"({ended!r}) — stopMoving genuinely aborts a move in "
                      f"flight")
    return FAIL, (f"travelled {moved:.2f} mm of 20.00 — the move ran to "
                  f"completion, so stopMoving does nothing on this machine")


def _t_pauseresume(ser, ctx, hold_s=3.0):
    why = []
    base = spi_probe.timed_move(ser, 0, MOVE_UM, 0, -1, last_error=why)
    if base is None:
        st = spi_probe.machine_status(ser)
        extra = ""
        if st is not None:
            flags = [k for _m, k, _d in spi_probe.SYSTEM_BITS if st.get(k)]
            extra = (f"; machine says system=0x{st['system']:08x} "
                     f"flags={','.join(flags) or 'none'} cmderr={st['cmderr']}")
        return FAIL, (f"the baseline move did not complete "
                      f"({why[0] if why else 'no reply'}){extra}")
    spi_probe.timed_move(ser, 0, -MOVE_UM, 0, -1)          # back to start
    ser.write(f"N 0 {MOVE_UM} 0 -1\n".encode())
    time.sleep(0.6)
    ser.write(b"~\n")                                      # pause mid-move
    time.sleep(hold_s)
    ser.write(b"^\n")                                      # resume
    line = _drain_until(ser, MOVE_DONE, 60.0)
    spi_probe.timed_move(ser, 0, -MOVE_UM, 0, -1)          # back to start
    if line is None:
        return FAIL, "the paused move never reported back"
    if not line.startswith("N "):
        # e.g. 'E ~ PAUSETIMEOUT', or the status guard tripping on the pause
        return FAIL, (f"the paused move ended with {line!r} instead of "
                      f"completing — the machine did not resume")
    try:
        held_ms = int(line.split()[1])
    except (IndexError, ValueError):
        return UNKNOWN, f"unparsable reply: {line!r}"
    extra = (held_ms - base["ms"]) / 1000.0
    if extra > hold_s * 0.6:
        return PASS, (f"move took {held_ms} ms vs {base['ms']} ms unpaused — "
                      f"{extra:.1f}s of hold for a {hold_s:.0f}s pause")
    return FAIL, (f"move took {held_ms} ms vs {base['ms']} ms unpaused "
                  f"({extra:+.1f}s) — the pause did not hold the machine")


def _t_speed(ser, ctx, move_timeout=45.0):
    """Timed there-and-back moves at a range of raw speed values.

    Every exit path halts the machine and drives the head back to where it
    started. Learned the hard way: a failed measurement used to leave the axis
    travelling, because abandoning the REPLY does nothing to a move already
    queued in the controller.
    """
    start = spi_probe.query_position(ser)
    rows, rates = [], []
    try:
        for sp in SPEED_STEPS:
            if ctx["abort"]():
                return SKIP, "stopped"
            why = []
            out = spi_probe.timed_move(ser, 0, MOVE_UM, 0, sp,
                                       timeout=move_timeout, last_error=why)
            if out is None:
                rows.append(f"speed {sp}: {why[0] if why else 'no answer'} "
                            f"(machine halted)")
                ctx["log"](rows[-1])
                break
            back = spi_probe.timed_move(ser, 0, -MOVE_UM, 0, sp,
                                        timeout=move_timeout, last_error=why)
            if back is None:
                rows.append(f"speed {sp}: return failed "
                            f"({why[-1] if why else 'no answer'})")
                break
            r = [m["mm_per_s"] for m in (out, back) if m["mm_per_s"]]
            mean = sum(r) / len(r) if r else 0.0
            rates.append(mean)
            rows.append(f"speed {sp} -> {mean:.1f} mm/s")
            ctx["log"](rows[-1])
    finally:
        # Whatever happened: stop, then put the head back.
        spi_probe.stop_moving_now(ser)
        if start is not None:
            now = spi_probe.query_position(ser)
            if now is not None:
                dy = int(round((start[1] - now[1]) * 1000))
                if abs(dy) > 10:
                    spi_probe.timed_move(ser, 0, dy, 0, -1, timeout=move_timeout)
    detail = "  |  ".join(rows)
    if len(rates) < 2:
        return UNKNOWN, (detail + "  — not enough speeds completed to compare. "
                         "The head has been stopped and returned to its start.")
    if max(rates) - min(rates) < 0.5:
        return UNKNOWN, (detail + "  — every speed gave the same rate, so the "
                         "machine IGNORES the speed argument: streamed feeds "
                         "cannot be controlled over SPI")
    return PASS, detail + "  — the speed argument does change the feed rate"


def _t_spindle(ser, ctx, rpm=3000, seconds=6):
    got = spi_probe.set_spindle(ser, rpm)
    if got is None:
        return FAIL, ("no answer to 'S' — refused (lid open?) or the firmware "
                      "is older than v3")
    peak, samples, spun, cmderr = 0, [], False, False
    try:
        for i in range(seconds):
            if ctx["abort"]():
                break
            time.sleep(1.0)
            st = spi_probe.machine_status(ser)   # also feeds the firmware deadman
            if st is None:
                continue
            peak = max(peak, st["rpm"])
            spun = spun or st["spindle"]
            cmderr = cmderr or st["cmderr"]
            samples.append(f"t+{i + 1}s rpm={st['rpm']}"
                           f"{' SPIN' if st['spindle'] else ''}")
            ctx["log"](samples[-1])
    finally:
        spi_probe.set_spindle(ser, 0)
    detail = (f"commanded {got} RPM; peak read {peak}; spindle bit "
              f"{'set' if spun else 'never set'}; cmderr={cmderr}.  "
              + "  |  ".join(samples))
    if peak > rpm * 0.2 or spun:
        return PASS, (detail + "  — the spindle STARTS AND STOPS over SPI (an "
                      "M3/M5 equivalent). Whether the RPM argument sets the "
                      "speed is a separate question — run the 'what do the "
                      "numbers mean?' test; measured 2026-08-21 it did not.")
    if cmderr:
        return FAIL, (detail + "  — the machine REJECTED the command (cmderr "
                      "set), so turnSpindle is refused in this state. Try with "
                      "a job active, or accept that RPM stays a VPanel setting.")
    return FAIL, (detail + "  — nothing reported turning. LISTEN to the "
                  "machine: if the spindle actually spun, turnSpindle works and "
                  "only getActualSpindleSpeed is broken (like readSensor). If "
                  "it was silent, turnSpindle is ignored.")


# Setpoints for the characterisation, LOW first. Deliberately stops well short
# of the firmware's 7000 clamp: commanding 3000 already read back 8487, so
# until the relationship is known, walking upward is walking blind.
SPINDLE_SETPOINTS = (500, 1000, 2000, 3000)


def _spindle_settle(ser, ctx, max_s=25, window=3, tol=0.03):
    """Poll RPM until it stops changing, and return (steady, peak, samples).

    The first spindle test sampled for a fixed 6 s and the reading was still
    climbing when it stopped — so 8487 was never a steady state, just wherever
    the ramp had got to. Waiting for a plateau is the difference between
    measuring the machine and measuring the timeout.
    """
    recent, peak, samples = [], 0, []
    for i in range(max_s):
        if ctx["abort"]():
            break
        time.sleep(1.0)
        st = spi_probe.machine_status(ser)      # also feeds the firmware deadman
        if st is None:
            continue
        rpm = st["rpm"]
        peak = max(peak, rpm)
        samples.append(rpm)
        recent.append(rpm)
        if len(recent) > window:
            recent.pop(0)
        if len(recent) == window and max(recent) > 0:
            spread = (max(recent) - min(recent)) / float(max(recent))
            if spread <= tol:
                return sum(recent) / float(window), peak, samples
    return (samples[-1] if samples else 0), peak, samples


def _t_spindlecal(ser, ctx):
    rows, steadies = [], []
    try:
        for sp in SPINDLE_SETPOINTS:
            if ctx["abort"]():
                break
            if spi_probe.set_spindle(ser, sp) is None:
                rows.append(f"cmd {sp}: refused")
                break
            steady, peak, samples = _spindle_settle(ser, ctx)
            settled = len(samples) < 25
            steadies.append(steady)
            rows.append(f"cmd {sp} -> steady {steady:.0f} (peak {peak})"
                        f"{'' if settled else ' NEVER SETTLED'}")
            ctx["log"](rows[-1])
            spi_probe.set_spindle(ser, 0)
            time.sleep(2.0)                     # spin down between setpoints
    finally:
        spi_probe.set_spindle(ser, 0)
    detail = "  |  ".join(rows)
    if len(steadies) < 2:
        return UNKNOWN, detail or "no readings"
    # The verdict this test exists for: does the commanded number do anything?
    # Measured 2026-08-21 it did not — 500/1000/2000/3000 all settled at ~8600.
    spread = (max(steadies) - min(steadies)) / max(max(steadies), 1.0)
    if spread < 0.10:
        return FAIL, (detail + f"  — every setpoint settled at the same speed "
                      f"(spread {spread * 100:.1f}%). turnSpindle is ON/OFF "
                      f"ONLY: the RPM argument is ignored and the actual speed "
                      f"still comes from VPanel's spindle slider. SPI can start "
                      f"and stop the spindle, but not set its speed.")
    return PASS, (detail + "  — the steady reading tracks the commanded value, "
                  "so the argument really does set the speed. Cross-check the "
                  "numbers against VPanel's spindle display before trusting "
                  "them as RPM.")


_RUNNERS = {
    "firmware": _t_firmware,
    "machine_version": _t_machine_version,
    "status": _t_status,
    "cover": _t_cover,
    "frame": _t_frame,
    "framesweep": _t_framesweep,
    "jobctl": _t_jobctl,
    "view": _t_view,
    "stopmoving": _t_stopmoving,
    "pauseresume": _t_pauseresume,
    "speed": _t_speed,
    "spindle": _t_spindle,
    "spindlecal": _t_spindlecal,
}


def run_test(key, ser, log=None, abort=None):
    """Run one test by key -> ``(status, detail)``. Never raises."""
    fn = _RUNNERS.get(key)
    if fn is None:
        return SKIP, f"unknown test {key!r}"
    ctx = {"log": log or (lambda _m: None), "abort": abort or (lambda: False)}
    try:
        return fn(ser, ctx)
    except Exception as e:                       # a flaky link must not crash the panel
        return FAIL, f"{type(e).__name__}: {e}"


def report_text(results, port=""):
    """Render collected ``{key: (status, detail)}`` as markdown for pasting."""
    lines = [f"# SRM-20 machine test — {port}".rstrip(), ""]
    lines.append("| Test | Risk | Result | Detail |")
    lines.append("|---|---|---|---|")
    for t in TESTS:
        status, detail = results.get(t.key, ("", ""))
        if not status:
            continue
        lines.append(f"| {t.label} | {t.risk} | {status} | "
                     f"{str(detail).replace('|', '/')} |")
    return "\n".join(lines) + "\n"




class _TestWorker(QThread):
    """Owns the serial link: polls status for the live strip, runs queued tests."""
    status = Signal(dict)
    result = Signal(str, str, str)          # key, status, detail
    log = Signal(str)
    batch_done = Signal()
    failed = Signal(str)

    def __init__(self, port):
        super().__init__()
        self._port, self._run = port, True
        self._lock = QMutex()
        self._queue = []
        self._abort = False

    def request_tests(self, keys):
        self._lock.lock()
        self._abort = False
        self._queue.extend(keys)
        self._lock.unlock()

    def request_abort(self):
        self._lock.lock()
        self._abort = True
        self._queue.clear()
        self._lock.unlock()

    def aborting(self):
        self._lock.lock()
        a = self._abort
        self._lock.unlock()
        return a

    def run(self):
        try:
            ser = spi_probe.open_link(self._port)
        except Exception as e:
            self.failed.emit(str(e))
            return
        try:
            while self._run:
                self._lock.lock()
                key = self._queue.pop(0) if self._queue else None
                empty = not self._queue
                self._lock.unlock()
                if key is not None:
                    self.log.emit(f"--- {TEST_BY_KEY[key].label}")
                    st, detail = run_test(key, ser, self.log.emit, self.aborting)
                    self.result.emit(key, st, detail)
                    if empty:
                        self.batch_done.emit()
                    continue
                st = spi_probe.machine_status(ser)
                if st is not None:
                    self.status.emit(st)
                self.msleep(500)
        finally:
            try:
                spi_probe.spindle_off(ser)      # never leave the tool spinning
                ser.close()
            except Exception:
                pass

    def stop(self):
        self.request_abort()
        self._run = False
        self.wait(5000)



# --- this interface's shell -------------------------------------------------

_RESULT_INK = {PASS: theme.VERIFIED, FAIL: theme.DANGER,
               UNKNOWN: theme.CAUTION, SKIP: theme.TEXT_3}
_RISK_WORD = {SAFE: "reads only", MOTION: "moves the head",
              SPINDLE: "spins the tool"}


class MachineTestDialog(QDialog):
    """Every SPI command, one row each, with what it costs to find out."""

    def __init__(self, port, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Machine test")
        self.setModal(True)
        self.setMinimumSize(880, 620)
        self._port = port
        self._results = {}

        v = QVBoxLayout(self)
        v.setContentsMargins(theme.GAP_L + 4, theme.GAP_L, theme.GAP_L + 4,
                             theme.GAP_L)
        v.setSpacing(theme.GAP_M)

        head = QLabel("Machine test")
        head.setFont(theme.font("title"))
        v.addWidget(head)
        blurb = QLabel(
            "Each row is one SPI command. None of this is needed to cut a "
            "board — it answers what this machine's link can be trusted to "
            "do. Read-only tests run as they are; anything that moves the head "
            "or spins the tool has to be armed first, and says so under Risk.")
        blurb.setWordWrap(True)
        blurb.setFont(theme.font("body"))
        blurb.setStyleSheet("color: %s;" % theme.TEXT_2)
        v.addWidget(blurb)

        self.table = QTableWidget(len(TESTS), 4)
        self.table.setHorizontalHeaderLabels(["Test", "Risk", "Result", "Detail"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        for r, t in enumerate(TESTS):
            label = QTableWidgetItem(t.label)
            label.setToolTip(t.blurb)
            self.table.setItem(r, 0, label)
            risk = QTableWidgetItem(_RISK_WORD.get(t.risk, t.risk))
            risk.setToolTip(t.blurb)
            self.table.setItem(r, 1, risk)
            self.table.setItem(r, 2, QTableWidgetItem(""))
            self.table.setItem(r, 3, QTableWidgetItem(""))
        v.addWidget(self.table, 1)

        self.allow_motion = QCheckBox("Allow motion")
        self.allow_motion.setToolTip(
            "Lets the tests that move the head run. Each one puts the head "
            "back where it started, but it does move — close the lid and "
            "take the tool out of the collet first.")
        self.allow_spindle = QCheckBox("Allow spindle")
        self.allow_spindle.setToolTip(
            "Lets the tests that spin the tool run. You are asked again "
            "before anything starts.")
        arm = QHBoxLayout()
        arm.addWidget(self.allow_motion)
        arm.addWidget(self.allow_spindle)
        arm.addStretch(1)
        v.addLayout(arm)

        self.log_lbl = QLabel("")
        self.log_lbl.setFont(theme.font("label"))
        self.log_lbl.setStyleSheet("color: %s;" % theme.TEXT_3)
        v.addWidget(self.log_lbl)

        row = QHBoxLayout()
        self.safe_btn = widgets.button("Run the read-only tests", on=self._run_safe)
        self.sel_btn = widgets.button("Run the selected row", on=self._run_selected)
        self.stop_btn = widgets.button("Stop", kind="stop", on=self._on_stop,
                                       enabled=False)
        self.copy_btn = widgets.button("Copy the report", on=self._copy_report)
        row.addWidget(self.safe_btn)
        row.addWidget(self.sel_btn)
        row.addWidget(self.stop_btn)
        row.addStretch(1)
        row.addWidget(self.copy_btn)
        row.addWidget(widgets.button("Close", on=self.reject))
        v.addLayout(row)

        self._worker = _TestWorker(port)
        self._worker.result.connect(self._on_result)
        self._worker.log.connect(self.log_lbl.setText)
        self._worker.batch_done.connect(self._on_batch_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    # -- running -----------------------------------------------------------
    def _start(self, keys):
        keys = [k for k in keys if self._armed(TEST_BY_KEY[k])]
        if not keys:
            return
        if any(TEST_BY_KEY[k].risk == SPINDLE for k in keys):
            if not dialogs.confirm_irreversible(
                    self, "Start the spindle?",
                    "These tests spin the tool. Check that the collet is empty "
                    "or holds a bit you are willing to run, and that the lid "
                    "is closed — the spindle will not start with it open.",
                    "Spin the tool"):
                return
        for k in keys:
            self._set_row(k, "", "waiting…")
        self.stop_btn.setEnabled(True)
        self.safe_btn.setEnabled(False)
        self.sel_btn.setEnabled(False)
        self._worker.request_tests(keys)

    def _armed(self, spec):
        """Refuse, and say which switch would have allowed it.

        A silent skip reads as a test that passed and produced nothing.
        """
        if spec.risk == MOTION and not self.allow_motion.isChecked():
            self._set_row(spec.key, SKIP, "needs Allow motion")
            return False
        if spec.risk == SPINDLE and not self.allow_spindle.isChecked():
            self._set_row(spec.key, SKIP, "needs Allow spindle")
            return False
        return True

    def _run_safe(self):
        self._start([t.key for t in TESTS if t.risk == SAFE])

    def _run_selected(self):
        r = self.table.currentRow()
        if 0 <= r < len(TESTS):
            self._start([TESTS[r].key])

    def _on_stop(self):
        self._worker.request_abort()
        self.log_lbl.setText("Stopping…")

    # -- results -----------------------------------------------------------
    def _set_row(self, key, status, detail):
        for r, t in enumerate(TESTS):
            if t.key != key:
                continue
            cell = self.table.item(r, 2)
            # The WORD carries the verdict, never the colour alone: PASS and
            # FAIL have to be tellable apart by someone who cannot separate
            # red from green, and in a pasted report there is no colour left.
            cell.setText(status)
            ink = _RESULT_INK.get(status)
            if ink:
                cell.setForeground(QColor(ink))
            self.table.item(r, 3).setText(str(detail))
            self.table.item(r, 3).setToolTip(str(detail))
            return

    def _on_result(self, key, status, detail):
        self._results[key] = (status, detail)
        self._set_row(key, status, detail)

    def _on_batch_done(self):
        self.stop_btn.setEnabled(False)
        self.safe_btn.setEnabled(True)
        self.sel_btn.setEnabled(True)
        self.log_lbl.setText("Done.")

    def _on_failed(self, msg):
        self._on_batch_done()
        dialogs.report_error(
            self, "The machine test could not reach the link", None,
            "%s. Check the USB lead, and that nothing else — VPanel, a "
            "serial monitor, or this app's own machine bar — already has "
            "%s open." % (msg, self._port))

    def _copy_report(self):
        QApplication.clipboard().setText(report_text(self._results, self._port))
        self.log_lbl.setText("Report copied to the clipboard.")

    def closeEvent(self, e):
        self._worker.stop()
        super().closeEvent(e)
