"""The link to the mill, and the bar that is always holding the stop button.

**The safety argument for this file.** The first interface puts the machine
controls in a dock that a UI mode can hide, and the stop button is in that
dock. When the beginner mode hid the dock it hid the stop button, so guided bed
levelling — which steps the spindle down onto the copper, repeatedly, under
software control — had to be removed from that mode entirely rather than ship
without a way to stop it.

Here the bar is a structural part of the window: it is not in a tab, not in a
dock, not in a panel any tier or view can put away, and it is the *only* place
in the application from which the machine can be made to move. Bed levelling
can therefore stay available to a beginner, which matters, because probing is
the single most useful thing the Arduino buys someone who has never run this
machine.

Three machine facts this file refuses to lie about, all of them learned on the
hardware and written up in ``docs/archive/2026-08-21-spi-command-audit.md``:

* **Spindle speed is not settable over this link.** ``turnSpindle``'s RPM
  argument is ignored: 500, 1000, 2000 and 3000 all settle on whatever VPanel's
  slider says. So there is a spindle button and there is no spindle speed
  control, and the label says where the speed actually comes from.
* **Only one status bit is proven.** The cover/lid bit (``0x20000``) follows
  the physical lid. The bit Roland's documentation labels "paused"
  demonstrably does not mean paused on this machine. Unproven bits are read and
  logged; none of them is displayed as a machine state.
* **XY origin is never touched.** There is a control that zeroes Z and there is
  no control that zeroes XY, because everything in the program — the screw
  fixture, the dowel registration, the ability to re-run a pass — depends on
  the XY origin surviving the whole job.
"""
import queue
import threading
import time

from PySide6.QtCore import Qt, QObject, Signal, QTimer
from PySide6.QtGui import QAction, QKeySequence, QPainter, QColor
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLabel,
                               QComboBox, QSizePolicy)

from gerber2rml.gui2 import theme, widgets
from gerber2rml.engine import spi_probe
from gerber2rml.engine.estimate import format_duration
from gerber2rml.engine.progress import RunProgress
from gerber2rml import platform as plat

POLL_MS = 300           # also the deadman feed: the firmware stops the spindle
                        # if the host goes quiet for 10 s, so this keeps a
                        # spindle we started alive only while the app is alive.


def list_ports():
    """``[(device, why), ...]``, most-likely-Arduino first, or [] with a reason.

    Returns the reason as the second element so the disconnected state can say
    something true instead of showing an empty dropdown.
    """
    try:
        from serial.tools import list_ports as lp
    except ImportError:
        return [], ("pyserial is not installed, so no serial ports can be "
                    "listed. Run the doctor to install the interface "
                    "dependencies.")
    try:
        ports = [(p.device, p.hwid) for p in lp.comports()]
    except Exception as e:                      # pragma: no cover - driver-specific
        return [], f"the serial ports could not be listed ({e.__class__.__name__})."
    if not ports:
        return [], ("no serial ports were found. Check the USB lead to the "
                    "Arduino inside the machine.")
    return spi_probe.rank_ports(ports), ""


class MachineLink(QObject):
    """Owns the serial port and a single worker thread.

    One worker, one queue: every command to the machine is serialised, so two
    controls can never interleave half a request each on a strict
    request/response protocol. The exception is :meth:`stop_now`, which writes
    from whichever thread called it — see its docstring.
    """
    linked = Signal(dict)
    unlinked = Signal(str)
    position = Signal(float, float, float, bool)
    status = Signal(dict)
    op_done = Signal(str, object)
    op_failed = Signal(str, str)
    busy_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ser = None
        self._q = queue.Queue()
        self._thread = None
        self._busy = False
        self._current = None          # name of the op the worker is inside
        self._abort = threading.Event()
        self._external = False        # something else owns the port (a probe run)
        self.firmware = None
        self.last_status = {}
        self.last_position = None     # (x, y, z, touch) mm, last good read
        # Machine Z of the copper, from the last verified touch (zero Z or a
        # touch-off). It is what the pre-flight measures the Z stroke from;
        # without it the deepest-cut check can only hedge.
        self.surface_z = None
        self.spindle_on = False
        self._spindle_ours = False
        # When this app last moved the head itself (a jog). Run tracking
        # auto-starts on motion, and a jog is motion we caused: the tracker
        # reads this to tell the two apart.
        self.last_jog_t = 0.0

    # -- lifecycle ---------------------------------------------------------
    def is_connected(self):
        return self._ser is not None

    def is_busy(self):
        """Whether the worker is inside an operation the OPERATOR would call one.

        The position poll is not one: it runs every ``POLL_MS`` and holds the
        port for its two serial round-trips, so a bare ``self._busy`` shut the
        probe gates on roughly one click in ten with "the machine is still
        doing something" while the mill stood still. Real work queues behind a
        poll in flight anyway, so a poll never needs to hold a gate closed."""
        return self._busy and self._current != "poll"

    def connect_to(self, port):
        if self._ser is not None:
            self.disconnect_from("reconnecting")
        self._abort.clear()
        # One worker, ever. A failed connect leaves the thread alive and
        # waiting for the next item; starting another per retry stacked
        # workers on the one queue, and two of them could then run two
        # commands on one serial port at once - the interleaving the queue
        # exists to make impossible.
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, name="srm-link",
                                            daemon=True)
            self._thread.start()
        self.submit("connect", lambda _s: None, _connect_port=port)

    def disconnect_from(self, reason=""):
        ser, self._ser = self._ser, None
        # Disconnecting never stops a spindle we did not start. Someone may
        # have started it from VPanel, and killing it because a USB cable moved
        # would be a surprise in the wrong direction.
        if ser is not None and self._spindle_ours:
            spi_probe.spindle_off(ser)
        # The worker is NOT told to exit: it is a daemon, it serialises the
        # port for the life of the app, and the next connect reuses it.
        # Closing the port under it is what ends an operation in flight.
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass
        self.firmware = None
        self.surface_z = None         # a new session touches off again
        self.last_position = None     # ...and reads its position afresh
        self.spindle_on = False
        self._spindle_ours = False
        self.unlinked.emit(reason)

    def submit(self, name, fn, *, _connect_port=None):
        """Queue ``fn(ser)`` on the worker. ``name`` comes back with the result."""
        if _connect_port is None and self._ser is None:
            self.op_failed.emit(name, "not connected")
            return
        self._q.put((name, fn, _connect_port))

    def mark_external(self, on):
        """A grid probe has taken the serial port for the duration of its run.

        ``spi_probe.probe_grid`` opens the port itself, so the live link must
        let go of it — but the run still has to be stoppable. It polls this
        object's abort event, so :meth:`stop_now` keeps working with no port of
        its own: it sets the event, the run's next read bails out, and the
        firmware stops the motion. This flag exists so the button can say so.
        """
        self._external = bool(on)

    def stop_now(self):
        """Halt motion and the spindle, from the calling thread, immediately.

        Deliberately NOT queued. If the worker is part-way through a long move
        or a probe descent, a queued stop would sit behind it — which is
        precisely the situation the button exists for. Both writes are
        fire-and-forget on a protocol whose firmware scans for the abort byte
        mid-move, and every failure is swallowed, because a stop that raises is
        worse than useless.

        Returns True when the stop reached something: an open port, or a probe
        run watching the abort event.
        """
        self._abort.set()
        self._paused = False
        ser = self._ser
        if ser is None:
            return self._external
        spi_probe.stop_moving_now(ser)
        spi_probe.spindle_off(ser)
        spi_probe.send_abort(ser)
        self.spindle_on = False
        self._spindle_ours = False
        return True

    def can_stop_something(self):
        return self._ser is not None or self._external

    def should_abort(self):
        return self._abort.is_set()

    def clear_abort(self):
        self._abort.clear()

    # -- worker ------------------------------------------------------------
    def _run(self):
        while True:
            item = self._q.get()
            if item is None:
                return
            name, fn, port = item
            # Name first, then the flag: is_busy() reads both, and a reader
            # that saw the flag before the name would call a poll real work.
            self._current = name
            self._busy = True
            self.busy_changed.emit(True)
            try:
                if port is not None:
                    ser = spi_probe.open_link(port)
                    ver, feats = spi_probe.firmware_version(ser)
                    self._ser = ser
                    self.firmware = {"version": ver, "features": sorted(feats),
                                     "port": port}
                    self.linked.emit(dict(self.firmware))
                else:
                    result = fn(self._ser)
                    if name in ("zero_z", "touch") and result:
                        self.surface_z = float(result[2])
                    self.op_done.emit(name, result)
            except Exception as e:
                self.op_failed.emit(name, f"{e.__class__.__name__}: {e}")
                if port is not None:
                    self._ser = None
            finally:
                self._busy = False
                self._current = None
                self.busy_changed.emit(False)

    def current_op(self):
        """The name of the op the worker is inside, or None."""
        return getattr(self, "_current", None)

    # -- hold ----------------------------------------------------------------
    # VPanel's Pause. Not a stop: the spindle keeps turning and the job
    # resumes where it was. Two paths, because two things can be running.
    # A streamed job is inside one long op that owns the port, so it is held
    # by a flag its loop polls; anything the machine runs from a VPanel file
    # is held by the firmware's suspendJob, queued like any other command.
    def pause(self):
        self._paused = True
        if self.current_op() == "stream":
            return True                 # the stream loop holds on the flag
        if self._ser is None:
            return False
        self.submit("pause", lambda ser: spi_probe.suspend_job(ser))
        return True

    def resume(self):
        self._paused = False
        if self.current_op() == "stream":
            return True
        if self._ser is None:
            return False
        self.submit("resume", lambda ser: spi_probe.resume_job(ser))
        return True

    def should_pause(self):
        return bool(getattr(self, "_paused", False))

    def is_paused(self):
        return self.should_pause()

    # -- the operations the bar drives ------------------------------------
    def poll(self):
        """Position + status. Skipped while the worker is busy, so a probe run
        is never slowed down by the readout."""
        if self._ser is None or self._busy:
            return
        self.submit("poll", self._do_poll)

    def _do_poll(self, ser):
        pos = spi_probe.query_position(ser)
        if pos:
            self.last_position = pos
            self.position.emit(pos[0], pos[1], pos[2], pos[3])
        st = spi_probe.machine_status(ser)
        if st:
            self.last_status = st
            self.spindle_on = bool(st.get("spindle"))
            self.status.emit(st)
        return pos

    def jog_z(self, dz_mm):
        def op(ser):
            return spi_probe.timed_move(ser, dz_um=int(round(dz_mm * 1000)),
                                        should_abort=self.should_abort)
        self.last_jog_t = time.time()
        self.clear_abort()
        self.submit("jog_z", op)

    def jog_to(self, x_mm, y_mm):
        def op(ser):
            return spi_probe.jog_to(ser, int(round(x_mm * 1000)),
                                    int(round(y_mm * 1000)))
        self.last_jog_t = time.time()
        self.clear_abort()
        self.submit("jog_xy", op)

    def has_feature(self, name):
        """Whether the connected firmware advertised ``name`` (``"zeroz"``,
        ``"retouch"``, ...). False when nothing is connected."""
        return name in ((self.firmware or {}).get("features") or ())

    def set_spindle(self, on):
        """Start or stop the tool. There is no speed argument, on purpose."""
        def op(ser):
            # The RPM here is a start/stop token, not a speed: the machine
            # ignores the value. It is the rated maximum so that a firmware
            # that ever does honour it errs toward the value VPanel is set to.
            return spi_probe.set_spindle(ser, 7000 if on else 0)
        self._spindle_ours = bool(on)
        self.clear_abort()
        self.submit("spindle", op)

    def zero_z(self):
        def op(ser):
            return spi_probe.zero_z(ser, should_abort=self.should_abort)
        self.clear_abort()
        self.submit("zero_z", op)

    def touch_off(self):
        def op(ser):
            return spi_probe.touch_off(ser, should_abort=self.should_abort)
        self.clear_abort()
        self.submit("touch", op)


# ---------------------------------------------------------------------------

Z_STEPS = [0.01, 0.05, 0.1, 0.5, 1.0, 5.0]


# ---------------------------------------------------------------------------

class RunTracker:
    """How far the run on the mill has got, read off the position poll.

    The mill is driven by VPanel, so the app never knows a run has started;
    what it has is the live position, and :class:`RunProgress` can project
    that onto a step's toolpath. This object holds that projection and the
    one decision around it: *when* to start. It starts by itself the moment
    the bit has been moving for three consecutive polls — the way the first
    interface's "Auto" box did — unless the app moved the bit itself a moment
    ago, because a jog is motion too and must not be mistaken for a run.

    Pure logic, no widgets: the window feeds it positions and paints what it
    returns, and the tests drive it with a fake link.
    """
    MOVE_MM = 0.25          # a poll-to-poll shift smaller than this is jitter
    MOVE_READS = 3          # ~0.75 s of continuous motion at POLL_MS
    JOG_GRACE_S = 2.0       # ignore motion this soon after our own jog

    def __init__(self, link, now=time.time):
        self.link = link
        self._now = now
        self.auto = True
        self.progress = None
        self.label = ""
        self.finished = False
        self._motion = 0
        self._last = None

    def arm(self, toolpaths, xy_feed, plunge_feed, label=""):
        """Start following ``toolpaths`` (machine mm) from the next position."""
        self.progress = RunProgress(toolpaths, xy_feed, plunge_feed)
        self.label = label
        self.finished = False
        self._motion = 0
        return self.progress.total

    def disarm(self):
        self.progress = None
        self.label = ""
        self.finished = False
        self._motion = 0

    def is_tracking(self):
        return self.progress is not None

    @property
    def total(self):
        return self.progress.total if self.progress is not None else 0.0

    def feed(self, x, y, z, start=None):
        """A live position. Returns ``(fraction, elapsed_s, remaining_s)``
        while a run is tracked, else None.

        ``start`` is called with no arguments when motion is seen and nothing
        is being tracked (or the tracked run has finished); it arms this
        object for whatever step is current and returns True if it did.
        """
        if self.auto and start is not None and (
                self.progress is None or self.finished):
            self._maybe_start(x, y, z, start)
        if self.progress is None:
            return None
        frac, elapsed, remaining = self.progress.update(x, y, z)
        if frac >= 0.999:
            self.finished = True
        return frac, elapsed, remaining

    def _maybe_start(self, x, y, z, start):
        if self._now() - getattr(self.link, "last_jog_t", 0.0) < self.JOG_GRACE_S:
            self._last = (x, y, z)          # our own motion: skip, but keep up
            self._motion = 0
            return
        prev, self._last = self._last, (x, y, z)
        if prev is None:
            return
        moved = ((x - prev[0]) ** 2 + (y - prev[1]) ** 2
                 + (z - prev[2]) ** 2) ** 0.5
        self._motion = self._motion + 1 if moved > self.MOVE_MM else 0
        if self._motion >= self.MOVE_READS:
            self._motion = 0
            start()


class RunReadout(QWidget):
    """The run, as one compact fact on the bar: which step, how far, how long.

    The first interface gave tracking a whole row — an op picker, a checkbox,
    a button, a progress bar and a label. Here it is the width of one readout
    and it is only there while a run is being followed, so the bar stays one
    row and STOP stays where it is. The bar under the label is painted rather
    than a QProgressBar: three pixels tall, it has no chrome to style.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(1)
        self._label = QLabel("Run")
        self._label.setFont(theme.font("label"))
        self._label.setStyleSheet(f"color: {theme.TEXT_3};")
        self._value = QLabel("—")
        self._value.setFont(theme.font("head", mono=True))
        self._value.setStyleSheet(f"color: {theme.TEXT};")
        # Neither label may set this widget's minimum: a long step title
        # would widen the whole bar. The title is elided to the width
        # instead, and the tooltip carries it whole.
        for lb in (self._label, self._value):
            lb.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        v.addWidget(self._label)
        v.addWidget(self._value)
        self.setFixedWidth(120)
        self.fraction = 0.0
        self.setToolTip(
            "How far the run on the mill has got, read from the bit's "
            "position, and the time left at the planned feeds. It follows the "
            "step the rail was on when tracking started. Tracking starts by "
            "itself when the bit begins moving; Machine ▸ Track this step's "
            "run starts or stops it by hand.")
        self.hide()

    def _title(self, label, pct):
        tail = f" · {pct}%"
        fm = self._label.fontMetrics()
        room = self.width() - fm.horizontalAdvance(tail.upper())
        return fm.elidedText(label, Qt.ElideRight, max(room, 20)) + tail

    def set_armed(self, label, total_s, linked=True):
        self.fraction = 0.0
        self.label = label
        self._label.setText(self._title(label, 0))
        self._value.setText(format_duration(total_s) + (" total" if linked
                                                        else " · connect"))
        self._value.setStyleSheet(f"color: {theme.TEXT_3};")
        self.show()
        self.update()

    def set_run(self, label, frac, remaining_s):
        self.fraction = max(0.0, min(1.0, frac))
        self.label = label
        done = frac >= 0.999
        self._label.setText(self._title(label, int(round(frac * 100))))
        self._value.setText("done" if done
                            else f"{format_duration(remaining_s)} left")
        self._value.setStyleSheet(
            f"color: {theme.VERIFIED if done else theme.TEXT};")
        self.show()
        self.update()

    def clear(self):
        self.fraction = 0.0
        self.hide()

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        r = self.rect()
        y = self._label.geometry().bottom() + 1
        w = r.width()
        p.fillRect(0, y, w, 3, QColor(theme.RULE_HI))
        if self.fraction > 0:
            p.fillRect(0, y, int(round(w * self.fraction)), 3,
                       QColor(theme.VERIFIED if self.fraction >= 0.999
                              else theme.LIVE))
        p.end()


class MachineBar(QWidget):
    """The persistent machine strip.

    One bar, not three. The first interface grew three stacked rows along the
    bottom — machine controls, run tracking, a status line — which between them
    took 100 px of a 900 px window and still pushed Connect and STOP toward the
    edge. Everything that is not needed with a hand on the machine has been
    moved into the Machine menu; what is left is what you reach for while
    standing at it.
    """
    jog_mode_changed = Signal(bool)
    message = Signal(str, str)          # (level, text) -> the window's log

    def __init__(self, link, parent=None):
        super().__init__(parent)
        self.link = link
        self.setObjectName("panel")
        self.setFixedHeight(theme.BAR_H)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        h = QHBoxLayout(self)
        h.setContentsMargins(theme.GAP_M + 2, theme.GAP_S, theme.GAP_M + 2,
                             theme.GAP_S)
        h.setSpacing(theme.GAP_M)

        # Where the link does not run, the bar says so and stops. Not a row of
        # greyed-out controls: a dead control with no reason is exactly what
        # this interface refuses to ship, and the honest sentence is short.
        #
        # Levelling is not lost with it. A height map is a file - the Level
        # page loads a probe grid from CSV and exports through it identically -
        # so the flow is "probe once on the CNC PC, carry the CSV", which is
        # worth saying here because nobody would guess it.
        self.gated = not plat.capabilities().machine_link
        if self.gated:
            note = QLabel(plat.NO_MACHINE_LINK_NOTE)
            # Wrapped, or the sentence sets the window's minimum width. A
            # QLabel that may not wrap reports its whole single line as its
            # minimum size hint, and a layout's minimum is the sum of its
            # children's - so 205 unwrapped characters made
            # MainWindow.minimumSizeHint() 2488 px wide against a 1400 px
            # default, and the window could not be narrowed below that on a
            # 1920 px display. Wrapped it is two lines inside BAR_H.
            note.setWordWrap(True)
            # "hint" is a real selector in style.py (TEXT_3, small). The name
            # this used before - "muted" - matched nothing repo-wide, so the
            # sentence rendered in full-strength body text.
            note.setObjectName("hint")
            h.addWidget(note, 1)
            return

        # -- link state --------------------------------------------------
        self.chip = widgets.Chip("Machine offline", "idle")
        h.addWidget(self.chip)

        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(122)
        self.port_combo.setToolTip(
            "Which serial port the Arduino inside the machine is on. The list "
            "is ordered with the most likely board first.")
        h.addWidget(self.port_combo)
        self.connect_btn = widgets.button("Connect", on=self._toggle_connect,
                                          tip="Open the link to the Arduino "
                                              "fitted to the machine's SPI "
                                              "header.")
        h.addWidget(self.connect_btn)

        h.addWidget(widgets.vrule())

        # -- the disconnected state, designed ----------------------------
        # Not an empty toolbar full of grey buttons: a sentence saying what the
        # link is for and what still works without it, because a bare SRM-20
        # with VPanel is a fully supported setup and the app should say so.
        self.offline_note = QLabel(
            "Everything except probing works without the link — export the "
            "files and send them from VPanel.")
        self.offline_note.setFont(theme.font("small"))
        self.offline_note.setStyleSheet(f"color: {theme.TEXT_3};")
        self.offline_note.setWordWrap(True)
        h.addWidget(self.offline_note, 1)

        # -- live controls (hidden until there is a machine to control) ---
        self.live = QWidget()
        lh = QHBoxLayout(self.live)
        lh.setContentsMargins(0, 0, 0, 0)
        # The related-rows gap, not the between-fields one: with two Z
        # touches and the run readout on it, this row is the width budget of
        # the whole window at 1400 px, and STOP must not be what gives.
        lh.setSpacing(theme.GAP_S)

        self.dro_x = widgets.Readout("X", "—", width=68)
        self.dro_y = widgets.Readout("Y", "—", width=68)
        self.dro_z = widgets.Readout("Z", "—", width=68)
        for d in (self.dro_x, self.dro_y, self.dro_z):
            d.setToolTip("Machine position, millimetres from the machine "
                         "origin at the front-left corner of the bed.")
            lh.addWidget(d)
        # Contact lives on the Z readout: the label says "Z · touching" and
        # the number goes red while the probe wire is closed. It used to be
        # a chip of its own beside the readouts; folding it into the number
        # it is about is what lets this row carry two Z touches and the run
        # readout and still fit a 1280 px window with STOP whole.
        self.dro_z.setToolTip(
            "Machine Z, millimetres from the machine origin. Turns red and "
            "says Touch while the bit is on the copper, read from the "
            "probe wire; jogging down is refused while it does.")

        lh.addWidget(widgets.vrule())

        zbox = QWidget()
        zv = QVBoxLayout(zbox)
        zv.setContentsMargins(0, 0, 0, 0)
        zv.setSpacing(2)
        zv.addWidget(widgets.eyebrow("Z jog"))
        zrow = QWidget()
        zh = QHBoxLayout(zrow)
        zh.setContentsMargins(0, 0, 0, 0)
        zh.setSpacing(4)
        self.z_up = widgets.button("↑", kind="key", on=lambda: self._jog(+1),
                                   tip="Raise the bit by one step. Page Up "
                                       "does the same. Raising always works.")
        self.z_down = widgets.button("↓", kind="key", on=lambda: self._jog(-1),
                                     tip="Lower the bit by one step. Page "
                                         "Down does the same. Refused while "
                                         "the Z readout says the bit is already "
                                         "touching copper.")
        for b in (self.z_up, self.z_down):
            b.setFixedSize(30, 28)
        self.step_combo = QComboBox()
        for s in Z_STEPS:
            self.step_combo.addItem(f"{s:g} mm", s)
        self.step_combo.setCurrentIndex(3)
        self.step_combo.setFixedWidth(68)
        zh.addWidget(self.z_down)
        zh.addWidget(self.z_up)
        zh.addWidget(self.step_combo)
        zv.addWidget(zrow)
        lh.addWidget(zbox)

        # Two touches, two different things changed. Probe Z tells the APP
        # where the copper is; Zero Z tells the MACHINE. They were one
        # button here for a while, and the tooltip could not say which of
        # the two it was doing — which matters, because only one of them
        # moves the origin VPanel shows.
        self.probe_btn = widgets.button(
            "Probe Z", on=self._probe_z,
            tip="Lower the bit from here until the probe wire says it has "
                "touched the copper, and stop there.\n\n"
                "This changes nothing on the machine: the app records the "
                "surface height so the pre-flight can check the Z stroke "
                "and the level page knows where the copper is. VPanel's "
                "origin is untouched. Start a few millimetres above the "
                "surface with the touch clips on.")
        lh.addWidget(self.probe_btn)
        self.zero_btn = widgets.button(
            "Zero Z", on=self._zero_z,
            tip="Touch off as Probe Z does, then have the FIRMWARE write the "
                "work origin's Z at the copper surface and lift 2 mm.\n\n"
                "This changes the origin VPanel displays — the same as "
                "pressing its Z0 button at the surface. Check VPanel's G54 Z "
                "once before trusting it for a job.\n"
                "Only Z. The XY origin is never moved — the fixture, the "
                "dowel registration and every re-run depend on it staying "
                "where it is.")
        lh.addWidget(self.zero_btn)

        self.spindle_btn = widgets.button(
            "Spindle", on=self._toggle_spindle,
            tip="Start and stop the tool.\n\n"
                "The speed is not settable over this link — the machine "
                "ignores the value and runs at whatever VPanel's slider says. "
                "Set the speed there.")
        self.spindle_btn.setCheckable(True)
        lh.addWidget(self.spindle_btn)

        self.pause_btn = widgets.button(
            "Pause", on=self._toggle_pause,
            tip="Hold the machine where it is, spindle still turning, and "
                "carry on from the same place with Resume. VPanel's Pause, "
                "from here.\n\nSTOP is the other thing: it drops the move "
                "and stops the spindle, and the job does not resume.")
        self.pause_btn.setCheckable(True)
        lh.addWidget(self.pause_btn)

        self.jog_btn = widgets.button(
            "Click to jog", on=self._toggle_jog,
            tip="While this is on, clicking the bed moves the head there. "
                "The canvas is in machine coordinates, so where you click is "
                "where it goes.")
        self.jog_btn.setCheckable(True)
        lh.addWidget(self.jog_btn)

        # The run readout takes the row's slack and is only there while a
        # run is being followed; see RunReadout for why it is this small.
        self.run = RunReadout()
        lh.addWidget(self.run)

        lh.addStretch(1)
        self.live.hide()
        h.addWidget(self.live, 1)

        # -- STOP --------------------------------------------------------
        # Last in the layout and first in the hierarchy: the largest type on
        # the bar, the only filled red in the application, and never hidden by
        # a mode, a tier, a view or a dialog. Escape does the same thing.
        self.stop_btn = widgets.button(
            "STOP", kind="stop", on=self._stop,
            tip="Stop the machine now: drops the move in flight and stops "
                "the spindle. The bit stays where it is - raise it with Page "
                "Up before moving on.\n\nEscape does the same from anywhere "
                "in the application.")
        self.stop_btn.setMinimumWidth(112)
        h.addWidget(self.stop_btn)

        # wiring
        link.linked.connect(self._on_linked)
        link.unlinked.connect(self._on_unlinked)
        link.position.connect(self._on_position)
        link.status.connect(self._on_status)
        link.op_done.connect(self._on_done)
        link.op_failed.connect(self._on_failed)

        self._timer = QTimer(self)
        self._timer.timeout.connect(link.poll)
        self._touching = False
        self.refresh_ports()

        # Page Up / Page Down nudge Z, as the two buttons' tooltips promise.
        # On the window rather than on a focused control: you are looking at
        # the bit, not the screen, and having to click into the right widget
        # first is the friction that sends people back to VPanel.
        for key, direction in ((Qt.Key_PageUp, +1), (Qt.Key_PageDown, -1)):
            act = QAction(self)
            act.setShortcut(QKeySequence(key))
            # Application-wide, like Escape: Page Up is the lift, and it has
            # to work with the 3D window in front. No auto-repeat: a held
            # Page Down would queue a step per key repeat, thirty a second,
            # and the firmware clamps Z upward only.
            act.setShortcutContext(Qt.ApplicationShortcut)
            act.setAutoRepeat(False)
            act.triggered.connect(lambda _c=False, d=direction: self._jog(d))
            self.addAction(act)

    # -- gated no-ops ------------------------------------------------------
    # The Machine menu still carries "Rescan the serial ports" and
    # "Connect / disconnect" (Ctrl+L), and window.py reads current_port() for
    # the machine test - all three reached straight past the early return above
    # and raised AttributeError on a gated bar. Gating the menu entries instead
    # would leave items that silently do nothing, which is the dead control
    # this interface refuses to ship; a no-op that SAYS WHY puts the
    # explanation where the user clicked, in the same log line the bar already
    # owns.
    def _refused(self):
        self.message.emit("warn", plat.NO_MACHINE_LINK_NOTE)

    def refresh_ports(self):
        if self.gated:
            return self._refused()
        return self._refresh_ports()

    def current_port(self):
        """None where the link is gated - every caller already handles it.

        window.py's machine test says "No serial port to test" and stops on a
        falsy port, so returning None keeps that path honest rather than
        handing a dialog a port that cannot be opened.
        """
        if self.gated:
            return None
        return self.port_combo.currentData()

    def _toggle_connect(self):
        if self.gated:
            return self._refused()
        return self._do_toggle_connect()

    # -- ports -------------------------------------------------------------
    def _refresh_ports(self):
        ports, why = list_ports()
        self.port_combo.clear()
        for device, chip in ports:
            self.port_combo.addItem(f"{device} · {chip}", device)
        self.port_combo.setEnabled(bool(ports))
        self.connect_btn.setEnabled(bool(ports))
        if why:
            self.offline_note.setText(
                f"No machine link: {why} Everything except probing works "
                f"without it — export the files and send them from VPanel.")

    # -- actions -----------------------------------------------------------
    def _do_toggle_connect(self):
        if self.link.is_connected():
            self.link.disconnect_from("disconnected")
        else:
            port = self.current_port()
            if not port:
                return
            self.chip.set("Connecting…", "busy")
            self.connect_btn.setEnabled(False)
            self.link.connect_to(port)

    def _jog(self, direction):
        if direction < 0 and self._touching:
            self.message.emit(
                "warn", "The bit is already touching the copper, so jogging "
                        "down is refused. Raise it first.")
            return
        step = self.step_combo.currentData() or 0.1
        self.link.jog_z(step * direction)

    def _touch_refused(self):
        """Both touches descend from where the bit is. Starting them on the
        copper would measure nothing and the firmware reports it as a failed
        contact; better to say so before it goes."""
        if self._touching:
            self.message.emit(
                "warn", "The bit is already touching the copper. Raise it a "
                        "few millimetres with Page Up, then try again.")
            return True
        return False

    def _probe_z(self):
        if self._touch_refused():
            return
        self.link.touch_off()
        self.message.emit("info", "Probing down to the copper… The machine's "
                                  "origin is not changed by this.")

    def _zero_z(self):
        if self._touch_refused():
            return
        if self.link.firmware and not self.link.has_feature("zeroz"):
            self.message.emit(
                "warn", "This firmware cannot write the origin (it needs v2 "
                        "or later — reflash hardware/srm20_spi_probe). Probe "
                        "Z still works, and VPanel's Z0 button sets the "
                        "origin.")
            return
        self.link.zero_z()
        self.message.emit("info", "Touching off and writing Z zero to the "
                                  "machine…")

    def _toggle_spindle(self):
        want = self.spindle_btn.isChecked()
        self.link.set_spindle(want)

    def _toggle_jog(self):
        self.jog_mode_changed.emit(self.jog_btn.isChecked())

    def _toggle_pause(self):
        want = self.pause_btn.isChecked()
        ok = self.link.pause() if want else self.link.resume()
        if not ok:
            self.pause_btn.setChecked(False)
            self.message.emit("warn", "Nothing to hold: connect to the "
                                      "machine first.")
            return
        self.pause_btn.setText("Resume" if want else "Pause")
        self.message.emit("ok", "Held. Resume carries on from here." if want
                          else "Resuming.")

    def _stop(self):
        # A stop is not a hold. The button must not claim one is in force.
        # (Absent on a gated bar, which has no live controls at all.)
        pause = getattr(self, "pause_btn", None)
        if pause is not None:
            pause.setChecked(False)
            pause.setText("Pause")
        if self.link.can_stop_something():
            self.link.stop_now()
            if not self.gated:                # no spindle button on a gated bar
                self.spindle_btn.setChecked(False)
            self.message.emit("warn", "STOP sent: move dropped, spindle off. "
                                      "Raise the bit with Page Up before the "
                                      "next move.")
        else:
            # Never a dead grey button. If there is no link there is still an
            # answer, and it is the one that actually stops this machine.
            self.message.emit(
                "warn", "No link to stop. Use the machine's own emergency "
                        "stop, or close the lid — the spindle will not run "
                        "with it open.")

    # -- link events -------------------------------------------------------
    def _on_linked(self, info):
        # One word on the chip; the port and the firmware version are in the
        # tooltip and the log line. The chip's width is STOP's margin.
        self.chip.set("Linked", "live")
        self.chip.setToolTip(
            f"Linked on {info['port']}, firmware v{info['version']}. Goes "
            f"amber while the lid is open or the spindle is running.")
        self.connect_btn.setText("Disconnect")
        self.connect_btn.setEnabled(True)
        # Put away, not greyed: a port picker that cannot pick is a dead
        # control, and its 122 px is what the live row needs to stay one row
        # with two Z touches and the run readout on it. The port is in the
        # log line below and comes back with the picker on disconnect.
        self.port_combo.setEnabled(False)
        self.port_combo.hide()
        self.offline_note.hide()
        self.live.show()
        self._timer.start(POLL_MS)
        self.message.emit("ok", f"Linked on {info['port']} "
                                f"(firmware v{info['version']}).")

    def _on_unlinked(self, reason):
        self._timer.stop()
        self.chip.set("Machine offline", "idle")
        self.connect_btn.setText("Connect")
        self.connect_btn.setEnabled(True)
        self.port_combo.setEnabled(True)
        self.port_combo.show()
        self.live.hide()
        self.run.clear()
        self.offline_note.show()
        self.jog_btn.setChecked(False)
        self.jog_mode_changed.emit(False)
        for d in (self.dro_x, self.dro_y, self.dro_z):
            d.set("—", colour=theme.TEXT_3)
        self.dro_z.set_label("Z")
        self._touching = False
        self.chip.setToolTip("")
        if reason and reason != "disconnected":
            self.message.emit("warn", f"Machine link closed: {reason}")

    def _on_position(self, x, y, z, touch):
        self.dro_x.set(f"{x:8.2f}")
        self.dro_y.set(f"{y:8.2f}")
        # "Touch", not "Z · touching": the readout is 68 px wide and the
        # label is set in tracked caps. The red number is the signal.
        self.dro_z.set(f"{z:8.2f}", colour=theme.DANGER if touch else None)
        self.dro_z.set_label("Touch" if touch else "Z")
        self._touching = touch
        self.z_down.setEnabled(not touch)

    def _on_status(self, st):
        # The cover bit is the ONLY status bit proven on this machine, so it is
        # the only one that becomes a state on screen. The rest are read and
        # available in the machine test panel, where they are labelled as
        # unverified.
        if st.get("cover"):
            self.chip.set("Lid open", "warn")   # ...and the spindle will not run
        elif self.link.is_connected():
            rpm = st.get("rpm") or 0
            if st.get("spindle"):
                self.chip.set(f"Spindle on · {rpm} rpm", "warn")
            else:
                self.chip.set("Linked", "live")
        self.spindle_btn.setChecked(bool(st.get("spindle")))

    def _on_done(self, name, result):
        """The two touches report here. The link has already recorded the
        surface height on a good contact; this is the sentence for it."""
        if name == "touch":
            if not result:
                self.message.emit(
                    "warn", "Probe Z found no contact in its whole stroke. "
                            "Check the touch clips, and start the bit closer "
                            "to the copper.")
                return
            self.message.emit(
                "ok", f"Surface found at machine Z {result[2]:.2f} mm. The "
                      f"app knows where the copper is; the machine's origin "
                      f"is unchanged.")
        elif name == "zero_z":
            if not result:
                self.message.emit(
                    "warn", "Zero Z failed: no verified contact, so the "
                            "origin was not written. Check the touch clips "
                            "and start closer to the copper.")
                return
            self.message.emit(
                "ok", f"Origin Z written to the machine at the copper "
                      f"(machine Z {result[2]:.2f} mm). Check VPanel's G54 Z "
                      f"once before the first job.")

    def _on_failed(self, name, msg):
        if name == "connect":
            self.chip.set("Link failed", "fail")
            self.connect_btn.setEnabled(True)
            self.connect_btn.setText("Connect")
            self.message.emit(
                "fail", f"Could not open the machine link on "
                        f"{self.current_port()}: {msg}. Check the USB lead, "
                        f"and that no other program (VPanel, a serial "
                        f"monitor) has the port open.")
        elif name != "poll":
            self.message.emit("warn", f"{name}: {msg}")
