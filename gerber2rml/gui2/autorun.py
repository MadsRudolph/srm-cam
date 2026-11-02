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
                               QDoubleSpinBox, QCheckBox, QComboBox,
                               QGridLayout)

from gerber2rml.engine import autorun as ar
from gerber2rml.engine import simmachine
from gerber2rml.engine.stockfind import CORNERS, datum_outline

# The DTU fixture's back-left bracket, measured 2026-11-02 (a 160 x 100
# stock found at 22.31, 29.47, turned -0.10°). Each machine saves its own.
DEFAULT_DATUM = (22.49, 129.47, "back-left")


def saved_datum():
    """(x, y, corner) of the corner bracket, from the settings."""
    from gerber2rml.gui2 import workspace
    raw = workspace.setting("autorun/datum", "") or ""
    try:
        x, y, c = raw.split(",")
        if c in CORNERS:
            return float(x), float(y), c
    except ValueError:
        pass
    return DEFAULT_DATUM
from gerber2rml.gui2 import theme, widgets, inspector

STATE_GLYPH = {"waiting": ("○", theme.TEXT_3),
               "running": ("●", theme.LIVE), "done": ("✓", theme.VERIFIED),
               "failed": ("✕", theme.DANGER),
               "skipped": ("–", theme.TEXT_3)}


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
        self.keep_placement = False      # the outline is real: keep the board

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
            # Where the operator put the board on the stock outline is where
            # it is cut: keep its offset from the stock's corner. That outline
            # is real only when the stock sits in the bracket; found by its
            # edges, or not on the outline, the board goes to the front-left
            # corner by the margin.
            sx, sy, sw, sh = w.stock
            on = (self.keep_placement
                  and b[0] >= sx - 1e-6 and b[1] >= sy - 1e-6
                  and b[2] <= sx + sw + 1e-6 and b[3] <= sy + sh + 1e-6)
            if on:
                ox, oy = b[0] - sx, b[1] - sy
            else:
                ox = oy = margin_mm
            w.action_place(st.place_x + pose.x + ox - b[0],
                           st.place_y + pose.y + oy - b[1])
            w.action_stock(pose.w, pose.h, pose.x, pose.y, show=True)
            w.set_stock_turn(ar.about(pose.x, pose.y, pose.angle))
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
    check_sig = Signal(str, float)
    level_sig = Signal(str, object, int, int)
    fit_sig = Signal(object, object, object)
    job_sig = Signal(str, str, str)

    def __init__(self):
        super().__init__()
        self.flipped = threading.Event()
        self.go_on = True
        self.checked = threading.Event()
        self.answer = ("stop", 0.0)

    def note(self, text):
        self.note_sig.emit(text)

    def step(self, key, state):
        self.step_sig.emit(key, state)

    def stock(self, pose):
        self.stock_sig.emit(pose)

    def level(self, side, rows, nx, ny):
        self.level_sig.emit(side, list(rows), nx, ny)

    def fit(self, nominal, measured, t):
        self.fit_sig.emit(list(nominal), list(measured), t)

    def job(self, key, label, program):
        self.job_sig.emit(key, label, program)

    def check(self, traces_label, deeper_mm):
        self.checked.clear()
        self.answer = ("stop", 0.0)
        self.check_sig.emit(traces_label, float(deeper_mm))
        self.checked.wait()
        return self.answer

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

        intro = widgets.hint(
            "Stock on the bed, probe clipped to its copper, size typed - "
            "then Start.")
        intro.setToolTip(
            "Start finds the stock, probes it and cuts the whole board with "
            "the one bit in the collet. The bed must not conduct (tape).")
        self.add(intro)

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
        self.where = QComboBox()
        self.where.addItem("In the corner bracket", "bracket")
        self.where.addItem("Anywhere - click it", "click")
        self.where.setToolTip(
            "In the bracket: push the stock into the corner bracket. Its "
            "outline is that corner and the size typed, so the run only "
            "touches the copper once for its height - any size of stock.\n"
            "Anywhere: click on the stock and the probe walks to its edges "
            "(slow, and every edge it crosses must be clear of clamps).")
        stock.add(self.where)
        self.datum_box = QWidget()
        dl = QVBoxLayout(self.datum_box)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(2)
        drow = QWidget()
        h = QHBoxLayout(drow)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(theme.GAP_S)
        dx, dy, dc = saved_datum()
        self.dx_spin, self.dy_spin = (self._spin(v, 0.0, 210.0, 2)
                                      for v in (dx, dy))
        self.corner_box = QComboBox()
        for c in CORNERS:
            self.corner_box.addItem(c, c)
        self.corner_box.setCurrentIndex(CORNERS.index(dc))
        h.addWidget(QLabel("Bracket X"))
        h.addWidget(self.dx_spin)
        h.addWidget(QLabel("Y"))
        h.addWidget(self.dy_spin)
        h.addStretch(1)
        dl.addWidget(drow)
        brow = QWidget()
        h = QHBoxLayout(brow)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(theme.GAP_S)
        h.addWidget(self.corner_box)
        self.datum_btn = widgets.button(
            "Set from the bit",
            tip="Jog the bit over the bracket's inside corner (where the "
                "stock's corner sits) and press this. Asks first; saved by "
                "the next Start.",
            on=self._datum_from_head)
        self.datum_back_btn = widgets.button(
            "Saved corner",
            tip="Put the bracket corner back to the one saved by the last "
                "run.", on=self._datum_back)
        h.addWidget(self.datum_btn)
        h.addWidget(self.datum_back_btn)
        h.addStretch(1)
        dl.addWidget(brow)
        stock.add(self.datum_box)
        self.pick_btn = widgets.button(
            "Click where it is",
            tip="Then click on the stage, anywhere on the stock. The probe "
                "goes there first and finds the edges from it. Click it "
                "again to cancel.")
        # A toggle, so it shows when the next click on the stage is for the
        # stock - and that click can be taken back by clicking it again.
        self.pick_btn.setCheckable(True)
        self.pick_btn.toggled.connect(self._arm_pick)
        stock.add(self.pick_btn)
        self.click_lbl = widgets.hint("No spot clicked yet.")
        stock.add(self.click_lbl)
        self.sim_lbl = widgets.hint("")
        stock.add(self.sim_lbl)
        self.add(stock)

        self.level_chk = QCheckBox("Probe the surface first (bed levelling)")
        self.level_chk.setChecked(True)
        self.level_chk.setToolTip(
            "A grid of touches over the board, so every cut follows the "
            "copper's real height. Off: Z zero is the copper at the clicked "
            "spot, and the board is assumed flat - quicker, fine for a small "
            "board on a flat bed.")
        stock.add(self.level_chk)
        self.check_chk = QCheckBox("Stop before the cut-out, so I can check "
                                   "the traces")
        self.check_chk.setChecked(True)
        self.check_chk.setToolTip(
            "After the traces the bit parks and the run waits. Look at the "
            "board: cut it out, or cut the traces again a little deeper on "
            "the same height map. Once it is cut free it cannot be re-cut "
            "where it lay.")
        stock.add(self.check_chk)
        srow = QWidget()
        h = QHBoxLayout(srow)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(theme.GAP_S)
        h.addWidget(QLabel("Start at"))
        self.start_box = QComboBox()
        self.start_box.setToolTip(
            "To finish a board that stopped part-way: the steps before this "
            "one are skipped. The stock must not have moved.")
        h.addWidget(self.start_box, 1)
        stock.add(srow)
        self.dry_chk = QCheckBox("Dry run: spindle off, every cut 5 mm "
                                 "above the copper")
        self.dry_chk.setToolTip(
            "Everything a real run does - finding the stock, probing, every "
            "job start to finish - with the bit kept in the air. For "
            "watching a new setup before it cuts.")
        stock.add(self.dry_chk)
        self.where.currentIndexChanged.connect(self._where_changed)
        self._where_changed()
        # The outline on the stage follows the size and the bracket as they
        # are typed, so what is drawn is where the run will think it is.
        for sp in (self.w_spin, self.h_spin, self.dx_spin, self.dy_spin):
            sp.valueChanged.connect(self._sync_outline)
        self.corner_box.currentIndexChanged.connect(self._sync_outline)
        self.where.currentIndexChanged.connect(self._sync_outline)

        run = widgets.Section("Run")
        self.offline_box = QWidget()
        h = QHBoxLayout(self.offline_box)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(theme.GAP_S)
        h.addWidget(widgets.hint("The machine is not connected."))
        self.connect_btn = widgets.button(
            "Connect", on=lambda: ctl.bar._toggle_connect())
        h.addWidget(self.connect_btn)
        h.addStretch(1)
        run.add(self.offline_box)
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
        # The check before the cut-out: shown only while the run waits.
        self.check_box = QWidget()
        cl = QVBoxLayout(self.check_box)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(theme.GAP_S)
        self.check_lbl = widgets.body("")
        cl.addWidget(self.check_lbl)
        # Re-cut where it came out shallow - rarely the whole board - the
        # way Rework does: boxes on the bed, the trace pass clipped to them.
        self._boxes = []
        def _row(*ws):
            r = QWidget()
            h = QHBoxLayout(r)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(theme.GAP_S)
            for w_ in ws:
                h.addWidget(w_)
            h.addStretch(1)
            cl.addWidget(r)
        self.box_btn = widgets.button(
            "Drag boxes over the shallow spots",
            tip="While this is lit, dragging on the bed draws a box. Only "
                "the traces inside the boxes are cut again.")
        self.box_btn.setCheckable(True)
        self.box_btn.toggled.connect(self._arm_boxes)
        self.clear_boxes_btn = widgets.button("Clear boxes",
                                              on=self._clear_boxes)
        _row(self.box_btn, self.clear_boxes_btn)
        self.again_btn = widgets.button(
            "Recut all traces", on=self._recut)
        self.deeper_spin = self._spin(0.05, 0.01, 0.5, 2)
        self.deeper_spin.setSuffix(" mm")
        self.deeper_spin.setToolTip("How much deeper than the last pass.")
        _row(self.again_btn, QLabel("deeper by"), self.deeper_spin)
        self.cut_btn = widgets.button(
            "Cut it out", kind="primary",
            on=lambda: self._answer("go", 0.0))
        self.stop_here_btn = widgets.button(
            "Stop here", on=lambda: self._answer("stop", 0.0))
        _row(self.cut_btn, self.stop_here_btn)
        self.check_box.setVisible(False)
        run.add(self.check_box)
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

        made = widgets.Section("What the run made")
        grid = QWidget()
        g = QGridLayout(grid)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(theme.GAP_S)
        made.add(grid)
        self.made_btns = {}
        for key, text, tip in (
                ("level", "Height map", "The probed surface: the table, the "
                 "heatmap on the stage and the 3D view, on the Level page."),
                ("fit", "Fiducial fit", "Where every fiducial was found after "
                 "the flip, and how well they agree."),
                ("sim3d", "Watch a step in 3D", "The selected step's toolpath, "
                 "played in the 3D view."),
                ("files", "The job files", "Every program the run sent to the "
                 "mill, exactly as sent, and the run log.")):
            b = widgets.button(text, tip=tip,
                               on=lambda _c=False, k=key: self._show(k))
            b.setEnabled(key == "sim3d")
            n = len(self.made_btns)
            self.made_btns[key] = b
            g.addWidget(b, n // 2, n % 2)
        self.add(made)
        self.finish()
        # Bound methods, so they queue onto this thread: the link emits these
        # from its worker, where a lambda would run and touch the widgets.
        ctl.link.linked.connect(self._sync_offline)
        ctl.link.unlinked.connect(self._sync_offline)
        self._sync_offline()

        self._sim_timer = QTimer(self)
        self._sim_timer.setInterval(120)
        self._sim_timer.timeout.connect(self._draw_sim)
        self.finished.connect(self._on_finished)

    @staticmethod
    def _spin(value, lo=10.0, hi=200.0, decimals=1):
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setDecimals(decimals)
        s.setValue(float(value))
        s.setKeyboardTracking(False)
        s.setFocusPolicy(Qt.StrongFocus)
        return s

    # -- where the stock is --------------------------------------------------
    def bracket(self):
        return self.where.currentData() == "bracket"

    def _sync_offline(self, *_):
        self.offline_box.setVisible(not self.ctl.link.is_connected()
                                    and self._thread is None)

    def sync_tier(self):
        """Novice: the stock is in the bracket, and a run is a real run."""
        from gerber2rml.gui2 import tier
        full = tier.is_full()
        self.where.setVisible(full)
        self.dry_chk.setVisible(full)
        if not full:
            self.where.setCurrentIndex(self.where.findData("bracket"))
            self.dry_chk.setChecked(False)

    def _where_changed(self, *_):
        on = self.bracket()
        self.datum_box.setVisible(on)
        self.pick_btn.setVisible(not on)
        self.click_lbl.setVisible(not on)
        if on:
            self.pick_btn.setChecked(False)

    def datum(self):
        return (self.dx_spin.value(), self.dy_spin.value(),
                self.corner_box.currentData())

    def _datum_from_head(self):
        pos = getattr(self.ctl, "_last_xyz", None)
        if not pos or not self.ctl.link.is_connected():
            self.ctl.say("warn", "Connect the machine and jog the bit over "
                                 "the bracket corner first.")
            return
        from gerber2rml.gui2 import dialogs
        x, y, c = self.datum()
        if not dialogs.confirm(
                self, "Move the bracket corner to the bit?",
                "The bit is at X %.2f, Y %.2f. The bracket corner (%s) is "
                "now X %.2f, Y %.2f.\n\nOnly do this with the bit right over "
                "the bracket's inside corner, where the stock's %s corner "
                "sits." % (pos[0], pos[1], c, x, y, c),
                "Use where the bit is"):
            return
        self.dx_spin.setValue(pos[0])
        self.dy_spin.setValue(pos[1])

    def _board_onto_outline(self):
        """Novice: what is on the screen is where it will be cut, so a board
        off the outline is brought onto it now, not surprisingly at Start. Pro
        decides for itself, and Start says so if it hangs off."""
        from gerber2rml.gui2 import tier
        ctl = self.ctl
        if tier.is_full() or ctl.state.board is None:
            return
        b = ctl.work_bounds()
        sx, sy, sw, sh = ctl.stock
        if (b[0] < sx or b[1] < sy or b[2] > sx + sw or b[3] > sy + sh):
            st = ctl.state
            ctl.action_place(st.place_x + sx + ar.PLACE_MARGIN_MM - b[0],
                             st.place_y + sy + ar.PLACE_MARGIN_MM - b[1])

    def _datum_back(self):
        x, y, c = saved_datum()
        self.dx_spin.setValue(x)
        self.dy_spin.setValue(y)
        self.corner_box.setCurrentIndex(CORNERS.index(c))

    def _sync_outline(self, *_):
        # Only while this page is the one open: it must not move the sheet
        # under someone working on another step.
        insp = getattr(self.ctl, "inspector", None)
        if insp is None or insp.stack.currentWidget() is not self:
            return
        w, h = self.w_spin.value(), self.h_spin.value()
        if self.bracket():
            x, y, c = self.datum()
            x0, y0 = datum_outline((x, y), c, (w, h))
            self.ctl.action_stock(w, h, x0, y0, show=True)
            self._board_onto_outline()
        else:
            self.ctl.action_stock(w, h, show=True)

    # -- the click ---------------------------------------------------------
    def _arm_pick(self, on):
        if on:
            self.pick_btn.setText("Now click on the stock…")
            self.ctl.set_stage_mode("stock")
            self.click_lbl.setText("Click anywhere on the stock, on the "
                                   "stage. Not near an edge.")
        else:
            self.pick_btn.setText("Click where it is")
            if self.ctl.stage.mode == "stock":
                self.ctl.set_stage_mode("place")
            if self._click is None:
                self.click_lbl.setText("No spot clicked yet.")

    def on_stock_click(self, x, y):
        self._click = (x, y)
        self.ctl.stage.set_target((x, y))
        self.pick_btn.setChecked(False)          # back to dragging the board
        self.click_lbl.setText("Starts looking at X %.1f, Y %.1f (the ring on "
                               "the stage). Click the button again to move "
                               "it." % (x, y))

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

    def _fill_start(self):
        keep = self.start_box.currentData()
        self.start_box.clear()
        self.start_box.addItem("The beginning", None)
        src = WindowSource(self.ctl, self._gui)
        for k, t in src.bottom_steps() + src.top_steps():
            self.start_box.addItem(t, k)
        i = self.start_box.findData(keep)
        self.start_box.setCurrentIndex(max(0, i))

    def _fill_rows(self):
        self._fill_start()
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
                "Simulator: the stock is %.0f × %.0f mm, about X %.0f, Y %.0f."
                % (m.w / 1000, m.h / 1000, cx, cy))
            if self._thread is None:
                # Its size is known here; the operator still has to click.
                self.w_spin.setValue(m.w / 1000.0)
                self.h_spin.setValue(m.h / 1000.0)
            self._sim_timer.start()
        else:
            self.sim_lbl.setText("")
        if self._thread is None:
            self._fill_rows()
        self._sync_outline()

    def hideEvent(self, e):
        super().hideEvent(e)
        if self.pick_btn.isChecked():
            self.pick_btn.setChecked(False)      # leaving the page disarms it

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
        datum = self.datum() if self.bracket() else None
        if datum is None and self._click is None:
            ctl.say("warn", "Click where the stock is first.")
            return
        from gerber2rml.gui2 import workspace
        if datum is not None:
            workspace.set_setting("autorun/datum", "%.3f,%.3f,%s" % datum)
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
        ev.check_sig.connect(self._on_check)
        ev.level_sig.connect(self._on_level)
        ev.fit_sig.connect(self._on_fit)
        ev.job_sig.connect(self._on_job)
        self._new_run_dir()
        src = WindowSource(ctl, self._gui)
        src.keep_placement = datum is not None
        self.start_btn.setEnabled(False)
        self._last_port = port
        self._measured = None
        click = self._click or (0.0, 0.0)
        bit = ctl.state.drill.bit_diameter
        level = self.level_chk.isChecked()
        dry = self.dry_chk.isChecked()
        check_cut = self.check_chk.isChecked()
        start_at = self.start_box.currentData()
        from gerber2rml.gui2 import workspace
        try:
            hint = float(workspace.setting("autorun/surface_z", "") or "x")
        except ValueError:
            hint = None

        def work():
            from gerber2rml.engine import spi_probe
            ser = None
            ok, msg = False, ""
            try:
                ser = spi_probe.open_link(port)
                run = ar.AutoRun(ser, printer, src, ev, click_mm=click,
                                 stock_mm=size, double=ctl._double,
                                 bit_mm=bit, should_abort=link.should_abort,
                                 should_pause=link.should_pause,
                                 level=level, surface_hint=hint,
                                 datum=datum, dry_run=dry,
                                 check_cut=check_cut, start_at=start_at)
                try:
                    ok = run.run()
                finally:
                    if run.pose is not None:
                        # The bed does not move: next time, drop straight
                        # to just above this instead of feeling down from
                        # the top.
                        workspace.set_setting("autorun/surface_z",
                                              "%.3f" % run.pose.z)
                msg = "The board is done."
            except Exception as e:
                msg = str(e) or e.__class__.__name__
                self._measured = getattr(e, "measured", None)
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
        self._log(text)

    # -- what the run made ---------------------------------------------------
    def _new_run_dir(self):
        import datetime
        from pathlib import Path
        from gerber2rml import platform as plat
        stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        self.run_dir = (Path(plat.documents_dir()) / "SRM-CAM" / "runs"
                        / ("%s_%s" % (self.ctl.state.name or "board", stamp)))
        try:
            self.run_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            self.run_dir = None
        self._jobs_sent = 0
        self.made_btns["files"].setEnabled(self.run_dir is not None)

    def _log(self, text):
        if getattr(self, "run_dir", None) is None:
            return
        import datetime
        try:
            with open(self.run_dir / "run.log", "a", encoding="utf-8") as f:
                f.write("%s  %s\n" % (datetime.datetime.now().strftime(
                    "%H:%M:%S"), text))
        except OSError:
            pass

    def _on_level(self, side, rows, nx, ny):
        self.ctl.level_page.adopt(side, rows, nx, ny)
        if getattr(self, "run_dir", None) is not None:
            try:
                with open(self.run_dir / ("height_map_%s.csv" % side), "w",
                          encoding="utf-8") as f:
                    f.write("# %d x %d grid; dz in mm from the first point\n"
                            "x_mm,y_mm,dz_mm\n" % (nx, ny))
                    for x, y, dz in rows:
                        f.write("%.3f,%.3f,%.4f\n" % (x, y, dz))
            except OSError:
                pass
        self.made_btns["level"].setEnabled(True)
        self._log("%s surface: %d points, %.3f mm from flat" % (
            side, len(rows), max(r[2] for r in rows) - min(r[2] for r in rows)))

    def _on_fit(self, nominal, measured, t):
        from gerber2rml.engine.fiducial import residuals
        self.ctl.set_top_fit(t, measured)
        self.made_btns["fit"].setEnabled(True)
        res = residuals(t, nominal, measured)
        for i, (m, r) in enumerate(zip(measured, res), 1):
            self._log("fiducial %d at %.3f, %.3f - off by %.3f mm"
                      % (i, m[0], m[1], r))

    def _on_job(self, key, label, rml):
        if getattr(self, "run_dir", None) is None:
            return
        from gerber2rml.naming import clean_name
        self._jobs_sent += 1
        name = "%02d_%s.nc" % (self._jobs_sent, clean_name(key))
        try:
            (self.run_dir / name).write_text(rml, encoding="ascii")
        except OSError:
            pass
        self._log("sent %s (%s)" % (name, label))

    def _show(self, what):
        ctl = self.ctl
        if what == "level":
            ctl.select_step("level")
        elif what == "fit" and ctl.plan.by_key("fitflip") is not None:
            ctl.select_step("fitflip")
        elif what == "sim3d":
            ctl.action_sim3d()
        elif what == "files" and getattr(self, "run_dir", None):
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.run_dir)))

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

    def _on_check(self, traces_label, deeper):
        self.check_lbl.setText(
            "%s done%s. Look at the board: is every trace through the "
            "copper? Then cut it out. If some are not, cut them again a "
            "little deeper - the stock has not moved, so they land in the "
            "same grooves." % (traces_label, "" if not deeper else
                               ", %.2f mm deeper" % deeper))
        self._boxes = []
        self._show_boxes()
        self.check_box.setVisible(True)
        self.ctl.say("warn", "Check the traces before the cut-out.")
        self._log("waiting: check the traces (%.2f mm deeper so far)" % deeper)

    # -- boxes over the shallow spots ----------------------------------------
    def _arm_boxes(self, on):
        self.ctl.set_stage_mode("box" if on else "place")

    def add_box(self, x0, y0, x1, y1):
        self._boxes.append((min(x0, x1), min(y0, y1),
                            max(x0, x1), max(y0, y1)))
        self._show_boxes()

    def _clear_boxes(self):
        self._boxes = []
        self._show_boxes()

    def _show_boxes(self):
        n = len(self._boxes)
        self.again_btn.setText("Recut the %d box%s" % (n, "" if n == 1
                                                       else "es")
                               if n else "Recut all traces")
        self.ctl.stage.set_regions(
            [b + (theme.CAUTION,) for b in self._boxes])

    def _recut(self):
        self._answer("again", self.deeper_spin.value(),
                     list(self._boxes) or None)

    def _answer(self, what, mm, boxes=None):
        self.check_box.setVisible(False)
        self.box_btn.setChecked(False)
        boxes_shown = bool(self._boxes)
        self._boxes = []
        if boxes_shown:
            # Give the stage back to Rework's own boxes.
            self.ctl.rework_page._push()
        if self._events is None:
            return
        self._log("check answered: %s %.2f%s" % (
            what, mm, "" if not boxes else " in boxes %s" % [
                tuple(round(v, 2) for v in b) for b in boxes]))
        self._events.answer = ((what, float(mm), boxes) if boxes
                               else (what, float(mm)))
        self._events.checked.set()

    def _on_finished(self, ok, msg):
        self._thread = None
        self.start_btn.setEnabled(True)
        self.flip_btn.setVisible(False)
        self.check_box.setVisible(False)
        if self.box_btn.isChecked():
            self.box_btn.setChecked(False)
        if self._events is not None:
            self._events.go_on = False
            self._events.flipped.set()
            self._events.answer = ("stop", 0.0)
            self._events.checked.set()
        self.status.setText(msg)
        if getattr(self, "_measured", None):
            self.w_spin.setValue(round(self._measured[0], 1))
            self.h_spin.setValue(round(self._measured[1], 1))
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
