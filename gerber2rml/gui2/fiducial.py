"""Measuring where the board landed after a fiducial flip.

Dowel registration works because the BED holds the knowledge: two pins, one
board, one way round. Fiducial registration moves that knowledge to the
operator — flip the board, put it down anywhere, and then *tell the app where
it actually is* by probing the reference holes. The top traces are warped by
the best-fit transform from where those holes should be to where they are.

Two things this page insists on, because both are ways the method fails
silently:

**The residual is the answer, not the fit.** A rigid fit through two or three
points will always produce *a* transform. What says whether it is a good one is
how far the fitted points miss the measured ones — so the RMS is the largest
number on the page and it carries a verdict in words, not a colour.

**The flip direction is a choice you can get wrong.** A rectangle of corner
fiducials is symmetric, so the fit comes out with a tiny RMS for BOTH flip
directions: it validates the rectangle, not the flip. Pick the wrong one and
every trace is mirrored while the numbers still look perfect. The page says so
where the choice is made rather than in a release note.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QTableWidget,
                               QTableWidgetItem, QHeaderView, QCheckBox,
                               QAbstractItemView, QFileDialog)

from gerber2rml.gui2 import theme, widgets, inspector
from gerber2rml.engine import fiducial as fid


class FlipFitPage(inspector.Page):
    """Probe the reference holes, fit, and rewrite the top traces."""

    def __init__(self, ctl, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.set_head("Between steps", "Measure where it landed")
        self._nominal = []

        self.add(widgets.body(
            "There are no pins holding this board in a known place, so the app "
            "has to be told where it ended up. Jog the bit into each reference "
            "hole in turn and capture the position; the top traces are then "
            "warped to match the board in front of you rather than the board "
            "you meant to put down."))

        warn = widgets.Card()
        warn.box.addWidget(widgets.eyebrow("The one that bites"))
        warn.box.addWidget(widgets.body(
            "Four corner holes make a rectangle, and a rectangle is symmetric. "
            "The fit will look excellent for BOTH flip directions — it is "
            "checking the rectangle, not the flip. If you turned the board the "
            "other way, every trace comes out mirrored and the numbers on this "
            "page will not tell you."))
        self.add(warn)

        grid = widgets.Section("The reference holes")
        grid.add(widgets.button(
            "List the holes to probe", on=self._build,
            tip="Reads the nominal positions from the current layout — where "
                "each reference hole would be after a perfect flip."))
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["#", "should be X", "Y", "measured X", "Y"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setMinimumSectionSize(40)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setMinimumHeight(150)
        self.table.itemChanged.connect(lambda _i: self._fit_preview())
        grid.add(self.table)
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(theme.GAP_S)
        h.addWidget(widgets.button(
            "Capture into the selected row", on=self._capture,
            tip="Takes the machine's current X and Y. Jog the bit down into "
                "the hole until it centres itself, then press this."))
        h.addStretch(1)
        grid.add(row)
        grid.add(widgets.hint(
            "You can also type the numbers, if you read them off VPanel "
            "instead."))
        self.add(grid)

        fit = widgets.Section("The fit")
        self.scale_chk = QCheckBox("Let the fit stretch the board as well")
        self.scale_chk.setToolTip(
            "Adds a uniform scale to the rotation and shift. Only tick it if "
            "you have a reason to think the stock moved dimensionally — "
            "otherwise it absorbs real measurement error into a fake stretch "
            "and makes a bad fit look good.")
        self.scale_chk.toggled.connect(lambda _v: self._fit_preview())
        fit.add(self.scale_chk)
        self.rms = widgets.Readout("Worst-case error", "—")
        fit.add(self.rms)
        self.verdict = widgets.body("")
        fit.add(self.verdict)
        self.fit_btn = widgets.button(
            "Fit, and rewrite the top traces", kind="primary",
            on=self._apply,
            tip="Overwrites <name>_top_traces with a copy warped to the "
                "measured flip. Nothing else is touched.")
        self.fit_btn.setEnabled(False)
        fit.add(self.fit_btn)
        self.add(fit)
        self.finish()

    # -- the list ----------------------------------------------------------
    def _build(self):
        from gerber2rml.doublesided import nominal_top_fiducials
        lay = self.ctl._ds_layout()
        if lay is None:
            self.ctl.say("warn", "Turn on double-sided with fiducial "
                                 "registration first.")
            return
        try:
            self._nominal = nominal_top_fiducials(lay)
        except Exception as e:
            self.ctl.report_error(
                "The reference holes could not be worked out", e,
                "They come from the double-sided layout, so the board has to "
                "be set up with fiducial registration before this can list "
                "them.")
            return
        self.table.blockSignals(True)
        self.table.setRowCount(len(self._nominal))
        for r, (x, y) in enumerate(self._nominal):
            for c, val in ((0, str(r + 1)), (1, f"{x:.3f}"), (2, f"{y:.3f}")):
                it = QTableWidgetItem(val)
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(r, c, it)
            for c in (3, 4):
                self.table.setItem(r, c, QTableWidgetItem(""))
        self.table.blockSignals(False)
        self.ctl.stage.set_probe_points(self._nominal)
        self.ctl.say("info", f"{len(self._nominal)} reference holes to probe.")

    def _capture(self):
        rows = {i.row() for i in self.table.selectedIndexes()}
        if not rows:
            self.ctl.say("warn", "Select the row for the hole the bit is in.")
            return
        pos = self.ctl.last_position()
        if pos is None:
            self.ctl.say("warn", "No live position — connect to the machine, "
                                 "or type the numbers in.")
            return
        r = sorted(rows)[0]
        self.table.blockSignals(True)
        self.table.setItem(r, 3, QTableWidgetItem(f"{pos[0]:.3f}"))
        self.table.setItem(r, 4, QTableWidgetItem(f"{pos[1]:.3f}"))
        self.table.blockSignals(False)
        self._fit_preview()

    def measured(self):
        """``[(x, y)]`` for the leading rows that have both numbers filled in."""
        out = []
        for r in range(self.table.rowCount()):
            mx, my = self.table.item(r, 3), self.table.item(r, 4)
            if not mx or not my or not mx.text().strip() or not my.text().strip():
                break
            try:
                out.append((float(mx.text()), float(my.text())))
            except ValueError:
                break
        return out

    # -- the fit -----------------------------------------------------------
    def _fit_preview(self):
        m = self.measured()
        if len(m) < 2:
            self.rms.set("—")
            self.verdict.setText(
                "Two holes is the minimum, and the further apart they are the "
                "better the fit. Three or four is better still.")
            self.fit_btn.setEnabled(False)
            return
        nom = self._nominal[:len(m)]
        try:
            t = fid.fit_transform(nom, m, allow_scale=self.scale_chk.isChecked())
            err = fid.rms(t, nom, m)
            worst = max(fid.residuals(t, nom, m))
        except ValueError as e:
            self.rms.set("—")
            self.verdict.setText(str(e))
            self.fit_btn.setEnabled(False)
            return
        colour = (theme.VERIFIED if worst < 0.05 else
                  theme.CAUTION if worst < 0.15 else theme.DANGER)
        self.rms.set(f"{worst:.3f} mm", colour=colour)
        import math
        deg = math.degrees(t.theta)
        if worst < 0.05:
            note = ("Good. The board is turned {:.2f}° from where it was "
                    "meant to be, and every hole agrees with that to within "
                    "{:.3f} mm.").format(deg, worst)
        elif worst < 0.15:
            note = ("Usable, but check it. One hole disagrees with the others "
                    "by {:.3f} mm — on a 0.2 mm trace that is most of the "
                    "isolation gap. Re-probe the worst one before you cut."
                    ).format(worst)
        else:
            note = ("Too far out to cut. {:.3f} mm of disagreement means the "
                    "board is not flat, a hole was mis-probed, or it was "
                    "flipped the other way. Re-seat it and probe again."
                    ).format(worst)
        self.verdict.setText(note + f"  (RMS {err:.3f} mm)")
        self.fit_btn.setEnabled(True)

    def _apply(self):
        from gerber2rml.doublesided import build_top_traces
        from gerber2rml.gui2 import workspace
        st = self.ctl.state
        m = self.measured()
        if len(m) < 2 or st.gerber_dir is None:
            return
        out = self.ctl.export_dir()
        if out is None:
            out = QFileDialog.getExistingDirectory(
                self, "Which folder holds this job's files?",
                workspace.remembered_dir("out", "exports"))
            if not out:
                return
        try:
            path = build_top_traces(
                st.gerber_dir, out, st.name, trace=st.trace,
                machine=st.machine, offset=(st.place_x, st.place_y),
                rotate=st.rotate, registration="fiducial",
                measured_fiducials=m,
                allow_scale=self.scale_chk.isChecked(),
                level=self.ctl.level_page.height_map())
        except Exception as e:
            self.ctl.report_error(
                "The top traces could not be re-written", e,
                "Nothing has been changed. Check that the folder still holds "
                "this job's files and that they are not open in another "
                "program.")
            return
        workspace.remember_dir("out", str(path))
        self.ctl.say("ok", f"{path.name} rewritten, warped to the flip you "
                           f"measured. Send that file, not the earlier one.")
