"""Rework: re-cut the spots the first pass did not finish.

An isolation pass that leaves copper bridging two tracks in three places does
not need re-running; it needs those three places cutting again, a little
deeper. This page boxes them up and writes ONE file containing all of them, so
the operator sends one program rather than standing at the machine three times.

The colours are a qualitative series from the palette: the boxes only have to
be told apart from each other, so they are a hue spread rather than six
independent decisions, and each row in the table carries its box's colour.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QComboBox,
                               QApplication,
                               QTableWidget, QTableWidgetItem, QHeaderView,
                               QFileDialog, QAbstractItemView, QCheckBox)
from PySide6.QtGui import QColor, QBrush

from gerber2rml.gui2 import theme, widgets, inspector
from gerber2rml.engine.select import clip_toolpaths_to_regions
from gerber2rml.backends import BACKENDS

# A hue spread, not six decisions. Boxes are categorical: the only requirement
# is that no two adjacent ones read as the same colour.
SERIES = [theme.PATH_FAR, theme.CAUTION, theme.VERIFIED, theme.HOLE,
          theme.PROBE, theme.COPPER_HI, theme.DANGER_HI, theme.FIXTURE]


def _one_of_each(runs):
    """One copy of each distinct run.

    A cut-out's source is one path per depth pass; clipped to a box and
    forced to one depth they become identical copies, cut one after another
    in air - and counted in the run time and the "runs written" line."""
    seen, out = set(), []
    for tp in runs:
        key = tuple((round(m.x, 4), round(m.y, 4), m.rapid) for m in tp)
        if key in seen:
            continue
        seen.add(key)
        out.append(tp)
    return out


def _ramped(runs, step):
    """Take each run down in passes of ``step`` to its own depth, the way the
    cut-out was cut the first time. One full-depth plunge of a 0.8 mm bit
    into 1.7 mm of FR-4 is how bits break."""
    from gerber2rml.toolpath import Move
    step = max(float(step), 0.05)
    out = []
    for tp in runs:
        cut_zs = [m.z for m in tp if not m.rapid]
        if not cut_zs:
            out.append(tp)
            continue
        target = -min(cut_zs)                     # depth, positive mm
        depths, depth = [], 0.0
        while depth < target - 1e-9:
            depth = min(depth + step, target)
            depths.append(depth)
        for d in depths or [target]:
            out.append([m if m.rapid else Move(m.x, m.y, -d, False)
                        for m in tp])
    return out


class ReworkPage(inspector.Page):

    def __init__(self, ctl, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.set_head("When you need it", "Rework")
        self._regions = []          # [(x0, y0, x1, y1, depth_mm)]

        self.add(widgets.body(
            "For a board that has already been cut, where a few spots did not "
            "come out. Box each one, give it a depth, and export them as a "
            "single program — the machine runs them all in one go, and the "
            "rest of the board is left alone."))

        src = widgets.Section("What to repeat")
        self.source = QComboBox()
        self.source.setToolTip(
            "Which pass the re-cut is taken from. The geometry is the "
            "original toolpath, clipped to your boxes, so it follows exactly "
            "the same route it did the first time.")
        self.refresh_sources()
        self.source.currentIndexChanged.connect(lambda _i: ctl.refresh_preview())
        src.add(widgets.Field("Repeat from", self.source))
        self.depth = inspector.num(0.25, 0.02, 3.0, 0.05, 2,
                                   lambda _v: None, suffix=" mm")
        src.add(widgets.Field(
            "Depth for the next box", self.depth,
            help="Deeper than the pass that missed. Each box keeps its own "
                 "depth once it is drawn — edit it in the table."))
        self.add(src)

        draw = widgets.Section("Mark the spots")
        self.add_chk = QCheckBox("Drag boxes on the bed")
        self.add_chk.setToolTip(
            "While this is on, dragging on the canvas adds a box instead of "
            "moving the board.")
        self.add_chk.toggled.connect(self._toggle_add)
        draw.add(self.add_chk)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["X0", "Y0", "X1", "Y1", "Depth"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setMinimumSectionSize(44)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setMinimumHeight(150)
        self.table.itemChanged.connect(self._on_edit)
        draw.add(self.table)
        brow = QWidget()
        bh = QHBoxLayout(brow)
        bh.setContentsMargins(0, 0, 0, 0)
        bh.setSpacing(theme.GAP_S)
        bh.addWidget(widgets.button("Remove selected", on=self._remove))
        bh.addWidget(widgets.button("Remove all", kind="danger", on=self._clear))
        bh.addStretch(1)
        draw.add(brow)
        self.add(draw)

        out = widgets.Section("Write the file")
        self.export_btn = widgets.button(
            "Export the rework program…", kind="primary", on=self._export)
        out.add(self.export_btn)
        self.status = widgets.hint("")
        out.add(self.status)
        self.add(out)
        self.finish()
        self._sync()

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh_sources()

    def refresh_sources(self):
        """The passes this job has. A top-side pass is offered only on a job
        that has a top side; a control for a pass that does not exist is the
        dead control this interface refuses to ship."""
        double = bool(getattr(self.ctl, "_double", False))
        want = ([("Bottom traces", "traces"), ("Top traces", "top_traces")]
                if double else [("Isolation traces", "traces")])
        want.append(("Board cut-out", "cutout"))
        current = self.source.currentData()
        self.source.blockSignals(True)
        self.source.clear()
        for label, op in want:
            self.source.addItem(label, op)
        i = self.source.findData(current)
        self.source.setCurrentIndex(i if i >= 0 else 0)
        self.source.blockSignals(False)

    def _step_for(self, op):
        """The plan step whose toolpath ``op`` repeats, or None."""
        plan = getattr(self.ctl, "plan", None)
        if plan is None:
            return None
        double = bool(getattr(self.ctl, "_double", False))
        key = {"traces": "bottom_traces" if double else "traces_run",
               "top_traces": "top_traces", "cutout": "cutout_run"}.get(op)
        return plan.by_key(key) if key else None

    # -- boxes -------------------------------------------------------------
    def _toggle_add(self, on):
        self.ctl.set_stage_mode("box" if on else "place")

    def add_region(self, x0, y0, x1, y1):
        self._regions.append((min(x0, x1), min(y0, y1), max(x0, x1),
                              max(y0, y1), self.depth.value()))
        self._rebuild_table()
        self._push()

    def _rebuild_table(self):
        self.table.blockSignals(True)
        self.table.setRowCount(len(self._regions))
        for r, (x0, y0, x1, y1, d) in enumerate(self._regions):
            colour = QColor(SERIES[r % len(SERIES)])
            for c, v in enumerate((x0, y0, x1, y1, d)):
                it = QTableWidgetItem(f"{v:.2f}")
                if c < 4:
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                it.setForeground(QBrush(colour if c == 0 else
                                        QColor(theme.TEXT_2)))
                self.table.setItem(r, c, it)
        self.table.blockSignals(False)
        self._sync()

    def _on_edit(self, item):
        if item.column() != 4:
            return
        try:
            depth = float(item.text())
        except ValueError:
            self._rebuild_table()
            return
        r = item.row()
        x0, y0, x1, y1, _d = self._regions[r]
        self._regions[r] = (x0, y0, x1, y1, depth)

    def _remove(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()},
                      reverse=True)
        for r in rows:
            del self._regions[r]
        self._rebuild_table()
        self._push()

    def _clear(self):
        self._regions = []
        self._rebuild_table()
        self._push()

    def _push(self):
        self.ctl.stage.set_regions(
            [(x0, y0, x1, y1, SERIES[i % len(SERIES)])
             for i, (x0, y0, x1, y1, _d) in enumerate(self._regions)])

    def _sync(self):
        has = bool(self._regions)
        self.export_btn.setEnabled(has)
        self.status.setText("" if has else
                            "Nothing marked yet. Tick the box above and drag "
                            "over each spot that needs re-cutting.")

    # -- export ------------------------------------------------------------
    def _export(self):
        from gerber2rml.gui2 import workspace
        st = self.ctl.state
        if st.board is None or not self._regions:
            return
        op = self.source.currentData()
        step = self._step_for(op)
        if step is None:
            self.ctl.say("warn", "This job has no such pass to repeat.")
            return
        # The controller's toolpath for the step, not the state's: on a
        # double-sided job the pass that was cut is the LAYOUT'S, which the
        # dowel frame shifts across the bed, and a top-side pass is warped to
        # the measured flip. Clipping the plain board's paths instead wrote a
        # rework file for a board that was never cut where it says.
        cached = self.ctl._paths_cache.get(step.key)
        if cached is not None:
            paths = cached[0]              # the pass as it was last drawn
        else:
            self.ctl.stage.set_busy("Working out the pass to repeat…")
            QApplication.processEvents()
            try:
                paths, _far, _width = self.ctl._toolpaths_for(step)
            except Exception as e:
                self.ctl.stage.set_busy("")
                self.ctl.report_error(
                    "The source pass could not be generated", e,
                    "The rework file is a clipped copy of a real pass, so "
                    "that pass has to build first.")
                return
            self.ctl.stage.set_busy("")
        regions = [((x0, y0, x1, y1), -abs(d))
                   for (x0, y0, x1, y1, d) in self._regions]
        clipped = _one_of_each(clip_toolpaths_to_regions(paths, regions))
        if not clipped:
            self.ctl.say("warn", "None of those boxes contains any cutting "
                                 "from that pass — nothing to re-cut.")
            return
        if op == "cutout":
            clipped = _ramped(clipped, st.cutout.cut_depth)
        # To the surface the pass was cut to. A rework exists because a spot
        # came out shallow; re-cutting it without the height map the export
        # used reproduces the original miss on a board that is not flat.
        levelled = False
        side = "top" if op == "top_traces" else "bottom"
        hmap = self.ctl.level_page.height_map(side)
        if hmap is not None:
            from gerber2rml.engine.leveling import apply_leveling
            clipped = apply_leveling(clipped, hmap)
            levelled = True
        backend = BACKENDS[st.machine]
        job = st.cutout if op == "cutout" else st.trace
        default = (workspace.remembered_dir("out", "exports")
                   + f"/{st.name}_{op}_rework{backend.ext}")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save the rework program", default,
            f"Machine program (*{backend.ext})")
        if not path:
            return
        try:
            open(path, "w", encoding="utf-8").write(backend.render(
                clipped, xy_feed=job.xy_feed, plunge_feed=job.plunge_feed,
                header=[f"{st.name} - REWORK, {len(self._regions)} area(s)",
                        f"repeat of the {op} pass, clipped to the marked boxes"
                        + (", warped to the probed surface" if levelled
                           else ""),
                        "re-zero Z first; do NOT move the XY origin"]))
        except OSError as e:
            self.ctl.report_error("The rework program could not be written", e)
            return
        workspace.remember_dir("out", path)
        self.status.setText(f"{len(clipped)} cut runs written.")
        self.ctl.say("ok", f"Rework program written with "
                           f"{len(self._regions)} area(s). Re-zero Z, then "
                           f"send it — the XY origin must be the one the "
                           f"board was cut on.")
