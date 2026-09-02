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
        self.source.addItem("Isolation traces", "traces")
        self.source.addItem("Board cut-out", "cutout")
        self.source.setToolTip(
            "Which pass the re-cut is taken from. The geometry is the "
            "original toolpath, clipped to your boxes, so it follows exactly "
            "the same route it did the first time.")
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
        try:
            paths = st.toolpaths(op)
        except Exception as e:
            self.ctl.report_error(
                "The source pass could not be generated", e,
                "The rework file is a clipped copy of a real pass, so that "
                "pass has to build first.")
            return
        regions = [((x0, y0, x1, y1), -abs(d))
                   for (x0, y0, x1, y1, d) in self._regions]
        clipped = clip_toolpaths_to_regions(paths, regions)
        if not clipped:
            self.ctl.say("warn", "None of those boxes contains any cutting "
                                 "from that pass — nothing to re-cut.")
            return
        backend = BACKENDS[st.machine]
        job = st.trace if op == "traces" else st.cutout
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
                        f"repeat of the {op} pass, clipped to the marked boxes",
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
