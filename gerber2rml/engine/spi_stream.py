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


def stream_toolpaths(ser, toolpaths, speed=-1, dry_run=True, dry_lift_mm=2.0,
                     move_timeout=120.0, on_progress=None, should_abort=None):
    """Stream Move lists (work-frame mm) move by move.

    ``dry_run=True`` (default) clamps EVERY move's Z to ``dry_lift_mm`` above
    the work origin — the whole job traces in air. ``speed`` is passed RAW to
    the firmware/library (-1 = machine default); calibrate it on dry runs
    before trusting it for a cut.

    ``on_progress(i, n)`` is called after each acked move. ``should_abort()``
    turning true sends ``!`` (firmware lifts to safe Z) and raises
    :class:`StreamError`. Returns the number of moves streamed.
    """
    moves = [m for tp in toolpaths for m in tp]
    if not moves:
        return 0
    begin_stream(ser)
    n = len(moves)
    for i, m in enumerate(moves):
        if should_abort is not None and should_abort():
            send_abort(ser)
            raise StreamError(f"aborted at move {i}/{n} — tool lifted")
        z_mm = dry_lift_mm if dry_run else m.z
        ser.write(f"M {round(m.x * 1000)} {round(m.y * 1000)} "
                  f"{round(z_mm * 1000)} {int(speed)}\n".encode())
        line = _read_line(ser, time.monotonic() + move_timeout, should_abort)
        if should_abort is not None and should_abort():
            send_abort(ser)
            raise StreamError(f"aborted at move {i}/{n} — tool lifted")
        if not (line and line.startswith("M ")):
            send_abort(ser)
            raise StreamError(
                f"move {i}/{n} failed (got {line!r}) — tool lifted; the lid "
                f"opening or a timeout stops the stream, never continues it")
        if on_progress:
            on_progress(i + 1, n)
    return n
