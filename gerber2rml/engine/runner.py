"""Run one RML job on the mill and know when it has finished.

The job goes to the printer (:mod:`gerber2rml.engine.rmlspool`, or the
simulator's); the Arduino link watches it. Neither one alone can say "done":
the spooler empties as soon as the driver has the bytes, long before the
last move, and the machine stands still between moves of a slow plunge. So
the end is all three at once - nothing queued, the motors stopped for
``still_s``, and the head where the program ends.

A head that has not moved at all for ``settled_s``, with nothing queued, has
finished too, wherever it is: waiting on would hang the run for hours with the
mill standing idle (seen 2026-11-03, the check before the cut-out never came).
The run goes on, and says how far off the head stopped, because that means the
job did not end where it was meant to.

STOP is the reverse: purge what the spooler still holds, tell the machine to
stop moving and drop its job, spindle off, lift. Lifting needs firmware v4
(the abort lift used to cancel itself; hardware/srm20_spi_probe).
"""
import math
import time

from gerber2rml.engine import spi_probe


class RunStopped(RuntimeError):
    """The run was stopped - by the operator, or by the machine."""


def program_end(rml_text):
    """The last commanded (x, y) of an RML program, in RML units (0.01 mm),
    or None."""
    last = None
    for cmd in rml_text.replace("\n", "").split(";"):
        cmd = cmd.strip()
        try:
            if cmd.startswith("Z"):
                x, y, _z = (int(v) for v in cmd[1:].split(","))
                last = (x, y)
            elif cmd.startswith("PU"):
                x, y = (int(v) for v in cmd[2:].split(","))
                last = (x, y)
        except ValueError:
            continue
    return last


class JobRunner:
    """Send jobs and supervise them over the link ``ser``."""

    def __init__(self, ser, printer, should_abort, should_pause=None,
                 note=None, still_s=2.0, poll_s=0.3, origin_mm=(0.0, 0.0),
                 settled_s=20.0):
        self.ser = ser
        self.printer = printer
        self.should_abort = should_abort
        self.should_pause = should_pause or (lambda: False)
        self.note = note or (lambda _m: None)
        self.still_s = still_s
        self.poll_s = poll_s
        self.settled_s = settled_s
        self.origin = origin_mm

    def run(self, program, name, timeout_s=6 * 3600, progress=None,
            end_mm=None):
        """Run ``program`` to the end. Raises :class:`RunStopped`.

        ``end_mm`` is where the head stops, machine XY; without it the end is
        read from the program as RML."""
        if end_mm is None:
            end = program_end(program)
            end_mm = (None if end is None else
                      (self.origin[0] + end[0] / 100.0,
                       self.origin[1] + end[1] / 100.0))
        self.printer.send(program, name)
        t0 = time.monotonic()
        still_since = None
        paused = False
        last_pos, settled_since = None, time.monotonic()
        while True:
            if self.should_abort():
                self.stop()
                raise RunStopped("stopped")
            if self.should_pause() != paused:
                paused = not paused
                (spi_probe.suspend_job if paused else spi_probe.resume_job)(
                    self.ser)
            st = spi_probe.machine_status(self.ser) or {}
            if st.get("cover"):
                self.stop()
                raise RunStopped("the lid was opened")
            if st.get("error") or st.get("fatal"):
                # What a refused program looks like: the mill holds in pause
                # with its error bit up (RML sent to a mill set to NC Code).
                self.stop()
                raise RunStopped("the mill refused the job. In VPanel, "
                                 "Setup ▸ Command Set must be NC Code; press "
                                 "Cancel there to clear it")
            pos = spi_probe.query_position(self.ser)
            if progress is not None and pos:
                progress(pos)
            moving = bool(st.get("moving"))
            queued = self.printer.pending()
            at_end = (end_mm is None or pos is None or
                      math.dist(pos[:2], end_mm) < 0.3)
            if not paused and not moving and not queued and at_end:
                still_since = still_since or time.monotonic()
                if time.monotonic() - still_since >= self.still_s:
                    return True
            else:
                still_since = None
            if (pos is None or paused or queued or last_pos is None
                    or math.dist(pos[:3], last_pos) > 0.02):
                settled_since = time.monotonic()
                last_pos = pos[:3] if pos else last_pos
            elif time.monotonic() - settled_since >= self.settled_s:
                self.note(
                    "%s: the mill stopped at X %.2f, Y %.2f, Z %.2f, not at the "
                    "program's end (X %.2f, Y %.2f). Check the job finished."
                    % ((name,) + tuple(pos[:3]) + tuple(end_mm or pos[:2])))
                return True
            if time.monotonic() - t0 > timeout_s:
                self.stop()
                raise RunStopped("the job ran past its time limit")
            time.sleep(self.poll_s)

    def stop(self):
        """Everything that stops the machine, each failure swallowed."""
        for step in (lambda: self.printer.purge(),
                     lambda: spi_probe.stop_moving_now(self.ser),
                     lambda: spi_probe.cancel_job(self.ser),
                     lambda: spi_probe.spindle_off(self.ser),
                     lambda: spi_probe.send_abort(self.ser)):
            try:
                step()
            except Exception:
                pass
