"""Bench-test the SRM-20's SPI command set — the experiments that decide whether
VPanel can be retired.

The project drives the machine through Roland's ``SRM20SPIRemote`` library but
has only ever called five of its commands. This script exercises the rest
against the real machine and answers the three questions that block progress:

1. **Which unused commands actually work?**  ``--features`` asks the board what
   it supports, reads the full status word, and reports what answered.
2. **How fast can the SPI link go?**  ``--frame-sweep`` walks the per-byte SS
   framing delay down from Roland's hard-coded 5000 us and measures, at each
   step, both the round-trip time AND the read-corruption rate. Speed is
   worthless if the position reads turn to garbage, so both are measured
   together. This delay is the real ceiling on move streaming: at 5 ms/byte a
   single ``jumpTo`` spends ~90 ms asleep.
3. **What are ``jumpTo``'s speed units?**  ``--speed-sweep`` runs timed
   there-and-back moves at a range of raw speed values and derives mm/s. Until
   this is known, streamed cutting stays experimental.

Nothing here moves the machine unless you pass ``--allow-motion``, and nothing
spins the bit unless you pass ``--allow-spindle``. Both print what they are
about to do and wait for confirmation (``--yes`` skips the prompt).

Usage:
    python scripts/srm20_bench.py --port COM5 --features
    python scripts/srm20_bench.py --port COM5 --frame-sweep
    python scripts/srm20_bench.py --port COM5 --speed-sweep --allow-motion
    python scripts/srm20_bench.py --port COM5 --all --allow-motion --report bench.md

Requires firmware v3 (hardware/srm20_spi_probe) and the patched library for the
frame sweep. Close the Arduino Serial Monitor first — only one program can hold
the port.
"""
import argparse
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gerber2rml.engine import spi_probe  # noqa: E402

# Framing delays to walk, in microseconds. 5000 is Roland's shipped value; the
# bottom of the range is where SPI transfers plausibly start failing, which is
# exactly what we want to find rather than assume.
FRAME_STEPS = (5000, 2000, 1000, 500, 200, 100, 50, 0)
# Raw movespeed values for jumpTo. -1 is the library default (= whatever the
# machine picks). The rest are guesses at a scale nobody outside Roland has
# documented; the sweep is how the scale gets discovered.
SPEED_STEPS = (-1, 1, 2, 5, 10, 20, 30, 50)


def _confirm(msg, assume_yes):
    if assume_yes:
        print(f"  (--yes) {msg}")
        return True
    try:
        return input(f"  {msg} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


# --------------------------------------------------------------------------
def probe_features(ser, out):
    """Ask the board and the machine what they can do. No motion."""
    out.section("Features")
    ver, feats = spi_probe.firmware_version(ser)
    out.row("sketch firmware", f"v{ver}")
    out.row("sketch features", ",".join(sorted(feats)) or "(none reported)")
    if ver < 3:
        out.note("Firmware is older than v3 — reflash hardware/srm20_spi_probe "
                 "or none of the commands below will answer.")

    mver = spi_probe.command_version(ser)
    out.row("machine command version", mver if mver is not None else
            "no answer (unpatched library, or the machine does not implement it)")

    fd = spi_probe.frame_delay(ser)
    out.row("SPI framing delay", f"{fd} us" if fd is not None else
            "no answer (library not patched)")

    st = spi_probe.machine_status(ser)
    if st is None:
        out.row("machine status", "NO ANSWER — getStatus is not reaching the machine")
        return
    flags = [k for _m, k, _d in spi_probe.SYSTEM_BITS if st.get(k)]
    out.row("status word", f"system=0x{st['system']:08x} remote=0x{st['remote']:08x}")
    out.row("state code", st["state"])
    out.row("flags set", ", ".join(flags) or "none")
    out.row("spindle RPM (read back)", st["rpm"])
    out.row("command rejected (remote cmderr)", st["cmderr"])
    # A sanity read: all-zero or all-ones words mean the transfer is garbage,
    # not that the machine is idle.
    if st["system"] in (0, 0xFFFFFFFF):
        out.note(f"system word is 0x{st['system']:08x} — that is a suspicious "
                 f"value; treat every status bit as unproven until it changes "
                 f"when you open the lid.")
    else:
        out.note("Open the lid and re-run: if 'cover' appears in the flags, the "
                 "status bits are real and the firmware's safety guard works.")


def frame_sweep(ser, out, samples=20):
    """Walk the framing delay down, measuring speed AND corruption at each step.

    Read-only: it only queries position. The corruption measure is what makes
    this trustworthy — a delay that halves the round trip but garbles one read
    in ten is worse than useless on a machine that moves on those reads.
    """
    out.section("SPI framing-delay sweep")
    original = spi_probe.frame_delay(ser)
    if original is None:
        out.note("The board did not answer 'F' — the vendored library is not "
                 "patched, so the delay cannot be changed. Skipping.")
        return
    out.row("starting delay", f"{original} us")
    out.table_header(["delay us", "ms/read", "reads ok", "garbage", "verdict"])
    best = None
    try:
        for us in FRAME_STEPS:
            if spi_probe.frame_delay(ser, us) is None:
                out.table_row([us, "-", "-", "-", "no answer"])
                continue
            times, reads = [], []
            for _ in range(samples):
                t0 = time.monotonic()
                p = spi_probe.query_position(ser)
                times.append((time.monotonic() - t0) * 1000.0)
                if p is not None:
                    reads.append(p[:3])
            if not reads:
                out.table_row([us, "-", 0, samples, "DEAD — no reads at all"])
                continue
            # Nothing is moving, so every read should agree. Anything more than
            # a few microns off the median is a corrupted transfer.
            med = [statistics.median(v[i] for v in reads) for i in range(3)]
            bad = sum(1 for v in reads
                      if any(abs(v[i] - med[i]) > 0.003 for i in range(3)))
            lost = samples - len(reads)
            ms = statistics.median(times)
            ok = bad == 0 and lost == 0
            verdict = "clean" if ok else f"CORRUPT ({bad} off, {lost} lost)"
            out.table_row([us, f"{ms:.1f}", len(reads) - bad, bad + lost, verdict])
            if ok:
                best = us
    finally:
        spi_probe.frame_delay(ser, original)
        out.row("restored delay", f"{original} us")
    if best is not None:
        out.note(f"Lowest CLEAN delay: {best} us (Roland ships 5000). A jumpTo "
                 f"is 18 bytes, so that is roughly "
                 f"{18 * best / 1000.0:.0f} ms of framing per move instead of "
                 f"{18 * 5000 / 1000.0:.0f} ms. Re-run this a few times before "
                 f"trusting the bottom of the range — corruption is intermittent.")


def frame_soak(ser, out, us, reads=400):
    """Hammer ONE framing delay for a few hundred reads and count corruption.

    The sweep only takes a dozen samples per step, which is enough to find a
    candidate and nowhere near enough to trust one. SPI corruption here is
    intermittent — a delay that looks clean over 12 reads can garble one in a
    hundred, and this link drives a bit toward a board. So: soak the candidate
    before lowering anything that matters.
    """
    out.section(f"Framing-delay soak @ {us} us")
    original = spi_probe.frame_delay(ser)
    if original is None:
        out.note("library not patched — cannot change the framing delay")
        return
    if spi_probe.frame_delay(ser, us) is None:
        out.note("the board refused the delay")
        return
    try:
        t0 = time.monotonic()
        good, lost = [], 0
        for _ in range(reads):
            p = spi_probe.query_position(ser)
            if p is None:
                lost += 1
            else:
                good.append(p[:3])
        elapsed = time.monotonic() - t0
    finally:
        spi_probe.frame_delay(ser, original)
    if not good:
        out.row("result", f"DEAD — 0/{reads} reads answered")
        return
    med = [statistics.median(v[i] for v in good) for i in range(3)]
    bad = sum(1 for v in good if any(abs(v[i] - med[i]) > 0.003 for i in range(3)))
    out.row("reads", f"{len(good)}/{reads} answered, {lost} lost")
    out.row("corrupted", f"{bad} ({100.0 * bad / len(good):.2f}%)")
    out.row("rate", f"{elapsed * 1000.0 / reads:.1f} ms per read")
    if bad or lost:
        out.note(f"NOT clean at {us} us — do not lower the default this far. "
                 f"Nothing moves on a bad read only because the firmware "
                 f"requires two agreeing reads; do not remove that.")
    else:
        out.note(f"Clean over {reads} reads. Still leave margin: pick a delay "
                 f"several times higher than the lowest clean one, and re-soak "
                 f"after any wiring change.")


def map_bits(ser, out, seconds=90):
    """Watch the status word and report every bit that CHANGES, live.

    Roland's example labels seven bits. On this machine the cover bit is proven
    but ``0x20`` ("pause") does not behave like its label, and several bits it
    does not document are set. Rather than trusting the labels, map them: run
    this and do one known thing at a time — open the lid, close it, press
    Pause in VPanel, press Resume, start a job — and watch which bit moves.

    Read-only.
    """
    out.section("Status-bit mapper")
    st = spi_probe.machine_status(ser)
    if st is None:
        out.note("no status to watch")
        return
    base_sys, base_rem = st["system"], st["remote"]
    out.row("baseline", f"system=0x{base_sys:08x} remote=0x{base_rem:08x}")
    print(f"\n  Watching for {seconds}s. Do ONE thing at a time and note what "
          f"you did when a line appears:")
    print("    open the lid / close it / VPanel Pause / VPanel Resume / start a job\n")
    known = {m: k for m, k, _d in spi_probe.SYSTEM_BITS}
    t0 = time.monotonic()
    seen = 0
    while time.monotonic() - t0 < seconds:
        st = spi_probe.machine_status(ser)
        if st is None:
            continue
        sys_d, rem_d = st["system"] ^ base_sys, st["remote"] ^ base_rem
        if sys_d or rem_d:
            bits = []
            for i in range(32):
                m = 1 << i
                if sys_d & m:
                    label = known.get(m, "UNDOCUMENTED")
                    bits.append(f"system 0x{m:08x} ({label}) "
                                f"-> {1 if st['system'] & m else 0}")
                if rem_d & m:
                    bits.append(f"remote 0x{m:08x} -> "
                                f"{1 if st['remote'] & m else 0}")
            line = f"t+{time.monotonic() - t0:5.1f}s  " + "; ".join(bits)
            out._emit("- " + line)
            base_sys, base_rem = st["system"], st["remote"]
            seen += 1
        time.sleep(0.25)
    if not seen:
        out.note("Nothing changed. Either nothing was done to the machine, or "
                 "the status word does not reflect it.")
    else:
        out.note("Write down which action caused which bit. A bit whose meaning "
                 "is confirmed can be added to GUARD_MASK in the firmware; an "
                 "unconfirmed one must not be.")


def speed_sweep(ser, out, axis="y", dist_mm=20.0, allow_motion=False,
                assume_yes=False):
    """Timed there-and-back moves at a range of raw speed values -> mm/s.

    Each measurement is a pair (out and back), so the head finishes where it
    started and the sweep cannot walk the machine into a limit.
    """
    out.section("Speed-unit calibration")
    if not allow_motion:
        out.note("Skipped — needs --allow-motion (this MOVES the machine).")
        return
    pos = spi_probe.query_position(ser)
    if pos is None:
        out.note("Could not read the position — refusing to move.")
        return
    out.row("start position", f"X {pos[0]:.2f}  Y {pos[1]:.2f}  Z {pos[2]:.2f} mm")
    print(f"\n  About to move {dist_mm} mm in ±{axis.upper()}, "
          f"{len(SPEED_STEPS)} times, spindle OFF.")
    print("  Make sure the head has that much clear travel in both directions.")
    if not _confirm("Proceed?", assume_yes):
        out.note("Declined at the prompt.")
        return

    um = int(dist_mm * 1000)
    delta = {"x": (um, 0, 0), "y": (0, um, 0), "z": (0, 0, um)}[axis]
    out.table_header(["raw speed", "out ms", "back ms", "dist mm", "mm/s"])
    for sp in SPEED_STEPS:
        a = spi_probe.timed_move(ser, *delta, speed=sp)
        if a is None:
            out.table_row([sp, "-", "-", "-", "no answer / aborted"])
            break
        b = spi_probe.timed_move(ser, *(-d for d in delta), speed=sp)
        if b is None:
            out.table_row([sp, a["ms"], "-", "-", "return move failed — STOPPED"])
            break
        rates = [m["mm_per_s"] for m in (a, b) if m["mm_per_s"]]
        out.table_row([sp, a["ms"], b["ms"], f"{a['dist_um'] / 1000.0:.2f}",
                       f"{statistics.mean(rates):.1f}" if rates else "-"])
    out.note("If mm/s does not change with the raw speed value, the machine is "
             "ignoring the argument and every move runs at its default rate — "
             "which would mean streamed feeds cannot be controlled over SPI.")


def spindle_test(ser, out, rpm=3000, allow_spindle=False, assume_yes=False):
    """Start the spindle over SPI, read the RPM back, stop it.

    This is the single most valuable unknown: if it works, RPM stops being a
    VPanel-only setting.
    """
    out.section("Spindle control")
    if not allow_spindle:
        out.note("Skipped — needs --allow-spindle (this SPINS THE TOOL).")
        return
    print(f"\n  About to run the spindle at {rpm} RPM for ~6 s.")
    print("  REMOVE THE TOOL or make sure the bit is clear of the work, close")
    print("  the lid, and keep clear. The firmware stops it if this script dies.")
    if not _confirm("Spin the spindle?", assume_yes):
        out.note("Declined at the prompt.")
        return
    got = spi_probe.set_spindle(ser, rpm)
    if got is None:
        out.row("turnSpindle", "NO ANSWER / refused (cover open, or v2 firmware)")
        return
    out.row("commanded RPM", got)
    try:
        for i in range(6):
            time.sleep(1.0)
            st = spi_probe.machine_status(ser)   # also feeds the firmware deadman
            if st is None:
                out.row(f"t+{i + 1}s", "status read failed")
                continue
            out.row(f"t+{i + 1}s", f"rpm={st['rpm']} spindle_bit={st['spindle']}")
    finally:
        spi_probe.set_spindle(ser, 0)
        out.row("spindle", "commanded OFF")
    out.note("If the RPM read climbs toward the commanded value, spindle control "
             "over SPI works and the 'RPM is a VPanel cut-setting' limitation is "
             "gone for the SPI path.")


def jobctl_test(ser, out, allow_motion=False, assume_yes=False):
    """suspend / resume / stopMoving / cancelJob — VPanel's transport buttons.

    Tested against a real move, because acking a command while idle proves
    nothing about whether it does anything.
    """
    out.section("Job control")
    for name, fn in (("suspendJob", spi_probe.suspend_job),
                     ("resumeJob", spi_probe.resume_job),
                     ("stopMoving", spi_probe.stop_moving),
                     ("cancelJob", spi_probe.cancel_job)):
        out.row(f"{name} (idle)", "acked" if fn(ser) else "no answer")
    out.note("An ack only means the firmware sent the opcode. Whether the "
             "machine acts on it can only be seen against a running move — use "
             "the GUI's Machine test panel, which pauses a real 20 mm move.")
    if not allow_motion:
        return
    pos = spi_probe.query_position(ser)
    if pos is None:
        out.note("No position read — skipping the live stopMoving test.")
        return
    print("\n  About to start a 20 mm +Y move and interrupt it with stopMoving.")
    if not _confirm("Proceed?", assume_yes):
        return
    t0 = time.monotonic()
    ser.write(b"N 0 20000 0 -1\n")
    time.sleep(0.7)                       # let it get going, then cut it short
    spi_probe.stop_moving(ser)            # consumes the '% ok' ack
    # An interrupted move reports 'E N ABORT', a completed one 'N <ms> ...' —
    # accept either, or this waits out the full timeout when the stop worked.
    deadline = time.monotonic() + 30.0
    line = None
    while time.monotonic() < deadline:
        line = spi_probe._read_line(ser, deadline)
        if line is None or line.startswith(("N ", "E ")):
            break
    end = spi_probe.query_position(ser)
    out.row("move reply", line or "(none)")
    out.row("elapsed", f"{time.monotonic() - t0:.1f} s")
    if end is not None:
        moved = abs(end[1] - pos[1])
        out.row("actual Y travel", f"{moved:.2f} mm of 20.00 commanded")
        out.note("Travel well short of 20 mm means stopMoving genuinely aborts a "
                 "move in flight — which is what makes STOP able to interrupt a "
                 "long move instead of waiting it out.")


# --------------------------------------------------------------------------
class Report:
    """Collects results as plain text + optional markdown for pasting back."""

    def __init__(self):
        self.lines = []

    def section(self, title):
        self._emit("")
        self._emit(f"## {title}")

    def row(self, key, value):
        self._emit(f"- **{key}:** {value}")

    def note(self, text):
        self._emit(f"  > {text}")

    def table_header(self, cols):
        self._emit("")
        self._emit("| " + " | ".join(str(c) for c in cols) + " |")
        self._emit("|" + "|".join("---" for _ in cols) + "|")

    def table_row(self, cols):
        self._emit("| " + " | ".join(str(c) for c in cols) + " |")

    def _emit(self, line):
        self.lines.append(line)
        print(line)

    def text(self):
        return "\n".join(self.lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Bench-test the SRM-20 SPI command set.")
    ap.add_argument("--port", help="serial port (auto-detected if omitted)")
    ap.add_argument("--features", action="store_true",
                    help="report firmware/machine capabilities + status (no motion)")
    ap.add_argument("--frame-sweep", action="store_true",
                    help="sweep the SPI framing delay: speed vs corruption (no motion)")
    ap.add_argument("--map-bits", action="store_true",
                    help="watch the status word and report bits that change, so "
                         "you can map them by doing one thing at a time (no motion)")
    ap.add_argument("--map-seconds", type=int, default=90,
                    help="how long --map-bits watches (default 90)")
    ap.add_argument("--frame-soak", type=int, metavar="US",
                    help="hammer ONE framing delay for --soak-reads reads and "
                         "report the corruption rate (no motion)")
    ap.add_argument("--soak-reads", type=int, default=400,
                    help="reads per --frame-soak (default 400)")
    ap.add_argument("--speed-sweep", action="store_true",
                    help="calibrate jumpTo's speed units (MOVES the machine)")
    ap.add_argument("--jobctl", action="store_true",
                    help="test pause/resume/stop/cancel")
    ap.add_argument("--spindle", action="store_true",
                    help="start and stop the spindle (SPINS THE TOOL)")
    ap.add_argument("--all", action="store_true", help="run everything allowed")
    ap.add_argument("--allow-motion", action="store_true",
                    help="permit tests that move the machine")
    ap.add_argument("--allow-spindle", action="store_true",
                    help="permit tests that spin the spindle")
    ap.add_argument("--yes", action="store_true", help="skip the confirmations")
    ap.add_argument("--axis", default="y", choices=("x", "y", "z"),
                    help="axis for the speed sweep (default y)")
    ap.add_argument("--dist", type=float, default=20.0,
                    help="speed-sweep move distance in mm (default 20)")
    ap.add_argument("--rpm", type=int, default=3000,
                    help="spindle test RPM (default 3000)")
    ap.add_argument("--report", help="write the markdown report to this file")
    args = ap.parse_args(argv)

    if args.all:
        args.features = args.frame_sweep = args.jobctl = True
        args.speed_sweep = args.allow_motion
        args.spindle = args.allow_spindle
    if not any((args.features, args.frame_sweep, args.frame_soak, args.map_bits,
                args.speed_sweep, args.jobctl, args.spindle)):
        args.features = True                     # the safe default

    port = args.port
    if not port:
        import serial.tools.list_ports
        ports = [(p.device, p.hwid) for p in serial.tools.list_ports.comports()]
        port = spi_probe.best_port(ports)
        if not port:
            print("No Arduino-like serial port found; pass --port explicitly.")
            return 2
        print(f"Auto-detected port {port}")

    out = Report()
    out._emit(f"# SRM-20 SPI bench — {port}")
    ser = spi_probe.open_link(port)
    try:
        if args.features:
            probe_features(ser, out)
        if args.frame_sweep:
            frame_sweep(ser, out)
        if args.frame_soak:
            frame_soak(ser, out, args.frame_soak, args.soak_reads)
        if args.map_bits:
            map_bits(ser, out, args.map_seconds)
        if args.jobctl:
            jobctl_test(ser, out, args.allow_motion, args.yes)
        if args.speed_sweep:
            speed_sweep(ser, out, args.axis, args.dist, args.allow_motion, args.yes)
        if args.spindle:
            spindle_test(ser, out, args.rpm, args.allow_spindle, args.yes)
    finally:
        try:
            spi_probe.spindle_off(ser)           # belt and braces on every exit
            ser.close()
        except Exception:
            pass

    if args.report:
        Path(args.report).write_text(out.text(), encoding="utf-8")
        print(f"\nReport written to {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
