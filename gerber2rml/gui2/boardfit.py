"""Drilling a board whose traces were made somewhere else.

A laser-etched board arrives with its copper finished and no holes. None of it
was cut from this machine's origin, so the drill file cannot simply be run: it
has to be moved onto the board that is actually on the bed. This page measures
where a few of the board's own pads are and fits that move.

What it insists on:

**Three pads, known by name.** Two fit any board rigidly, mirrored or not; a
third off their line catches a board etched from the wrong side - provided
each pad is found on the board as "pin 1 of U3", not as "the pad at top left",
because a position read off a mirrored picture describes the picture.

**The residual is the answer.** Same as the flip fit: a transform always comes
out, and only how badly the pads disagree with it says whether to drill.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QTableWidget,
                               QTableWidgetItem, QHeaderView, QCheckBox,
                               QAbstractItemView, QFileDialog)

from gerber2rml.gui2 import theme, widgets, inspector, dialogs
from gerber2rml.engine import boardfit as bf
from gerber2rml.engine import fiducial as fid

# Worst pad disagreement, mm. A 0.8 mm drill in a 1.6-2 mm pad has about
# 0.4 mm before it breaks the ring; the verdicts leave room for that.
GOOD, USABLE = 0.10, 0.25


class BoardFitPage(inspector.Page):
    """Measure pads on a board made elsewhere, fit, write the drill file."""

    def __init__(self, ctl, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.set_head("Drill only", "Drill a board made elsewhere")
        self._pads = []          # indices into state.board.holes
        self._worst = None
        self._run = None

        self.add(widgets.body(
            "For a board whose copper is already done - etched on the laser, "
            "say - and only needs its holes. Put it down anywhere on the bed "
            "and clamp it. Then tell the app where three of its pads really "
            "are; the holes are moved onto the board in front of you instead "
            "of where the design would put them."))

        warn = widgets.Card()
        warn.box.addWidget(widgets.eyebrow("Before measuring"))
        warn.box.addWidget(widgets.body(
            "The picture has to show the copper the way it looks on the bed. "
            "If the board was etched the other way round, flip Mirror under "
            "Set up the job until it matches. Three pads catch a mismatch - "
            "the fit comes out millimetres wrong - but only if you find each "
            "pad on the board by WHICH pin it is, never by where it sits in "
            "the picture."))
        warn.box.addWidget(widgets.hint(
            "Drag the board on the stage to roughly where it sits on the bed: "
            "\"Go to it\" then lands the bit near the first pads."))
        self.add(warn)

        pads = widgets.Section("The pads to measure")
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(theme.GAP_S)
        h.addWidget(widgets.button(
            "Suggest three", on=self.suggest,
            tip="Picks three holes far apart and well out of line - the "
                "spread makes the rotation accurate, the triangle catches a "
                "mirrored board."))
        self.pick_chk = QCheckBox("Pick on the board")
        self.pick_chk.setToolTip(
            "Click holes on the stage to add them. Choose pads you can see "
            "clearly and reach, as far apart as the board allows.")
        self.pick_chk.toggled.connect(self._on_pick)
        h.addWidget(self.pick_chk)
        h.addStretch(1)
        pads.add(row)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["#", "design X", "Y", "real X", "Y"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setMinimumSectionSize(40)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setMinimumHeight(150)
        self.table.itemChanged.connect(lambda _i: self.refit())
        pads.add(self.table)
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(theme.GAP_S)
        h.addWidget(widgets.button(
            "Go to it", on=self._goto,
            tip="Jogs the bit over the selected pad. A measured pad: to the "
                "centre it was measured at, to check it by eye. Otherwise "
                "where the fit says it is once two pads are measured, else "
                "where the picture has it."))
        h.addWidget(widgets.button(
            "Capture", on=self._capture,
            tip="Takes the machine's current X and Y for the selected row. "
                "Lower the bit to just above the pad and centre it by eye - a "
                "loupe helps - then press this."))
        self.auto_btn = widgets.button(
            "Find it for me", on=self._auto,
            tip="Finds the centre electrically, to about 50 um - but only if "
                "the laser left the drill mark in the pad as bare laminate, "
                "and only with the probe clip on THAT pad's net (a laser "
                "board's pads are isolated from each other; ground pads are "
                "the easy choice). Put the bit over the pad first.")
        h.addStretch(1)
        pads.add(row)
        # Two rows: four buttons side by side are wider than the inspector
        # and push every paragraph on the page off its right edge.
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(theme.GAP_S)
        h.addWidget(self.auto_btn)
        h.addWidget(widgets.button("Remove", on=self._remove,
                                   tip="Drops the selected pad from the list."))
        h.addStretch(1)
        pads.add(row)
        pads.add(widgets.hint(
            "You can also type the measured numbers in, if you read them off "
            "VPanel."))
        self.jog_hint = widgets.hint("")
        pads.add(self.jog_hint)
        self.add(pads)

        fit = widgets.Section("The fit")
        self.scale_chk = QCheckBox("Let the fit stretch the board as well")
        self.scale_chk.setToolTip(
            "Adds a uniform scale, for a laser whose output is a fraction of a "
            "percent off size. Leave it off unless the residual says you need "
            "it - it can hide a mis-measured pad as a fake stretch.")
        self.scale_chk.toggled.connect(lambda _on: self.refit())
        fit.add(self.scale_chk)
        self.rms = widgets.Readout("Worst pad", "—")
        fit.add(self.rms)
        self.verdict = widgets.body("")
        fit.add(self.verdict)
        self.write_btn = widgets.button(
            "Write the drill file", kind="primary", on=self._write,
            tip="Writes <name>_drill_fitted: every hole, moved onto the "
                "measured board. Nothing else is written or changed.")
        self.write_btn.setEnabled(False)
        fit.add(self.write_btn)
        fit.add(widgets.hint(
            "Do not move the board, and do not reset XY, between measuring and "
            "drilling. Z is zeroed on the board as usual, with the drill bit."))
        self.add(fit)
        self.finish()
        self.refit()

    # -- the list ----------------------------------------------------------
    def _holes(self):
        b = self.ctl.state.board
        return list(b.holes) if b is not None else []

    def pads(self):
        return list(self._pads)

    def set_pads(self, indices):
        """Replace the list, keeping what was measured for pads kept."""
        keep = {i: m for i, m in zip(self._pads, self._measured_rows())
                if m is not None}
        holes = self._holes()
        self._pads = [i for i in indices if 0 <= i < len(holes)]
        self.table.blockSignals(True)
        self.table.setRowCount(len(self._pads))
        for r, i in enumerate(self._pads):
            x, y = holes[i][0], holes[i][1]
            for c, val in ((0, str(r + 1)), (1, f"{x:.3f}"), (2, f"{y:.3f}")):
                it = QTableWidgetItem(val)
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(r, c, it)
            m = keep.get(i)
            self.table.setItem(r, 3, QTableWidgetItem(
                "" if m is None else f"{m[0]:.3f}"))
            self.table.setItem(r, 4, QTableWidgetItem(
                "" if m is None else f"{m[1]:.3f}"))
        self.table.blockSignals(False)
        self.refit()

    def suggest(self):
        holes = self._holes()
        if len(holes) < bf.MIN_PADS:
            self.ctl.say("warn", "This board has fewer than three holes - "
                                 "there is nothing to fit it by.")
            return
        self.set_pads(bf.suggest_pads(holes))
        self.ctl.say("info", "Three pads picked, far apart and out of line. "
                             "Measure each one.")

    def add_pad_near(self, x, y):
        """A click on the stage: add the hole nearest to it."""
        holes = self._holes()
        t = self.current_fit()
        if t is not None:
            # The stage shows the board where the fit puts it; the list is in
            # design positions.
            x, y = _invert(t, x, y)
        i = bf.nearest_hole(holes, x, y)
        if i is None:
            return
        if i in self._pads:
            self.ctl.say("info", "That pad is already on the list.")
            return
        self.set_pads(self._pads + [i])

    def _on_pick(self, on):
        self.ctl.set_stage_mode("pad" if on else "place")

    def _remove(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()},
                      reverse=True)
        if not rows:
            self.ctl.say("warn", "Select the pad to remove.")
            return
        pads = list(self._pads)
        for r in rows:
            pads.pop(r)
        self.set_pads(pads)

    def _selected_row(self, what):
        rows = {i.row() for i in self.table.selectedIndexes()}
        if not rows:
            self.ctl.say("warn", f"Select the pad to {what}.")
            return None
        return sorted(rows)[0]

    # -- measuring ---------------------------------------------------------
    def _set_measured(self, row, x, y):
        self.table.blockSignals(True)
        self.table.setItem(row, 3, QTableWidgetItem(f"{x:.3f}"))
        self.table.setItem(row, 4, QTableWidgetItem(f"{y:.3f}"))
        self.table.blockSignals(False)
        self.refit()

    def _capture(self):
        r = self._selected_row("capture")
        if r is None:
            return
        pos = self.ctl.last_position()
        if pos is None:
            self.ctl.say("warn", "No live position - connect to the machine, "
                                 "or type the numbers in.")
            return
        self._set_measured(r, pos[0], pos[1])

    def predicted(self, row):
        """Where pad ``row`` should be on the bed: by the fit when there is
        one (two measured pads are enough to aim), else the design."""
        hx, hy = self._holes()[self._pads[row]][:2]
        nom, meas = self._pairs()
        if len(meas) >= 2:
            try:
                t = fid.fit_transform(nom, meas,
                                      allow_scale=self.scale_chk.isChecked())
                return t.apply(hx, hy)
            except ValueError:
                pass
        return hx, hy

    def _goto(self):
        r = self._selected_row("go to")
        if r is None:
            return
        if not self.ctl.link.is_connected():
            self.ctl.say("warn", "Not connected - there is nothing to jog.")
            return
        x, y = self.aim(r)
        where = ("its measured centre" if self._measured_rows()[r] is not None
                 else "where it should be")
        self.ctl.link.jog_to(x, y)
        self.ctl.say("info", f"Jogging to pad {r + 1}, {where}: "
                             f"X{x:.3f} Y{y:.3f}.")

    def aim(self, row):
        """Where Go to it sends the bit: a measured pad's own measurement, so
        it can be checked by eye, else the prediction."""
        m = self._measured_rows()[row]
        return m if m is not None else self.predicted(row)

    def _auto(self):
        from gerber2rml.gui2.fiducial import FidFindRun
        r = self._selected_row("find")
        if r is None:
            return
        if self._run is not None:
            self.ctl.say("warn", "Already probing. STOP stops it.")
            return
        link = self.ctl.link
        if not link.is_connected():
            self.ctl.say("warn", "Connect to the machine first - the button "
                                 "is on the bar at the bottom.")
            return
        pos = self.ctl.last_position()
        if pos is None:
            self.ctl.say("warn", "No live position yet. Give the readout a "
                                 "moment and try again.")
            return
        dia = self._holes()[self._pads[r]][2]
        bit = self.ctl.state.drill.bit_diameter
        clearance = max(0.1, (dia - bit) / 2.0)
        port = (link.firmware or {}).get("port")
        link.mark_external(True)
        link.disconnect_from("handing the port to the pad finder")
        link.clear_abort()
        self.auto_btn.setEnabled(False)
        self._run = FidFindRun(port, r, (pos[0], pos[1]), link.should_abort,
                               self, clearance_um=int(clearance * 1000))
        self._run.note.connect(lambda m: self.ctl.say("info", m))
        self._run.found.connect(self._on_found)
        self._run.found.connect(lambda *_a, p=port: self._reclaim(p))
        self._run.failed.connect(
            lambda _row, msg, p=port: self._on_failed(msg, p))
        self._run.start()
        self.ctl.say("info", "Finding the drill mark - STOP stops it and "
                             "lifts the tool.")

    def _on_found(self, row, x, y):
        self._set_measured(row, x, y)
        self.ctl.say("ok", "Pad centre found at %.3f, %.3f." % (x, y))

    def _on_failed(self, msg, port):
        self.ctl.say("warn", "Could not find the pad centre: %s  - if the "
                             "pad has no bare drill mark, or its net is not "
                             "on the probe clip, centre the bit by eye and "
                             "Capture instead." % msg)
        self._reclaim(port)

    def _reclaim(self, port):
        self._run = None
        self.auto_btn.setEnabled(True)
        self.ctl.link.mark_external(False)
        if port:
            self.ctl.link.connect_to(port)

    def _measured_rows(self):
        """Per row, ``(x, y)`` or None when the row is not filled in."""
        out = []
        for r in range(self.table.rowCount()):
            mx, my = self.table.item(r, 3), self.table.item(r, 4)
            try:
                out.append((float(mx.text()), float(my.text())))
            except (AttributeError, ValueError):
                out.append(None)
        return out

    def _pairs(self):
        """(design, measured) for every pad that has been measured."""
        holes = self._holes()
        nom, meas = [], []
        for i, m in zip(self._pads, self._measured_rows()):
            if m is not None and i < len(holes):
                nom.append(tuple(holes[i][:2]))
                meas.append(m)
        return nom, meas

    # -- the fit -----------------------------------------------------------
    def current_fit(self):
        """The transform design -> bed, or None until three pads agree on
        one. Recomputed from the board every time, so dragging the picture
        or changing the mirror can never leave a stale fit behind."""
        nom, meas = self._pairs()
        if len(meas) < bf.MIN_PADS:
            return None
        try:
            return fid.fit_transform(nom, meas,
                                     allow_scale=self.scale_chk.isChecked())
        except ValueError:
            return None

    def refit(self):
        nom, meas = self._pairs()
        self._worst = None
        self.write_btn.setEnabled(False)
        self._show_where_to_jog()
        if len(meas) < bf.MIN_PADS:
            self.rms.set("—")
            self.verdict.setText(
                "%d of %d measured. Three is the minimum: two fit a mirrored "
                "board as happily as a right one. More, spread out, is better."
                % (len(meas), max(bf.MIN_PADS, len(self._pads))))
            self.ctl.set_board_fit(None)
            return
        t = self.current_fit()
        if t is None:
            self.rms.set("—")
            self.verdict.setText("These pads do not fix the board - they are "
                                 "all in one place. Pick some further apart.")
            self.ctl.set_board_fit(None)
            return
        worst = max(fid.residuals(t, nom, meas))
        self._worst = worst
        colour = (theme.VERIFIED if worst < GOOD else
                  theme.CAUTION if worst < USABLE else theme.DANGER)
        self.rms.set(f"{worst:.3f} mm", colour=colour)
        import math
        deg = math.degrees(t.theta)
        if worst < GOOD:
            note = ("Good. The board sits turned {:+.2f}° and every pad agrees "
                    "with that to within {:.3f} mm.").format(deg, worst)
        elif worst < USABLE:
            note = ("Usable, but check it. One pad disagrees by {:.3f} mm - a "
                    "good part of the ring around a hole. Re-measure the worst "
                    "one before drilling.").format(worst)
        else:
            note = ("Too far out to drill. {:.3f} mm of disagreement means a "
                    "pad was mis-measured, the wrong pad was measured, or the "
                    "picture is mirrored against the board. Check Mirror under "
                    "Set up the job.").format(worst)
        if abs(t.scale - 1.0) > 1e-9:
            note += " Stretch x{:.4f}.".format(t.scale)
        if bf.mirror_ambiguous(nom):
            note += (" These pads are nearly in a line, so a mirrored board "
                     "would fit them too - add one off to the side.")
        self.verdict.setText(note + "  (RMS {:.3f} mm)".format(
            fid.rms(t, nom, meas)))
        self.write_btn.setEnabled(True)
        self.ctl.set_board_fit(t)

    def _show_where_to_jog(self):
        _nom, meas = self._pairs()
        rows = self._measured_rows()
        if len(meas) < 2:
            self.jog_hint.setText("")
            markers = [tuple(self._holes()[i][:2]) for i in self._pads]
        else:
            markers = [self.predicted(r) for r in range(len(self._pads))]
            rest = ["    %d  %.2f, %.2f" % (r + 1, *markers[r])
                    for r in range(len(self._pads)) if rows[r] is None]
            self.jog_hint.setText(
                "" if not rest else
                "Still to measure - the first two put them here:" + chr(10)
                + chr(10).join(rest))
        # The stage's markers are shared with the other measuring pages; only
        # claim them while this one is on screen.
        if self.isVisible():
            self.ctl.stage.set_probe_points(markers)

    def showEvent(self, e):
        super().showEvent(e)
        self.refit()

    def hideEvent(self, e):
        super().hideEvent(e)
        if self.pick_chk.isChecked():
            self.pick_chk.setChecked(False)

    # -- the file ----------------------------------------------------------
    def _write(self):
        from gerber2rml.gui2 import workspace
        st = self.ctl.state
        t = self.current_fit()
        if t is None or st.board is None:
            return
        if self._worst is not None and self._worst >= USABLE:
            if not dialogs.confirm_irreversible(
                    self, "The fit is too far out to trust",
                    "The worst pad disagrees with the others by %.3f mm - "
                    "enough to drill beside the pad instead of through it. "
                    "Re-measure, unless you know why it is out." % self._worst,
                    "Use it anyway and write the file"):
                return
        out = self.ctl.export_dir()
        if out is None:
            out = QFileDialog.getExistingDirectory(
                self, "Where should the drill file go?",
                workspace.remembered_dir("out", "exports"))
            if not out:
                return
        self.write_to(out)

    def write_to(self, out):
        """Write the fitted drill file(s) into ``out``. Tests call this."""
        from gerber2rml.gui2 import workspace
        st = self.ctl.state
        t = self.current_fit()
        if t is None or st.board is None:
            return []
        try:
            written = bf.write_fitted_drill(
                st.board.holes, self.ctl.cutting_drill(), t, out, st.name,
                st.machine, level=self.ctl.level_page.height_map(side="bottom"))
        except Exception as e:
            self.ctl.report_error(
                "The drill file could not be written", e,
                "Nothing has been changed. Check the folder is writable.")
            return []
        workspace.remember_dir("out", str(written[0]))
        self.ctl.say("ok", "Wrote %s - the holes moved onto the board you "
                           "measured. Zero Z with the drill bit and send it."
                     % ", ".join(p.name for p in written))
        return written


def _invert(t, x, y):
    """The design point that ``t`` puts at (x, y)."""
    import math
    c, s = math.cos(-t.theta), math.sin(-t.theta)
    dx, dy = (x - t.tx) / t.scale, (y - t.ty) / t.scale
    return c * dx - s * dy, s * dx + c * dy
