"""Bed levelling: measure the surface, then cut to the surface you measured.

Why this is in the essential tier when the first interface had to take it out
of its beginner mode: isolation depth is 0.15 mm and copper foil is 0.035 mm
thick, so a bed or a board that is 0.1 mm out across its width is the
difference between a track that is isolated and a track that is still joined to
its neighbour. Probing is the one thing the Arduino buys a beginner that
changes whether their board works.

It can be here safely because the stop control is not in a panel — see
``machine.py``. The probe run is driven from the same window that is holding
STOP, the run is abortable at every point, and the firmware stops the motion on
abort.

There are two ways in, and neither one is second-class:

* **Over the link** — the bit taps each point and the heights fill themselves
  in. Needs the Arduino.
* **By hand** — the app writes one tiny program per point, you run each in
  VPanel, read Z off the display at contact and type it in. Slower, and
  produces exactly the same height map and exactly the same exported files.
"""
import csv
import threading

from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QTableWidget, QTableWidgetItem, QCheckBox,
                               QHeaderView, QFileDialog, QProgressBar,
                               QAbstractItemView)

from gerber2rml.gui2 import dialogs, theme, widgets, inspector, tier
from gerber2rml.engine import leveling as lv


class ProbeRun(QObject):
    """One grid probe, on its own thread.

    The port is opened by :func:`spi_probe.probe_grid` itself, so the live link
    has to let go of it for the duration. That hand-off is explicit here rather
    than implicit: the link is released, the run owns the port, and STOP still
    reaches the run because it aborts through the link's shared abort event and
    not through the serial port.
    """
    point = Signal(dict)
    # The drift check re-touches the reference every few points and corrects
    # the whole set afterwards, so what ``point`` showed live was raw. These
    # two arrive before ``finished``, and only when a correction was made.
    corrected = Signal(list)            # the corrected results, every point
    drift = Signal(float)               # how far the reference moved, in um
    finished = Signal(str)              # "" = clean, else a sentence to show

    def __init__(self, port, points, should_abort, parent=None,
                 retouch_every=0):
        super().__init__(parent)
        self._port, self._points = port, points
        self._should_abort = should_abort
        self._retouch_every = int(retouch_every or 0)

    def start(self):
        threading.Thread(target=self._run, name="srm-probe", daemon=True).start()

    def _run(self):
        from gerber2rml.engine.spi_probe import probe_grid
        try:
            log = []
            res = probe_grid(self._port, self._points,
                             on_result=self.point.emit,
                             should_abort=self._should_abort,
                             retouch_every=self._retouch_every,
                             drift_log=log)
            if any("z_raw" in r for r in res):
                # Published even for a run that stopped early: the points it
                # did measure were corrected too, and they are being kept.
                zs = [e["z"] for e in log]
                self.drift.emit(float(max(zs) - min(zs)))
                self.corrected.emit(res)
            if self._should_abort():
                self.finished.emit("Stopped. Motion is off and the points "
                                   "already measured have been kept. Raise "
                                   "the bit before jogging.")
                return
            if len(res) < len(self._points):
                last = res[-1] if res else {"id": -1, "error": "no datum"}
                self.finished.emit(
                    f"Stopped at point {last['id'] + 1}: "
                    f"{last.get('error', 'unknown')}. Check "
                    f"the probe clip is on the copper and that the surface is "
                    f"found before this point.")
                return
            missed = [r["id"] + 1 for r in res if r.get("z") is None]
            self.finished.emit(
                f"No contact at point(s) {', '.join(map(str, missed))}. Fill "
                f"those in by hand or re-probe them." if missed else "")
        except Exception as e:
            self.finished.emit(
                f"The probe run failed: {e.__class__.__name__}: {e}. The port "
                f"may still be held by the live link, or by VPanel.")


def resume_selection(measured):
    """Which grid indices to probe again, given which are already measured.

    The anchor (index 0) is always re-probed: every Z is stored relative to
    it, and a run that starts elsewhere would have no datum to store
    against. After it, only the points that have no number yet.
    """
    if not measured:
        return []
    return [0] + [i for i, ok in enumerate(measured) if not ok and i != 0]


class LevelPage(inspector.Page):
    """The levelling workbench, as one inspector page."""

    def __init__(self, ctl, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.set_head("When you need it", "Level the bed")
        self._points = []              # [(x, y)] in machine mm
        self._failed = []              # [(row, why)] from the last probe run
        # Which face this map describes. After a flip the top is a different
        # physical surface with its own zero, so a map is only meaningful on
        # the side it was probed on - and one map that silently applies to
        # both is how a good measurement ends up cutting the wrong face.
        self._side = "bottom"
        # One measurement PER FACE, kept side by side. They describe different
        # physical surfaces, so overwriting one with the other loses a couple
        # of minutes of machine time and, worse, invites cutting the top with
        # the bottom's numbers.
        self._maps = {"bottom": None, "top": None}
        self._run = None
        self._z0 = None                # the run's datum, in raw microns
        self._drift_um = None          # how far the reference moved, if checked

        self.add(widgets.body(
            "Isolation cuts 0.15 mm deep into copper that is 0.035 mm thick. "
            "If the surface rises or falls by more than about a tenth of a "
            "millimetre across the board — and a clamped sheet of FR-4 usually "
            "does — one end of the board is cut through and the other is not. "
            "Measuring the surface lets the cut follow it."))

        first = widgets.Card()
        first.box.addWidget(widgets.eyebrow("Before you probe"))
        first.box.addWidget(widgets.body(
            "Set the Z origin on the copper in VPanel, and leave X and Y "
            "alone. Put paper or tape under the board so it is isolated from "
            "the bed, and clip the probe wire to the copper — the tool is "
            "already earthed through the spindle."))
        first.box.addWidget(widgets.body(
            "Leave the tool a couple of millimetres above the copper when you "
            "start. That height is the one it lifts back to between points, "
            "so starting low makes it drag and starting high makes it slow."))
        self.add(first)

        grid = widgets.Section("The grid")
        self.side_switch = widgets.Segmented(
            [("bottom", "Bottom",
              "The face milled first, with the board as you laid it down."),
             ("top", "Top",
              "The face milled after the flip. A different physical surface "
              "with its own zero, so it gets its own measurement.")],
            "bottom")
        self.side_switch.changed.connect(self._on_side)
        grid.add(self.side_switch)
        grid.add(widgets.hint(
            "Each face is measured separately and both are kept. The one you "
            "are looking at follows the step you are on, and probing writes "
            "into whichever is selected here."))
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(theme.GAP_S)
        self.nx = inspector.count(3, 2, 21, lambda _v: None)
        self.ny = inspector.count(3, 2, 21, lambda _v: None)
        h.addWidget(QLabel("across"))
        h.addWidget(self.nx)
        h.addWidget(QLabel("×"))
        h.addWidget(self.ny)
        h.addWidget(QLabel("up"))
        h.addStretch(1)
        grid.add(row)
        grid.add(widgets.button(
            "Build the grid over the board", on=self._build,
            tip="Lays probe points over the board's footprint, inset from the "
                "edge so every point lands on copper."))
        self.grid_note = widgets.hint(
            "A denser grid follows a warped board more closely and takes "
            "proportionally longer — every point is a physical touch.")
        grid.add(self.grid_note)
        self.add(grid)

        probe = widgets.Section("Measure it")
        prow = QWidget()
        ph = QHBoxLayout(prow)
        ph.setContentsMargins(0, 0, 0, 0)
        ph.setSpacing(theme.GAP_S)
        self.probe_btn = widgets.button(
            "Probe over the link", kind="primary", on=self._probe,
            tip="Drives the machine: the bit descends onto each point until it "
                "touches copper, records the height and moves on.\n\n"
                "STOP stops it at any point.")
        ph.addWidget(self.probe_btn)
        ph.addStretch(1)
        probe.add(prow)
        # The drift check. Spindle warm-up and a board settling under its
        # clamps move the reference by tens of microns over a long grid, and
        # a row probed minutes after the others then reads low as one piece.
        # Re-touching the first point every N points measures that movement,
        # and the whole set is corrected for it when the run ends. Full tier:
        # it needs the v2 firmware, and the number is one more thing to
        # explain to someone probing for the first time.
        self.retouch = inspector.count(6, 0, 20, lambda _v: None)
        self.retouch.setSpecialValueText("off")
        self.retouch.setSuffix(" points")
        self.retouch_field = widgets.Field(
            "Drift check", self.retouch,
            help="Re-touch the first point after every so many points and "
                 "correct the whole grid for how far the reference has moved "
                 "since the start. Set it to off if the Arduino runs the "
                 "first firmware.")
        probe.add(self.retouch_field)
        self.progress = QProgressBar()
        self.progress.hide()
        probe.add(self.progress)
        self.probe_state = widgets.hint("")
        probe.add(self.probe_state)
        probe.add(widgets.button(
            "No Arduino? Write one file per point…", on=self._export_probe_files,
            tip="Writes a tiny program per point plus a checklist. Run each "
                "in VPanel, read Z at contact off the display, and type it "
                "into the table. The height map and the export are identical."))
        self.add(probe)

        table = widgets.Section("Measured heights")
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["X mm", "Y mm", "Height mm"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setMinimumSectionSize(44)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setMinimumHeight(190)
        self.table.itemChanged.connect(self._on_edit)
        table.add(self.table)
        self.show_mesh = QCheckBox("Draw the measured surface on the board")
        self.show_mesh.setToolTip(
            "Shade the board by how far the surface sits above or below the "
            "plane you set Z on — amber high, blue low, and the bed's own "
            "grey where it is flat." + chr(10) + chr(10) +
            "It is the quickest way to see whether the number in the corner "
            "is a real tilt or one bad point.")
        self.show_mesh.toggled.connect(lambda _v: self._draw_mesh())
        table.add(self.show_mesh)
        self.solid_btn = widgets.button(
            "See the surface in 3D…", on=self._show_solid,
            tip="The same measurement as a solid you can turn over." +
                chr(10)*2 +
                "The heatmap says where it is high, which is what the cut "
                "depth needs. This says what shape it is - a bow, a dish and "
                "a tipped corner look alike from above and want different "
                "fixtures.")
        self.check_btn = widgets.button(
            "Check the mesh…", on=self._mesh_check,
            tip="Looks for a point no smooth board surface can explain - a "
                "flaky touch - and for places where the surface changes more "
                "between two probe lines than the map can follow, with one "
                "click to add the missing lines." + chr(10)*2 +
                "Also says how deep the traces need to go to survive what "
                "the mesh cannot see between points.")
        trow = QWidget()
        th = QHBoxLayout(trow)
        th.setContentsMargins(0, 0, 0, 0)
        th.setSpacing(theme.GAP_S)
        th.addWidget(self.solid_btn)
        th.addWidget(self.check_btn)
        th.addStretch(1)
        table.add(trow)
        table.add(widgets.hint(
            "Height is relative to the first point, not an absolute machine Z. "
            "Positive means that spot sits higher than the reference."))
        brow = QWidget()
        bh = QHBoxLayout(brow)
        bh.setContentsMargins(0, 0, 0, 0)
        bh.setSpacing(theme.GAP_S)
        bh.addWidget(widgets.button("Save…", on=self._save_csv))
        bh.addWidget(widgets.button("Load…", on=self._load_csv))
        bh.addWidget(widgets.button("Clear", kind="danger", on=self._clear,
                                    tip="Discards this face's measured heights. "
                                        "The grid stays, and so does the other "
                                        "face's measurement."))
        bh.addStretch(1)
        table.add(brow)
        self.add(table)

        use = widgets.Section("Use it")
        self.use_chk = QCheckBox("Warp the exported cut to this surface")
        self.use_chk.setToolTip(
            "Every Z in the exported files is adjusted to follow the measured "
            "heights. The dry run is deliberately left alone — it is in the "
            "air, and it has to stay identical whatever the surface does.")
        self.use_chk.toggled.connect(lambda _v: ctl.action_level_toggled())
        use.add(self.use_chk)
        self.advice = widgets.body("")
        use.add(self.advice)
        # The top face of a dowel-registered job. The export writes the top
        # traces flat, because that face cannot be probed until the board is
        # flipped; this is the second half of it. A fiducial job does the
        # same thing from the flip-fit page, with the measured fit folded in,
        # so the button belongs to dowel jobs only.
        self.top_btn = widgets.button(
            "Write the top traces to this surface…", on=self._export_top_traces,
            tip="Re-writes the top traces file warped to the TOP face's "
                "measurement. Do it after milling the bottom, flipping the "
                "board onto the pins, re-zeroing Z on the new face and "
                "probing the top from this page.")
        self.top_hint = widgets.hint(
            "After the flip, switch to Top above, probe the flipped board and "
            "write the file. The first export's top traces are flat: that "
            "face did not exist yet when they were written.")
        use.add(self.top_btn)
        use.add(self.top_hint)
        self.add(use)
        self.finish()
        self._sync_enabled()
        self.sync_job()

    def sync_job(self):
        """Match the page to the job and to the tier.

        Called by the window whenever the plan is rebuilt - which is what a
        change of tier, of sidedness or of registration does - so the page
        has no listeners of its own to keep in step.
        """
        self.retouch_field.setVisible(tier.is_full())
        dowel = (bool(getattr(self.ctl, "_double", False))
                 and getattr(self.ctl, "_registration", "dowel") == "dowel")
        self.top_btn.setVisible(dowel)
        self.top_hint.setVisible(dowel)

    # -- grid --------------------------------------------------------------
    def _build(self):
        # Machine coordinates, from the controller. On a double-sided job the
        # layout shifts the board to make room for the registration holes, so
        # the board's OWN bounds put a corner of the grid off the copper — and
        # a probe point that misses the copper is a bit descending until the
        # runaway guard stops it.
        b = self.ctl.work_bounds()
        if b is None:
            self.ctl.say("warn", "Load a board first — the grid is laid over "
                                 "its footprint.")
            return
        b, clipped = self._reachable(b)
        if b is None:
            self.ctl.say("warn", "None of the job is on copper the machine "
                                 "can reach — see the checks.")
            return
        self._points = lv.probe_points(b, self.nx.value(), self.ny.value())
        self.table.blockSignals(True)
        self.table.setRowCount(len(self._points))
        for r, (x, y) in enumerate(self._points):
            for c, val in ((0, f"{x:.3f}"), (1, f"{y:.3f}")):
                it = QTableWidgetItem(val)
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(r, c, it)
            self.table.setItem(r, 2, QTableWidgetItem(""))
        self.table.blockSignals(False)
        self.ctl.stage.set_probe_points(self._points)
        self.ctl.refresh_preview()          # so the key picks up the points
        self._sync_enabled()
        if clipped:
            self.ctl.say("warn", f"{len(self._points)} probe points laid over "
                                 f"the part of the job the machine can reach: "
                                 f"{clipped}. The checks say the same about "
                                 f"the job itself.")
        else:
            self.ctl.say("info", f"{len(self._points)} probe points laid over "
                                 f"the board.")

    def _points_off_the_travel(self):
        """A sentence naming the grid rows the machine cannot get to, or "".

        The grid is built inside the travel now, but a grid can also come
        from a CSV or a setup written before that. Whatever built it, a point
        past the end of an axis is one the head cannot reach, and sending it
        cost a whole column of failures with no clue why.
        """
        from gerber2rml.backends import BACKENDS
        bx, by = BACKENDS[self.ctl.state.machine].bed
        rows = [i + 1 for i, (x, y) in enumerate(self._points)
                if not (0.0 <= x <= bx and 0.0 <= y <= by)]
        if not rows:
            return ""
        shown = ", ".join(str(r) for r in rows[:6]) + ("…" if len(rows) > 6 else "")
        return (f"{len(rows)} probe point{'s' if len(rows) != 1 else ''} "
                f"(row{'s' if len(rows) != 1 else ''} {shown}) lie outside the "
                f"machine's travel of {bx:g} × {by:g} mm. Move the job onto "
                f"the bed and build the grid again.")

    def _reachable(self, b):
        """``b`` clipped to the travel and to the copper, and a sentence about
        what was cut off - or ``(None, ...)`` if nothing is left.

        A probe point past the end of the travel is one the machine cannot
        get to, and a whole column of them fails with no clue why; one past
        the edge of the copper is a bit descending onto bare spoilboard.
        """
        from gerber2rml.backends import BACKENDS
        x0, y0, x1, y1 = b
        bx, by = BACKENDS[self.ctl.state.machine].bed
        limits = [(0.0, 0.0, bx, by, "the travel")]
        ctl = self.ctl
        if getattr(ctl, "show_stock", False) or getattr(ctl, "screwed", False):
            sx, sy, sw, sh = ctl.stock
            limits.append((sx, sy, sx + sw, sy + sh, "the copper"))
        cut = []
        for lx0, ly0, lx1, ly1, what in limits:
            nx0, ny0 = max(x0, lx0), max(y0, ly0)
            nx1, ny1 = min(x1, lx1), min(y1, ly1)
            lost = max(lx0 - x0, x1 - lx1, ly0 - y0, y1 - ly1)
            if lost > 1e-6:
                cut.append(f"{lost:.1f} mm of it is past {what}")
            x0, y0, x1, y1 = nx0, ny0, nx1, ny1
        if x1 - x0 <= 0 or y1 - y0 <= 0:
            return None, "; ".join(cut)
        return (x0, y0, x1, y1), "; ".join(cut)

    def points(self, side=None):
        """``[(x, y, dz)]`` for every row with a height, in machine mm.

        ``side`` asks for one face's measurement whichever face is on screen;
        None is the table in front of you."""
        if side and side != self._side:
            out = []
            for cells in ((self._maps.get(side) or {}).get("rows") or []):
                try:
                    if str(cells[2]).strip():
                        out.append((float(cells[0]), float(cells[1]),
                                    float(cells[2])))
                except (TypeError, ValueError, IndexError):
                    continue
            return out
        out = []
        for r in range(self.table.rowCount()):
            z = self.table.item(r, 2)
            if not z or not z.text().strip():
                continue
            try:
                out.append((float(self.table.item(r, 0).text()),
                            float(self.table.item(r, 1).text()),
                            float(z.text())))
            except ValueError:
                continue
        return out

    def map_side(self):
        return self._side

    def height_map(self, side=None):
        """The height map, or None if it is not on, not complete, or not this
        face's. ``side`` defaults to whichever face the plan is showing."""
        want = side or self.ctl.current_side() or self._side
        if want and self._side != want:
            # Not the face on screen: read that face's own measurement, and
            # its OWN apply flag. The checkbox on screen belongs to the other
            # face, and gating on it handed the flip-fit page no top map
            # whenever the bottom was being looked at.
            other = self._maps.get(want)
            if not other or not other.get("apply"):
                return None
            pts = []
            for cells in (other.get("rows") or []):
                try:
                    pts.append((float(cells[0]), float(cells[1]),
                                float(cells[2])))
                except (TypeError, ValueError, IndexError):
                    continue
            if len(pts) < 3:
                return None
            try:
                return lv.HeightMap.from_points(pts, other.get("nx", 3),
                                                other.get("ny", 3))
            except Exception:
                return None
        if not self.use_chk.isChecked():
            return None
        pts = self.points()
        if len(pts) < 3:
            return None
        try:
            return lv.HeightMap.from_points(pts, self.nx.value(), self.ny.value())
        except Exception:
            return None

    def _on_side(self, side):
        """Switch faces, keeping both measurements."""
        if side == self._side:
            return
        self._maps[self._side] = self._table_state()
        self._side = side
        self._load_table(self._maps.get(side))
        n = len(self.points())
        self.ctl.say("info", "Showing the %s. %s"
                     % ("top" if side == "top" else "bottom",
                        "%d points measured." % n if n else "Nothing probed "
                        "on this face yet."))

    def _table_state(self):
        rows = []
        for r in range(self.table.rowCount()):
            rows.append([(self.table.item(r, c).text()
                          if self.table.item(r, c) else "") for c in range(3)])
        return {"nx": int(self.nx.value()), "ny": int(self.ny.value()),
                "apply": bool(self.use_chk.isChecked()),
                "show": bool(self.show_mesh.isChecked()), "rows": rows}

    def _load_table(self, data):
        data = data or {"rows": [], "apply": False, "show": False}
        rows = data.get("rows") or []
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        pts = []
        for r, cells in enumerate(rows):
            for c, txt in enumerate(list(cells)[:3]):
                it = QTableWidgetItem(str(txt))
                if c < 2:
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(r, c, it)
            try:
                pts.append((float(cells[0]), float(cells[1])))
            except (TypeError, ValueError, IndexError):
                pass
        self.table.blockSignals(False)
        self._points = pts
        if "nx" in data:
            self.nx.setValue(int(data["nx"]))
            self.ny.setValue(int(data["ny"]))
        self.use_chk.setChecked(bool(data.get("apply", False)))
        self.show_mesh.setChecked(bool(data.get("show", False)))
        self.ctl.stage.set_probe_points(self._points)
        self._sync_enabled()
        self._advise()
        self._draw_mesh()

    def follow_step(self, side):
        """The plan moved to a face that CUTS; show that face's measurement.

        ``side`` is None when the step cuts nothing - the levelling page's own
        step included - and then the operator's choice stands.
        """
        if side and side != self._side:
            self.side_switch.set_current(side)
            self._on_side(side)

    def _draw_mesh(self):
        """Sample the measured surface over the board and hand it to the stage.

        Sampled over the footprint the GRID was laid on, not the board's own
        outline: on a mirrored bottom side or a placed board those frames
        differ, and the heatmap would sit offset from the points that made it.
        """
        stage = self.ctl.stage
        if not self.show_mesh.isChecked():
            stage.set_level_mesh(None, None, 0.0)
            return
        showing = self.ctl.current_side()
        if showing is not None and self._side != showing:
            # Drawn on the wrong face it is not a helpful approximation, it is
            # a picture of a surface that is not there.
            stage.set_level_mesh(None, None, 0.0)
            self.ctl.say("info",
                         "This height map was probed on the %s. Nothing is "
                         "drawn on the %s until you probe it."
                         % (self._side, showing))
            return
        hmap = self.height_map()
        pts = self.points()
        # The extent of the PROBE POINTS, not the board's current footprint.
        # Those are two different things the moment the job is moved after
        # probing - and a setup restore sets the placement AFTER the map, so
        # sampling the footprint drew the surface against the previous job's
        # position. Outside the probed area the map is extrapolating anyway,
        # so this also stops it claiming to know more than it measured.
        bounds = None
        if len(pts) >= 3:
            xs = [x for x, _y, _z in pts]
            ys = [y for _x, y, _z in pts]
            bounds = (min(xs), min(ys), max(xs), max(ys))
        if hmap is None or bounds is None or len(pts) < 3:
            stage.set_level_mesh(None, None, 0.0)
            if self.show_mesh.isChecked():
                self.ctl.say("warn", "Nothing measured yet — probe the grid "
                                     "first, or tick 'apply' if you have.")
            return
        from PySide6.QtGui import QImage
        x0, y0, x1, y1 = bounds
        n = 64
        zs = [[float(hmap(x0 + (x1 - x0) * i / (n - 1.0),
                          y0 + (y1 - y0) * j / (n - 1.0)))
               for i in range(n)] for j in range(n)]
        flat = [z for row in zs for z in row]
        span = max(1e-4, max(abs(min(flat)), abs(max(flat))))
        img = QImage(n, n, QImage.Format_RGB32)
        for j in range(n):
            # Row 0 of the image is the TOP; the stage flips it back.
            row = zs[n - 1 - j]
            for i in range(n):
                img.setPixelColor(i, j, theme.height_ink(row[i], span))
        stage.set_level_mesh(img, (x0, y0, x1, y1), span)
        self.ctl.say("ok", "Surface drawn — %.3f mm from the lowest point to "
                           "the highest." % (max(flat) - min(flat)))

    def state(self):
        """Everything worth saving about the measurement, as plain data.

        The probed heights especially. Nine points is nine physical touches
        and a couple of minutes of machine time, and a measurement that does
        not survive closing the app is one nobody relies on.
        """
        rows = []
        for r in range(self.table.rowCount()):
            cells = []
            for c in range(3):
                it = self.table.item(r, c)
                cells.append(it.text() if it else "")
            rows.append(cells)
        maps = dict(self._maps)
        maps[self._side] = self._table_state()
        return {"side": self._side, "maps": maps,
                "retouch": int(self.retouch.value()),
                # The visible face, flat, so a setup written here still opens
                # in a build that predates two-sided maps.
                "nx": int(self.nx.value()), "ny": int(self.ny.value()),
                "apply": bool(self.use_chk.isChecked()),
                "show": bool(self.show_mesh.isChecked()),
                "rows": rows}

    def restore(self, data):
        """Put a saved measurement back, points and heights together."""
        if not isinstance(data, dict):
            return
        self.nx.setValue(int(data.get("nx", 3)))
        self.ny.setValue(int(data.get("ny", 3)))
        if "retouch" in data:
            try:
                self.retouch.setValue(int(data["retouch"]))
            except (TypeError, ValueError):
                pass
        rows = data.get("rows") or []
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        pts = []
        for r, cells in enumerate(rows):
            for c, txt in enumerate(list(cells)[:3]):
                it = QTableWidgetItem(str(txt))
                if c < 2:
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(r, c, it)
            try:
                pts.append((float(cells[0]), float(cells[1])))
            except (TypeError, ValueError, IndexError):
                pass               # a row without coordinates is not a point
        self.table.blockSignals(False)
        self._points = pts
        self._side = data.get("side", "bottom")
        maps = data.get("maps")
        if isinstance(maps, dict):
            self._maps = {"bottom": maps.get("bottom"), "top": maps.get("top")}
        else:
            # A setup from before there were two: whatever it holds belongs to
            # the face it says, and the other has not been probed.
            self._maps = {"bottom": None, "top": None}
            self._maps[self._side] = {
                "nx": data.get("nx", 3), "ny": data.get("ny", 3),
                "apply": bool(data.get("apply", False)),
                "show": bool(data.get("show", False)),
                "rows": data.get("rows") or []}
        self.side_switch.set_current(self._side)
        self.use_chk.setChecked(bool(data.get("apply", False)))
        self.show_mesh.setChecked(bool(data.get("show", False)))
        self.ctl.stage.set_probe_points(self._points)
        self._sync_enabled()
        self._advise()
        self._draw_mesh()

    def is_active(self):
        return self.height_map() is not None

    # -- probing -----------------------------------------------------------
    def _probe(self):
        link = self.ctl.link
        if not link.is_connected():
            self.ctl.say("warn", "Connect to the machine first — the button is "
                                 "on the bar at the bottom.")
            return
        if not self._points:
            self.ctl.say("warn", "Build a grid first.")
            return
        if link.is_busy():
            # Taking the port off a worker mid-move ends the command, not the
            # move: the Roland controller finishes it on its own, and the
            # datum would be latched somewhere along the way.
            self.ctl.say("warn", "The machine is still doing something. Wait "
                                 "for it to finish before probing.")
            return
        off = self._points_off_the_travel()
        if off:
            self.ctl.say("fail", off)
            return
        # WHERE THE TOOL IS STANDING IS THE ORIGIN OF EVERY POINT BELOW.
        #
        # probe_grid opens the port and latches the datum with 'D', which the
        # firmware defines as "the current X,Y" - and every 'P' after it probes
        # at datum + (x, y). The grid, though, is in MACHINE coordinates. Send
        # it raw and the two only agree when the tool happens to be standing on
        # the machine origin: park it over the first probe point at (100, 50)
        # instead and the first point is probed at (200, 100), which is a
        # different part of the bed and possibly not over the board at all.
        #
        # Nothing said so. Rather than add an instruction to remember, the
        # points are sent relative to where the tool actually is, so probing
        # lands where the grid is drawn no matter where you started.
        pos = self.ctl.last_position()
        if pos is None:
            self.ctl.say("warn", "No live position yet — the grid is measured "
                                 "from where the tool is standing, so the "
                                 "readout has to be alive first. Give it a "
                                 "moment and try again.")
            return
        dx, dy = pos[0], pos[1]
        # A grid that is part-done - after a STOP, or a few points the probe
        # could not read - is resumed, not started over. Every measured point
        # is a minute of machine time.
        which = list(range(len(self._points)))
        measured = self._measured()
        done, todo = sum(measured), len(measured) - sum(measured)
        if done and todo:
            choice = self._ask_resume(done, todo)
            if choice is None:
                return
            if choice == "resume":
                which = resume_selection(measured)
        port = (link.firmware or {}).get("port")
        every = self._retouch_every(link)
        # probe_grid opens the port itself, so the live link has to release it.
        link.mark_external(True)
        link.disconnect_from("handing the port to the probe run")
        link.clear_abort()
        pts = [(i, int(round((self._points[i][0] - dx) * 1000)),
                int(round((self._points[i][1] - dy) * 1000)))
               for i in which]
        self.progress.setRange(0, len(pts))
        self.progress.setValue(0)
        self.progress.show()
        self.probe_btn.setEnabled(False)
        self.probe_state.setText(
            "Probing from X%.2f Y%.2f. STOP stops it at the next point."
            % (dx, dy))
        self._z0 = None
        self._failed = []
        self._drift_um = None
        # The switch, not the step. The operator picked a face; a step that
        # cuts nothing has no opinion, and taking one from it is how a top
        # probe ended up stored as the bottom.
        self._run = ProbeRun(port, pts, link.should_abort, self,
                             retouch_every=every)
        self._run.point.connect(self._on_point)
        self._run.corrected.connect(self._on_corrected)
        self._run.drift.connect(self._on_drift)
        self._run.finished.connect(lambda msg, p=port: self._on_done(msg, p))
        self._run.start()

    def _retouch_every(self, link):
        """How often this run re-touches the reference: the setting, or 0
        when the firmware cannot do it.

        The re-touch is a v2 command. The first firmware does not refuse it,
        it ignores it - and the run would then sit out the whole point
        timeout at every checkpoint, waiting for a reply that never comes.
        """
        every = int(self.retouch.value())
        if not every:
            return 0
        feats = (link.firmware or {}).get("features") or ()
        if "retouch" not in feats:
            self.ctl.say("warn", "This Arduino's firmware cannot re-touch the "
                                 "reference, so the drift check is off for "
                                 "this run. Reflash hardware/srm20_spi_probe "
                                 "to get it.")
            return 0
        return every

    def _measured(self):
        """One flag per grid point: does the table hold a number for it?"""
        flags = []
        for r in range(len(self._points)):
            it = self.table.item(r, 2) if r < self.table.rowCount() else None
            txt = it.text().strip() if it else ""
            try:
                float(txt)
                flags.append(True)
            except ValueError:
                flags.append(False)
        return flags

    def _ask_resume(self, done, todo):
        """'resume', 'all', or None for cancel. Named buttons, not Yes/No:
        this sits directly in front of a probing run."""
        d = dialogs.Sheet(self, "Carry on, or start again?", width=520)
        d.say(f"{done} of {done + todo} points are already measured. The "
              f"missing {todo} can be probed on their own; the first point "
              "is re-touched too, so the new numbers share the old datum.")
        out = {"c": None}

        def pick(v):
            out["c"] = v
            d.accept()
        d.act("Cancel", on=d.reject)
        d.act("Probe all again", on=lambda: pick("all"))
        d.act(f"Only the missing {todo}", kind="primary",
              on=lambda: pick("resume"), default=True)
        d.exec()
        return out["c"]

    def _on_point(self, d, draw=True):
        row = d["id"]
        z = d.get("z")
        if z is None:
            # A point the machine could not measure. The firmware probes every
            # point TWICE - a coarse touch, then a lift and a fine re-descend -
            # and reports UNSTABLE when the two disagree, which is what a noisy
            # or dirty contact looks like. Skipping it silently left a blank
            # cell and a height map quietly built from fewer points than were
            # probed.
            why = str(d.get("error") or "no contact")
            short = ("unstable" if "UNSTABLE" in why.upper() else
                     "no touch" if "timeout" in why.lower() else "failed")
            self._failed.append((row, why))
            if row < self.table.rowCount():
                self.table.blockSignals(True)
                it = QTableWidgetItem(short)
                it.setToolTip(why)
                it.setForeground(QColor(theme.CAUTION))
                self.table.setItem(row, 2, it)
                self.table.blockSignals(False)
            self.progress.setValue(row + 1)
            return
        if self._z0 is None:
            self._z0 = z
        if row < self.table.rowCount():
            self.table.blockSignals(True)
            self.table.setItem(row, 2,
                               QTableWidgetItem(f"{(z - self._z0) / 1000.0:.4f}"))
            self.table.blockSignals(False)
        self.progress.setValue(row + 1)
        if draw:
            self._draw_mesh()

    def _on_corrected(self, res):
        """The drift-corrected set: put every point back, corrected.

        The reference resets first so the heights are relative to the
        CORRECTED first point; the failures are rebuilt from the same set so
        a point is not reported twice.
        """
        self._z0 = None
        self._failed = []
        for d in res:
            self._on_point(d, draw=False)
        self._draw_mesh()

    def _on_drift(self, um):
        self._drift_um = float(um)

    def _show_solid(self):
        """Open the measured surface as a turnable mesh."""
        hmap = self.height_map(side=self._side)
        pts = self.points()
        if hmap is None or len(pts) < 3:
            self.ctl.say("warn", "Probe at least three points on this face "
                                 "first — there is no surface to show yet.")
            return
        try:
            import numpy as np
            from gerber2rml.gui2.bedviz import BedVisualizerWindow
        except Exception as e:
            self.ctl.report_error(
                "The 3D view could not start", e,
                "It needs pyqtgraph and PyOpenGL. Run "
                "'python -m gerber2rml.doctor' to install the interface "
                "dependencies, then try again.")
            return
        xs_p = [x for x, _y, _z in pts]
        ys_p = [y for _x, y, _z in pts]
        xs = np.linspace(min(xs_p), max(xs_p), 40)
        ys = np.linspace(min(ys_p), max(ys_p), 40)
        Z = [[float(hmap(float(x), float(y))) for y in ys] for x in xs]
        self._solid = BedVisualizerWindow(
            xs, ys, Z, pts,
            title="%s — the %s face" % (self.ctl.state.name or "board",
                                        self._side),
            parent=self)
        self._solid.show()
        self._solid.raise_()

    def _report_failures(self):
        """Say which points the machine refused to stand behind, and why."""
        if not self._failed:
            return
        unstable = sum(1 for _r, w in self._failed if "UNSTABLE" in w.upper())
        rows = ", ".join(str(r + 1) for r, _w in self._failed[:6])
        plural = "" if len(self._failed) == 1 else "s"
        if unstable:
            self.ctl.say(
                "warn",
                "%d of %d points would not settle (row%s %s). Every point is "
                "probed twice and these two touches disagreed - usually a "
                "dirty contact or electrical noise. Clean the copper there, "
                "check the clip, and probe again."
                % (len(self._failed), self.table.rowCount(), plural, rows))
        else:
            self.ctl.say(
                "warn",
                "%d point%s never touched (row%s %s). The bit may be starting "
                "too high, or those points are not over copper."
                % (len(self._failed), plural, plural, rows))

    def _on_done(self, msg, port):
        self.progress.hide()
        self.probe_btn.setEnabled(True)
        self.probe_state.setText(msg or "Done. Every point measured.")
        self.ctl.link.mark_external(False)
        # A map that took minutes of machine time and is then not applied is
        # the worst of both: the cut is not warped, and the flex margin
        # charges the whole range of a surface nobody is correcting for.
        # Probing is the decision to use it.
        used = ""
        if len(self.points()) >= 3 and not self.use_chk.isChecked():
            self.use_chk.setChecked(True)
            used = " It will warp the exported cut."
        drifted = ""
        if getattr(self, "_drift_um", None) is not None:
            # Said out loud: a reference that moved 60 um over the run is a
            # board still settling or a spindle still warming, and the
            # correction that hid it is worth knowing about.
            drifted = (" The reference moved %.0f µm during the run; every "
                       "point has been corrected for it." % self._drift_um)
            self.probe_state.setText(self.probe_state.text() + drifted)
        self.ctl.say("warn" if msg else "ok",
                     (msg or "Bed probed — the height map is ready.") + used
                     + drifted)
        self._report_failures()
        self._advise()
        # Take the port back so the readout and STOP are live again.
        if port:
            self.ctl.link.connect_to(port)

    def _export_probe_files(self):
        if not self._points:
            self.ctl.say("warn", "Build a grid first.")
            return
        off = self._points_off_the_travel()
        if off:
            self.ctl.say("fail", off)
            return
        from gerber2rml.gui2 import workspace
        d = QFileDialog.getExistingDirectory(
            self, "Where should the per-point programs go?",
            workspace.remembered_dir("probe", "exports"))
        if not d:
            return
        workspace.remember_dir("probe", d)
        try:
            written = lv.write_probe_files(d, self.ctl.state.name, self._points)
        except Exception as e:
            self.ctl.report_error("The probe programs could not be written", e,
                                  "Check that the folder exists and is writable.")
            return
        self.ctl.say("ok", f"{len(written)} files written. Run each one in "
                           f"VPanel and type the Z you read at contact into "
                           f"the table.")

    # -- table -------------------------------------------------------------
    def _on_edit(self, _item):
        self._advise()
        self.ctl.refresh_plan()

    def _clear(self):
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            self.table.setItem(r, 2, QTableWidgetItem(""))
        self.table.blockSignals(False)
        self._advise()
        self._sync_enabled()

    def _save_csv(self):
        from gerber2rml.gui2 import workspace
        path, _ = QFileDialog.getSaveFileName(
            self, "Save the height map",
            workspace.remembered_dir("level", "sessions") + "/heightmap.csv",
            "CSV (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                # Which face, and whose: the file is carried between
                # machines (probe on the CNC PC, level on Linux), and a top
                # map loaded as the bottom's is a wrong cut with no warning.
                f.write(f"# face: {self._side}  job: {self.ctl.state.name}\n")
                w = csv.writer(f)
                w.writerow(["x_mm", "y_mm", "dz_mm"])
                w.writerows(self.points())
        except OSError as e:
            self.ctl.report_error("The height map could not be saved", e)
            return
        workspace.remember_dir("level", path)
        self.ctl.say("ok", "Height map saved.")

    def _load_csv(self):
        from gerber2rml.gui2 import workspace
        path, _ = QFileDialog.getOpenFileName(
            self, "Load a height map",
            workspace.remembered_dir("level", "sessions"), "CSV (*.csv)")
        if not path:
            return
        try:
            with open(path, newline="", encoding="utf-8") as f:
                raw = list(csv.reader(f))
            face = None
            for r in raw:
                if r and r[0].startswith("# face:"):
                    face = r[0].split("face:", 1)[1].split()[0].strip()
            rows = [r for r in raw if r and not r[0].startswith(("x", "#"))]
            pts = [(float(r[0]), float(r[1]), float(r[2])) for r in rows]
        except (OSError, ValueError, IndexError) as e:
            self.ctl.report_error(
                "That file is not a height map this app wrote", e,
                "It needs three columns — x, y and the height deviation — with "
                "one row per probe point.")
            return
        self._points = [(x, y) for x, y, _z in pts]
        self.table.blockSignals(True)
        self.table.setRowCount(len(pts))
        for r, (x, y, z) in enumerate(pts):
            for c, val in ((0, f"{x:.3f}"), (1, f"{y:.3f}"), (2, f"{z:.4f}")):
                it = QTableWidgetItem(val)
                if c < 2:
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(r, c, it)
        self.table.blockSignals(False)
        self.ctl.stage.set_probe_points(self._points)
        self._advise()
        self._sync_enabled()
        if face and face != self._side:
            self.ctl.say("warn", f"That map was probed on the {face} face and "
                                 f"has been loaded as the {self._side}'s. "
                                 f"Switch faces first if that is not what "
                                 f"you meant.")

    # -- advice ------------------------------------------------------------
    def _advise(self):
        pts = self.points()
        if len(pts) < 3:
            self.advice.setText("")
            self._sync_enabled()
            return
        try:
            rec = lv.recommend_depth(pts, self.nx.value(), self.ny.value())
        except Exception:
            self.advice.setText("")
            return
        text = (f"The surface varies by {rec['range']:.3f} mm across the board. "
                f"With this grid, a trace depth of at least {rec['depth']:.2f} mm "
                f"survives what the mesh cannot see between points.")
        # The two findings a person cannot see in a column of numbers, said
        # here so the check is not something you have to think to run.
        try:
            odd = self._mesh_findings(pts)
        except Exception:
            odd = ""
        self.advice.setText(text + (" " + odd if odd else ""))
        self._sync_enabled()

    def _mesh_findings(self, pts):
        """One sentence pointing at 'Check the mesh', or "" when it is clean."""
        if len(pts) < 5:
            return ""
        n_odd = len(lv.flag_outliers(pts))
        sug = lv.suggest_refinement_rows(pts, self.nx.value(), self.ny.value())
        n_lines = len(sug["rows"]) + len(sug["cols"])
        bits = []
        if n_odd:
            bits.append("%d point%s no smooth surface can explain"
                        % (n_odd, "" if n_odd == 1 else "s"))
        if n_lines:
            bits.append("%d place%s where the grid is too coarse"
                        % (n_lines, "" if n_lines == 1 else "s"))
        if not bits:
            return ""
        one = len(bits) == 1 and (n_odd or n_lines) == 1
        return ("There is " if one else "There are ") + " and ".join(bits) \
            + " — check the mesh."

    # -- mesh check ----------------------------------------------------------
    def _mesh_check(self):
        """Three questions about the measurement, on one sheet.

        Is any point wrong? Is the grid fine enough? How deep does the cut
        have to be to survive what the map cannot see? The depth advice is
        already on the page; the other two need the table read as a surface,
        which is exactly what a person cannot do by eye.
        """
        pts = self.points()
        if len(pts) < 5:
            self.ctl.say("warn", "Probe or type in at least five points first "
                                 "— with fewer there is nothing to compare a "
                                 "point against.")
            return
        nx, ny = self.nx.value(), self.ny.value()
        try:
            flags = lv.flag_outliers(pts)
            rec = lv.recommend_depth(pts, nx, ny)
            sug = lv.suggest_refinement_rows(pts, nx, ny)
        except Exception as e:
            self.ctl.report_error(
                "The mesh could not be checked", e,
                "Every height has to be a number. Fill in or clear the cells "
                "that say 'no touch' or 'unstable', then try again.")
            return
        # points() skips blank rows, so its indices are not table rows.
        rows = [r for r in range(self.table.rowCount())
                if self.table.item(r, 2) and self.table.item(r, 2).text().strip()]
        d = dialogs.Sheet(self, "How good is this measurement?",
                          level="warn" if flags else "info", width=560)
        if flags:
            many = len(flags) != 1
            d.say("%d point%s sit%s where no smooth board surface can put "
                  "%s — usually a flaky touch. Re-probe %s:"
                  % (len(flags), "s" if many else "", "" if many else "s",
                     "them" if many else "it", "them" if many else "it"))
            lines = []
            for k, resid in flags[:6]:
                x, y, z = pts[k]
                lines.append("row %d   X %.1f  Y %.1f   height %+.3f mm, "
                             "%.0f µm off the fit"
                             % (rows[k] + 1, x, y, z, resid * 1000))
            d.say(chr(10).join(lines), mono=True, small=True)
            self._mark_suspicious([(rows[k], resid) for k, resid in flags])
        else:
            d.say("Every point agrees with a smooth surface through the "
                  "others.")
            self._mark_suspicious([])
        depth = ("The surface varies by %.3f mm; the worst cell spreads "
                 "%.0f µm between its corners. Cut the traces at least "
                 "%.2f mm deep for the copper between the probe points to "
                 "come away."
                 % (rec["range"], rec["worst_spread"] * 1000, rec["depth"]))
        try:
            t = self.ctl.cutting_trace()
            cur = float(t.effective_cut_depth() if t.tool_type == "vbit"
                        else t.cut_depth)
            if rec["depth"] > cur + 1e-9:
                depth += (" They are set to go %.2f mm deep — raise that "
                          "to %.2f mm in the trace step." % (cur, rec["depth"]))
        except Exception:
            pass
        d.say(depth)
        lines = []
        if sug["rows"]:
            lines.append("a row at Y = " + ", ".join(
                "%.1f" % y for y in sug["rows"]))
        if sug["cols"]:
            lines.append("a column at X = " + ", ".join(
                "%.1f" % x for x in sug["cols"]))
        if lines:
            d.say("The surface changes by more than 80 µm between "
                  "neighbouring probe lines, which is more than the map can "
                  "follow between them. Add " + " and ".join(lines) +
                  ", then probe again and choose 'Only the missing' — the "
                  "points already measured are kept.")
        else:
            d.say("The grid is fine enough: no two neighbouring probe lines "
                  "differ by more than 80 µm.", small=True)
        out = {"insert": False}

        def insert():
            out["insert"] = True
            d.accept()
        if lines:
            d.act("Close", on=d.reject)
            d.act("Add the missing lines", kind="primary", on=insert,
                  default=True)
        else:
            d.act("Close", kind="primary", on=d.accept, default=True)
        d.exec()
        if out["insert"]:
            self._insert_probe_lines(sug["rows"], sug["cols"])

    def _mark_suspicious(self, flagged):
        """Colour the flagged heights so they can be found in the table."""
        self.table.blockSignals(True)
        try:
            for r in range(self.table.rowCount()):
                it = self.table.item(r, 2)
                if it and it.text().strip():
                    it.setForeground(QColor(theme.TEXT))
                    it.setToolTip("")
            for r, resid in flagged:
                it = self.table.item(r, 2)
                if it:
                    it.setForeground(QColor(theme.CAUTION))
                    it.setToolTip("%.0f µm off a smooth surface through the "
                                  "other points — re-probe it."
                                  % (resid * 1000))
        finally:
            self.table.blockSignals(False)

    def _insert_probe_lines(self, new_ys, new_xs=()):
        """Add whole probe rows and columns, blank, keeping the grid whole.

        Whole lines and not single points: half a row leaves a grid that
        only a plane can be fitted to, which throws away the warp the extra
        points were meant to capture. The heights already measured stay, so
        the next probe run offers to measure only the new ones.
        """
        rows = []
        for r in range(self.table.rowCount()):
            xi, yi, zi = (self.table.item(r, c) for c in range(3))
            if xi is None or yi is None:
                continue
            try:
                rows.append((float(xi.text()), float(yi.text()),
                             zi.text().strip() if zi else ""))
            except ValueError:
                continue
        rows, nx, ny = lv.refine_grid(rows, new_ys, new_xs)
        if nx > self.nx.maximum() or ny > self.ny.maximum():
            self.ctl.say("warn", "That would make the grid %d × %d, more than "
                                 "the %d a side this table holds. Build a "
                                 "denser grid instead."
                         % (nx, ny, self.nx.maximum()))
            return
        added = len(rows) - self.table.rowCount()
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        for r, (x, y, z) in enumerate(rows):
            for c, val in ((0, f"{x:.3f}"), (1, f"{y:.3f}"), (2, str(z))):
                it = QTableWidgetItem(val)
                if c < 2:
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(r, c, it)
        self.table.blockSignals(False)
        self._points = [(x, y) for x, y, _z in rows]
        self.nx.setValue(nx)
        self.ny.setValue(ny)
        self.ctl.stage.set_probe_points(self._points)
        self.ctl.refresh_preview()
        self._advise()
        self._sync_enabled()
        self.ctl.say("ok", "%d probe point%s added. Probe over the link and "
                           "choose 'Only the missing' to measure just those."
                     % (added, "" if added == 1 else "s"))

    # -- the top face of a dowel job -----------------------------------------
    def _export_top_traces(self):
        """Re-write the top traces warped to the TOP face's measurement.

        Explicitly the top's map, whichever face is on screen: a bottom map
        describes a surface that was unclamped and turned over, and cutting
        the top by it is worse than cutting flat.
        """
        from gerber2rml.gui2 import workspace
        st = self.ctl.state
        if st.gerber_dir is None:
            self.ctl.say("warn", "Load a board first.")
            return
        level = self.height_map(side="top")
        if level is None:
            if self._side != "top":
                self.ctl.say("warn", "Switch to Top above and probe the flipped "
                                     "board first. The top is a different "
                                     "surface with its own zero, so the "
                                     "bottom's map does not describe it.")
            else:
                self.ctl.say("warn", "Probe at least three points on the top "
                                     "face first, and leave 'Warp the exported "
                                     "cut' ticked.")
            return
        out = self.ctl.export_dir()
        if out is None:
            out = QFileDialog.getExistingDirectory(
                self, "Which folder holds this job's files?",
                workspace.remembered_dir("out", "exports"))
            if not out:
                return
        from gerber2rml.doublesided import build_top_traces
        try:
            # cutting_trace, not st.trace: the same board, held the same
            # way, wants the same flex margin the bottom got.
            path = build_top_traces(
                st.gerber_dir, out, st.name, trace=self.ctl.cutting_trace(),
                machine=st.machine, offset=(st.place_x, st.place_y),
                rotate=st.rotate, registration="dowel", level=level)
        except Exception as e:
            self.ctl.report_error(
                "The top traces could not be re-written", e,
                "Nothing has been changed. Check that the folder still holds "
                "this job's files and that they are not open in another "
                "program.")
            return
        workspace.remember_dir("out", str(path))
        self.ctl.say("ok", f"{path.name} rewritten, warped to the top face "
                           f"you measured. Send that file, not the one from "
                           f"the first export.")

    def _sync_enabled(self):
        has = len(self.points()) >= 3
        self.use_chk.setEnabled(has)
        if not has:
            self.use_chk.setChecked(False)
