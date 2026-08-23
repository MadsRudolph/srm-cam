"""The inspector: whatever the selected step needs, and nothing else.

This is where progressive disclosure actually happens. The first interface
stacks the board controls, the preview-mode tabs, the job parameters, the
double-sided block, the leveling block and the fixture block into one scrolling
column and lets the scrollbar do the hiding — which is why that column resizes
itself from 513 px to 1032 px as you walk the plan, and why it overwrites a
splitter position the user set.

Here the panel is a stack, one page per kind of step, each page sized for its
own content. Selecting a step changes the page; nothing resizes, and nothing
the user arranged gets rearranged for them.

Vocabulary rule for every label in this file: the words are the operator's, not
the code's. ``xy_feed`` is "how fast it moves across the copper"; ``travel_z``
is "how high it lifts between cuts"; ``offsets`` is "isolation passes". Where a
term is genuinely domain jargon it is used — consistently — and explained the
first time it appears.
"""
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
                               QScrollArea, QFrame, QLabel, QLineEdit, QComboBox,
                               QCheckBox, QDoubleSpinBox, QSpinBox, QSizePolicy)

from gerber2rml.gui2 import theme, widgets, tier
from gerber2rml.engine.estimate import format_duration


# ---------------------------------------------------------------------------
# small bound controls
# ---------------------------------------------------------------------------

def num(value, lo, hi, step, decimals, on_change, *, suffix=""):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setDecimals(decimals)
    s.setValue(value)
    s.setKeyboardTracking(False)
    if suffix:
        s.setSuffix(suffix)
    s.valueChanged.connect(on_change)
    return s


def count(value, lo, hi, on_change):
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setValue(value)
    s.setKeyboardTracking(False)
    s.valueChanged.connect(on_change)
    return s


def scroller(inner):
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.NoFrame)
    sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    sa.setWidget(inner)
    return sa


class Page(QWidget):
    """A page of the inspector: a fixed head, then a scrolling body."""

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        headw = QWidget()
        hv = QVBoxLayout(headw)
        hv.setContentsMargins(theme.GAP_M + 2, theme.GAP_M + 2,
                              theme.GAP_M + 2, theme.GAP_M)
        hv.setSpacing(2)
        self.eyebrow = widgets.eyebrow("")
        self.title = QLabel("")
        self.title.setFont(theme.font("head"))
        self.title.setWordWrap(True)
        hv.addWidget(self.eyebrow)
        hv.addWidget(self.title)
        outer.addWidget(headw)
        outer.addWidget(widgets.rule())
        inner = QWidget()
        self.body = QVBoxLayout(inner)
        self.body.setContentsMargins(theme.GAP_M + 2, theme.GAP_M,
                                     theme.GAP_M + 2, theme.GAP_L)
        self.body.setSpacing(theme.GAP_L)
        outer.addWidget(scroller(inner), 1)

    def set_head(self, eyebrow, title):
        self.eyebrow.setText(eyebrow)
        self.title.setText(title)

    def add(self, w):
        self.body.addWidget(w)
        return w

    def finish(self):
        self.body.addStretch(1)


# ---------------------------------------------------------------------------

class SetupPage(Page):
    """The job: what it is, what it is cut with, and where it sits."""

    def __init__(self, ctl, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        st = ctl.state
        self.set_head("Step", "Set up the job")

        # -- the board ---------------------------------------------------
        src = widgets.Section("The board")
        self.folder = widgets.mono("no folder loaded")
        self.folder.setWordWrap(True)
        src.add(self.folder)
        row = QWidget()
        rh = QHBoxLayout(row)
        rh.setContentsMargins(0, 0, 0, 0)
        rh.setSpacing(theme.GAP_S)
        rh.addWidget(widgets.button(
            "Open Gerber folder…", on=ctl.action_open,
            tip="The folder KiCad's Plot wrote: the copper layers, Edge.Cuts "
                "and the .drl drill file."))
        rh.addWidget(widgets.button(
            "Demo board", on=ctl.action_open_demo,
            tip="A bundled 40 × 30 mm coupon that exercises every operation, "
                "so you can try the whole workflow without exporting anything "
                "from KiCad."))
        rh.addStretch(1)
        src.add(row)
        self.name = QLineEdit(st.name)
        self.name.setToolTip("What the exported files are called. Taken from "
                             "the KiCad project name when a folder is loaded.")
        self.name.textChanged.connect(self._on_name)
        src.add(widgets.Field("Job name", self.name))
        self.add(src)

        # -- the tool ----------------------------------------------------
        tools = widgets.Section("The tool")
        self.preset = QComboBox()
        self.preset.setToolTip(
            "A saved set of bit sizes, depths and feeds. The lab's profile is "
            "the numbers this machine is known to cut well with.")
        tools.add(widgets.Field("Profile", self.preset))
        prow = QWidget()
        ph = QHBoxLayout(prow)
        ph.setContentsMargins(0, 0, 0, 0)
        ph.setSpacing(theme.GAP_S)
        ph.addWidget(widgets.button("Apply profile", on=ctl.action_apply_preset))
        self.save_preset_btn = widgets.button("Save as…", on=ctl.action_save_preset)
        ph.addWidget(self.save_preset_btn)
        ph.addStretch(1)
        tools.add(prow)
        self.tool_summary = widgets.hint("")
        tools.add(self.tool_summary)
        self.add(tools)

        # -- the stock ---------------------------------------------------
        stock = widgets.Section("The copper")
        self.thickness = num(1.6, 0.2, 6.0, 0.1, 2, self._on_thickness,
                             suffix=" mm")
        stock.add(widgets.Field(
            "Board thickness", self.thickness,
            help="Measured with calipers, not assumed. Drill and cut-out "
                 "depth are derived from it."))
        self.auto_depth = QCheckBox("Cut through by")
        self.auto_depth.setChecked(True)
        self.auto_depth.setToolTip(
            "Set drill and cut-out depth to the board thickness plus this, so "
            "the bit breaks through cleanly and takes a controlled bite out of "
            "the spoilboard rather than an uncontrolled one.")
        self.auto_depth.toggled.connect(self._on_auto_depth)
        self.overshoot = num(0.10, 0.0, 1.0, 0.05, 2, self._on_auto_depth,
                             suffix=" mm")
        arow = QWidget()
        ah = QHBoxLayout(arow)
        ah.setContentsMargins(0, 0, 0, 0)
        ah.setSpacing(theme.GAP_S)
        ah.addWidget(self.auto_depth)
        ah.addWidget(self.overshoot)
        ah.addStretch(1)
        stock.add(arow)
        self.stock_w = num(100.0, 10.0, 300.0, 5.0, 1, self._on_stock,
                           suffix=" mm")
        self.stock_h = num(80.0, 10.0, 300.0, 5.0, 1, self._on_stock,
                           suffix=" mm")
        stock.add(widgets.Field(
            "Sheet width", self.stock_w,
            help="The piece of copper, not the board. Its front-left corner "
                 "sits on the machine origin — which is exactly what the bed "
                 "fixture guarantees."))
        stock.add(widgets.Field("Sheet height", self.stock_h))
        self.screwed = QCheckBox("Held down with M4 screws")
        self.screwed.setToolTip(
            "Tick this if the copper is screwed to the spoilboard grid.\n\n"
            "The screw heads stand 3 mm above the copper and the default lift "
            "between cuts is 2 mm, so a rapid would pass a millimetre BELOW "
            "the top of every screw. Ticking this raises the lift to 4 mm on "
            "all three operations. It only ever raises — a higher value you "
            "set yourself is kept.")
        self.screwed.toggled.connect(ctl.action_screws_toggled)
        stock.add(self.screwed)
        self.add(stock)

        # -- placement ---------------------------------------------------
        place = widgets.Section("Where it sits on the bed")
        self.place_x = num(0.0, -50.0, 400.0, 1.0, 2, self._on_place, suffix=" mm")
        self.place_y = num(0.0, -50.0, 400.0, 1.0, 2, self._on_place, suffix=" mm")
        place.add(widgets.Field("Across (X)", self.place_x))
        place.add(widgets.Field("Up the bed (Y)", self.place_y))
        self.rotate = widgets.Segmented(
            [("0", "0°", ""), ("90", "90°", ""), ("180", "180°", ""),
             ("270", "270°", "")], "0")
        self.rotate.changed.connect(lambda k: ctl.action_rotate(int(k)))
        place.add(widgets.Field("Turned", self.rotate))
        arow = QWidget()
        ah2 = QHBoxLayout(arow)
        ah2.setContentsMargins(0, 0, 0, 0)
        ah2.setSpacing(theme.GAP_S)
        self.autoplace_btn = widgets.button(
            "Centre it on the bed", kind="primary", on=ctl.action_autoplace,
            tip="Drops the whole job into the middle of the machine's travel, "
                "with whatever room is left shared equally on all four sides.\n\n"
                "On a double-sided board the registration pins are counted "
                "too — they sit outside the board, and a placement that puts "
                "the board on the bed but a dowel off it cannot be run.")
        ah2.addWidget(self.autoplace_btn)
        ah2.addStretch(1)
        place.add(arow)
        place.add(widgets.hint(
            "Or drag the board on the bed. Measured from the machine origin "
            "at the front-left corner — the same zero VPanel shows."))
        self.add(place)

        # -- advanced ----------------------------------------------------
        self.advanced = widgets.Disclosure("Output format and mirroring",
                                           key="setup_output")
        self.machine = QComboBox()
        self.machine.setToolTip(
            "G-code (.nc) is what this lab runs: VPanel streams it in NC-code "
            "command mode and it honours the work Z origin. RML is a fallback.")
        self.machine.currentTextChanged.connect(self._on_machine)
        self.advanced.add(widgets.Field("File format", self.machine))
        self.mirror = QCheckBox("Mirror for bottom-up milling")
        self.mirror.setChecked(True)
        self.mirror.setToolTip(
            "The bottom copper layer is cut from above, so the design has to "
            "be mirrored. Leave this on unless your Gerbers are already "
            "mirrored.")
        self.mirror.toggled.connect(self._on_mirror)
        self.advanced.add(self.mirror)
        self.add(self.advanced)

        # -- double-sided ------------------------------------------------
        self.ds_section = widgets.Section("Double-sided")
        self.double = QCheckBox("This board has copper on both faces")
        self.double.setToolTip(
            "Needs an F.Cu layer in the folder. Adds registration holes, the "
            "flip, and a top-side trace pass — and moves the cut-out to after "
            "the flip, because it is what frees the board from its own "
            "registration.")
        self.double.toggled.connect(ctl.action_double_sided)
        self.ds_section.add(self.double)
        self.registration = QComboBox()
        self.registration.addItem("Dowel pins — the mill drills its own", "dowel")
        self.registration.addItem("Fiducial holes — measured after the flip",
                                  "fiducial")
        self.registration.setToolTip(
            "Dowels: the mill drills two holes through the stock into the bed, "
            "you seat two pins of different sizes, and the board can only go "
            "back one way. Proven, sub-0.1 mm, needs waste around the board.\n\n"
            "Fiducials: reference holes in the stock only. Flip and re-place "
            "freely, probe where they landed, and the top traces are warped to "
            "fit. No waste needed; the fit is only as good as your probing.")
        self.registration.currentIndexChanged.connect(
            lambda _i: ctl.action_registration(self.registration.currentData()))
        self.ds_section.add(widgets.Field("Registration", self.registration))
        self.add(self.ds_section)

        self.finish()

    # -- handlers ------------------------------------------------------
    def _on_name(self, text):
        self.ctl.state.name = text.strip() or "board"
        self.ctl.refresh_plan()

    def _on_thickness(self, v):
        self.ctl.action_thickness(v, self.overshoot.value(),
                                  self.auto_depth.isChecked())

    def _on_auto_depth(self, *_a):
        self.ctl.action_thickness(self.thickness.value(), self.overshoot.value(),
                                  self.auto_depth.isChecked())

    def _on_place(self, *_a):
        self.ctl.action_place(self.place_x.value(), self.place_y.value())

    def _on_stock(self, *_a):
        self.ctl.action_stock(self.stock_w.value(), self.stock_h.value())

    def _on_machine(self, text):
        self.ctl.action_machine(text)

    def _on_mirror(self, on):
        self.ctl.action_mirror(on)

    def sync(self):
        ctl, st = self.ctl, self.ctl.state
        # A full Windows path is one unbreakable token as far as word wrap is
        # concerned, so it sets the minimum width of the whole panel. The last
        # two components are what identifies the folder to a person; the rest
        # is in the tooltip.
        if st.gerber_dir:
            parts = Path(st.gerber_dir).parts
            self.folder.setText("…\\" + "\\".join(parts[-2:])
                                if len(parts) > 2 else str(st.gerber_dir))
            self.folder.setToolTip(str(st.gerber_dir))
        else:
            self.folder.setText("no folder loaded")
            self.folder.setToolTip("")
        if self.name.text() != st.name:
            self.name.blockSignals(True)
            self.name.setText(st.name)
            self.name.blockSignals(False)
        for spin, val in ((self.place_x, st.place_x), (self.place_y, st.place_y)):
            spin.blockSignals(True)
            spin.setValue(val)
            spin.blockSignals(False)
        self.rotate.set_current(str(st.rotate % 360))
        plan = getattr(ctl, "plan", None)
        spec = (f"Traces {st.trace.effective_diameter():.2f} mm wide at "
                f"{st.trace.effective_cut_depth():.2f} mm · drill "
                f"{st.drill.bit_diameter:.2f} mm · cut-out "
                f"{st.cutout.bit_diameter:.2f} mm")
        if plan is not None and plan.single_tool:
            spec = (f"One {plan.tool_label} for all three operations — no bit "
                    f"changes in this job.\n" + spec)
        self.tool_summary.setText(spec)
        full = tier.is_full()
        self.advanced.setVisible(full)
        self.ds_section.setVisible(full)
        self.save_preset_btn.setVisible(full)
        self.registration.setVisible(full and self.double.isChecked())


# ---------------------------------------------------------------------------

class ChecksPage(Page):
    """Pre-flight, on the screen rather than in a modal.

    The first interface runs the same checks and shows them in a
    ``QMessageBox``, which means the findings are gone the moment you dismiss
    it and cannot be read next to the thing they are about. Here they sit
    beside the stage while you fix them, and the worst of them is also on the
    rail as a banner that does not expire.
    """

    def __init__(self, ctl, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.set_head("Step", "Check before cutting")
        self.summary = widgets.body("")
        self.add(self.summary)
        self.list = widgets.Section("Findings")
        self.add(self.list)
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(theme.GAP_S)
        h.addWidget(widgets.button("Re-run the checks", on=ctl.refresh_checks))
        h.addWidget(widgets.button("Copy report", on=ctl.action_copy_checks,
                                   tip="Copies the findings as plain text — "
                                       "for a lab logbook or an email to "
                                       "whoever owns the machine."))
        h.addStretch(1)
        self.add(row)
        self.finish()
        self._items = []

    def set_checks(self, checks):
        for w in self._items:
            w.setParent(None)
            w.deleteLater()
        self._items = []
        if not checks:
            note = widgets.empty_note(
                "Load a board and the checks run themselves.")
            self.list.add(note)
            self._items.append(note)
            self.summary.setText("")
            return
        n_fail = sum(1 for c in checks if c.level == "fail")
        n_warn = sum(1 for c in checks if c.level == "warn")
        if n_fail:
            self.summary.setText(
                f"{n_fail} finding will cost you a board, a bit or the "
                f"spoilboard if you cut like this. Fix it first."
                if n_fail == 1 else
                f"{n_fail} findings will each cost you a board, a bit or the "
                f"spoilboard if you cut like this. Fix them first.")
        elif n_warn:
            self.summary.setText(
                "One thing to look at. It does not stop the job, but it is a "
                "way the job could come out wrong."
                if n_warn == 1 else
                f"{n_warn} things to look at. None of them stops the job, but "
                f"each is a way it could come out wrong.")
        else:
            self.summary.setText("Everything checks out. Run the dry run "
                                 "anyway — it is the only check that tests "
                                 "where the copper actually is.")
        for c in checks:
            card = widgets.Card(quiet=True, pad=theme.GAP_M, gap=5)
            top = QWidget()
            h = QHBoxLayout(top)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(theme.GAP_S)
            h.addWidget(widgets.Dot(c.level, 8))
            t = QLabel(c.title)
            t.setFont(theme.font("sub"))
            t.setWordWrap(True)
            colour = {"ok": theme.TEXT, "warn": theme.CAUTION,
                      "fail": theme.DANGER}[c.level]
            t.setStyleSheet(f"color: {colour};")
            h.addWidget(t, 1)
            card.box.addWidget(top)
            d = QLabel(c.detail)
            d.setFont(theme.font("small"))
            d.setWordWrap(True)
            d.setStyleSheet(f"color: {theme.TEXT_2};")
            card.box.addWidget(d)
            self.list.add(card)
            self._items.append(card)


# ---------------------------------------------------------------------------

class StepPage(Page):
    """One machining step: what it does, what it needs, what it writes."""

    def __init__(self, ctl, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.step = None

        self.note = widgets.body("")
        self.add(self.note)

        facts = widgets.Section("What it needs")
        self.bit = widgets.Readout("Bit needed", "—")
        self.est = widgets.Readout("Cutting time", "—")
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(theme.GAP_M)
        h.addWidget(self.bit)
        h.addWidget(self.est)
        h.addStretch(1)
        facts.add(row)
        self.zero_note = widgets.hint(
            "Re-zero Z after every bit change. Never re-zero XY.")
        facts.add(self.zero_note)
        self.add(facts)

        self.file_section = widgets.Section("The file")
        self.file_name = widgets.mono("not exported yet", strong=True)
        self.file_name.setWordWrap(True)
        self.file_section.add(self.file_name)
        frow = QWidget()
        fh = QHBoxLayout(frow)
        fh.setContentsMargins(0, 0, 0, 0)
        fh.setSpacing(theme.GAP_S)
        self.done_btn = widgets.button("Mark as run", on=self._toggle_done,
                                       tip="A note to yourself on the "
                                           "traveller. It never blocks "
                                           "anything — real runs jump around.")
        fh.addWidget(self.done_btn)
        self.reveal_btn = widgets.button("Show the file", on=ctl.action_reveal)
        fh.addWidget(self.reveal_btn)
        fh.addStretch(1)
        self.file_section.add(frow)
        self.add(self.file_section)

        # -- parameters, behind a disclosure, and only in the full tier ---
        self.params = widgets.Section("Cutting parameters")
        self.param_box = QVBoxLayout()
        self.param_box.setSpacing(theme.GAP_S)
        self.params.add_layout(self.param_box)
        self.add(self.params)
        self._param_widgets = []

        self.finish()

    def _toggle_done(self):
        if self.step:
            self.ctl.action_toggle_done(self.step.key)

    def set_step(self, step, plan):
        self.step = step
        label = f"Step {step.ordinal}" if step.numbered else "Step"
        self.set_head(label, step.title)
        self.note.setText(step.note or step.detail)
        self.bit.set(f"{step.bit:.2f} mm" if step.bit else "none — spindle off")
        self.est.set("~" + format_duration(step.seconds) if step.seconds
                     else "run the export first")
        self.file_name.setText(step.file or "—")
        exported = self.ctl.exported_path(step.file) if step.file else None
        self.reveal_btn.setEnabled(exported is not None)
        self.file_name.setText(
            step.file if exported else f"{step.file} — not written yet")
        self.done_btn.setText("Mark as not run" if self.ctl.is_done(step.key)
                              else "Mark as run")
        # What to say about Z depends on whether this job changes bits at all.
        # Telling someone to "re-zero Z after every bit change" on a job with no
        # bit change is noise, and noise is how the useful half of that
        # sentence - never re-zero XY - stops being read.
        if plan is not None and plan.single_tool:
            self.zero_note.setText(
                f"One {plan.tool_label} for the whole job: Z stays where you "
                f"zeroed it. Never re-zero XY.")
        else:
            self.zero_note.setText(
                "Re-zero Z after every bit change. Never re-zero XY.")
        self.zero_note.setVisible(step.bit is not None)
        self._rebuild_params(step)

    def _rebuild_params(self, step):
        for w in self._param_widgets:
            w.setParent(None)
            w.deleteLater()
        self._param_widgets = []
        op = {"traces": "trace", "drill": "drill", "cutout": "cutout",
              "top_traces": "trace", "align": "drill"}.get(step.op)
        show = tier.is_full() and op is not None
        self.params.setVisible(show)
        if not show:
            return
        st = self.ctl.state
        job = getattr(st, op)
        fields = []
        if op == "trace":
            fields.append(widgets.Field(
                "Bit diameter", num(job.bit_diameter, 0.05, 6.0, 0.05, 2,
                                    lambda v: self._set(job, "bit_diameter", v),
                                    suffix=" mm"),
                help="The cut width. Two nets closer than this cannot be "
                     "separated — the checks will tell you if that happens."))
            fields.append(widgets.Field(
                "Cut depth", num(job.cut_depth, 0.02, 1.0, 0.01, 2,
                                 lambda v: self._set(job, "cut_depth", v),
                                 suffix=" mm"),
                help="Just through the copper foil, which is 35 µm. The rest "
                     "is margin for an uneven surface — which is what bed "
                     "levelling removes."))
            fields.append(widgets.Field(
                "Isolation passes", count(job.offsets, -1, 12,
                                          lambda v: self._set(job, "offsets", v)),
                help="How many channels are cut around each track. −1 clears "
                     "every scrap of background copper, which is much slower."))
            fields.append(widgets.Field(
                "Pass overlap", num(job.stepover, 0.1, 1.0, 0.05, 2,
                                    lambda v: self._set(job, "stepover", v)),
                help="Fraction of the bit width each extra pass steps across."))
        elif op == "drill":
            fields.append(widgets.Field(
                "Bit diameter", num(job.bit_diameter, 0.1, 6.0, 0.05, 2,
                                    lambda v: self._set(job, "bit_diameter", v),
                                    suffix=" mm")))
            fields.append(widgets.Field(
                "Depth through", num(job.total_depth, 0.2, 12.0, 0.1, 2,
                                     lambda v: self._set(job, "total_depth", v),
                                     suffix=" mm"),
                help="Total, from the copper surface. It has to pass the "
                     "bottom of the board to leave a clean hole."))
            fields.append(widgets.Field(
                "Bite per peck", num(job.cut_depth, 0.1, 3.0, 0.1, 2,
                                     lambda v: self._set(job, "cut_depth", v),
                                     suffix=" mm"),
                help="How deep it goes before lifting to clear the chips."))
            one = QCheckBox("One bit for every hole size")
            one.setChecked(job.single_bit)
            one.setToolTip(
                "On: one file, one bit. Holes that match are plunged; larger "
                "ones are circled out to size.\n"
                "Off: one file per hole size, and a bit change between each.")
            one.toggled.connect(lambda v: self._set(job, "single_bit", v))
            fields.append(one)
        elif op == "cutout":
            fields.append(widgets.Field(
                "Bit diameter", num(job.bit_diameter, 0.1, 6.0, 0.05, 2,
                                    lambda v: self._set(job, "bit_diameter", v),
                                    suffix=" mm")))
            fields.append(widgets.Field(
                "Depth through", num(job.total_depth, 0.2, 12.0, 0.1, 2,
                                     lambda v: self._set(job, "total_depth", v),
                                     suffix=" mm")))
            fields.append(widgets.Field(
                "Holding tabs", count(job.tabs, 0, 16,
                                      lambda v: self._set(job, "tabs", v)),
                help="Slivers of copper left uncut so the board does not come "
                     "loose and get thrown while the last pass is still "
                     "running. Snap them afterwards."))
            fields.append(widgets.Field(
                "Tab width", num(job.tab_width, 0.2, 6.0, 0.1, 2,
                                 lambda v: self._set(job, "tab_width", v),
                                 suffix=" mm")))

        speed = widgets.Disclosure("Feeds and lift height", key="feeds")
        speed.add(widgets.Field(
            "Across the copper", num(job.xy_feed, 0.2, 40.0, 0.5, 1,
                                     lambda v: self._set(job, "xy_feed", v),
                                     suffix=" mm/s")))
        speed.add(widgets.Field(
            "Straight down", num(job.plunge_feed, 0.1, 20.0, 0.1, 1,
                                 lambda v: self._set(job, "plunge_feed", v),
                                 suffix=" mm/s"),
            help="Slower than across: the tip of an end mill cuts badly."))
        speed.add(widgets.Field(
            "Lift between cuts", num(job.travel_z, 0.2, 20.0, 0.5, 1,
                                     lambda v: self._set(job, "travel_z", v),
                                     suffix=" mm"),
            help="Must clear anything on the bed — screw heads stand 3 mm "
                 "above the copper."))
        fields.append(speed)

        for f in fields:
            self.param_box.addWidget(f)
            self._param_widgets.append(f)

    def _set(self, job, field, value):
        setattr(job, field, value)
        self.ctl.refresh_plan()
        self.ctl.refresh_preview()


# ---------------------------------------------------------------------------

class HandoffPage(Page):
    """The part with no file: what you do with your hands.

    Given its own page rather than a line of small print because these are
    where boards are actually scrapped. A wrong bit is a ruined trace pass; a
    re-zeroed XY origin is a job whose passes no longer register with each
    other; a flip about the wrong axis is every trace mirrored while the
    registration still looks perfect.
    """

    def __init__(self, ctl, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.step = None
        self.instruction = QLabel("")
        self.instruction.setFont(theme.font("title"))
        self.instruction.setWordWrap(True)
        self.add(self.instruction)
        self.note = widgets.body("")
        self.add(self.note)
        self.rule_card = widgets.Card()
        self.rule_card.box.addWidget(widgets.eyebrow("The standing rule"))
        self.rule_text = widgets.body("")
        self.rule_card.box.addWidget(self.rule_text)
        self.add(self.rule_card)
        self.done_btn = widgets.button("Done — mark it off", on=self._done)
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self.done_btn)
        h.addStretch(1)
        self.add(row)
        self.finish()

    def _done(self):
        if self.step:
            self.ctl.action_toggle_done(self.step.key)

    def set_step(self, step, plan=None):
        self.step = step
        self.set_head("Between steps", step.title)
        one_bit = plan is not None and plan.single_tool
        self.rule_text.setText(
            "Never re-zero XY — not once, not between passes. The traces, the "
            "holes and the outline only line up with each other because they "
            "were all cut from the same XY origin."
            + ("\n\nZ is zeroed once, at the start. This job never changes "
               "bits, so there is nothing to re-zero for."
               if one_bit else
               "\n\nRe-zero Z after every bit change and after every flip."))
        self.instruction.setText(step.detail)
        self.note.setText(step.note or "")
        self.note.setVisible(bool(step.note))
        self.done_btn.setText("Not done after all" if self.ctl.is_done(step.key)
                              else "Done — mark it off")


# ---------------------------------------------------------------------------

class Inspector(QWidget):
    """The stack, and the routing into it."""

    def __init__(self, ctl, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.setFixedWidth(theme.INSPECTOR_W)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.stack = QStackedWidget()
        v.addWidget(self.stack, 1)

        self.setup = SetupPage(ctl)
        self.checks = ChecksPage(ctl)
        self.step = StepPage(ctl)
        self.handoff = HandoffPage(ctl)
        for p in (self.setup, self.checks, self.step, self.handoff):
            self.stack.addWidget(p)
        self._extra = {}

    def add_page(self, key, page):
        self.stack.addWidget(page)
        self._extra[key] = page
        return page

    def show_step(self, step, plan):
        if step.key in self._extra:
            self.stack.setCurrentWidget(self._extra[step.key])
        elif step.key == "setup":
            self.setup.sync()
            self.stack.setCurrentWidget(self.setup)
        elif step.key == "checks":
            self.stack.setCurrentWidget(self.checks)
        elif step.kind == "handoff":
            self.handoff.set_step(step, plan)
            self.stack.setCurrentWidget(self.handoff)
        else:
            self.step.set_step(step, plan)
            self.stack.setCurrentWidget(self.step)
