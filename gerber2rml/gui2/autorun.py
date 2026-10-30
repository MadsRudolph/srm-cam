"""Run it all: the page that drives the autonomous run.

The operator's part is four things: type the stock's size, put it on the bed
with the probe clip on it, click roughly where it is, press Start. On a
double-sided job, a fifth: turn it over when asked and press Continue.
Everything between is :mod:`gerber2rml.engine.autorun` on its own thread.

The run takes the serial port the way a probe run does - the live link lets
go of it and STOP on the bar still reaches the run through the link's shared
abort event - and gives it back when it ends, however it ends.

On the simulator (port ``SIM``) the bed is drawn live on the stage: the
stock where it really lies, every cut as it is made, the stock as the probe
found it, and the head.
"""
import threading

from PySide6.QtCore import QObject, Qt, Signal, QTimer
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLabel,
                               QDoubleSpinBox)

from gerber2rml.engine import autorun as ar
from gerber2rml.engine import simmachine
from gerber2rml.gui2 import theme, widgets, inspector

STATE_GLYPH = {"waiting": ("○", theme.TEXT_3),
               "running": ("●", theme.LIVE), "done": ("✓", theme.VERIFIED),
               "failed": ("✕", theme.DANGER)}


class _OnGui(QObject):
    """Run a callable on the GUI thread and wait for its result.

    The run's thread needs the window's toolpaths, and the window's state is
    the GUI thread's to touch. A blocking queued signal hands the call over
    and waits for the answer."""
    call = Signal(object)

    def __init__(self):
        super().__init__()
        self.call.connect(self._do, Qt.BlockingQueuedConnection)

    def _do(self, job):
        fn, box = job
        try:
            box["value"] = fn()
        except Exception as e:                        # handed back, raised there
            box["error"] = e

    def __call__(self, fn):
        if threading.current_thread() is threading.main_thread():
            return fn()
        box = {}
        self.call.emit((fn, box))
        if "error" in box:
            raise box["error"]
        return box.get("value")


class WindowSource(ar.JobSource):
    """The job, as the window has it."""

    def __init__(self, win, gui):
        self.w, self.gui = win, gui

    def _plan_steps(self):
        steps = [s for s in self.w.plan.steps
                 if s.kind == "run" and s.op != "airpass"]
        keys = [s.key for s in self.w.plan.steps]
        if "flip" not in keys:
            return steps, []
        cut = keys.index("flip")
        before = [s for s in steps if keys.index(s.key) < cut]
        after = [s for s in steps if keys.index(s.key) > cut]
        return before, after

    def bottom_steps(self):
        return self.gui(lambda: [(s.key, s.title)
                                 for s in self._plan_steps()[0]])

    def top_steps(self):
        return self.gui(lambda: [(s.key, s.title)
                                 for s in self._plan_steps()[1]])

    def place(self, pose, margin_mm):
        def go():
            w = self.w
            b = w.work_bounds()
            st = w.state
            w.action_place(st.place_x + pose.x + margin_mm - b[0],
                           st.place_y + pose.y + margin_mm - b[1])
            w.action_stock(pose.w, pose.h, pose.x, pose.y, show=True)
        self.gui(go)

    def toolpaths(self, key):
        def go():
            w = self.w
            step = w.plan.by_key(key)
            if w._double and step.op == "cutout":
                # The cut-out runs after the flip, so it is cut from the top:
                # the top-frame outline, through the measured fit.
                from gerber2rml.engine.cutout import cut_outline
                lay = w._ds_layout()
                paths = w._fit_paths(cut_outline(lay.top_outline,
                                                 w.cutting_cutout()))
            else:
                paths = w._toolpaths_for(step)[0]
            job = {"drill": w.cutting_drill(), "align": w.cutting_drill(),
                   "cutout": w.cutting_cutout()}.get(step.op,
                                                     w.cutting_trace())
            return paths, job.xy_feed, job.plunge_feed
        return self.gui(go)

    def area(self, side):
        def go():
            w = self.w
            if side == "top" and w._double:
                lay = w._ds_layout()
                x0, y0, x1, y1 = lay.top_outline.bounds
                pts = [w._top_fit.apply(x, y) for x, y in
                       ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
                xs, ys = zip(*pts)
                return min(xs), min(ys), max(xs), max(ys)
            return w.work_bounds()
        return self.gui(go)

    def fiducials(self):
        def go():
            from gerber2rml.doublesided import nominal_top_fiducials
            lay = self.w._ds_layout()
            return ([(x, y) for x, y, _d in lay.align_holes],
                    nominal_top_fiducials(lay))
        return self.gui(go)

    def fiducial_clearance_um(self):
        w = self.w
        return int(max(0.15, (w._fid_diameter - w.state.drill.bit_diameter)
                       / 2.0) * 1000)

    def set_top_fit(self, t):
        self.gui(lambda: self.w.set_top_fit(t))


class _Events(QObject, ar.Events):
    note_sig = Signal(str)
    step_sig = Signal(str, str)
    stock_sig = Signal(object)
    flip_sig = Signal()

    def __init__(self):
        super().__init__()
        self.flipped = threading.Event()
        self.go_on = True

    def note(self, text):
        self.note_sig.emit(text)

    def step(self, key, state):
        self.step_sig.emit(key, state)

    def stock(self, pose):
        self.stock_sig.emit(pose)

    def flip(self):
        self.flipped.clear()
        self.flip_sig.emit()
        self.flipped.wait()
        return self.go_on


class AutoRunPage(inspector.Page):
    """Stock size, a click, Start; then a live checklist."""
    finished = Signal(bool, str)

    def __init__(self, ctl, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.set_head("Run it all", "Automatically, start to finish")
        self._click = None
        self._thread = None
        self._events = None
        self._gui = _OnGui()
        self._rows = {}

        self.add(widgets.body(
            "Put the copper stock on the bed (on tape - the bed must not "
            "conduct), clip the probe to its copper, type its size and click "
            "roughly where it lies. Start finds it, probes it and cuts the "
            "whole board with the one bit in the collet."))

        stock = widgets.Section("The stock")
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(theme.GAP_S)
        self.w_spin, self.h_spin = (self._spin(v) for v in ctl.stock[2:4])
        for lab, sp in (("W", self.w_spin), ("H", self.h_spin)):
            h.addWidget(QLabel(lab))
            h.addWidget(sp)
        h.addWidget(QLabel("mm"))
        h.addStretch(1)
        stock.add(row)
        self.pick_btn = widgets.button(
            "Click where it is", on=self._arm_pick,
            tip="Then click on the stage, anywhere on the stock. The probe "
                "goes there first and finds the edges from it.")
        stock.add(self.pick_btn)
        self.click_lbl = widgets.hint("No spot clicked yet.")
        stock.add(self.click_lbl)
        self.sim_lbl = widgets.hint("")
        stock.add(self.sim_lbl)
        self.add(stock)

        run = widgets.Section("Run")
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(theme.GAP_S)
        self.start_btn = widgets.button("Start", kind="primary",
                                        on=self.start)
        self.flip_btn = widgets.button(
            "It is flipped - continue", kind="primary", on=self._flipped)
        self.flip_btn.setVisible(False)
        h.addWidget(self.start_btn)
        h.addWidget(self.flip_btn)
        h.addStretch(1)
        run.add(row)
        self.status = widgets.body("")
        run.add(self.status)
        self.list_box = QWidget()
        self.list_lay = QVBoxLayout(self.list_box)
        self.list_lay.setContentsMargins(0, 0, 0, 0)
        self.list_lay.setSpacing(2)
        run.add(self.list_box)
        run.add(widgets.hint("STOP on the bar stops the run at any point and "
                             "lifts the bit."))
        self.add(run)
        self.finish()

        self._sim_timer = QTimer(self)
        self._sim_timer.setInterval(120)
        self._sim_timer.timeout.connect(self._draw_sim)
        self.finished.connect(self._on_finished)

    @staticmethod
    def _spin(value):
        s = QDoubleSpinBox()
        s.setRange(10.0, 200.0)
        s.setDecimals(1)
        s.setValue(float(value))
        s.setKeyboardTracking(False)
        s.setFocusPolicy(Qt.StrongFocus)
        return s

    # -- the click ---------------------------------------------------------
    def _arm_pick(self):
        self.ctl.set_stage_mode("stock")
        self.click_lbl.setText("Click on the stock, on the stage.")

    def on_stock_click(self, x, y):
        self._click = (x, y)
        self.ctl.set_stage_mode("place")
        self.click_lbl.setText("Starts looking at X %.1f, Y %.1f." % (x, y))

    # -- the checklist -------------------------------------------------------
    def _plan_rows(self):
        src = WindowSource(self.ctl, self._gui)
        rows = [("stock", "Find the stock"), ("level", "Probe the surface")]
        rows += src.bottom_steps()
        if self.ctl._double:
            rows += [("flip", "Turn it over"),
                     ("stock_top", "Find the stock again"),
                     ("fiducials", "Find the fiducials"),
                     ("level_top", "Probe the top")]
            rows += [(k, t) for k, t in src.top_steps() if k != "cutout_run"]
            rows += [(k, t) for k, t in src.top_steps() if k == "cutout_run"]
        return rows

    def _fill_rows(self):
        while self.list_lay.count():
            item = self.list_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._rows = {}
        for key, title in self._plan_rows():
            lab = QLabel()
            lab.setTextFormat(Qt.RichText)
            self._rows[key] = (lab, title)
            self._set_row(key, "waiting")
            self.list_lay.addWidget(lab)

    def _set_row(self, key, state):
        if key not in self._rows:
            return
        lab, title = self._rows[key]
        glyph, colour = STATE_GLYPH.get(state, STATE_GLYPH["waiting"])
        lab.setText('<span style="color:%s">%s</span>&nbsp;&nbsp;%s'
                    % (colour, glyph, title))

    # -- running -------------------------------------------------------------
    def _port(self):
        link = self.ctl.link
        return (link.firmware or {}).get("port") if link.is_connected() else None

    def showEvent(self, e):
        super().showEvent(e)
        port = self._port()
        if port and simmachine.is_sim(port):
            m = simmachine.machine()
            c = m.view()["stock"]
            cx = sum(p[0] for p in c) / 4
            cy = sum(p[1] for p in c) / 4
            self.sim_lbl.setText(
                "Simulator: the stock is %.0f × %.0f mm, about X %.0f, Y %.0f "
                "- click near there." % (m.w / 1000, m.h / 1000, cx, cy))
            self._sim_timer.start()
        else:
            self.sim_lbl.setText("")
        if self._thread is None:
            self._fill_rows()

    def start(self):
        ctl = self.ctl
        if self._thread is not None:
            ctl.say("warn", "Already running. STOP stops it.")
            return
        port = self._port()
        if port is None:
            ctl.say("warn", "Connect to the machine first (or pick Simulator "
                            "on the bar to try it).")
            return
        if ctl.state.board is None:
            ctl.say("warn", "Load a board first.")
            return
        if self._click is None:
            ctl.say("warn", "Click where the stock is first.")
            return
        sim = simmachine.is_sim(port)
        if sim:
            printer = simmachine.printer()
        else:
            from gerber2rml.engine import rmlspool
            name = rmlspool.find_mill()
            if name is None:
                ctl.say("fail", "The Roland SRM-20 printer is not installed on "
                                "this PC, so there is nothing to send jobs to.")
                return
            printer = rmlspool.SpoolPrinter(name)
        if ctl._double:
            # Fiducials are the alignment, flipped left to right, and wide
            # enough for the probe bit to drop into.
            ctl._registration = "fiducial"
            ctl._fid_flip = "vertical"
            ctl._fid_diameter = round(ctl.state.drill.bit_diameter + 0.8, 2)
            ctl.refresh_plan()
        size = (self.w_spin.value(), self.h_spin.value())
        ctl.action_stock(size[0], size[1])
        self._fill_rows()
        link = ctl.link
        link.mark_external(True)
        link.disconnect_from("handing the port to the run")
        link.clear_abort()
        self._events = ev = _Events()
        ev.note_sig.connect(self._on_note)
        ev.step_sig.connect(self._set_row)
        ev.stock_sig.connect(self._on_stock)
        ev.flip_sig.connect(self._on_flip)
        src = WindowSource(ctl, self._gui)
        self.start_btn.setEnabled(False)
        self._last_port = port
        click = self._click
        bit = ctl.state.drill.bit_diameter

        def work():
            from gerber2rml.engine import spi_probe
            ser = None
            ok, msg = False, ""
            try:
                ser = spi_probe.open_link(port)
                run = ar.AutoRun(ser, printer, src, ev, click_mm=click,
                                 stock_mm=size, double=ctl._double,
                                 bit_mm=bit, should_abort=link.should_abort,
                                 should_pause=link.should_pause)
                ok = run.run()
                msg = "The board is done."
            except Exception as e:
                msg = str(e) or e.__class__.__name__
            finally:
                try:
                    if ser is not None:
                        ser.close()
                except Exception:
                    pass
            self.finished.emit(ok, msg)

        self._thread = threading.Thread(target=work, name="srm-autorun",
                                        daemon=True)
        self._thread.start()
        if sim:
            self._sim_timer.start()
        ctl.say("info", "Running. STOP on the bar stops it.")

    def _on_note(self, text):
        self.status.setText(text)

    def _on_stock(self, pose):
        if simmachine.is_sim(getattr(self, "_last_port", "")):
            m = simmachine.machine()
            m.found = [pose.to_machine(u, v) for u, v in
                       ((0, 0), (pose.w, 0), (pose.w, pose.h), (0, pose.h))]

    def _on_flip(self):
        self.flip_btn.setVisible(True)
        self.ctl.say("warn", "Turn the board over, left to right, put it back "
                             "where it was, then press Continue.")

    def _flipped(self):
        self.flip_btn.setVisible(False)
        if self._events is None:
            return
        if simmachine.is_sim(getattr(self, "_last_port", "")):
            simmachine.machine().flip()
        self._events.go_on = True
        self._events.flipped.set()

    def _on_finished(self, ok, msg):
        self._thread = None
        self.start_btn.setEnabled(True)
        self.flip_btn.setVisible(False)
        if self._events is not None:
            self._events.go_on = False
            self._events.flipped.set()
        self.status.setText(msg)
        self.ctl.say("ok" if ok else "fail",
                     msg if ok else "The run stopped: " + msg)
        link = self.ctl.link
        link.mark_external(False)
        port = getattr(self, "_last_port", None)
        if port:
            link.connect_to(port)

    def _draw_sim(self):
        m = simmachine.machine()
        self.ctl.stage.set_sim(m.view())
        if self._thread is not None:
            x, y, z = m.pos
            self.ctl.stage.set_tool((x / 1000.0, y / 1000.0),
                                    touch=m.touching())
