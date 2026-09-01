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
hardware and written up in ``docs/2026-08-21-spi-command-audit.md``:

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
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLabel,
                               QComboBox, QSizePolicy)

from gerber2rml.gui2 import theme, widgets
from gerber2rml.engine import spi_probe
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
        self._abort = threading.Event()
        self._external = False        # something else owns the port (a probe run)
        self.firmware = None
        self.last_status = {}
        self.last_position = None     # (x, y, z, touch) mm, last good read
        self.spindle_on = False
        self._spindle_ours = False

    # -- lifecycle ---------------------------------------------------------
    def is_connected(self):
        return self._ser is not None

    def is_busy(self):
        return self._busy

    def connect_to(self, port):
        if self._ser is not None:
            self.disconnect_from("reconnecting")
        self._abort.clear()
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
        self._q.put(None)
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass
        self.firmware = None
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
        firmware lifts the tool. This flag exists so the button can say so.
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
                    self.op_done.emit(name, result)
            except Exception as e:
                self.op_failed.emit(name, f"{e.__class__.__name__}: {e}")
                if port is not None:
                    self._ser = None
            finally:
                self._busy = False
                self.busy_changed.emit(False)

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
        self.clear_abort()
        self.submit("jog_z", op)

    def jog_to(self, x_mm, y_mm):
        def op(ser):
            return spi_probe.jog_to(ser, int(round(x_mm * 1000)),
                                    int(round(y_mm * 1000)))
        self.clear_abort()
        self.submit("jog_xy", op)

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
        if not plat.capabilities().machine_link:
            note = QLabel(
                "The machine link runs on Windows only, so there is no "
                "Connect here. Prepare the job, export, and send the files "
                "from VPanel on the CNC PC — or load a height map "
                "measured there to export levelled toolpaths.")
            note.setWordWrap(False)
            note.setObjectName("muted")
            h.addWidget(note)
            h.addStretch(1)
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
        lh.setSpacing(theme.GAP_M)

        self.dro_x = widgets.Readout("X", "—", width=72)
        self.dro_y = widgets.Readout("Y", "—", width=72)
        self.dro_z = widgets.Readout("Z", "—", width=72)
        for d in (self.dro_x, self.dro_y, self.dro_z):
            d.setToolTip("Machine position, millimetres from the machine "
                         "origin at the front-left corner of the bed.")
            lh.addWidget(d)

        self.touch = widgets.Chip("Clear", "idle")
        self.touch.setToolTip(
            "Whether the bit is touching the copper, read from the probe "
            "wire. Jogging down is refused while it says Touching.")
        lh.addWidget(self.touch)

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
                                         "the probe says the bit is already "
                                         "touching copper.")
        for b in (self.z_up, self.z_down):
            b.setFixedSize(30, 28)
        self.step_combo = QComboBox()
        for s in Z_STEPS:
            self.step_combo.addItem(f"{s:g} mm", s)
        self.step_combo.setCurrentIndex(3)
        self.step_combo.setFixedWidth(78)
        zh.addWidget(self.z_down)
        zh.addWidget(self.z_up)
        zh.addWidget(self.step_combo)
        zv.addWidget(zrow)
        lh.addWidget(zbox)

        self.zero_btn = widgets.button(
            "Zero Z here", on=self._zero_z,
            tip="Touch the bit down on the copper and call that Z zero.\n"
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

        self.jog_btn = widgets.button(
            "Click to jog", on=self._toggle_jog,
            tip="While this is on, clicking the bed moves the head there. "
                "The canvas is in machine coordinates, so where you click is "
                "where it goes.")
        self.jog_btn.setCheckable(True)
        lh.addWidget(self.jog_btn)

        lh.addStretch(1)
        self.live.hide()
        h.addWidget(self.live, 1)

        # -- STOP --------------------------------------------------------
        # Last in the layout and first in the hierarchy: the largest type on
        # the bar, the only filled red in the application, and never hidden by
        # a mode, a tier, a view or a dialog. Escape does the same thing.
        self.stop_btn = widgets.button(
            "STOP", kind="stop", on=self._stop,
            tip="Stop the machine now: drops the move in flight, stops the "
                "spindle and lifts.\n\nEscape does the same from anywhere in "
                "the application.")
        self.stop_btn.setMinimumWidth(112)
        h.addWidget(self.stop_btn)

        # wiring
        link.linked.connect(self._on_linked)
        link.unlinked.connect(self._on_unlinked)
        link.position.connect(self._on_position)
        link.status.connect(self._on_status)
        link.op_failed.connect(self._on_failed)

        self._timer = QTimer(self)
        self._timer.timeout.connect(link.poll)
        self._touching = False
        self.refresh_ports()

    # -- ports -------------------------------------------------------------
    def refresh_ports(self):
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

    def current_port(self):
        return self.port_combo.currentData()

    # -- actions -----------------------------------------------------------
    def _toggle_connect(self):
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

    def _zero_z(self):
        self.link.zero_z()
        self.message.emit("info", "Touching off and setting Z zero…")

    def _toggle_spindle(self):
        want = self.spindle_btn.isChecked()
        self.link.set_spindle(want)

    def _toggle_jog(self):
        self.jog_mode_changed.emit(self.jog_btn.isChecked())

    def _stop(self):
        if self.link.can_stop_something():
            self.link.stop_now()
            self.spindle_btn.setChecked(False)
            self.message.emit("warn", "STOP sent: move dropped, spindle off, "
                                      "tool lifting.")
        else:
            # Never a dead grey button. If there is no link there is still an
            # answer, and it is the one that actually stops this machine.
            self.message.emit(
                "warn", "No link to stop. Use the machine's own emergency "
                        "stop, or close the lid — the spindle will not run "
                        "with it open.")

    # -- link events -------------------------------------------------------
    def _on_linked(self, info):
        self.chip.set(f"Linked · firmware v{info['version']}", "live")
        self.connect_btn.setText("Disconnect")
        self.connect_btn.setEnabled(True)
        self.port_combo.setEnabled(False)
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
        self.live.hide()
        self.offline_note.show()
        self.jog_btn.setChecked(False)
        self.jog_mode_changed.emit(False)
        for d in (self.dro_x, self.dro_y, self.dro_z):
            d.set("—", colour=theme.TEXT_3)
        if reason and reason != "disconnected":
            self.message.emit("warn", f"Machine link closed: {reason}")

    def _on_position(self, x, y, z, touch):
        self.dro_x.set(f"{x:8.2f}")
        self.dro_y.set(f"{y:8.2f}")
        self.dro_z.set(f"{z:8.2f}")
        self._touching = touch
        self.touch.set("Touching" if touch else "Clear",
                       "warn" if touch else "idle")
        self.z_down.setEnabled(not touch)

    def _on_status(self, st):
        # The cover bit is the ONLY status bit proven on this machine, so it is
        # the only one that becomes a state on screen. The rest are read and
        # available in the machine test panel, where they are labelled as
        # unverified.
        if st.get("cover"):
            self.chip.set("Lid open — spindle inhibited", "warn")
        elif self.link.is_connected():
            rpm = st.get("rpm") or 0
            if st.get("spindle"):
                self.chip.set(f"Spindle running · {rpm} rpm", "warn")
            else:
                v = (self.link.firmware or {}).get("version", "?")
                self.chip.set(f"Linked · firmware v{v}", "live")
        self.spindle_btn.setChecked(bool(st.get("spindle")))

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
