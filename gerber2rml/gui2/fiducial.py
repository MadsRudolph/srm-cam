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
import threading

from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QTableWidget,
                               QTableWidgetItem, QHeaderView, QCheckBox,
                               QAbstractItemView, QFileDialog)

from gerber2rml.gui2 import theme, widgets, inspector, dialogs
from gerber2rml.engine import fiducial as fid


# Directions tried for the surface reference, in order. The probe has to touch
# copper ONCE before it can tell hole from copper, and the obvious spot - just
# beside the hole - is not always metal: a hole near the board edge, in a
# cleared pour, or beside another hole has bare laminate on one side. The first
# interface tried due west only and gave up if that missed.
_REF_DIRS = ((-2500, 0, "west"), (2500, 0, "east"),
             (0, 2500, "north"), (0, -2500, "south"))


class FidFindRun(QObject):
    """Find one reference hole's centre electrically, on its own thread.

    Same hand-off as the grid prober: this opens the port itself, so the live
    link lets go of it, and STOP still reaches the run through the link's
    shared abort event rather than through the port.

    The coordinates need care, because the two commands used here do NOT agree
    with each other. ``P`` - the surface reference - is an offset from the
    datum ``D`` latched at the current position. ``H`` - the hole test the
    edge-walking is built from - takes ABSOLUTE machine coordinates; the
    firmware says so at the top of its handler and jumps straight to them.

    So the start point is the tool's machine position, not (0, 0). Passing
    zero drives the head to the corner of the bed at full speed, which is
    exactly what it did the first time this ran on the machine.
    """
    found = Signal(int, float, float)         # row, machine x, machine y
    failed = Signal(int, str)
    note = Signal(str)

    def __init__(self, port, row, datum_xy, should_abort, parent=None,
                 clearance_um=400, search_um=1500):
        super().__init__(parent)
        self._port, self._row = port, row
        self._dx, self._dy = datum_xy
        self._should_abort = should_abort
        # How much room the bit has inside the hole, and how far to hunt for
        # it. The step can never exceed the clearance or the search walks
        # straight over the hole without seeing it.
        self._clearance_um = clearance_um
        self._search_um = search_um

    def start(self):
        threading.Thread(target=self._run, name="srm-fidfind",
                         daemon=True).start()

    def _run(self):
        import time as _t
        from gerber2rml.engine import fidfind, spi_probe
        ser = None
        try:
            ser = spi_probe.open_link(self._port)
            ack = None
            for _ in range(3):
                ser.write(b"D" + bytes([10]))
                ack = spi_probe._read_line(ser, _t.monotonic() + 3.0)
                if ack and ack.startswith("D"):
                    break
            if not (ack and ack.startswith("D")):
                self.failed.emit(self._row,
                                 "the machine did not acknowledge the datum "
                                 "(got %r). Check the firmware is v2 or "
                                 "later." % (ack,))
                return
            if not self._surface_reference(ser, spi_probe):
                return
            seed = self._find_the_hole(ser, fidfind)
            if seed is None:
                return
            self.note.emit("Walking the hole edges…")
            # Absolute machine millimetres: H is not datum-relative.
            cx, cy = fidfind.find_hole_center(
                ser, seed[0] / 1000.0, seed[1] / 1000.0,
                should_abort=self._should_abort)
            if self._should_abort():
                self.failed.emit(self._row, "stopped")
                return
            self.found.emit(self._row, cx, cy)
        except Exception as e:
            try:
                if ser is not None:
                    spi_probe.send_abort(ser)
            except Exception:
                pass
            self.failed.emit(self._row, str(e))
        finally:
            try:
                if ser is not None:
                    ser.close()
            except Exception:
                pass

    def _find_the_hole(self, ser, fidfind):
        """A start point that is actually inside the hole, in datum microns.

        The bisection needs to begin somewhere the probe reads NO copper. Aim
        by eye through a spindle and a couple of tenths of error is normal, so
        rather than refuse, walk outward in rings until a point reads hole.

        Bounded on purpose. Every test is a physical descend of a second or
        two, so an unbounded search is a machine moving for ten minutes; and
        this forgives AIMING error, not a board that is somewhere else
        entirely. If the board landed millimetres away, jog to the hole you
        can actually see - it is visible, and that is faster than any search.
        """
        import math
        # H is absolute, so the search walks around where the TOOL is.
        x0 = int(round(self._dx * 1000))
        y0 = int(round(self._dy * 1000))
        if not fidfind.hole_test(ser, x0, y0, should_abort=self._should_abort):
            return (x0, y0)                    # already inside; nothing to do
        step = max(200, int(self._clearance_um))    # never step over the hole
        rings = max(1, int(self._search_um // step))
        tested = 1
        for ring in range(1, rings + 1):
            r = ring * step
            n = max(6, int(round(2 * math.pi * r / step)))
            self.note.emit("Hunting for the hole, %.1f mm out…"
                           % (r / 1000.0))
            for k in range(n):
                if self._should_abort():
                    self.failed.emit(self._row, "stopped")
                    return None
                a = 2 * math.pi * k / n
                x = x0 + int(round(r * math.cos(a)))
                y = y0 + int(round(r * math.sin(a)))
                tested += 1
                if not fidfind.hole_test(ser, x, y,
                                         should_abort=self._should_abort):
                    self.note.emit("Found it %.2f mm from where you aimed."
                                   % (r / 1000.0))
                    return (x, y)
        self.failed.emit(
            self._row,
            "no hole within %.1f mm of the bit, after %d tests - copper "
            "everywhere. Either the bit is not over the hole (jog to the one "
            "you can see; a board that landed millimetres out will not be "
            "found by searching), or the hole is too small for the bit to "
            "enter and it is riding the rim."
            % (self._search_um / 1000.0, tested))
        return None

    def _surface_reference(self, ser, spi_probe):
        """Touch copper once, so the firmware knows where the surface is.

        Tries each side of the hole and takes the first that makes contact,
        rather than insisting on one direction that may be over laminate.
        """
        import time as _t
        last = None
        for dx, dy, name in _REF_DIRS:
            if self._should_abort():
                self.failed.emit(self._row, "stopped")
                return False
            self.note.emit("Looking for the copper surface, %s of the hole…"
                           % name)
            ser.write(("P 999 %d %d" % (dx, dy) + chr(10)).encode())
            line = spi_probe._read_line(ser, _t.monotonic() + 90.0,
                                        self._should_abort)
            if line and line.startswith("R"):
                return True
            last = line
        self.failed.emit(
            self._row,
            "no copper found 2.5 mm on any side of the hole (last reply %r). "
            "The bit needs bare copper within reach of the hole for its "
            "surface reference - move to a hole that has some, or measure "
            "this one by hand." % (last,))
        return False


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
        self.auto_btn = widgets.button(
            "Find it for me", on=self._auto,
            tip="Walks the hole's edges electrically and works out its centre "
                "to about 50 um, which is better than anyone can do by eye."
                + chr(10)*2 +
                "Put the bit just above the hole first. It refines a hole it "
                "is already over - it does not hunt across the board, so if "
                "the board landed millimetres out, jog to where the fit says "
                "the hole is rather than to the nominal number.")
        h.addWidget(self.auto_btn)
        h.addStretch(1)
        grid.add(row)
        grid.add(widgets.hint(
            "You can also type the numbers, if you read them off VPanel "
            "instead."))
        self.jog_hint = widgets.hint("")
        self.jog_hint.setWordWrap(True)
        grid.add(self.jog_hint)
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
        # The fit is NOT this button. It is adopted as soon as two rows are
        # filled, because everything downstream needs it before this point is
        # reached - the probe grid included. Calling the button "Fit and
        # export" implied one step where there are three, and the middle one
        # is the one people were skipping.
        fit.add(widgets.body(
            "The fit is applied as soon as two holes are measured — the top "
            "views already show the board where it really is. What is left is "
            "to measure THIS face's surface and then write the files:"))
        self.order = widgets.hint("")
        fit.add(self.order)
        # Finishing blind holes is a separate job from writing the top traces:
        # it only exists when the first side did not break through, and it is
        # deliberately shallow, so it does not belong behind the same button.
        self.finish_depth = inspector.num(0.50, 0.10, 3.0, 0.05, 2,
                                          lambda _v: None, suffix=" mm")
        fit.add(widgets.Field(
            "Finish blind holes, depth", self.finish_depth,
            help="How far to drill from THIS face, for holes the first side "
                 "did not break through." + chr(10)*2 +
                 "It is not the board thickness. The hole is already most of "
                 "the way through, so a few tenths meets it - and going the "
                 "whole way would put the bit into the bed for no reason."))
        self.drill_btn = widgets.button(
            "Finish the blind holes from this side", on=self._finish_holes,
            tip="Writes <name>_top_drill: every hole, reflected and warped to "
                "the measured flip so it lands on the one already there, at "
                "the depth above.")
        fit.add(self.drill_btn)
        self.fit_btn = widgets.button(
            "Write the top traces and the cut-out", kind="primary",
            on=self._apply,
            tip="Rewrites <name>_top_traces and <name>_cutout, both warped to "
                "the measured flip and levelled to this face if it has been "
                "probed. Nothing else is touched.")
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
        # Measurements saved with the setup come back with it. Probing four
        # holes is the expensive part of this job; losing it to a restart, or
        # to rebuilding the list, is the kind of loss that makes people not
        # trust saving.
        for r, (mx, my) in enumerate(self.ctl._fid_measured or []):
            if r >= self.table.rowCount():
                break
            self.table.setItem(r, 3, QTableWidgetItem("%.3f" % mx))
            self.table.setItem(r, 4, QTableWidgetItem("%.3f" % my))
        self.table.blockSignals(False)
        self.ctl.stage.set_probe_points(self._nominal)
        restored = min(len(self.ctl._fid_measured or []), self.table.rowCount())
        self.ctl.say("info", "%d reference holes to probe.%s"
                     % (len(self._nominal),
                        "" if not restored
                        else "  %d already measured, from the setup."
                             % restored))
        self._fit_preview()

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

    # -- finding a hole electrically ---------------------------------------
    def _auto(self):
        rows = {i.row() for i in self.table.selectedIndexes()}
        if not rows:
            self.ctl.say("warn", "Select the row for the hole the bit is over.")
            return
        if getattr(self, "_run", None) is not None:
            self.ctl.say("warn", "Already probing. STOP stops it.")
            return
        link = self.ctl.link
        if not link.is_connected():
            self.ctl.say("warn", "Connect to the machine first — the button "
                                 "is on the bar at the bottom.")
            return
        pos = self.ctl.last_position()
        if pos is None:
            self.ctl.say("warn", "No live position yet. Give the readout a "
                                 "moment and try again.")
            return
        # Refuse before a minute of probing, not after. The hole is found by
        # lowering the bit INSIDE it and reading no copper; a bit that cannot
        # fit rides the rim and reads copper at every point, centre included.
        bit = self.ctl.state.drill.bit_diameter
        dia = self.ctl._fid_diameter
        clearance = (dia - bit) / 2.0
        if clearance < 0.15:
            dialogs.report_error(
                self, "The bit will not fit in that hole", None,
                "The reference holes are %.2f mm and the bit is %.2f mm, so "
                "the bit cannot get inside one — it rests on the rim and "
                "reads copper everywhere, including dead centre. Set the "
                "reference hole to at least %.1f mm under Set up the job and "
                "re-cut the align file, or measure this one by hand."
                % (dia, bit, bit + 0.6))
            return
        r = sorted(rows)[0]
        port = (link.firmware or {}).get("port")
        # The finder opens the port itself, so the live link has to let go of
        # it - the same hand-off the grid prober makes. STOP still reaches the
        # run through the shared abort event.
        link.mark_external(True)
        link.disconnect_from("handing the port to the hole finder")
        link.clear_abort()
        self.auto_btn.setEnabled(False)
        self._run = FidFindRun(port, r, (pos[0], pos[1]), link.should_abort,
                               self, clearance_um=int(clearance * 1000))
        self._run.note.connect(lambda m: self.ctl.say("info", m))
        self._run.found.connect(self._on_found)
        self._run.failed.connect(lambda row, msg, p=port: self._on_failed(msg, p))
        self._run.finished_with = port
        self._run.found.connect(lambda *_a, p=port: self._reclaim(p))
        self._run.start()
        self.ctl.say("info", "Finding the hole — STOP stops it and lifts "
                             "the tool.")

    def _on_found(self, row, x, y):
        self.table.blockSignals(True)
        self.table.setItem(row, 3, QTableWidgetItem("%.3f" % x))
        self.table.setItem(row, 4, QTableWidgetItem("%.3f" % y))
        self.table.blockSignals(False)
        self.ctl.say("ok", "Hole centre found at %.3f, %.3f." % (x, y))
        self._fit_preview()

    def _on_failed(self, msg, port):
        self.ctl.say("warn", "Could not find the hole: %s" % msg)
        self._reclaim(port)

    def _reclaim(self, port):
        """Take the port back, so the readout and STOP are live again."""
        self._run = None
        self.auto_btn.setEnabled(True)
        self.ctl.link.mark_external(False)
        if port:
            self.ctl.link.connect_to(port)

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
            self.jog_hint.setText("")
            self.ctl.set_top_fit(None)
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
        # Adopt it as soon as it is computed, not only when files are written:
        # the point of the fit is to SEE the board where it really is, and
        # exporting is a separate decision made afterwards.
        self.ctl.set_top_fit(t, m)
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
        self._sync_order()
        self.fit_btn.setEnabled(True)
        self._show_where_to_jog(t, len(m))

    def _finish_holes(self):
        """Re-drill the holes from this side, to meet the blind ones."""
        from gerber2rml.doublesided import build_top_drill
        from gerber2rml.gui2 import workspace
        st = self.ctl.state
        m = self.measured()
        if len(m) < 2 or st.gerber_dir is None:
            self.ctl.say("warn", "Measure two reference holes first — without "
                                 "the fit the new holes would not land on the "
                                 "old ones.")
            return
        out = self.ctl.export_dir()
        if out is None:
            out = QFileDialog.getExistingDirectory(
                self, "Which folder holds this job's files?",
                workspace.remembered_dir("out", "exports"))
            if not out:
                return
        depth = self.finish_depth.value()
        thickness = self.ctl.inspector.setup.thickness.value()
        if depth >= thickness:
            if not dialogs.confirm_irreversible(
                    self, "That goes through the board and into the bed",
                    "%.2f mm from this face on a %.2f mm board reaches the "
                    "spoilboard. The holes only need finishing — they are "
                    "already drilled from the other side."
                    % (depth, thickness), "Drill it anyway"):
                return
        try:
            path = build_top_drill(
                st.gerber_dir, out, st.name, drill=self.ctl.cutting_drill(),
                machine=st.machine, offset=(st.place_x, st.place_y),
                rotate=st.rotate, registration="fiducial",
                fiducials=self.ctl.fiducial_spec(), measured_fiducials=m,
                allow_scale=self.scale_chk.isChecked(),
                level=self.ctl.level_page.height_map(side="top"),
                depth=depth)
        except Exception as e:
            self.ctl.report_error(
                "The finishing drill could not be written", e,
                "Nothing has been changed. Check the folder still holds this "
                "job's files.")
            return
        self.ctl.say("ok", "Wrote %s — %.2f mm from this face, on the fit."
                     % (path.name, depth))

    def _sync_order(self):
        """The three steps, with the one you are on marked.

        Written out because the middle one has no button of its own on this
        page and was being skipped: the top traces would go out levelled by
        the other face's map, or not levelled at all.
        """
        fitted = self.ctl._top_fit is not None
        probed = self.ctl.level_page.height_map(side="top") is not None
        rows = [("1  fit from the fiducials", fitted, "done" if fitted
                 else "measure two holes"),
                ("2  probe THIS face on Level the bed", probed,
                 "done" if probed else "not yet - the traces would go out "
                 "unlevelled"),
                ("3  write the files", False, "this button")]
        self.order.setText(chr(10).join(
            "%s %s  -  %s" % ("[x]" if ok else "[ ]", label, note)
            for label, ok, note in rows))

    def _show_where_to_jog(self, t, done):
        """Where the holes you have NOT measured yet actually are.

        The auto-finder starts wherever the bit is; it refines a hole it is
        already over, it does not hunt for one metres away. So a board that
        landed a few millimetres out defeats it if you aim at the nominal
        position — which is the number printed in the table.

        Once two holes are measured the transform is known, and the rest can
        be predicted exactly. Jog to the predicted place instead and the bit
        starts inside the hole, where Auto can do its job. Shown as guidance,
        never written into the measured columns: a predicted number that looks
        measured is how a bad fit gets believed.
        """
        rest = self._nominal[done:]
        if not rest:
            self.jog_hint.setText("")
            return
        bits = []
        for i, (nx, ny) in enumerate(rest, start=done):
            px, py = t.apply(nx, ny)
            label = self.table.item(i, 0).text() if self.table.item(i, 0) else str(i + 1)
            bits.append("%s  %.2f, %.2f  (nominal %.2f, %.2f)"
                        % (label, px, py, nx, ny))
        self.jog_hint.setText(
            "Still to measure — jog HERE, not to the nominal position:"
            + chr(10) + (chr(10)).join("    " + b for b in bits))

    def _apply(self):
        from gerber2rml.doublesided import build_top_traces, build_top_cutout
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
        # The height map in hand is whichever face was last probed. After a
        # flip the top is a DIFFERENT physical surface, with its own shape and
        # its own zero, so the bottom's map does not describe it - applying it
        # is worse than not levelling at all. Only the operator knows which
        # side it came from, so ask rather than guess.
        # Explicitly the TOP face's map: height_map() returns None when the
        # one in hand belongs to the other side, so a bottom map cannot leak
        # into a top-side export.
        level = self.ctl.level_page.height_map(side="top")
        if level is None and self.ctl.level_page.points():
            self.ctl.say("warn",
                         "The height map you have was probed on the %s, so the "
                         "top traces will be written UNLEVELLED. Probe this "
                         "face first if you want it levelled."
                         % self.ctl.level_page.map_side())
        if level is not None:
            if not dialogs.confirm_irreversible(
                    self, "Was this height map probed on THIS side?",
                    "The top traces are about to be levelled with the height "
                    "map currently loaded. That is whichever face you probed "
                    "last, and after the flip the top is a different surface "
                    "with a different zero." + chr(10)*2 +
                    "Re-probe the top first if you have not, or clear the map "
                    "and export unlevelled.",
                    "It is this side's map"):
                return
        try:
            # cutting_trace, not st.trace: the top is cut from the same board,
            # held the same way, so it needs the same flex margin the bottom
            # got. Passing the nominal job gave the top a 0.15 mm cut while
            # the bottom had 0.585.
            path = build_top_traces(
                st.gerber_dir, out, st.name, trace=self.ctl.cutting_trace(),
                machine=st.machine, offset=(st.place_x, st.place_y),
                rotate=st.rotate, registration="fiducial",
                fiducials=self.ctl.fiducial_spec(),
                measured_fiducials=m,
                allow_scale=self.scale_chk.isChecked(),
                level=level)
            # The cut-out runs last, on the same flipped board this fit
            # describes, so it takes the same warp. Left alone it keeps the
            # geometry written before the fit existed and misses the outline
            # by the whole placement error.
            cut = build_top_cutout(
                st.gerber_dir, out, st.name, cutout=st.cutout,
                machine=st.machine, offset=(st.place_x, st.place_y),
                rotate=st.rotate, registration="fiducial",
                fiducials=self.ctl.fiducial_spec(),
                measured_fiducials=m,
                allow_scale=self.scale_chk.isChecked(),
                level=level)
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
