"""EXPERIMENTAL: stream toolpaths to the SRM-20 over the SPI link.

This bypasses VPanel's file player entirely: the host sends every move as a
firmware ``M`` command (origin-relative, microns, raw library speed value)
and waits for the per-move ack. The prize is closed-loop milling — live
leveling, native progress, native abort. The catch, and why every entry
point says EXPERIMENTAL:

- the SPI ``jumpTo`` speed value's units are Roland-internal and NOT yet
  calibrated against mm/s;
- the spindle can be started and stopped over this link, but NOT set: the
  ``turnSpindle`` RPM argument is ignored, so the actual speed is whatever
  VPanel's slider says.

Therefore the mandatory first step on any new setup is a DRY RUN
(``dry_run=True``, the default): the full job traces in XY with Z clamped
``dry_lift_mm`` ABOVE the work origin, cutting nothing, while you watch the
motion and the clock. Only after the dry run looks right (and the speed
value is dialed in against a stopwatch) does a wet run make sense.
"""
import time

from gerber2rml.engine import spi_probe
from gerber2rml.engine.spi_probe import _read_line, send_abort


# The firmware stops a spindle IT was told to start if the host goes quiet
# for SPINDLE_DEADMAN_MS (10 s). A held pause is silence, so the pause loop has
# to keep talking. Status reads are the documented keep-alive and cost nothing.
PAUSE_KEEPALIVE_S = 2.0

# Poll the lid on a clock OR a move count, whichever comes first. The count
# alone (the old `i % 20 == 19`) never checked a job shorter than 20 moves.
# The clock alone misses the opposite case: 40 short moves can all execute
# inside one poll interval. Both, and neither hole is open.
COVER_POLL_S = 1.0
COVER_POLL_MOVES = 10

# An unreadable status word is not "the lid is shut" - it is no information.
# Tolerate a couple in a row (SPI reads are flaky by nature), then stop.
COVER_BLIND_LIMIT = 3


class StreamError(RuntimeError):
    pass


def _status_or_none(ser):
    """``machine_status`` but with the known-dead words folded into None.

    ``machine_status`` deliberately returns an all-zero/all-ones word rather
    than None so a dead link reports as dead. For a safety interlock that
    distinction matters the other way round: we need "I could not read it".
    """
    st = spi_probe.machine_status(ser)
    if st is None or st.get("system") in (0, 0xFFFFFFFF):
        return None
    return st


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
    blind = 0                 # consecutive unreadable status words
    next_cover = 0.0          # monotonic deadline for the next lid poll
    try:
        # Check the lid BEFORE the spindle, not 20 moves in.
        if watch_cover:
            st = _status_or_none(ser)
            if st is not None and st.get("cover"):
                raise StreamError(
                    "the machine reports its lid open — close it before "
                    "starting a run")
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
                next_ka = 0.0
                while should_pause():
                    if not paused:
                        spi_probe.suspend_job(ser)
                        paused = True
                    if should_abort is not None and should_abort():
                        _halt(ser)
                        raise StreamError(f"aborted while paused at move {i}/{n}")
                    # Keep the link busy. Without this the firmware's spindle
                    # deadman sees a silent host and stops the tool, and the
                    # resume below would drive a stationary bit into copper.
                    now = time.monotonic()
                    if now >= next_ka:
                        next_ka = now + PAUSE_KEEPALIVE_S
                        st = _status_or_none(ser)
                        if watch_cover and st is not None and st.get("cover"):
                            _halt(ser)
                            raise StreamError(
                                f"lid opened while paused at move {i}/{n} — "
                                f"stopped and lifted")
                    time.sleep(0.2)
                if paused:
                    spi_probe.resume_job(ser)
                    paused = False
                    # The pause may have outlived the spindle regardless (a
                    # deadman that already fired, someone hitting stop on the
                    # machine). Never resume a wet cut on an unverified tool.
                    if spindle_started:
                        st = _status_or_none(ser)
                        if st is not None and not st.get("spindle"):
                            _halt(ser)
                            raise StreamError(
                                f"the spindle stopped during the pause at move "
                                f"{i}/{n} — stopped and lifted rather than "
                                f"resuming the cut with a stationary tool")
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
            # Safety poll on a CLOCK. This used to be `i % 20 == 19`, which
            # meant a job of fewer than 20 moves - a drill file, a small
            # cut-out - was never checked at all.
            due = (time.monotonic() >= next_cover
                   or i % COVER_POLL_MOVES == COVER_POLL_MOVES - 1)
            if watch_cover and due:
                next_cover = time.monotonic() + COVER_POLL_S
                st = _status_or_none(ser)
                if st is None:
                    blind += 1
                    if blind >= COVER_BLIND_LIMIT:
                        _halt(ser)
                        raise StreamError(
                            f"lost the machine's status word for "
                            f"{blind} reads at move {i}/{n} — stopped and "
                            f"lifted rather than cut blind")
                else:
                    blind = 0
                    if st.get("cover"):
                        _halt(ser)
                        raise StreamError(
                            f"lid opened at move {i}/{n} — stopped and lifted")
        return n
    finally:
        if spindle_started:
            spi_probe.spindle_off(ser)
