"""EXPERIMENTAL: stream toolpaths to the SRM-20 over the SPI link.

This bypasses VPanel's file player entirely: the host sends every move as a
firmware ``M`` command (origin-relative, microns, raw library speed value)
and waits for the per-move ack. The prize is closed-loop milling — live
leveling, native progress, native abort. The catch, and why every entry
point says EXPERIMENTAL:

- the SPI ``jumpTo`` speed value's units are Roland-internal and NOT yet
  calibrated against mm/s;
- the spindle is not controllable over this link — it must be started in
  VPanel by hand for a wet run.

Therefore the mandatory first step on any new setup is a DRY RUN
(``dry_run=True``, the default): the full job traces in XY with Z clamped
``dry_lift_mm`` ABOVE the work origin, cutting nothing, while you watch the
motion and the clock. Only after the dry run looks right (and the speed
value is dialed in against a stopwatch) does a wet run make sense.
"""
import time

from gerber2rml.engine import spi_probe
from gerber2rml.engine.spi_probe import _read_line, send_abort


class StreamError(RuntimeError):
    pass


def begin_stream(ser, timeout=3.0):
    """Send ``C``: cache the work origin on the firmware and clear any stale
    abort. Returns the origin (ox, oy, oz) in um. Firmware v2 only."""
    ser.write(b"C\n")
    line = _read_line(ser, time.monotonic() + timeout)
    if not (line and line.startswith("C ")):
        raise StreamError(
            f"no stream session ack (got {line!r}) — firmware v2 with the "
            f"'stream' feature required (reflash hardware/srm20_spi_probe)")
    parts = line.split()
    return int(parts[1]), int(parts[2]), int(parts[3])


def _halt(ser):
    """Stop the machine and lift, in that order.

    Order matters: the move is queued in the Roland controller, so ``!`` on its
    own would have to wait for a long travel to finish before the lift could
    even be commanded. ``stopMoving`` kills it first (proven on the machine: it
    cut a 20 mm move short at 4.8 mm).
    """
    spi_probe.stop_moving_now(ser)
    send_abort(ser)


def _start_spindle(ser, rpm, settle_s=4.0):
    """Start the spindle for a wet run and let it come up to speed.

    Refuses if the machine reports its lid open. Note the speed is NOT ours to
    set — measured on the machine, ``turnSpindle``'s argument is ignored and the
    real speed comes from VPanel's slider. This is the ``M3`` half of the job,
    which is still worth having: it is one less VPanel round-trip per run.
    """
    st = spi_probe.machine_status(ser)
    if st is not None and st.get("cover"):
        raise StreamError("the machine reports its lid open — refusing to "
                          "start the spindle")
    if spi_probe.set_spindle(ser, rpm) is None:
        raise StreamError("the machine refused to start the spindle")
    # Give it time to reach speed before the first plunge — the NC path does the
    # same thing with a G04 dwell, for the same reason (M3 does not wait).
    deadline = time.monotonic() + settle_s
    while time.monotonic() < deadline:
        time.sleep(0.5)
        st = spi_probe.machine_status(ser)
        if st is not None and st.get("spindle"):
            return
    # It was COMMANDED on and simply did not report back. It may well be
    # turning, so stop it before bailing out — walking away here would leave a
    # bit spinning on the strength of a status read we already do not trust.
    spi_probe.spindle_off(ser)
    raise StreamError("the spindle never reported running — stopped it and "
                      "aborted before anything touched the work")


def stream_toolpaths(ser, toolpaths, speed=-1, dry_run=True, dry_lift_mm=2.0,
                     move_timeout=120.0, on_progress=None, should_abort=None,
                     spindle_rpm=0, should_pause=None, watch_cover=True):
    """Stream Move lists (work-frame mm) move by move.

    ``dry_run=True`` (default) clamps EVERY move's Z to ``dry_lift_mm`` above
    the work origin — the whole job traces in air. ``speed`` is passed RAW to
    the firmware/library (-1 = machine default, measured at 19.1 mm/s).

    ``spindle_rpm`` non-zero starts the spindle before the first move and stops
    it at the end, however the run finishes. ``should_pause()`` returning true
    holds the machine (the operator's Pause) and resumes when it goes false.
    ``watch_cover`` aborts the run if the machine reports its lid opening.

    ``on_progress(i, n)`` is called after each acked move. ``should_abort()``
    turning true halts the machine, lifts, and raises :class:`StreamError`.
    Returns the number of moves streamed.
    """
    moves = [m for tp in toolpaths for m in tp]
    if not moves:
        return 0
    begin_stream(ser)
    n = len(moves)
    spindle_started = False
    paused = False
    try:
        if spindle_rpm and not dry_run:
            _start_spindle(ser, spindle_rpm)
            spindle_started = True
        for i, m in enumerate(moves):
            if should_abort is not None and should_abort():
                _halt(ser)
                raise StreamError(f"aborted at move {i}/{n} — tool lifted")
            # Operator pause: hold the machine here rather than racing on. The
            # firmware honours '~'/'^' mid-move, so this is safe to enter at
            # any point in the job.
            if should_pause is not None:
                while should_pause():
                    if not paused:
                        spi_probe.suspend_job(ser)
                        paused = True
                    if should_abort is not None and should_abort():
                        _halt(ser)
                        raise StreamError(f"aborted while paused at move {i}/{n}")
                    time.sleep(0.2)
                if paused:
                    spi_probe.resume_job(ser)
                    paused = False
            z_mm = dry_lift_mm if dry_run else m.z
            ser.write(f"M {round(m.x * 1000)} {round(m.y * 1000)} "
                      f"{round(z_mm * 1000)} {int(speed)}\n".encode())
            line = _read_line(ser, time.monotonic() + move_timeout, should_abort)
            if should_abort is not None and should_abort():
                _halt(ser)
                raise StreamError(f"aborted at move {i}/{n} — tool lifted")
            if not (line and line.startswith("M ")):
                _halt(ser)
                raise StreamError(
                    f"move {i}/{n} failed (got {line!r}) — tool lifted; the lid "
                    f"opening or a timeout stops the stream, never continues it")
            if on_progress:
                on_progress(i + 1, n)
            # Cheap safety poll: the machine's own cover bit is proven to follow
            # the lid, so a run can be stopped by opening it. Once every 20
            # moves keeps the cost off the critical path.
            if watch_cover and i % 20 == 19:
                st = spi_probe.machine_status(ser)
                if st is not None and st.get("cover"):
                    _halt(ser)
                    raise StreamError(
                        f"lid opened at move {i}/{n} — stopped and lifted")
        return n
    finally:
        if spindle_started:
            spi_probe.spindle_off(ser)
