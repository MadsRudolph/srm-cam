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
from gerber2rml.engine import bracket as br
from gerber2rml.engine.stockfind import CORNERS, datum_outline


def saved_bracket():
    """Where the corner bracket is screwed down, from the settings.

    Each machine saves its own. A corner saved by an older version as a
    measured X, Y is moved to the hole position nearest it; with nothing
    saved it is the DTU fixture's (br.DEFAULT)."""
    from gerber2rml.gui2 import workspace
    b = br.from_text(workspace.setting("autorun/bracket", ""))
    if b is None:
        try:
            x, y, c = (workspace.setting("autorun/datum", "") or "").split(",")
            if c in CORNERS:
                b = br.snap(float(x), float(y), c)
        except ValueError:
            pass
    return br.DEFAULT if b is None or b == br.OLD_DEFAULT else b
from gerber2rml.gui2 import theme, widgets, inspector

STATE_GLYPH = {"waiting": ("○", theme.TEXT_3),
               "running": ("●", theme.LIVE), "done": ("✓", theme.VERIFIED),
               "failed": ("✕", theme.DANGER),
               "skipped": ("–", theme.TEXT_3)}



def nogo_to_text(zones):
    """No-go zones as one settings string, in mm: ``x0,y0,x1,y1`` for a box,
    ``cx,cy,d`` for a clamp, joined by ``;``."""
    return ";".join(",".join("%.2f" % v for v in z) for z in zones)


def nogo_from_text(raw):
    """The reverse of :func:`nogo_to_text`. A string that does not parse
    gives no zones for that entry rather than a zone in the wrong place."""
    from gerber2rml.engine.nogo import normal
    zones = []
    for part in str(raw or "").split(";"):
        try:
            vals = tuple(float(v) for v in part.split(","))
        except ValueError:
            continue
        if len(vals) == 4 or (len(vals) in (3, 5) and vals[2] > 0):
            zones.append(normal(vals))
    return zones


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
        self.centre = False              # centre it on the stock found

    def copper_nets(self, side="bottom", fitted=True):
        """One face's copper where it is cut, and its nets, for the run's
        proof that what it leaves uncut joins nothing. The top is given
        through the measured flip, or as the layout has it (``fitted``
        False) for the check made before the flip."""
        def go():
            w = self.w
            b = w.state.board
            if side == "top":
                g = w._ds_layout().top_copper
                nets = w._nets_aligned(getattr(b, "copper_top_nets", None),
                                       b.copper_top, g)
                return (w._fit_geom(g) if fitted else g), nets
            if w._double:
                g = w._ds_layout().bottom_copper
                return g, w._nets_aligned(getattr(b, "copper_nets", None),
                                          b.copper, g)
            return b.copper, getattr(b, "copper_nets", None)
        return self.gui(go)

    def nominal_top(self, key):
        """A top-side job's toolpaths as the layout has them, with no
        measured flip applied - whatever fit an earlier run left behind."""
        def go():
            w = self.w
            keep = w._top_fit
            w._top_fit = None
            try:
                return w._toolpaths_for(w.plan.by_key(key))[0]
            finally:
                w._top_fit = keep
        return self.gui(go)

    def _plan_steps(self):
        steps = [s for s in self.w.plan.steps
                 if s.kind == "run" and s.op != "airpass"]
        if getattr(self.w, "_no_cutout", False):
            # The board stays in the sheet: there is no cut-out to run.
            steps = [s for s in steps if s.op != "cutout"]
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
            b = w.work_extent()
            st = w.state
            # Where the operator put the board on the stock outline is where
            # it is cut: keep its offset from the stock's corner. That outline
            # is real only when the stock sits in the bracket; found by its
            # edges, or not on the outline, the board goes to the front-left
            # corner by the margin. Centred, it goes in the middle of the
            # stock as FOUND - its measured size, before the turn - whatever
            # the outline said.
            sx, sy, sw, sh = w.stock
            # "On the outline" is asked of what has to be on it: a board
            # left in the sheet may hang off with its work on the copper
            # (window.work_reach), and is then kept where it was put, not
            # pulled back to the margin as one dropped beside the stock is.
            r = w.work_reach()
            on = (self.keep_placement
                  and r[0] >= sx - 1e-6 and r[1] >= sy - 1e-6
                  and r[2] <= sx + sw + 1e-6 and r[3] <= sy + sh + 1e-6)
            if self.centre:
                ox = (pose.w - (b[2] - b[0])) / 2.0
                oy = (pose.h - (b[3] - b[1])) / 2.0
            elif on:
                ox, oy = b[0] - sx, b[1] - sy
            else:
                ox = oy = margin_mm
            w.action_place(st.place_x + pose.x + ox - b[0],
                           st.place_y + pose.y + oy - b[1])
            w.action_stock(pose.w, pose.h, pose.x, pose.y, show=True)
            w.set_stock_turn(ar.about(pose.x, pose.y, pose.angle))
        self.gui(go)

    def _holes_again(self):
        """The board's holes, from the side it is on now. Turned over, that
        is where the fit says they came through: not the first side's frame."""
        w = self.w
        job = w.cutting_drill()
        if w._double and w._top_fit is not None:
            from gerber2rml.doublesided import reflect_holes
            from gerber2rml.engine.drill import drill_holes, drill_single_bit
            lay = w._ds_layout()
            holes = w._fit_holes(reflect_holes(lay.holes, lay.axis, lay.flip_pos))
            paths = (drill_single_bit(holes, job) if w.state.drill.single_bit
                     else drill_holes(holes, job))
        else:
            step = next(s for s in w.plan.steps if s.op == "drill")
            paths = w._toolpaths_for(step)[0]
        return paths, job.xy_feed, job.plunge_feed

    def toolpaths(self, key):
        def go():
            w = self.w
            if key == ar.HOLES_AGAIN:
                return self._holes_again()
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

    def extent(self, side):
        def go():
            w = self.w
            if side == "top" and w._double and w._registration == "fiducial":
                from gerber2rml.doublesided import nominal_top_fiducials
                lay = w._ds_layout()
                x0, y0, x1, y1 = lay.top_outline.bounds
                pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
                pts += [tuple(p[:2]) for p in nominal_top_fiducials(lay)]
                xs, ys = zip(*[w._top_fit.apply(x, y) for x, y in pts])
                r = w._fid_diameter / 2.0
                return min(xs) - r, min(ys) - r, max(xs) + r, max(ys) + r
            return w.work_extent()
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

    def nogo(self):
        # Read on the GUI thread when Continue was pressed (_flipped); the
        # run only picks the list up here.
        return getattr(self, "nogo_now", None)


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
            "Stock in the bracket, under its probe tongue, size typed - "
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
        # The bracket is drawn on the bed as the part it is, and dragged
        # there hole to hole; no coordinates to type. Its corner is what the
        # run measures the stock from.
        self._bracket = saved_bracket()
        self.datum_box = QWidget()
        dl = QVBoxLayout(self.datum_box)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(2)
        brow = QWidget()
        h = QHBoxLayout(brow)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(theme.GAP_S)
        self.corner_box = QComboBox()
        for c in CORNERS:
            self.corner_box.addItem(c, c)
        self.corner_box.setCurrentIndex(CORNERS.index(self._bracket.corner))
        self.corner_box.setToolTip(
            "Which corner of the stock the bracket holds.")
        h.addWidget(self.corner_box)
        self.datum_btn = widgets.button(
            "Find it with the bit",
            tip="Jog the bit over the bracket's inside corner (where the "
                "stock's corner sits) and press this: the bracket moves to "
                "the holes nearest. Asks first.",
            on=self._datum_from_head)
        h.addWidget(self.datum_btn)
        h.addStretch(1)
        dl.addWidget(brow)
        self.bracket_lbl = widgets.hint(
            "Drag the bracket on the bed to the holes it is screwed into.")
        dl.addWidget(self.bracket_lbl)
        # The board goes into the bracket's corner by itself, snaps back
        # into it when dragged near, and this puts it back there.
        self.reset_btn = widgets.button(
            "Reset position",
            tip="Put the board back in the bracket's corner of the stock, "
                "%g mm in from its edges and clear of the probe tongue."
                % ar.PLACE_MARGIN_MM,
            on=self.reset_position)
        rrow = QWidget()
        rh = QHBoxLayout(rrow)
        rh.setContentsMargins(0, 0, 0, 0)
        rh.addWidget(self.reset_btn)
        rh.addStretch(1)
        dl.addWidget(rrow)
        stock.add(self.datum_box)
        # True until the board is put somewhere by hand: a board just loaded
        # goes into the corner when this page opens.
        self._auto_place = True
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

        from gerber2rml.gui2 import workspace
        self.centre_chk = QCheckBox("Centre the board on the copper")
        self.centre_chk.setChecked(str(workspace.setting(
            "autorun/centre", "false")).lower() in ("true", "1"))
        self.centre_chk.setToolTip(
            "The run puts the board in the middle of the stock it finds, "
            "with the spare copper shared equally on every side. Off: in "
            "the bracket the board is cut where it is on the outline; found "
            "by its edges it goes %g mm in from the front-left corner."
            % ar.PLACE_MARGIN_MM)
        self.centre_chk.toggled.connect(self._centre_changed)
        stock.add(self.centre_chk)

        self.nocut_chk = QCheckBox("Leave the board in the sheet (no "
                                   "cut-out)")
        self.nocut_chk.setToolTip(
            "For a board about as big as the sheet. Nothing is cut round "
            "its outline, so it needs no room for that: it is put against "
            "the two edges away from the bracket and may reach right up to "
            "the bracket, even under its probe tongue. Any isolation that "
            "would be under the tongue is left uncut and the bit goes round "
            "it - but the run first works out that this joins no nets, and "
            "does not start if it would. A hole under the tongue stops it "
            "too.\n"
            "A double-sided board is centred across the sheet, and its top "
            "is checked the same way before anything is cut, laid where the "
            "flip will put it. A reference hole that lands under the bracket "
            "then is not used; three have to be reachable.")
        self.nocut_chk.toggled.connect(self._nocut_changed)
        stock.add(self.nocut_chk)

        # Where a double-sided board's reference holes go. Three ways, the
        # same three as on Your board in Pro; here because a sheet barely
        # bigger than the board is discovered on this page.
        self.ref_row = QWidget()
        rr = QHBoxLayout(self.ref_row)
        rr.setContentsMargins(0, 0, 0, 0)
        rr.setSpacing(theme.GAP_S)
        rr.addWidget(QLabel("Reference holes"))
        self.ref_box = QComboBox()
        self.ref_box.addItem("In the waste, outside the board", "waste")
        self.ref_box.addItem("Inside the board's corners", "onboard")
        self.ref_box.addItem("The board's own mounting holes", "mounting")
        self.ref_box.setToolTip(
            "A double-sided board is found again after the flip by small "
            "reference holes the probe drops into.\n"
            "In the waste: %g mm outside the corners - a clean board, but "
            "the sheet must be that much bigger all round.\n"
            "Inside the corners: the same distance inside, and they stay in "
            "the finished board - for a sheet barely bigger than the board.\n"
            "The board's own mounting holes: nothing extra is drilled. Needs "
            "at least two holes of one size, wide enough for the bit, at "
            "opposite ends of the board." % ctl._fid_offset)
        self.ref_box.currentIndexChanged.connect(self._ref_holes_changed)
        rr.addWidget(self.ref_box, 1)
        stock.add(self.ref_row)

        self.level_chk = QCheckBox("Probe the surface first (bed levelling)")
        self.level_chk.setChecked(True)
        self.level_chk.setToolTip(
            "A grid of touches over the board, so every cut follows the "
            "copper's real height. Off: Z zero is the copper at the clicked "
            "spot, and the board is assumed flat - quicker, fine for a small "
            "board on a flat bed.")
        stock.add(self.level_chk)
        # How far in from the board's edge the surface is touched. Its own
        # setting because the right answer depends on how the stock is held:
        # 2 mm with tape, more with clamps on the edge of a board as big as
        # its sheet. Kept with this PC.
        mrow = QWidget()
        mh = QHBoxLayout(mrow)
        mh.setContentsMargins(0, 0, 0, 0)
        mh.setSpacing(theme.GAP_S)
        mh.addSpacing(theme.GAP_L)          # under the tick it belongs to
        mh.addWidget(QLabel("Levelling: touches this far in from the edge"))
        try:
            saved = float(workspace.setting("autorun/level_margin", "") or 2.0)
        except ValueError:
            saved = 2.0
        self.level_margin_spin = self._spin(saved, lo=0.5, hi=40.0)
        self.level_margin_spin.setSuffix(" mm")
        self.level_margin_spin.setToolTip(
            "The surface is touched on a 4 x 3 grid over the board. This is "
            "how far its outer touches are kept from the board's edge. "
            "Raise it to keep the probe away from clamps on the edge; the "
            "height map carries its outer rows out to the edge. A no-go "
            "zone is still the way to say where a clamp IS.")
        self.level_margin_spin.valueChanged.connect(self._margin_changed)
        mh.addWidget(self.level_margin_spin)
        mh.addStretch(1)
        stock.add(mrow)
        self.level_chk.toggled.connect(mrow.setEnabled)
        self.level_chk.toggled.connect(lambda _on: self._show_touches())
        self._points_before = None
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

        # What holds the stock down. The bracket is drawn because the app
        # knows its shape; a clamp is known only if somebody says where it
        # is. Not kept between sessions: the clamps come off with every
        # board, and yesterday's marks on the bed would be wrong today
        # (Mads, 2026-11-15). The old saved setting is cleared once.
        self._nogo = []
        if workspace.setting("autorun/nogo", ""):
            workspace.set_setting("autorun/nogo", "")
        nrow = QWidget()
        nh = QHBoxLayout(nrow)
        nh.setContentsMargins(0, 0, 0, 0)
        nh.setSpacing(theme.GAP_S)
        self.nogo_btn = widgets.button(
            "Mark a clamp (no-go zone)",
            tip="While this is lit, click the bed hole a clamp is screwed "
                "into: the lab's printed cam clamp (26 mm, its screw 5.5 mm "
                "off centre) is put there, turned clockwise onto the stock's "
                "edge - the way tightening the thumbscrew presses it on - "
                "with its 2 mm lip over the copper. Drag instead to draw a "
                "box round anything else that stands above the copper. "
                "The bit stays out of both: no surface touch in one, no "
                "cut or move through one, and a move that would cross one "
                "is led round it. It keeps 1 mm from a clamp and 2 mm from "
                "a box.")
        self.nogo_btn.setCheckable(True)
        self.nogo_btn.toggled.connect(self._arm_nogo)
        self.nogo_clear_btn = widgets.button("Clear zones",
                                             on=self._clear_nogo)
        nh.addWidget(self.nogo_btn)
        nh.addWidget(self.nogo_clear_btn)
        nh.addStretch(1)
        stock.add(nrow)
        self.nogo_lbl = widgets.hint("")
        stock.add(self.nogo_lbl)
        self._show_nogo()
        self.where.currentIndexChanged.connect(self._where_changed)
        self._where_changed()
        # The outline on the stage follows the size and the bracket as they
        # are typed, so what is drawn is where the run will think it is.
        for sp in (self.w_spin, self.h_spin):
            sp.valueChanged.connect(self._sync_outline)
        self.corner_box.currentIndexChanged.connect(self._corner_changed)
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
        self.holes_btn = widgets.button(
            "Drill the holes again", on=self._holes,
            tip="If the holes did not come through: every board hole again from "
                "the side facing up now, this much deeper than before.")
        self.holes_spin = self._spin(0.3, 0.05, 1.0, 2)
        self.holes_spin.setSuffix(" mm")
        self.holes_spin.setToolTip("How much deeper than the drill job's depth.")
        _row(self.holes_btn, QLabel("deeper by"), self.holes_spin)
        self.cut_btn = widgets.button(
            "Cut it out", kind="primary",
            on=lambda: self._answer("go", 0.0))
        self.stop_here_btn = widgets.button(
            "Stop here", on=lambda: self._answer("stop", 0.0))
        _row(self.cut_btn, self.stop_here_btn)
        self.check_box.setVisible(False)
        run.add(self.check_box)
        # How far, and how long still: a bar, the step in hand, the time
        # left and the time of day it should be done. The checklist below
        # says what is finished; this says when the rest will be.
        from PySide6.QtWidgets import QProgressBar
        self.progress = QProgressBar()
        self.progress.setObjectName("runProgress")
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        self.progress.setVisible(False)
        run.add(self.progress)
        self.progress_lbl = widgets.body("")
        self.progress_lbl.setVisible(False)
        run.add(self.progress_lbl)
        self._clock = None
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._tick)
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
        # The bracket is on every step in Novice and only here in Pro.
        if getattr(self.ctl, "inspector", None) is not None:
            if self._everywhere():
                self._sync_outline()
            elif not self._on_this_page():
                self._draw_bracket(False)

    def _where_changed(self, *_):
        on = self.bracket()
        self.datum_box.setVisible(on)
        self.pick_btn.setVisible(not on)
        self.click_lbl.setVisible(not on)
        if on:
            self.pick_btn.setChecked(False)

    def datum(self):
        """(x, y, corner): the bracket's inside corner, machine mm."""
        x, y = self._bracket.inside_corner()
        return x, y, self._bracket.corner

    def _bed(self):
        from gerber2rml.backends import BACKENDS
        return BACKENDS[self.ctl.state.machine].bed

    def set_bracket(self, b):
        """Put the bracket in hole position ``b``: saved at once - it is a
        fact about the machine, not about this job - and drawn."""
        from gerber2rml.gui2 import workspace
        self._bracket = b
        workspace.set_setting("autorun/bracket", br.to_text(b))
        if self.corner_box.currentData() != b.corner:
            self.corner_box.blockSignals(True)
            self.corner_box.setCurrentIndex(CORNERS.index(b.corner))
            self.corner_box.blockSignals(False)
        self._sync_outline()

    def _snap_view(self, corner):
        """For the stage: where a drag would put it, as it would be drawn."""
        bed = self._bed()

        def snap(x, y):
            b = br.snap(x, y, corner, bed=bed)
            if b is None:
                return None
            return b.outline(), b.screw_points(), b.inside_corner()
        return snap

    def on_bracket_moved(self, x, y):
        b = br.snap(x, y, self._bracket.corner, bed=self._bed())
        if b is not None:
            self.set_bracket(b)

    def _corner_changed(self, *_):
        """The same bracket, holding another corner: it is turned to suit
        and put in the holes nearest where its corner was."""
        c = self.corner_box.currentData()
        if c == self._bracket.corner:
            return
        x, y = self._bracket.inside_corner()
        self.set_bracket(br.snap(x, y, c, bed=self._bed()) or self._bracket)

    def _draw_bracket(self, on):
        stage = getattr(self.ctl, "stage", None)
        if stage is None:
            return
        if hasattr(stage, "set_place_snap"):
            stage.set_place_snap(self._place_snap if on else None)
        if not on:
            stage.set_bracket(None)
            return
        b = self._bracket
        # Dragged to other holes only from this page; elsewhere it is the
        # picture of where the stock goes, and stays put.
        stage.set_bracket(b.outline(), b.screw_points(), b.inside_corner(),
                          self._snap_view(b.corner) if self._on_this_page()
                          else None)

    def _datum_from_head(self):
        pos = getattr(self.ctl, "_last_xyz", None)
        if not pos or not self.ctl.link.is_connected():
            self.ctl.say("warn", "Connect the machine and jog the bit over "
                                 "the bracket corner first.")
            return
        from gerber2rml.gui2 import dialogs
        b = br.snap(pos[0], pos[1], self._bracket.corner, bed=self._bed())
        if b is None:
            self.ctl.say("warn", "The bracket cannot be screwed down with "
                                 "its corner there.")
            return
        if not dialogs.confirm(
                self, "Move the bracket to the bit?",
                "The bit is at X %.2f, Y %.2f. The bracket goes to the holes "
                "that put its inside corner nearest there.\n\nOnly do this "
                "with the bit right over the bracket's inside corner, where "
                "the stock's %s corner sits." % (pos[0], pos[1], b.corner),
                "Move it there"):
            return
        self.set_bracket(b)

    def _centre_changed(self, on):
        from gerber2rml.gui2 import workspace
        workspace.set_setting("autorun/centre", bool(on))
        self._sync_outline()

    def show_size(self, w, h):
        """A setup was loaded: its sheet, without moving anything. These boxes
        are what Start uses and what the outline is drawn from."""
        for spin, v in ((self.w_spin, w), (self.h_spin, h)):
            spin.blockSignals(True)
            spin.setValue(v)
            spin.blockSignals(False)

    def board_loaded(self):
        """A new board: it goes into the corner when this page next opens."""
        self._auto_place = True

    def board_opened(self):
        """The operator opened a board - from KiCad, the dialog, the demo.
        In Novice the stock IS in the bracket, so the sheet and the L are
        what the board was opened onto: drawn, and the board put in the
        corner, at once and on every step. (Not from ``load_folder`` itself:
        a programmatic load leaves the placement it was given, which is what
        keeps the two tiers' exports the same.)"""
        self._sync_outline()

    def _everywhere(self):
        """Is the bracket part of the picture on every step? In Novice, where
        there is no other way to hold the stock, once there is a board."""
        from gerber2rml.gui2 import tier
        return (not tier.is_full() and self.bracket()
                and getattr(self.ctl.state, "board", None) is not None)

    def _on_this_page(self):
        insp = getattr(self.ctl, "inspector", None)
        return insp is not None and insp.stack.currentWidget() is self

    def board_placed(self):
        """A placement restored from a setup is meant: leave it."""
        self._auto_place = False

    def no_cutout(self):
        """Is the board left in the sheet? Only with the stock in the
        bracket: that is what its checks are made against."""
        return bool(getattr(self.ctl, "_no_cutout", False)) and self.bracket()

    def _nocut_changed(self, on):
        ctl = self.ctl
        if bool(getattr(ctl, "_no_cutout", False)) == bool(on):
            return
        ctl.set_no_cutout(bool(on))
        self._sync_nocut()
        if self._thread is None:
            self._fill_rows()
        if self.bracket() and not self.centre_chk.isChecked():
            self._auto_place = True
            self.place_in_corner()

    def _sync_nocut(self):
        ctl = self.ctl
        self.nocut_chk.setVisible(self.bracket())
        self.nocut_chk.blockSignals(True)
        self.nocut_chk.setChecked(bool(getattr(ctl, "_no_cutout", False)))
        self.nocut_chk.blockSignals(False)
        # Nothing to stop before when nothing is cut out.
        self.check_chk.setEnabled(not self.no_cutout())

    def _corner_args(self):
        """What :func:`bracket.corner_place` needs, or None without a board."""
        ctl = self.ctl
        if ctl.state.board is None or ctl.work_extent() is None:
            return None
        bit = ctl.state.drill.bit_diameter
        return dict(corner=self._bracket.corner, stock=tuple(ctl.stock),
                    keepout=self._bracket.keepout(), bit_mm=bit,
                    margin_mm=ar.PLACE_MARGIN_MM)

    def place_in_corner(self, say=False):
        """Put the board in the bracket's corner of the outline. Says when the
        stock typed is too small for it to sit there whole."""
        args = self._corner_args()
        if args is None:
            return
        ctl, st = self.ctl, self.ctl.state
        b = ctl.work_extent()
        if self.no_cutout():
            # Not cut out: against the edges AWAY from the bracket, and it
            # needs no more sheet than its own size.
            nx, ny = br.far_place(args["corner"], args["stock"], b,
                                  flipped=bool(ctl._double))
            need = (b[2] - b[0], b[3] - b[1])
        else:
            nx, ny = br.corner_place(extent=b, **args)
            need = br.stock_needed(extent=b, **args)
        if abs(nx - b[0]) > 1e-6 or abs(ny - b[1]) > 1e-6:
            ctl.action_place(st.place_x + nx - b[0], st.place_y + ny - b[1])
        _sx, _sy, sw, sh = args["stock"]
        short = need[0] > sw + 1e-6 or need[1] > sh + 1e-6
        # Said once per sheet and board, not on every digit typed.
        key = (round(sw, 1), round(sh, 1), round(need[0], 1),
               round(need[1], 1))
        if short and (say or key != getattr(self, "_short_said", None)):
            self._short_said = key
            # What the board itself may measure: the sheet less what the
            # margins, the tongue and any outside reference holes take.
            o = ctl.work_bounds() or b
            max_w = sw - (need[0] - (o[2] - o[0]))
            max_h = sh - (need[1] - (o[3] - o[1]))
            more = ""
            if self.no_cutout():
                ctl.say("warn", "The board is %.1f × %.1f mm and the sheet "
                                "%.0f × %.0f mm: it does not fit on it."
                                % (need[0], need[1], sw, sh))
                return
            more = (" Or leave the board in the sheet (below): with no "
                    "cut-out it needs no room round it.")
            if (ctl._double and ctl._registration == "fiducial"
                    and ctl._fid_placement == "waste"):
                more += (" Reference holes inside the corners, or the "
                         "board's own mounting holes (below), need less "
                         "room; a single-sided board needs none.")
            ctl.say("warn", "The board does not fit in the corner of a "
                            "%.0f × %.0f mm sheet clear of the probe tongue: "
                            "it needs at least %.1f × %.1f mm. In KiCad, make "
                            "the outline at most %.1f × %.1f mm.%s"
                            % (sw, sh, need[0], need[1], max_w, max_h, more))
        elif not short and say:
            ctl.say("ok", "The board is back in the bracket's corner.")

    def reset_position(self):
        """The button: back into the corner, and kept there."""
        if self.centre_chk.isChecked():
            self.centre_chk.blockSignals(True)
            self.centre_chk.setChecked(False)
            self.centre_chk.blockSignals(False)
            from gerber2rml.gui2 import workspace
            workspace.set_setting("autorun/centre", False)
        self._auto_place = True
        self.place_in_corner(say=True)

    def _ref_holes_changed(self, *_):
        ctl = self.ctl
        want = self.ref_box.currentData()
        if want is None or ctl.reference_holes() == want:
            return
        ctl.action_fiducial_layout(ctl._fid_count, want, ctl._fid_offset)
        ctl.inspector.setup.sync()
        self._sync_ref_holes()                   # back, if it was refused
        if self.bracket() and not self.centre_chk.isChecked():
            self.place_in_corner()

    def _sync_ref_holes(self):
        ctl = self.ctl
        self.ref_row.setVisible(bool(ctl._double)
                                and ctl._registration == "fiducial")
        i = self.ref_box.findData(ctl.reference_holes())
        self.ref_box.blockSignals(True)
        # Hand-placed pins (Pro) are none of the three: shown as they are,
        # and not changed from here.
        self.ref_box.setEnabled(i >= 0)
        if i >= 0:
            self.ref_box.setCurrentIndex(i)
        self.ref_box.blockSignals(False)

    def _place_snap(self, dx, dy):
        """For the stage: a drag of the board, pulled into the corner on
        each axis it comes near."""
        args = self._corner_args()
        if args is None or self.centre_chk.isChecked():
            return dx, dy
        b = self.ctl.work_extent()
        if self.no_cutout():
            nx, ny = br.far_place(args["corner"], args["stock"], b,
                                  flipped=bool(self.ctl._double))
            if abs(b[0] + dx - nx) <= br.SNAP_MM:
                dx = nx - b[0]
            if abs(b[1] + dy - ny) <= br.SNAP_MM:
                dy = ny - b[1]
            return dx, dy
        return br.snap_offset(extent=b, dx=dx, dy=dy, **args)

    def board_dragged(self):
        """The operator put the board somewhere by hand. "Centre" would move
        it away again at Start, so it goes off, and says so."""
        self._auto_place = False
        if self.centre_chk.isChecked():
            self.centre_chk.setChecked(False)
            self.ctl.say("info", "Centring is off: the board stays where you "
                                 "dragged it.")

    def _board_onto_outline(self):
        """Novice: what is on the screen is where it will be cut, so a board
        off the outline is brought onto it now, not surprisingly at Start. Pro
        decides for itself, and Start says so if it hangs off.

        Centring is what is on the screen in both: the board goes to the
        middle of the outline as it is typed, and the run centres it again on
        the stock it finds."""
        from gerber2rml.gui2 import tier
        ctl = self.ctl
        if ctl.state.board is None:
            return
        b = ctl.work_extent()
        sx, sy, sw, sh = ctl.stock
        st = ctl.state
        if self.centre_chk.isChecked():
            ctl.action_place(st.place_x + sx + (sw - (b[2] - b[0])) / 2 - b[0],
                             st.place_y + sy + (sh - (b[3] - b[1])) / 2 - b[1])
            return
        if tier.is_full():
            return
        off = b[0] < sx or b[1] < sy or b[2] > sx + sw or b[3] > sy + sh
        if self.bracket():
            # In the bracket the board belongs in its corner: a new board
            # goes there, and so does one that has been dragged off.
            if self._auto_place or off:
                self.place_in_corner()
            return
        if off:
            ctl.action_place(st.place_x + sx + ar.PLACE_MARGIN_MM - b[0],
                             st.place_y + sy + ar.PLACE_MARGIN_MM - b[1])

    def _sync_outline(self, *_):
        # Only while this page is the one open: it must not move the sheet
        # under someone working on another step. Novice is the exception -
        # its stock is always in the bracket, so the sheet is there, and the
        # board on it, from the moment a board is loaded.
        if getattr(self.ctl, "inspector", None) is None:
            return
        if not self._on_this_page() and not self._everywhere():
            return
        w, h = self.w_spin.value(), self.h_spin.value()
        self._sync_ref_holes()
        self._sync_nocut()
        self._draw_bracket(self.bracket())
        if self.bracket():
            x, y, c = self.datum()
            x0, y0 = datum_outline((x, y), c, (w, h))
            self.ctl.action_stock(w, h, x0, y0, show=True)
            self._board_onto_outline()
        else:
            self.ctl.action_stock(w, h, show=True)
            if self.centre_chk.isChecked():
                self._board_onto_outline()

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
        for k, t in src.bottom_steps():
            self.start_box.addItem(t, k)
        top = src.top_steps()
        if top:
            self.start_box.addItem("Find the fiducials (already flipped)",
                                   ar.START_AT_FIDUCIALS)
        for k, t in top:
            self.start_box.addItem(t, k)
        self.start_box.addItem("Check the board (traces are cut)",
                               ar.START_AT_CHECK)
        i = self.start_box.findData(keep)
        self.start_box.setCurrentIndex(max(0, i))

    def _fill_rows(self):
        self._fill_start()
        while self.list_lay.count():
            item = self.list_lay.takeAt(0)
            if item.widget():
                # setParent(None) too: out of the layout is not off the screen,
                # and a stale row draws under the new one until it is deleted.
                item.widget().setParent(None)
                item.widget().deleteLater()
        self._rows = {}
        for key, title in self._plan_rows():
            lab = QLabel()
            lab.setTextFormat(Qt.RichText)
            self._rows[key] = (lab, title)
            self._set_row(key, "waiting")
            self.list_lay.addWidget(lab)

    # -- how far, and how long still ---------------------------------------
    def _estimates(self, src):
        """``[(key, label, seconds)]`` for the run about to start.

        The cutting steps from their own toolpaths at the planned feeds,
        with a fifth added and twenty seconds each for getting there and
        back (the frame check, the lift, the spin-up). The rest are what
        they took on the lab mill: a touch is about twelve seconds, a stock
        found in the bracket one touch from the top. They only have to be
        roughly right - the clock corrects itself from the first step that
        finishes (runclock.py)."""
        from gerber2rml.engine.estimate import estimate_toolpaths_seconds
        fixed = {"stock": 45.0, "stock_top": 45.0, "fiducials": 120.0,
                 "flip": 0.0,
                 "level": 150.0 if self.level_chk.isChecked() else 2.0,
                 "level_top": 150.0 if self.level_chk.isChecked() else 2.0}
        out = []
        for key, label in self._plan_rows():
            if key in fixed:
                out.append((key, label, fixed[key]))
                continue
            try:
                paths, xy, plunge = src.toolpaths(key)
                s = estimate_toolpaths_seconds(paths, xy, plunge) * 1.2 + 20.0
            except Exception:           # noqa: BLE001 - the top before a fit
                s = 300.0
            out.append((key, label, s))
        return out

    def _tick(self):
        """Once a second while a run is going: the bar, the line under it,
        and the same line on the machine bar."""
        if self._clock is None:
            return
        from datetime import datetime, timedelta
        from gerber2rml.engine.estimate import format_duration
        s = self._clock.snapshot()
        self.progress.setValue(int(round(s["fraction"] * 1000)))
        pct = int(s["fraction"] * 100)
        where = ("Step %d of %d · %s" % (s["index"], s["count"], s["label"])
                 if s["index"] else "Starting")
        if s["waiting"]:
            line = "%s · %d%% · waiting for you - the clock is stopped" % (
                where, pct)
            short = "%d%% · waiting for you" % pct
        else:
            left = format_duration(s["left_s"])
            at = (datetime.now() + timedelta(seconds=s["left_s"])).strftime(
                "%H:%M")
            more = "at least " if s["over"] else "about "
            line = "%s · %d%% · %s%s left · done %s%s · %s so far" % (
                where, pct, more, left, "after " if s["over"] else "about ",
                at, format_duration(s["elapsed_s"]))
            short = "%s · %d%% · %s%s left · done ~%s" % (
                where, pct, more, left, at)
        self.progress_lbl.setText(line)
        bar = getattr(self.ctl, "bar", None)
        if bar is not None and hasattr(bar, "set_run_progress"):
            bar.set_run_progress(short)

    def _clock_wait(self, on):
        if self._clock is not None:
            self._clock.wait(on)
            self._tick()

    def _set_row(self, key, state):
        if self._clock is not None:
            self._clock.step(key, state)
            self._tick()
        if key == "stock_top" and state == "running":
            self.ctl.show_auto_face(True)
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
        # The margin is shared with the Level page: take what it left.
        from gerber2rml.gui2 import workspace
        try:
            m = float(workspace.setting("autorun/level_margin", "") or 2.0)
        except ValueError:
            m = 2.0
        if abs(m - self.level_margin_spin.value()) > 1e-6:
            self.level_margin_spin.blockSignals(True)
            self.level_margin_spin.setValue(m)
            self.level_margin_spin.blockSignals(False)
        # The bed's probe points are another page's while it is open (the
        # Level page's grid, the reference holes). Borrowed here, given back
        # on the way out.
        self._points_before = list(self.ctl.stage._probe)
        self._show_touches()
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
        if self._points_before is not None:
            self.ctl.stage.set_probe_points(self._points_before)
            self._points_before = None
        # The stack still has this page as current while it hides: redraw
        # once the next one is up, so the bracket stays (Novice) but can no
        # longer be dragged, or goes (Pro).
        QTimer.singleShot(0, lambda: self._draw_bracket(self._everywhere()))
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
        sim = simmachine.is_sim(port)
        if sim:
            printer = simmachine.printer()
        else:
            from gerber2rml.engine import rmlspool
            if rmlspool.MACOS:
                from gerber2rml.gui2 import macmill
                name = macmill.find_or_setup(self.window())
            else:
                name = rmlspool.find_mill()
            if name is None:
                ctl.say("fail", "The Roland SRM-20 printer is not installed on "
                                "this PC, so there is nothing to send jobs to."
                        + (" " + rmlspool.CUPS_SETUP_HINT
                           if rmlspool.MACOS else ""))
                return
            printer = rmlspool.SpoolPrinter(name)
            if rmlspool.MACOS and not macmill.preflight(self.window(),
                                                        printer):
                return
            if rmlspool.MACOS:
                # The mill's own settings, which used to need VPanel on a
                # Windows PC: the command set is put right and said in the
                # log; a run that would stop at the frame check asks first.
                from gerber2rml.gui2 import millsettings
                if not millsettings.preflight(self.window(), say=ctl.say):
                    return
        if ctl._double:
            # Fiducials are the alignment, flipped left to right, and wide
            # enough for the probe bit to drop into.
            ctl._registration = "fiducial"
            ctl._fid_flip = "vertical"
            if not ctl._fid_mounting:      # those have the size they have
                ctl._fid_diameter = round(ctl.state.drill.bit_diameter + 0.8,
                                          2)
            ctl.refresh_plan()
        ctl.show_auto_face(False)
        size = (self.w_spin.value(), self.h_spin.value())
        ctl.action_stock(size[0], size[1])
        self._fill_rows()
        link = ctl.link
        link.mark_external(True)
        link.disconnect_from("handing the port to the run")
        ctl.bar.set_held_by_run(True)
        link.clear_abort()
        from gerber2rml.gui2.runclock import RunClock
        self._clock = RunClock(self._estimates(WindowSource(ctl, self._gui)))
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.progress_lbl.setVisible(True)
        self._clock_timer.start()
        self._tick()
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
        # In the run's folder with its programs: Novice has no export to carry
        # it, and a file that did not get made must not stop the run. The
        # setup page keeps what it has to say.
        if ctl._solder_mask and self.run_dir is not None:
            paths, notes = ctl.write_mask_to(self.run_dir)
            for p in paths:
                self._log(f"Solder mask file: {p.name}")
            for n in notes:
                self._log(f"Solder mask: {n}")
        if ctl._silkscreen and self.run_dir is not None:
            paths, notes = ctl.write_silk_to(self.run_dir)
            for p in paths:
                self._log(f"Silkscreen file: {p.name}")
            for n in notes:
                self._log(f"Silkscreen: {n}")
        src = WindowSource(ctl, self._gui)
        src.keep_placement = datum is not None
        src.centre = self.centre_chk.isChecked()
        self.start_btn.setEnabled(False)
        self._last_port = port
        self._measured = None
        click = self._click or (0.0, 0.0)
        bit = ctl.state.drill.bit_diameter
        level = self.level_chk.isChecked()
        dry = self.dry_chk.isChecked()
        check_cut = self.check_chk.isChecked()
        no_cut = self.no_cutout() and datum is not None
        start_at = self.start_box.currentData()
        nogo = self.nogo()
        level_margin = self.level_margin_spin.value()
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
                                 keepout=(self._bracket.keepout()
                                          if datum is not None else None),
                                 arms=(self._bracket.arms()
                                       if datum is not None else None),
                                 leave_under=no_cut,
                                 margin_mm=(0.0 if no_cut
                                            else ar.PLACE_MARGIN_MM),
                                 check_cut=check_cut and not no_cut,
                                 start_at=start_at, nogo=nogo,
                                 level_margin=level_margin)
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
        # The link let go of the port before the run took it: "not connected"
        # would be the wrong thing to say for as long as the run has it.
        self._sync_offline()
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
        from gerber2rml.engine.fiducial import pair_measured, residuals
        self.ctl.set_top_fit(t, measured)
        self.made_btns["fit"].setEnabled(True)
        res = iter(residuals(t, *pair_measured(nominal, measured)))
        for i, m in enumerate(measured, 1):
            if m is None:
                self._log("fiducial %d not found" % i)
                continue
            self._log("fiducial %d at %.3f, %.3f - off by %.3f mm"
                      % (i, m[0], m[1], next(res)))

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
        self._clock_wait(True)
        self.flip_btn.setVisible(True)
        self.ctl.say("warn", "Turn the board over, left to right, put it back "
                             "where it was, then press Continue.")

    def _flipped(self):
        self.flip_btn.setVisible(False)
        if self._events is None:
            return
        if simmachine.is_sim(getattr(self, "_last_port", "")):
            simmachine.machine().flip()
        # The zones as they are NOW: the clamps came off for the flip, and
        # the boxes may have been redrawn while the run waited.
        self._events.nogo_now = self.nogo()
        self._clock_wait(False)
        self._events.go_on = True
        self._events.flipped.set()

    def _on_check(self, traces_label, deeper):
        self._clock_wait(True)
        self.check_lbl.setText(
            "%s done%s. The board is at the view position. Is every trace "
            "through the copper, and every hole through the board? Then cut it "
            "out. If not, cut them again a little deeper: as long as the stock "
            "has not moved, they land in the same place. Close the lid first; "
            "the run waits for it." % (traces_label, "" if not deeper else
                               ", %.2f mm deeper" % deeper))
        self._boxes = []
        self._show_boxes()
        self.check_box.setVisible(True)
        self.ctl.say("warn", "Check the traces before the cut-out.")
        self._log("waiting: check the traces (%.2f mm deeper so far)" % deeper)

    # -- boxes over the shallow spots ----------------------------------------
    def _arm_boxes(self, on):
        if on and self.nogo_btn.isChecked():
            # One owner of the dragged box at a time.
            self.nogo_btn.blockSignals(True)
            self.nogo_btn.setChecked(False)
            self.nogo_btn.blockSignals(False)
        self.ctl.set_stage_mode("box" if on else "place")

    # -- where the surface will be touched --------------------------------------
    def _margin_changed(self, v):
        from gerber2rml.gui2 import workspace
        workspace.set_setting("autorun/level_margin", "%.1f" % v)
        self._show_touches()

    def touch_points(self):
        """Where the run will touch the surface, worked out the way the run
        does it (engine/autorun.py, ``level_grid`` and ``level_targets``):
        the grid over the board, set in by the margin, clear of the
        bracket's tongue, on the sheet, and with every touch that would land
        in a no-go zone moved to the nearest free spot. [] with levelling
        off or no board."""
        ctl = self.ctl
        b = ctl.work_bounds() if ctl.state.board is not None else None
        if b is None or not self.level_chk.isChecked():
            return []
        bit = ctl.state.drill.bit_diameter
        sx, sy, sw, sh = ctl.stock
        pts, _area = ar.level_grid(
            b, self.level_margin_spin.value(),
            keepout=self._bracket.keepout() if self.bracket() else None,
            bit=bit,
            stock=(sx, sy, sx + sw, sy + sh) if self.no_cutout() else None)
        from gerber2rml.engine.nogo import zone_shape
        g = bit / 2.0 + ar.NOGO_CLEAR_MM
        zones = [zone_shape(z, g) for z in self._nogo]
        return [t for t in ar.level_targets(pts, zones) if t is not None]

    def _show_touches(self):
        """Draw them on the bed while this page is the one open, so a
        margin or a zone is seen to move them before anything runs."""
        if getattr(self.ctl, "inspector", None) is None:
            return                      # the window is still being built
        if self._on_this_page() and self._thread is None:
            self.ctl.stage.set_probe_points(self.touch_points())

    # -- no-go zones ---------------------------------------------------------
    def _arm_nogo(self, on):
        if on and self.box_btn.isChecked():
            self.box_btn.blockSignals(True)
            self.box_btn.setChecked(False)
            self.box_btn.blockSignals(False)
        self.ctl.set_stage_mode("box" if on else "place")

    def nogo(self):
        """The no-go zones, ``[(x0, y0, x1, y1)]`` in machine mm."""
        return list(self._nogo)

    def add_nogo(self, x0, y0, x1, y1):
        from gerber2rml.engine.nogo import normal
        z = normal((x0, y0, x1, y1))
        if z[2] - z[0] < 0.5 or z[3] - z[1] < 0.5:
            return                  # a click, not a drag: no zone of nothing
        self._nogo.append(z)
        self._save_nogo()

    def add_clamp(self, x, y):
        """A click on the bed while marking: one of the lab's cam clamps
        (engine/nogo.py): screwed into the bed hole nearest the click and
        turned against the nearest edge of the stock."""
        from gerber2rml.engine import spoilboard
        from gerber2rml.engine.nogo import clamp_at
        st = getattr(self.ctl, "stock", None)
        stock = (None if not st else
                 (st[0], st[1], st[0] + st[2], st[1] + st[3]))
        # Every hole in the plate, as the bed draws them - not only those a
        # bracket screw may use: a clamp goes in the outer ring too.
        g = spoilboard.measured_grid()
        holes = [g.centre(i, j) for j in range(g.ny) for i in range(g.nx)]
        self._nogo.extend(clamp_at(x, y, stock, holes))
        self._save_nogo()

    def _clear_nogo(self):
        self._nogo = []
        self._save_nogo()

    def remove_nogo(self, index):
        """Delete one zone. Out of range does nothing: the menu that asked
        may be older than the list."""
        if 0 <= index < len(self._nogo):
            del self._nogo[index]
            self._save_nogo()

    def on_nogo_picked(self, index, where):
        """A zone was right-clicked on the bed: it is deleted, no questions -
        one more click puts a clamp back."""
        if not 0 <= index < len(self._nogo):
            return
        if self._thread is not None and self.flip_btn.isHidden():
            # A run in motion has the zones it was given. At the flip it
            # waits and takes them afresh, so there they may be changed.
            self.ctl.say("warn", "The run is using these zones. They can be "
                                 "changed while it waits at the flip.")
            return
        self.remove_nogo(index)

    def _save_nogo(self):
        """The zones changed: show them. They live only as long as this
        session (see where ``_nogo`` is made)."""
        self._show_nogo()

    def _show_nogo(self):
        n = len(self._nogo)
        self.nogo_clear_btn.setEnabled(bool(n))
        self.nogo_lbl.setText(
            "No zones. With clamps on the stock, mark each one: the surface "
            "probe touches 2 mm in from the board's edge, which is where "
            "clamps sit." if not n else
            "%d no-go zone%s on this bed. The bit stays out: 1 mm clear of "
            "a clamp, 2 mm of a box. Right-click one to delete it."
            % (n, "" if n == 1 else "s"))
        self.ctl.stage.set_nogo(self._nogo)
        self._show_touches()
        # The checks say when work lies in a zone: they follow the zones.
        refresh = getattr(self.ctl, "refresh_checks", None)
        if refresh is not None and getattr(self.ctl, "plan", None) is not None:
            refresh()

    def add_box(self, x0, y0, x1, y1):
        self._boxes.append((min(x0, x1), min(y0, y1),
                            max(x0, x1), max(y0, y1)))
        self._show_boxes()

    def _clear_boxes(self):
        self._boxes = []
        self._show_boxes()

    def _show_boxes(self):
        n = len(self._boxes)
        self.again_btn.setText("Recut %d box%s" % (n, "" if n == 1 else "es")
                               if n else "Recut all traces")
        self.ctl.stage.set_regions(
            [b + (theme.CAUTION,) for b in self._boxes])

    def _holes(self):
        self._answer("holes", self.holes_spin.value())

    def _recut(self):
        self._answer("again", self.deeper_spin.value(),
                     list(self._boxes) or None)

    def _answer(self, what, mm, boxes=None):
        self._clock_wait(False)
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
        # The bar stays, at what it reached: full for a board that is done,
        # where it stopped for one that is not. The line says how long it
        # took; the time left is nobody's business any more.
        self._clock_timer.stop()
        if self._clock is not None:
            from gerber2rml.engine.estimate import format_duration
            s = self._clock.snapshot()
            if ok:
                self.progress.setValue(1000)
            self.progress_lbl.setText(
                ("Done in %s." if ok else "Stopped after %s.")
                % format_duration(s["elapsed_s"]))
            self._clock = None
        self.ctl.bar.set_held_by_run(False)
        self._sync_offline()
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
