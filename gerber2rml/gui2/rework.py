"""Rework: re-cut the spots the first pass did not finish.

An isolation pass that leaves copper bridging two tracks in three places does
not need re-running; it needs those three places cutting again, a little
deeper. This page boxes them up and writes ONE file containing all of them, so
the operator sends one program rather than standing at the machine three times.

Each box carries its own depth and its own "level" flag - whether its cut
follows the probed height map. On a bowed board the first miss was usually the
map being a little wrong at that spot, and the two ways of finding out how
wrong are both here: the photo (a channel with no cut in it at all) and the
probe (the bit tapped in the middle of each box, compared with what the map
believed). The probe run hands the port over the way the levelling page does,
so STOP keeps working while it taps.

The colours are a qualitative series from the palette: the boxes only have to
be told apart from each other, so they are a hue spread rather than six
independent decisions, and each row in the table carries its box's colour.
"""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QComboBox,
                               QApplication, QDialog,
                               QTableWidget, QTableWidgetItem, QHeaderView,
                               QFileDialog, QAbstractItemView, QCheckBox)
from PySide6.QtGui import QColor, QBrush

from gerber2rml.gui2 import theme, widgets, inspector, tier, dialogs
from gerber2rml.engine.select import clip_toolpaths_to_regions
from gerber2rml.backends import BACKENDS

# A hue spread, not six decisions. Boxes are categorical: the only requirement
# is that no two adjacent ones read as the same colour.
SERIES = [theme.PATH_FAR, theme.CAUTION, theme.VERIFIED, theme.HOLE,
          theme.PROBE, theme.COPPER_HI, theme.DANGER_HI, theme.FIXTURE]

# Below this the probe and the map agree to within the probe's own repeat
# (two touches on clean copper differ by a few microns): not a correction.
PROBE_MIN_DELTA = 0.005

# The photo detector reads the channel's cross-profile, and that signature is
# gone below about 12 px/mm; the first interface settled on 16.
DETECT_PX_PER_MM = 16.0


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


def clip_boxes(paths, boxes, hmap=None, ramp_step=None):
    """Clip ``paths`` to every box at that box's depth.

    ``boxes`` is ``[((x0, y0, x1, y1, depth), follow), ...]``. A box whose
    ``follow`` is on is warped to ``hmap`` when there is one; ``ramp_step``
    takes each run down in passes first (the cut-out). Returns
    ``(clipped, n_levelled)``: the runs, and how many boxes were warped, which
    the file header and the status line both say.
    """
    from gerber2rml.engine.leveling import apply_leveling
    out, n = [], 0
    for (x0, y0, x1, y1, d), follow in boxes:
        part = _one_of_each(clip_toolpaths_to_regions(
            paths, [((x0, y0, x1, y1), -abs(d))]))
        if not part:
            continue
        if ramp_step is not None:
            part = _ramped(part, ramp_step)
        if follow and hmap is not None:
            part = apply_leveling(part, hmap)
            n += 1
        out.extend(part)
    return out, n


def outline_xy(geom):
    """The board edge as ``[(x, y), ...]`` for the photo detector, which
    drops channels that run along it (the cut-out's job, not the traces').
    A polygon's exterior, the largest piece of a multipolygon, or None."""
    if geom is None or getattr(geom, "is_empty", True):
        return None
    try:
        if hasattr(geom, "geoms"):
            geom = max(geom.geoms, key=lambda g: g.area)
        ring = getattr(geom, "exterior", geom)
        return [(float(x), float(y)) for x, y in ring.coords]
    except Exception:
        return None


def deepen_from_probe(regions, results, hmap, ref, min_delta=PROBE_MIN_DELTA):
    """Deepen each box by how much LOWER the copper is there than the map said.

    ``results`` are probe_grid's dicts: id 0 is the map's own first point, id
    ``i + 1`` the middle of box ``i``. Every height is read relative to the
    reference, exactly as the map's own numbers are, so the two compare.

    The sign matters and is easy to get backwards. The map is positive where
    the copper is HIGH, and a cut that follows it rides at ``-depth + map``.
    Where the real copper sits lower than the map by ``short``, that cut only
    went ``depth - short`` into it - which is the shallow spot the box was
    drawn for - so the box goes deeper by exactly ``short``. Where the copper
    sits higher than mapped the first cut was already deeper than asked; a
    rework never makes a cut shallower, so that box is left alone.

    Returns ``(regions, deepened, skipped)``: the new boxes, ``[(index, mm)]``
    of the ones changed, and how many had no contact. ``None`` when the
    reference itself was not measured, since nothing is comparable then.
    """
    from gerber2rml.engine.spi_probe import deviations_mm
    dz = deviations_mm(results, ref_id=0)
    if 0 not in dz:
        return None
    rx, ry = ref
    base = float(hmap(rx, ry)) if hmap is not None else 0.0
    new, deepened, skipped = [], [], 0
    for i, (x0, y0, x1, y1, d) in enumerate(regions):
        if i + 1 not in dz:
            skipped += 1
            new.append((x0, y0, x1, y1, d))
            continue
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        modelled = (float(hmap(cx, cy)) - base) if hmap is not None else 0.0
        short = modelled - dz[i + 1]
        if short > min_delta:
            d = round(d + short, 3)
            deepened.append((i, short))
        new.append((x0, y0, x1, y1, d))
    return new, deepened, skipped


class ReworkPage(inspector.Page):

    def __init__(self, ctl, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.set_head("When you need it", "Rework")
        self._regions = []          # [(x0, y0, x1, y1, depth_mm)]
        # One flag per box, kept BESIDE the boxes rather than inside them: the
        # setup file's "regions" entry stays the five numbers it has always
        # been, so a file written by an earlier build still reads, and one
        # written now still reads there.
        self._follow = []
        self._probe_run = None
        self._probe_results = []
        self._probe_hmap = None
        self._probe_ref = None

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
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["X0", "Y0", "X1", "Y1", "Depth", "Level"])
        self.table.horizontalHeaderItem(5).setToolTip(
            "Ticked: this box's cut follows the probed height map, so its "
            "depth stays even over the board's bow. New boxes are ticked "
            "whenever a map is on. Untick to cut it flat.")
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
        self.detect_btn = widgets.button(
            "Propose boxes from the photo", on=self._detect_from_photo,
            tip="Walk every isolation channel of the pass above and look "
                "at the photo for stretches with no cut in them at all. "
                "Each becomes a box at the depth above.")
        draw.add(self.detect_btn)
        self.detect_hint = widgets.hint(
            "Needs a photo laid on the bed (View menu). It sees channels that "
            "were never cut; a cut that is merely too shallow still looks "
            "like a channel in any photo — the probe below finds those.")
        draw.add(self.detect_hint)
        self.add(draw)

        self.probe_section = widgets.Section("Check the depth")
        self.probe_section.add(widgets.body(
            "The bit taps the middle of each box and the map's first point, "
            "and where the copper sits lower than the map believed, that box "
            "is deepened by exactly the difference. The way to find a cut "
            "that is too shallow rather than missing."))
        self.probe_btn = widgets.button(
            "Probe the boxes over the link", on=self._probe_boxes)
        self.probe_section.add(self.probe_btn)
        self.probe_state = widgets.hint(
            "Leave the tool a couple of millimetres above the copper, spindle "
            "off, probe clip on the copper. STOP stops it at the next point.")
        self.probe_section.add(self.probe_state)
        self.add(self.probe_section)

        out = widgets.Section("Write the file")
        self.sim_btn = widgets.button(
            "Watch the boxes in 3D…", on=self._watch_in_3d,
            tip="Only the re-cut: the pass clipped to your boxes, at their "
                "depths, played through in the 3D view.")
        out.add(self.sim_btn)
        self.export_btn = widgets.button(
            "Export the rework program…", kind="primary", on=self._export)
        out.add(self.export_btn)
        self.status = widgets.hint("")
        out.add(self.status)
        self.add(out)
        self.finish()
        self._sync()
        self.sync_tier()

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh_sources()
        self.sync_tier()

    def sync_tier(self):
        """The photo detector and the probe assume the operator knows what a
        height map and a link are: Full only. Hidden, not disabled, as
        everywhere else in this interface."""
        full = tier.is_full()
        for w in (self.detect_btn, self.detect_hint, self.probe_section):
            w.setVisible(full)

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

    def _side(self):
        """The face the chosen pass cuts, which is the face whose map
        applies."""
        return "top" if self.source.currentData() == "top_traces" else "bottom"

    def _height_map(self):
        page = getattr(self.ctl, "level_page", None)
        return page.height_map(self._side()) if page is not None else None

    # -- boxes -------------------------------------------------------------
    def _toggle_add(self, on):
        self.ctl.set_stage_mode("box" if on else "place")

    def add_region(self, x0, y0, x1, y1, depth=None, follow=None):
        """A new box. It follows the height map when there is one to follow:
        a rework exists because a spot came out shallow, and on a board that
        is not flat, re-cutting it without the map reproduces the miss."""
        if depth is None:
            depth = self.depth.value()
        if follow is None:
            follow = self._height_map() is not None
        self._regions.append((min(x0, x1), min(y0, y1), max(x0, x1),
                              max(y0, y1), float(depth)))
        self._follow.append(bool(follow))
        self._rebuild_table()
        self._push()

    def follows(self):
        """One flag per box: does its cut follow the height map?"""
        return list(self._follow)

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
            lvl = QTableWidgetItem("")
            lvl.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled
                         | Qt.ItemIsSelectable)
            lvl.setCheckState(Qt.Checked if self._follow[r] else Qt.Unchecked)
            lvl.setToolTip("Follow the probed height map in this box.")
            self.table.setItem(r, 5, lvl)
        self.table.blockSignals(False)
        self._sync()

    def _on_edit(self, item):
        r = item.row()
        if item.column() == 5:
            self._follow[r] = item.checkState() == Qt.Checked
            return
        if item.column() != 4:
            return
        try:
            depth = float(item.text())
        except ValueError:
            self._rebuild_table()
            return
        x0, y0, x1, y1, _d = self._regions[r]
        self._regions[r] = (x0, y0, x1, y1, depth)

    def _remove(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()},
                      reverse=True)
        for r in rows:
            del self._regions[r]
            del self._follow[r]
        self._rebuild_table()
        self._push()

    def _clear(self):
        self._regions = []
        self._follow = []
        self._rebuild_table()
        self._push()

    def _push(self):
        self.ctl.stage.set_regions(
            [(x0, y0, x1, y1, SERIES[i % len(SERIES)])
             for i, (x0, y0, x1, y1, _d) in enumerate(self._regions)])

    def _sync(self):
        has = bool(self._regions)
        self.export_btn.setEnabled(has)
        self.sim_btn.setEnabled(has)
        self.status.setText("" if has else
                            "Nothing marked yet. Tick the box above and drag "
                            "over each spot that needs re-cutting.")

    # -- setup file --------------------------------------------------------
    def state(self):
        """What the setup file keeps: every box, whether each follows the
        map, the pass it repeats, and the depth for the next one."""
        return {"regions": [list(r) for r in self._regions],
                "follow": list(self._follow),
                "source": self.source.currentData(),
                "depth": float(self.depth.value())}

    def restore(self, data):
        data = data or {}
        regions = []
        for r in data.get("regions") or []:
            try:
                x0, y0, x1, y1, d = (float(v) for v in r)
            except (TypeError, ValueError):
                continue
            regions.append((min(x0, x1), min(y0, y1), max(x0, x1),
                            max(y0, y1), d))
        self._regions = regions
        try:
            self.depth.setValue(float(data.get("depth", self.depth.value())))
        except (TypeError, ValueError):
            pass
        src = data.get("source")
        if src is not None:
            i = self.source.findData(src)
            if i >= 0:
                self.source.setCurrentIndex(i)
        # A file from before the flag existed: the same default a new box
        # gets, decided against the map that was restored just before this.
        flags = data.get("follow")
        default = self._height_map() is not None
        self._follow = [bool(flags[i]) if isinstance(flags, list)
                        and i < len(flags) else default
                        for i in range(len(regions))]
        self._rebuild_table()
        self._push()

    # -- the clipped pass --------------------------------------------------
    def _source_paths(self, op):
        """The pass to repeat, as it was last drawn; None after saying why not."""
        st = self.ctl.state
        if st.board is None:
            self.ctl.say("warn", "Load a board first.")
            return None
        step = self._step_for(op)
        if step is None:
            self.ctl.say("warn", "This job has no such pass to repeat.")
            return None
        # The controller's toolpath for the step, not the state's: on a
        # double-sided job the pass that was cut is the LAYOUT'S, which the
        # dowel frame shifts across the bed, and a top-side pass is warped to
        # the measured flip. Clipping the plain board's paths instead wrote a
        # rework file for a board that was never cut where it says.
        cached = self.ctl._paths_cache.get(step.key)
        if cached is not None:
            return cached[0]               # the pass as it was last drawn
        self.ctl.stage.set_busy("Working out the pass to repeat…")
        QApplication.processEvents()
        try:
            paths, _far, _width = self.ctl._toolpaths_for(step)
        except Exception as e:
            self.ctl.report_error(
                "The source pass could not be generated", e,
                "The rework file is a clipped copy of a real pass, so "
                "that pass has to build first.")
            return None
        finally:
            self.ctl.stage.set_busy("")
        return paths

    def clipped_paths(self):
        """The rework itself: the chosen pass clipped to every box, at each
        box's depth, warped where the box says so. ``(runs, n_levelled)``,
        or None after saying what is missing."""
        if not self._regions:
            self.ctl.say("warn", "Draw a box first — there is nothing to "
                                 "re-cut yet.")
            return None
        op = self.source.currentData()
        paths = self._source_paths(op)
        if paths is None:
            return None
        st = self.ctl.state
        clipped, n = clip_boxes(
            paths, list(zip(self._regions, self._follow)),
            hmap=self._height_map(),
            ramp_step=st.cutout.cut_depth if op == "cutout" else None)
        if not clipped:
            self.ctl.say("warn", "None of those boxes contains any cutting "
                                 "from that pass — nothing to re-cut.")
            return None
        return clipped, n

    def _watch_in_3d(self):
        got = self.clipped_paths()
        if got is None:
            return
        clipped, _n = got
        n = len(self._regions)
        self.ctl.open_sim3d(
            clipped, f"{self.ctl.state.name or 'board'} — rework, "
                     f"{n} box{'' if n == 1 else 'es'}")

    # -- export ------------------------------------------------------------
    def _export(self):
        from gerber2rml.gui2 import workspace
        st = self.ctl.state
        got = self.clipped_paths()
        if got is None:
            return
        clipped, levelled = got
        op = self.source.currentData()
        backend = BACKENDS[st.machine]
        job = st.cutout if op == "cutout" else st.trace
        default = (workspace.remembered_dir("out", "exports")
                   + f"/{st.name}_{op}_rework{backend.ext}")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save the rework program", default,
            f"Machine program (*{backend.ext})")
        if not path:
            return
        n = len(self._regions)
        warped = ("" if not levelled else
                  f", {levelled} of {n} warped to the probed surface"
                  if levelled < n else ", warped to the probed surface")
        try:
            open(path, "w", encoding="utf-8").write(backend.render(
                clipped, xy_feed=job.xy_feed, plunge_feed=job.plunge_feed,
                header=[f"{st.name} - REWORK, {n} area(s)",
                        f"repeat of the {op} pass, clipped to the marked boxes"
                        + warped,
                        "re-zero Z first; do NOT move the XY origin"]))
        except OSError as e:
            self.ctl.report_error("The rework program could not be written", e)
            return
        workspace.remember_dir("out", path)
        self.status.setText(f"{len(clipped)} cut runs written"
                            + (f", {levelled} box{'' if levelled == 1 else 'es'}"
                               " following the height map." if levelled
                               else "."))
        self.ctl.say("ok", f"Rework program written with "
                           f"{n} area(s). Re-zero Z, then "
                           f"send it — the XY origin must be the one the "
                           f"board was cut on.")

    # -- from the photo ----------------------------------------------------
    def _detect_from_photo(self):
        """Propose a box wherever the photo shows no cut in a channel."""
        from gerber2rml.engine.cutcheck import CutCheckError, detect_uncut
        from gerber2rml.engine.photofit import fit_homography, warp_photo
        from gerber2rml.app.preview import toolpath_segments
        po = self.ctl.photo_overlay()
        if not po:
            self.ctl.say("warn", "Lay a photo of the board on the bed first "
                                 "— it is in the View menu.")
            return
        op = self.source.currentData()
        if op == "cutout":
            self.ctl.say("warn", "The detector walks isolation channels. "
                                 "Choose a traces pass to repeat first.")
            return
        paths = self._source_paths(op)
        if paths is None:
            return
        channels = [c for c in toolpath_segments(paths)[0] if len(c) >= 2]
        if not channels:
            self.ctl.say("warn", "That pass has no channels to walk.")
            return
        src = po.get("path")
        if not (src and Path(src).is_file()):
            self.ctl.say("warn", "The detector reads the photo file at full "
                                 "size, and that file is not where it was. "
                                 "Lay the photo on the bed again.")
            return
        st = self.ctl.state
        self.ctl.stage.set_busy("Reading the photo…")
        QApplication.processEvents()
        try:
            # Re-warped from the file, not taken from the stage: the overlay
            # is drawn at a resolution that loses the channel signature.
            img = self.ctl.decode_photo(src)
            H = fit_homography(po["photo_pts"], po["machine_pts"])
            wb = self.ctl.work_bounds()
            if wb is None:
                bx, by = BACKENDS[st.machine].bed or (203.2, 152.4)
                wb = (0.0, 0.0, bx, by)
            rgba, extent = warp_photo(img, H, (wb[0] - 2, wb[1] - 2,
                                               wb[2] + 2, wb[3] + 2),
                                      px_per_mm=DETECT_PX_PER_MM)
            bit = float(st.trace.effective_diameter())
            r = detect_uncut(rgba, extent, channels, bit_d=max(bit, 0.4),
                             exclude_outline=outline_xy(st.board.outline))
        except CutCheckError as e:
            self.ctl.stage.set_busy("")
            self.ctl.report_error(
                "The photo cannot judge these channels", e,
                "Either it covers too little of the toolpath, or the fit is "
                "off and every channel reads as uncut. Lay the photo on the "
                "bed again, shot straight down and evenly lit, and check the "
                "anchor residual it reports.")
            return
        except Exception as e:
            self.ctl.stage.set_busy("")
            self.ctl.report_error(
                "The photo could not be read", e,
                "Lay the photo on the bed again from the original file.")
            return
        self.ctl.stage.set_busy("")
        cov = (f"{r['n_suspect_tiles']} of {r['n_tiles']} readable 8 mm tiles "
               f"look failed; {r['decided_frac'] * 100:.0f}% of the samples "
               f"read clearly")
        if not r["boxes"]:
            self.ctl.say("ok", f"No uncut channel found in the photo ({cov}). "
                               "A cut that is merely too shallow does not "
                               "show here — probe the boxes for that.")
            return
        for b in r["boxes"]:
            self.add_region(*b)
        n = len(r["boxes"])
        self.ctl.say("warn", f"{n} suspect area{'' if n == 1 else 's'} boxed, "
                             f"most evidence first ({cov}). Look them over on "
                             f"the bed — the last few are usually dust or "
                             f"glare; remove those before exporting.")

    # -- probing -----------------------------------------------------------
    def _off_the_bed(self, points):
        """The centres the machine cannot reach, as a sentence, or ''."""
        bx, by = BACKENDS[self.ctl.state.machine].bed or (203.2, 152.4)
        off = [i + 1 for i, (x, y) in enumerate(points)
               if not (0.0 <= x <= bx and 0.0 <= y <= by)]
        if not off:
            return ""
        return ("Box%s %s sit%s outside the machine's travel, so the bit "
                "cannot reach %s. Remove or move %s first."
                % ("" if len(off) == 1 else "es",
                   ", ".join(map(str, off)),
                   "s" if len(off) == 1 else "",
                   "it" if len(off) == 1 else "them",
                   "it" if len(off) == 1 else "them"))

    def _probe_boxes(self):
        from gerber2rml.gui2.leveling import ProbeRun
        link = self.ctl.link
        if not self._regions:
            self.ctl.say("warn", "Draw a box first — there is nothing to "
                                 "probe yet.")
            return
        if not link.is_connected():
            self.ctl.say("warn", "Connect to the machine first — the button is "
                                 "on the bar at the bottom.")
            return
        if link.is_busy():
            self.ctl.say("warn", "The machine is still doing something. Wait "
                                 "for it to finish before probing.")
            return
        hmap = self._height_map()
        page = getattr(self.ctl, "level_page", None)
        pts = page.points(self._side()) if page is not None else []
        if hmap is None or not pts:
            self.ctl.say("warn", "The comparison needs this face's height map. "
                                 "Probe or load it on the Level the bed page "
                                 "first, and leave it switched on.")
            return
        centres = [((x0 + x1) / 2.0, (y0 + y1) / 2.0)
                   for (x0, y0, x1, y1, _d) in self._regions]
        off = self._off_the_bed(centres)
        if off:
            self.ctl.say("fail", off)
            return
        # The grid is measured from where the tool stands, exactly as the
        # levelling page does it (see its _probe for why): the firmware
        # probes at datum + (x, y), and the datum is the tool's position.
        pos = self.ctl.last_position()
        if pos is None:
            self.ctl.say("warn", "No live position yet — the points are "
                                 "measured from where the tool is standing, "
                                 "so the readout has to be alive first. Give "
                                 "it a moment and try again.")
            return
        ref = (float(pts[0][0]), float(pts[0][1]))
        n = len(self._regions)
        d = dialogs.Sheet(self, "Probe the boxes?", width=520)
        d.say(f"The bit taps the map's first point at X{ref[0]:.1f} "
              f"Y{ref[1]:.1f} for a datum, then the middle of each of the "
              f"{n} box{'' if n == 1 else 'es'}. Leave the tool a couple of "
              f"millimetres above the copper, spindle off, probe clip on the "
              f"copper.")
        d.say("STOP stops it at the next point. Boxes it did measure are "
              "still adjusted.", small=True)
        d.act("Cancel", on=d.reject)
        d.act(f"Probe {n} box{'' if n == 1 else 'es'}", kind="primary",
              on=d.accept, default=True)
        if d.exec() != QDialog.Accepted:
            return
        dx, dy = pos[0], pos[1]
        points = [(0, int(round((ref[0] - dx) * 1000)),
                   int(round((ref[1] - dy) * 1000)))]
        points += [(i + 1, int(round((cx - dx) * 1000)),
                    int(round((cy - dy) * 1000)))
                   for i, (cx, cy) in enumerate(centres)]
        port = (link.firmware or {}).get("port")
        # probe_grid opens the port itself, so the live link has to release
        # it. STOP still reaches the run through the link's abort event.
        link.mark_external(True)
        link.disconnect_from("handing the port to the probe run")
        link.clear_abort()
        self._probe_results = []
        self._probe_hmap, self._probe_ref = hmap, ref
        self.probe_btn.setEnabled(False)
        self.probe_state.setText(
            "Probing from X%.2f Y%.2f. STOP stops it at the next point."
            % (dx, dy))
        self._probe_run = ProbeRun(port, points, link.should_abort, self)
        self._probe_run.point.connect(self._probe_results.append)
        self._probe_run.finished.connect(
            lambda msg, p=port: self._on_probed(msg, p))
        self._probe_run.start()

    def _on_probed(self, msg, port):
        self.probe_btn.setEnabled(True)
        self.ctl.link.mark_external(False)
        # Take the port back first, so the readout and STOP are live again
        # whatever the numbers say.
        if port:
            self.ctl.link.connect_to(port)
        summary = self.apply_probe_results(self._probe_results)
        self.probe_state.setText(summary)
        if msg:
            self.ctl.say("warn", msg + " " + summary)
        else:
            self.ctl.say("ok" if "deepened" in summary or "already" in summary
                         else "warn", summary)

    def apply_probe_results(self, results, hmap=None, ref=None):
        """Fold a probe run into the boxes; returns the sentence to show."""
        hmap = hmap if hmap is not None else self._probe_hmap
        ref = ref if ref is not None else self._probe_ref
        if ref is None:
            return "Nothing measured."
        got = deepen_from_probe(self._regions, results, hmap, ref)
        if got is None:
            return ("The reference point had no contact, so nothing is "
                    "comparable — no box was changed. Check the probe clip "
                    "and try again.")
        regions, deepened, skipped = got
        self._regions = regions
        self._rebuild_table()
        self._push()
        if deepened:
            most = max(mm for _i, mm in deepened)
            text = (f"{len(deepened)} of {len(regions)} box"
                    f"{'' if len(regions) == 1 else 'es'} deepened to match "
                    f"the real copper — up to {most:.3f} mm more.")
        else:
            text = ("Every box already matches the real copper; the map was "
                    "right there.")
        if skipped:
            text += (f" {skipped} box{'' if skipped == 1 else 'es'} had no "
                     f"contact and {'is' if skipped == 1 else 'are'} unchanged.")
        return text
