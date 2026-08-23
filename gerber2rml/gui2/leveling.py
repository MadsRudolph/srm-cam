"""Bed levelling: measure the surface, then cut to the surface you measured.

Why this is in the essential tier when the first interface had to take it out
of its beginner mode: isolation depth is 0.15 mm and copper foil is 0.035 mm
thick, so a bed or a board that is 0.1 mm out across its width is the
difference between a track that is isolated and a track that is still joined to
its neighbour. Probing is the one thing the Arduino buys a beginner that
changes whether their board works.

It can be here safely because the stop control is not in a panel — see
``machine.py``. The probe run is driven from the same window that is holding
STOP, the run is abortable at every point, and the firmware lifts the tool on
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
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QTableWidget, QTableWidgetItem, QCheckBox,
                               QHeaderView, QFileDialog, QProgressBar,
                               QAbstractItemView)

from gerber2rml.gui2 import theme, widgets, inspector
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
    finished = Signal(str)              # "" = clean, else a sentence to show

    def __init__(self, port, points, should_abort, parent=None):
        super().__init__(parent)
        self._port, self._points = port, points
        self._should_abort = should_abort

    def start(self):
        threading.Thread(target=self._run, name="srm-probe", daemon=True).start()

    def _run(self):
        from gerber2rml.engine.spi_probe import probe_grid
        try:
            res = probe_grid(self._port, self._points,
                             on_result=self.point.emit,
                             should_abort=self._should_abort)
            if self._should_abort():
                self.finished.emit("Stopped. The tool has lifted; the points "
                                   "already measured have been kept.")
                return
            if len(res) < len(self._points):
                last = res[-1] if res else {"id": -1, "error": "no datum"}
                self.finished.emit(
                    f"Stopped at point {last['id'] + 1}: "
                    f"{last.get('error', 'unknown')}. The tool lifted. Check "
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


class LevelPage(inspector.Page):
    """The levelling workbench, as one inspector page."""

    def __init__(self, ctl, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.set_head("When you need it", "Level the bed")
        self._points = []              # [(x, y)] in machine mm
        self._run = None

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
        self.add(first)

        grid = widgets.Section("The grid")
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
                "STOP stops it at any point, and the tool lifts.")
        ph.addWidget(self.probe_btn)
        ph.addStretch(1)
        probe.add(prow)
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
                                    tip="Discards every measured height. The "
                                        "grid stays."))
        bh.addStretch(1)
        table.add(brow)
        self.add(table)

        use = widgets.Section("Use it")
        self.use_chk = QCheckBox("Warp the exported cut to this surface")
        self.use_chk.setToolTip(
            "Every Z in the exported files is adjusted to follow the measured "
            "heights. The dry run is deliberately left alone — it is in the "
            "air, and it has to stay identical whatever the surface does.")
        self.use_chk.toggled.connect(lambda _v: ctl.refresh_plan())
        use.add(self.use_chk)
        self.advice = widgets.body("")
        use.add(self.advice)
        self.add(use)
        self.finish()
        self._sync_enabled()

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
        self.ctl.say("info", f"{len(self._points)} probe points laid over the "
                             f"board.")

    def points(self):
        """``[(x, y, dz)]`` for every row with a height, in machine mm."""
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

    def height_map(self):
        """The height map, or None if it is not on or not complete enough."""
        if not self.use_chk.isChecked():
            return None
        pts = self.points()
        if len(pts) < 3:
            return None
        try:
            return lv.HeightMap.from_points(pts, self.nx.value(), self.ny.value())
        except Exception:
            return None

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
        port = (link.firmware or {}).get("port")
        # probe_grid opens the port itself, so the live link has to release it.
        link.mark_external(True)
        link.disconnect_from("handing the port to the probe run")
        link.clear_abort()
        pts = [(i, int(round(x * 1000)), int(round(y * 1000)))
               for i, (x, y) in enumerate(self._points)]
        self.progress.setRange(0, len(pts))
        self.progress.setValue(0)
        self.progress.show()
        self.probe_btn.setEnabled(False)
        self.probe_state.setText(
            "Probing. STOP stops it at the next point and lifts the tool.")
        self._z0 = None
        self._run = ProbeRun(port, pts, link.should_abort, self)
        self._run.point.connect(self._on_point)
        self._run.finished.connect(lambda msg, p=port: self._on_done(msg, p))
        self._run.start()

    def _on_point(self, d):
        z = d.get("z")
        if z is None:
            return
        if self._z0 is None:
            self._z0 = z
        row = d["id"]
        if row < self.table.rowCount():
            self.table.blockSignals(True)
            self.table.setItem(row, 2,
                               QTableWidgetItem(f"{(z - self._z0) / 1000.0:.4f}"))
            self.table.blockSignals(False)
        self.progress.setValue(row + 1)

    def _on_done(self, msg, port):
        self.progress.hide()
        self.probe_btn.setEnabled(True)
        self.probe_state.setText(msg or "Done. Every point measured.")
        self.ctl.link.mark_external(False)
        self.ctl.say("warn" if msg else "ok",
                     msg or "Bed probed — the height map is ready.")
        self._advise()
        # Take the port back so the readout and STOP are live again.
        if port:
            self.ctl.link.connect_to(port)

    def _export_probe_files(self):
        if not self._points:
            self.ctl.say("warn", "Build a grid first.")
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
                rows = [r for r in csv.reader(f) if r and not r[0].startswith("x")]
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
        self.advice.setText(
            f"The surface varies by {rec['range']:.3f} mm across the board. "
            f"With this grid, a trace depth of at least {rec['depth']:.2f} mm "
            f"survives what the mesh cannot see between points.")
        self._sync_enabled()

    def _sync_enabled(self):
        has = len(self.points()) >= 3
        self.use_chk.setEnabled(has)
        if not has:
            self.use_chk.setChecked(False)
