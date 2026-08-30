"""The window: three regions, one bar, and the wiring between them.

    ┌──────────────────────────────────────────────────────────────┐
    │  header — frame switch, view controls, live coordinates       │
    ├────────────┬────────────────────────────────┬────────────────┤
    │ TRAVELLER  │            STAGE               │   INSPECTOR    │
    │ the plan,  │   the bed and the work,        │  whatever the  │
    │ in order   │   the one dominant object      │  selected step │
    │            │                                │  needs         │
    ├────────────┴────────────────────────────────┴────────────────┤
    │  MACHINE BAR — link, position, jog, spindle, ███ STOP ███     │
    └──────────────────────────────────────────────────────────────┘

The regions do not move, resize themselves, or swap places. The first
interface's settings column grows from 513 px to 1032 px as you walk its run
plan and overwrites any splitter position you set; here the rail and the
inspector are fixed widths and the stage takes everything left over, so the
window you arranged stays arranged.

Selecting a step in the traveller is the only thing that changes what is on
screen. It sets the stage's geometry and the inspector's page together, from
one handler, so the two cannot disagree about which operation you are looking
at.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QDesktopServices
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                               QLabel, QStackedWidget, QFileDialog, QApplication,
                               QInputDialog, QSizePolicy)

from gerber2rml.app.state import ProjectState
from gerber2rml.app.preview import toolpath_segments, traverse_segments
from gerber2rml.app import presets as presets_mod
from gerber2rml.backends import BACKENDS
from gerber2rml.engine import diagnostics as diag
from gerber2rml.engine import spoilboard
from gerber2rml.engine.drc import isolation_bridges
from gerber2rml.engine.estimate import estimate_file_seconds, format_duration

from gerber2rml.gui2 import (theme, widgets, style, runplan, tier, workspace,
                             dialogs)
from gerber2rml.gui2.stage import Stage
from gerber2rml.gui2.traveller import Traveller
from gerber2rml.gui2.inspector import Inspector
from gerber2rml.gui2.machine import MachineLink, MachineBar
from gerber2rml.gui2.leveling import LevelPage
from gerber2rml.gui2.rework import ReworkPage
from gerber2rml.gui2.fiducial import FlipFitPage
from gerber2rml.gui2.sheet import RunSheet

DEMO = Path(__file__).resolve().parents[2] / "examples" / "calibration"
FIXTURE = Path(__file__).resolve().parents[1] / "examples"


class Toast(QLabel):
    """Transient confirmations, and only those.

    Anything that matters after ten seconds goes on the traveller's banner or
    into the checks list instead. This is for "height map saved" and "linked on
    COM4" — sentences whose whole value is that you saw them happen.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFont(theme.font("small"))
        self.setWordWrap(True)
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_message(self, level, text):
        colours = {"ok": theme.VERIFIED, "warn": theme.CAUTION,
                   "fail": theme.DANGER, "info": theme.TEXT_2}
        fills = {"ok": theme.VERIFIED_FILL, "warn": theme.CAUTION_FILL,
                 "fail": theme.DANGER_FILL, "info": theme.PANEL_HI}
        edges = {"ok": theme.VERIFIED_EDGE, "warn": theme.CAUTION_EDGE,
                 "fail": theme.DANGER_EDGE, "info": theme.RULE_HI}
        self.setStyleSheet(
            f"color: {colours.get(level, theme.TEXT_2)};"
            f" background: {fills.get(level, theme.PANEL_HI)};"
            f" border: 1px solid {edges.get(level, theme.RULE_HI)};"
            f" border-radius: {theme.RADIUS}px; padding: 9px 13px;")
        self.setText(text)
        self.adjustSize()
        self.show()
        self.raise_()
        self._timer.start(9000 if level in ("warn", "fail") else 5000)


class MainWindow(QMainWindow):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = ProjectState()
        self.link = MachineLink(self)
        self.plan = None
        self._checks = []
        self._shorts = []
        self._exported = {}
        self._export_dir = None
        self._double = False
        self._registration = "dowel"
        self._layout_base = None       # the layout at offset (0, 0)
        self._layout_key = None        # what that base was built from
        self._layout_placed = None     # ...translated to the placement
        self._layout_placed_key = None
        self._paths_cache = {}         # step key -> (paths, far, cut width)
        self._last_pos = None
        self.stock = (0.0, 0.0, 100.0, 80.0)
        self.screwed = False

        self._build_ui()
        self._build_menus()
        self._load_presets()
        self.refresh_plan()
        self._sync_window_title()
        self.select_step("setup")
        self.resize(1400, 900)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        root = QWidget()
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        v.addWidget(self._build_header())
        v.addWidget(widgets.rule())

        middle = QWidget()
        h = QHBoxLayout(middle)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        self.traveller = Traveller()
        self.traveller.step_selected.connect(self.select_step)
        self.traveller.export_requested.connect(self.action_export)
        self.traveller.banner_action.connect(lambda: self.select_step("checks"))
        h.addWidget(self.traveller)
        h.addWidget(widgets.vrule())

        self.stage = Stage()
        self.stage.placement_changed.connect(self._on_drag)
        self.stage.placement_dragging.connect(self._on_dragging)
        self.stage.jog_requested.connect(self._on_jog_click)
        self.stage.hovered.connect(self._on_hover)
        self.stage.region_added.connect(self._on_region)
        self.stage.set_empty(
            "No board loaded",
            "File ▸ Open Gerber folder, or try the demo board")
        self.sheet = RunSheet()
        self.sheet.back.connect(lambda: self.centre.setCurrentWidget(self.stage))
        self.sheet.open_folder.connect(self.action_open_export_folder)
        self.sheet.copy_text.connect(self._copy_sheet)
        self.centre = QStackedWidget()
        self.centre.addWidget(self.stage)
        self.centre.addWidget(self.sheet)
        h.addWidget(self.centre, 1)

        h.addWidget(widgets.vrule())
        self.inspector = Inspector(self)
        self.level_page = self.inspector.add_page("level", LevelPage(self))
        self.rework_page = self.inspector.add_page("rework", ReworkPage(self))
        self.flipfit_page = self.inspector.add_page("fitflip", FlipFitPage(self))
        h.addWidget(self.inspector)
        v.addWidget(middle, 1)

        v.addWidget(widgets.rule())
        self.bar = MachineBar(self.link)
        self.bar.message.connect(self.say)
        self.bar.jog_mode_changed.connect(
            lambda on: self.set_stage_mode("jog" if on else "place"))
        self.link.position.connect(self._on_machine_position)
        self.link.unlinked.connect(lambda _r: self.stage.set_tool(None))
        v.addWidget(self.bar)

        self.setCentralWidget(root)
        self.toast = Toast(root)

        # Escape stops the machine from anywhere, including with a dialog's
        # child widget focused. It is the one shortcut that must never be
        # context-dependent.
        stop = QAction(self)
        stop.setShortcut(QKeySequence(Qt.Key_Escape))
        stop.setShortcutContext(Qt.ApplicationShortcut)
        stop.triggered.connect(self.bar._stop)
        self.addAction(stop)

    def _build_header(self):
        head = QWidget()
        head.setObjectName("panel")
        head.setFixedHeight(theme.HEADER_H)
        h = QHBoxLayout(head)
        h.setContentsMargins(theme.GAP_M + 2, 0, theme.GAP_M + 2, 0)
        h.setSpacing(theme.GAP_M)

        mark = QLabel("SRM·CAM")
        mark.setFont(theme.font("head"))
        mark.setStyleSheet(f"color: {theme.TEXT};")
        h.addWidget(mark)
        sub = QLabel("Roland SRM-20")
        sub.setFont(theme.font("label"))
        sub.setStyleSheet(f"color: {theme.TEXT_4};")
        h.addWidget(sub)

        h.addSpacing(theme.GAP_M)
        h.addWidget(widgets.vrule())
        h.addSpacing(theme.GAP_XS)

        self.frame_switch = widgets.Segmented(
            [("bed", "Bed — as cut",
              "Machine coordinates: exactly what the machine will do, in the "
              "frame VPanel and the position readout use."),
             ("xray", "Design X-ray",
              "The board as KiCad drew it, for checking that the two sides "
              "register. This is NOT what gets cut.")], "bed")
        self.frame_switch.changed.connect(self._on_frame)
        h.addWidget(self.frame_switch)

        h.addWidget(widgets.button("Fit", on=self.action_fit,
                                   tip="Frame the work. Scroll to zoom, "
                                       "right-drag to pan."))
        self.travel_btn = widgets.button(
            "Travel moves", on=self._toggle_travel,
            tip="Show the moves where the bit is in the air. Useful for "
                "spotting a path that crosses the board when it should go "
                "around.")
        self.travel_btn.setCheckable(True)
        self.travel_btn.setChecked(True)
        h.addWidget(self.travel_btn)

        h.addStretch(1)
        self.coords = QLabel("")
        self.coords.setFont(theme.font("small", mono=True))
        self.coords.setStyleSheet(f"color: {theme.TEXT_3};")
        self.coords.setMinimumWidth(150)
        self.coords.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        h.addWidget(self.coords)
        self.tier_chip = widgets.Chip("Essential", "idle")
        self.tier_chip.setToolTip(
            "Which set of controls is on screen. Interface ▸ tells you exactly "
            "what the other one adds.")
        h.addWidget(self.tier_chip)
        return head

    def _build_menus(self):
        mb = self.menuBar()

        f = mb.addMenu("&File")
        self._act(f, "Open Gerber folder…", self.action_open, "Ctrl+O")
        self._act(f, "Open the demo board", self.action_open_demo)
        f.addSeparator()
        self._act(f, "Save the setup…", self.action_save_setup, "Ctrl+S")
        self._act(f, "Load a setup…", self.action_load_setup)
        f.addSeparator()
        self._act(f, "Export the job…", self.action_export, "Ctrl+E")
        self._act(f, "Open the export folder", self.action_open_export_folder)
        f.addSeparator()
        self._act(f, "Quit", self.close, "Ctrl+Q")

        v = mb.addMenu("&View")
        self._act(v, "Fit the work", self.action_fit, "Ctrl+0")
        self._act(v, "Fit the whole bed", lambda: self.stage.fit(), "Ctrl+Shift+0")
        v.addSeparator()
        self._act(v, "Centre the job on the bed", self.action_autoplace, "Ctrl+B")
        v.addSeparator()
        self.xray_act = self._act(v, "Design X-ray", self._toggle_xray, "Ctrl+D",
                                  checkable=True)
        self.travel_act = self._act(v, "Travel moves", self._toggle_travel_menu,
                                    checkable=True, checked=True)

        m = mb.addMenu("&Machine")
        self._act(m, "Rescan the serial ports", self.bar.refresh_ports)
        self._act(m, "Connect / disconnect", self.bar._toggle_connect, "Ctrl+L")
        m.addSeparator()
        self._act(m, "Move the head to the View position",
                  self.action_view_position)
        m.addSeparator()
        self.screw_act = self._act(m, "Export the hold-down screw file…",
                                   self.action_export_screws)
        self.fixture_act = self._act(m, "Export the bed fixture (pin holes)…",
                                     self.action_export_fixture)
        m.addSeparator()
        self.stream_act = self._act(m, "Stream this step over the link "
                                       "(experimental)…", self.action_stream)

        i = mb.addMenu("&Interface")
        self.tier_group = QActionGroup(self)
        self.tier_group.setExclusive(True)
        self.essential_act = self._act(i, "Essential",
                                       lambda: self.set_tier(tier.ESSENTIAL),
                                       checkable=True)
        self.full_act = self._act(i, "Full",
                                  lambda: self.set_tier(tier.FULL),
                                  checkable=True)
        for a in (self.essential_act, self.full_act):
            self.tier_group.addAction(a)
        i.addSeparator()
        self._act(i, "What the two tiers differ by…",
                  lambda: dialogs.about_tier(self))

        h = mb.addMenu("&Help")
        self._act(h, "How this works", self.action_help)
        self._act(h, "About SRM-CAM", self.action_about)

        self._sync_tier()

    def _act(self, menu, text, slot, shortcut=None, *, checkable=False,
             checked=False):
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.setCheckable(checkable)
        a.setChecked(checked)
        a.triggered.connect(slot)
        menu.addAction(a)
        return a

    # -------------------------------------------------------------- tiers
    def set_tier(self, which):
        if not tier.set_tier(which):
            self.say("warn", "The tier is pinned by SRM_CAM_MODE on this "
                             "machine, so it cannot be switched here.")
        self._sync_tier()
        self.refresh_plan()
        self.inspector.setup.sync()

    def _sync_tier(self):
        full = tier.is_full()
        self.tier_chip.set("Full" if full else "Essential",
                           "live" if full else "idle")
        self.essential_act.setChecked(not full)
        self.full_act.setChecked(full)
        pinned = tier.pinned_tier() is not None
        self.essential_act.setEnabled(not pinned)
        self.full_act.setEnabled(not pinned)
        for a in (self.stream_act, self.fixture_act):
            a.setVisible(full)

    # ------------------------------------------------------- the ctl protocol
    def say(self, level, text):
        self.toast.show_message(level, text)
        self._place_toast()

    def report_error(self, headline, exc=None, guidance=""):
        dialogs.report_error(self, headline, exc, guidance)

    def is_done(self, key):
        return self.traveller.is_done(key)

    def last_position(self):
        """The machine's last reported XY, or None. Used by the fiducial
        capture, which is the only place that needs a live reading rather than
        a live display."""
        return self._last_pos

    def export_dir(self):
        return self._export_dir

    def job_extent(self):
        """Everything that has to fit inside the machine's travel, in machine mm.

        Wider than :meth:`work_bounds`: on a double-sided job the registration
        pins sit OUTSIDE the board, in the waste the cut-out removes, and a
        placement that puts the board on the bed but a dowel off it is a job
        that cannot be run.
        """
        if self.state.board is None:
            return None
        boxes = []
        if self._double:
            lay = self._ds_layout()
            if lay is not None:
                for g in (lay.outline, lay.bottom_copper, lay.top_copper):
                    if g is not None and not g.is_empty:
                        boxes.append(g.bounds)
                for (x, y, d) in lay.align_holes:
                    r = d / 2.0
                    boxes.append((x - r, y - r, x + r, y + r))
        else:
            for g in (self.state.board.outline, self.state.board.copper):
                if g is not None and not g.is_empty:
                    boxes.append(g.bounds)
        if not boxes:
            return None
        return (min(b[0] for b in boxes), min(b[1] for b in boxes),
                max(b[2] for b in boxes), max(b[3] for b in boxes))

    def action_autoplace(self):
        """Drop the whole job into the middle of the machine's travel.

        A board that nearly fills the bed does not want nudging into place a
        millimetre at a time — it wants centring, once, with whatever margin is
        left shared equally on both sides. That margin is the honest measure of
        how much room there is to be wrong by, so it is what the confirmation
        reports.
        """
        if self.state.board is None:
            self.say("warn", "Load a board first.")
            return
        extent = self.job_extent()
        if extent is None:
            return
        x0, y0, x1, y1 = extent
        bx, by = BACKENDS[self.state.machine].bed
        w, h = x1 - x0, y1 - y0
        # Move so the extent is centred: the gap either side is (bed - span)/2.
        self.state.set_placement(self.state.place_x + (bx - w) / 2.0 - x0,
                                 self.state.place_y + (by - h) / 2.0 - y0)
        self._paths_cache = {}
        self.inspector.setup.sync()
        self.refresh_checks()
        self._refresh_preview_now()
        self.stage.fit_work()
        mx, my = (bx - w) / 2.0, (by - h) / 2.0
        if mx < 0 or my < 0:
            over_x, over_y = max(0.0, -mx * 2), max(0.0, -my * 2)
            self.say("fail",
                     f"This job is bigger than the machine can reach — by "
                     f"{over_x:.1f} mm across and {over_y:.1f} mm up. It is "
                     f"centred, so the overhang is shared, but it cannot be "
                     f"cut as it is. Rotating it 90° may help.")
        else:
            what = "job" if not self._double else "job, dowels included,"
            self.say("ok", f"{w:.1f} × {h:.1f} mm {what} centred on the bed — "
                           f"{mx:.1f} mm spare each side, {my:.1f} mm front "
                           f"and back.")

    def work_bounds(self):
        """``(x0, y0, x1, y1)`` of the work, in MACHINE millimetres, or None.

        On a double-sided job the layout translates the board to make room for
        the registration holes, so the board's own bounds are not where the
        copper is. Anything that has to land ON the copper — the probe grid,
        above all — has to ask here rather than reach into ``state.board``.
        """
        if self.state.board is None:
            return None
        if self._double:
            lay = self._ds_layout()
            if lay is not None and lay.outline is not None                     and not lay.outline.is_empty:
                return lay.outline.bounds
        geom = (self.state.board.outline
                if self.state.board.outline is not None
                else self.state.board.copper)
        return None if geom is None or geom.is_empty else geom.bounds

    def _on_machine_position(self, x, y, _z, _touch):
        self._last_pos = (x, y)
        self.stage.set_tool((x, y))

    def exported_path(self, filename):
        return self._exported.get(filename)

    def set_stage_mode(self, mode):
        self.stage.set_mode(mode)
        if mode != "box":
            self.rework_page.add_chk.setChecked(False)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_toast()

    def _place_toast(self):
        if not self.toast.isVisible():
            return
        self.toast.setMaximumWidth(max(self.width() - theme.RAIL_W
                                       - theme.INSPECTOR_W - 60, 260))
        self.toast.adjustSize()
        x = theme.RAIL_W + 24
        y = self.height() - theme.BAR_H - self.toast.height() - 20
        self.toast.move(x, y)

    # ------------------------------------------------------------- the plan
    def refresh_plan(self):
        holes, align = None, None
        if self._double and self.state.board is not None:
            lay = self._ds_layout()
            if lay is not None:
                holes, align = lay.holes, lay.align_holes
        self.plan = runplan.build(self.state, double_sided=self._double,
                                  registration=self._registration, holes=holes,
                                  align_holes=align)
        if self._exported:
            self.plan.apply_estimates(
                {n: estimate_file_seconds(p) for n, p in self._exported.items()
                 if p.suffix == ".nc"})
        self.traveller.set_plan(self.plan)
        self.traveller.set_exported(
            {s.key for s in self.plan if s.file and s.file in self._exported})
        self._sync_job_header()
        self._sync_window_title()
        self.traveller.set_export_enabled(
            self.state.board is not None,
            "" if self.state.board is not None
            else "Load a Gerber folder first.")

    def _sync_window_title(self):
        """The job first, then the app. It is what tells two of these windows
        apart on a taskbar, and it is what a person is actually looking for."""
        from gerber2rml import __version__ as ver
        name = self.state.name if self.state.board is not None else None
        self.setWindowTitle(f"{name} — SRM-CAM {ver}" if name
                            else f"SRM-CAM {ver}")

    def _sync_job_header(self):
        st = self.state
        if st.board is None:
            self.traveller.set_job("No job", "Load a Gerber folder to begin")
            return
        x0, y0, x1, y1 = st.board.outline.bounds if st.board.outline is not None \
            else st.board.copper.bounds
        bits = [f"{x1 - x0:.1f} × {y1 - y0:.1f} mm",
                f"{len(st.board.holes)} holes"]
        if self.plan is not None and self.plan.single_tool:
            bits.append(f"one {self.plan.tool_label}")
        if self._double:
            bits.append("double-sided")
        if self.level_page.is_active():
            bits.append("levelled")
        self.traveller.set_job(st.name, " · ".join(bits))

    def select_step(self, key):
        if self.plan is None:
            return
        step = self.plan.by_key(key)
        if step is None:
            return
        self.traveller.select(key)
        self.inspector.show_step(step, self.plan)
        self.centre.setCurrentWidget(self.stage)
        self._draw_step(step)

    # --------------------------------------------------------- the drawing
    def refresh_preview(self):
        QTimer.singleShot(0, self._refresh_preview_now)

    def _refresh_preview_now(self):
        if self.plan is None:
            return
        key = self.traveller.current()
        step = self.plan.by_key(key) if key else None
        if step is not None:
            self._draw_step(step)

    def _draw_step(self, step):
        st = self.state
        if st.board is None:
            self.stage.clear_board()
            self.stage.set_legend([])
            return
        self._draw_board(step)
        cuts, rapids, far = [], [], []
        width = st.trace.effective_diameter()
        if step.op in ("traces", "drill", "cutout", "airpass", "align",
                       "top_traces"):
            cached = self._paths_cache.get(step.key)
            if cached is not None:
                # The SAME list objects go back to the stage, which lets it
                # recognise them and keep both its built QPainterPath and its
                # rendered raster. Handing it freshly-built equal lists would
                # cost a path rebuild and a full re-stroke for no reason.
                _p, _f, width, cuts, rapids, far = cached
                self.stage.set_toolpaths(cuts, rapids, far=far, cut_width=width)
                self._draw_shorts(step)
                self._set_legend(step)
                return
            self.stage.set_busy("Working out the toolpath…")
            QApplication.processEvents()
            try:
                paths, far_paths, width = self._toolpaths_for(step)
            except Exception as e:
                self.stage.set_busy("")
                self.stage.set_toolpaths([], [])
                self.report_error(
                    f"The {step.title.lower()} toolpath could not be built", e,
                    "The board geometry the engine got from these Gerbers is "
                    "not something it can offset. Check that Edge.Cuts is a "
                    "single closed outline and that the copper layer exported "
                    "cleanly.")
                return
            self.stage.set_busy("")
            cuts, rapids = toolpath_segments(paths)
            rapids = rapids + traverse_segments(paths)
            if far_paths:
                far, _ = toolpath_segments(far_paths)
            self._paths_cache[step.key] = (paths, far_paths, width,
                                           cuts, rapids, far)
            self._record_estimate(step, paths)
        self.stage.set_toolpaths(cuts, rapids, far=far, cut_width=width)
        self._draw_shorts(step)
        self._set_legend(step)

    def _record_estimate(self, step, paths):
        """Fill in a step's run time from the toolpath we just built.

        The estimate arrives when the toolpath does, which is when you select
        the step — so the rail fills in as you walk it rather than sitting empty
        until an export. Generating all of them up front would mean running the
        isolation offsetter on every board load, which on a ground-poured board
        is several seconds of nothing happening.
        """
        from gerber2rml.engine.estimate import estimate_toolpaths_seconds
        if step.kind != "run":
            return
        job = {"traces": self.state.trace, "top_traces": self.state.trace,
               "drill": self.state.drill, "align": self.state.drill,
               "cutout": self.state.cutout}.get(step.op)
        if job is None:                       # the dry run has its own feed
            from gerber2rml.engine.airpass import DEFAULT_FEED
            secs = estimate_toolpaths_seconds(paths, DEFAULT_FEED, DEFAULT_FEED)
        else:
            secs = estimate_toolpaths_seconds(paths, job.xy_feed, job.plunge_feed)
        step.seconds = secs
        self.traveller.refresh_step(step.key, self.plan)
        if self.inspector.stack.currentWidget() is self.inspector.step:
            self.inspector.step.est.set("~" + format_duration(secs))

    def _toolpaths_for(self, step):
        """(paths, far_side_paths, cut_width) for one step, in the machine frame."""
        from gerber2rml.engine.airpass import air_path
        from gerber2rml.engine.traces import isolate
        from gerber2rml.engine.drill import drill_single_bit, drill_holes
        from gerber2rml.engine.cutout import cut_outline
        st = self.state
        width = st.trace.effective_diameter()
        if not self._double:
            if step.op == "airpass":
                return air_path(st.board.outline), None, 0.4
            if step.op == "drill":
                return st.toolpaths("drill"), None, st.drill.bit_diameter
            if step.op == "cutout":
                return st.toolpaths("cutout"), None, st.cutout.bit_diameter
            return st.toolpaths("traces"), None, width
        lay = self._ds_layout()
        if lay is None:
            return [], None, width
        if step.op == "airpass":
            return air_path(lay.outline), None, 0.4
        if step.op == "align":
            return (drill_single_bit(lay.align_holes, st.drill), None,
                    st.drill.bit_diameter)
        if step.op == "drill":
            paths = (drill_single_bit(lay.holes, st.drill) if st.drill.single_bit
                     else drill_holes(lay.holes, st.drill))
            return paths, None, st.drill.bit_diameter
        if step.op == "cutout":
            return cut_outline(lay.outline, st.cutout), None, st.cutout.bit_diameter
        if step.op == "top_traces":
            return (isolate(lay.top_copper, st.trace, outline=lay.top_outline),
                    None, width)
        return (isolate(lay.bottom_copper, st.trace, outline=lay.outline),
                None, width)

    def _ds_layout(self):
        """The double-sided layout at the current placement.

        Cached on the things that change its SHAPE — the folder, the rotation
        and the registration scheme — and translated for placement, which
        changes only where it sits. That distinction matters: building the
        layout re-reads the Gerbers from disk, mirrors both copper layers and
        reflects them about the flip axis, while moving it is a handful of
        shapely translates. Rebuilding it for every millimetre of a drag is
        what made a full-bed board crawl behind the cursor.

        The translate is ``doublesided._offset_layout`` — the engine's own
        function, and the one ``layout_double_sided`` applies internally for
        its ``offset`` argument, so the result is the same object it would
        have built.
        """
        from gerber2rml.doublesided import layout_double_sided, _offset_layout
        if self.state.gerber_dir is None:
            return None
        key = (str(self.state.gerber_dir), self.state.rotate,
               self._registration)
        if self._layout_base is None or self._layout_key != key:
            try:
                self._layout_base = layout_double_sided(
                    self.state.gerber_dir, offset=(0.0, 0.0),
                    rotate=self.state.rotate, registration=self._registration)
                self._layout_key = key
            except Exception as e:
                self.report_error(
                    "This board cannot be set up as double-sided", e,
                    "Double-sided needs an F.Cu layer in the Gerber folder, "
                    "and enough waste copper around the board for the "
                    "registration holes. Untick 'copper on both faces' to "
                    "carry on single-sided.")
                self._double = False
                self.inspector.setup.double.setChecked(False)
                return None
        # The PLACED layout is cached as well, so that repeated asks at an
        # unchanged placement hand back the identical geometry objects. That is
        # what lets the stage recognise the board has not moved and keep its
        # built paths and its rendered raster.
        pkey = (key, round(self.state.place_x, 6), round(self.state.place_y, 6))
        if self._layout_placed is None or self._layout_placed_key != pkey:
            self._layout_placed = _offset_layout(
                self._layout_base, (self.state.place_x, self.state.place_y))
            self._layout_placed_key = pkey
        return self._layout_placed

    def _draw_board(self, step=None):
        """Draw the board in the frame the SELECTED step is cut in.

        On a double-sided job that means the top-side steps show the top face,
        and they show it where it will physically be after the flip — the holes
        reflected about the flip axis, not where they are now. A view that
        showed the bottom face's holes while you were looking at the top pass
        would be showing you a board that does not exist in that setup, and
        every serious scare in this program's history has been exactly that
        kind of frame mix-up.
        """
        st = self.state
        if self._double:
            from gerber2rml.doublesided import (preview_layout_double_sided,
                                                reflect_holes)
            lay = self._ds_layout()
            if lay is None:
                return
            if self.stage.frame == "xray":
                # X-ray is the registration check: both faces in the DESIGN
                # frame, where they are meant to overlay.
                try:
                    prev = preview_layout_double_sided(
                        st.gerber_dir, offset=(st.place_x, st.place_y),
                        rotate=st.rotate, registration=self._registration)
                    self.stage.set_board(prev.bottom_copper, prev.outline,
                                         prev.holes, copper_far=prev.top_copper,
                                         align_holes=prev.align_holes)
                    return
                except Exception:
                    pass
            if step is not None and step.side == "top":
                self.stage.set_board(
                    lay.top_copper, lay.top_outline,
                    reflect_holes(lay.holes, lay.axis, lay.flip_pos),
                    align_holes=lay.align_holes)
            else:
                self.stage.set_board(lay.bottom_copper, lay.outline, lay.holes,
                                     align_holes=lay.align_holes)
        else:
            self.stage.set_board(st.board.copper, st.board.outline,
                                 st.board.holes)
        self.stage.set_stock(self.stock if self.screwed else None)
        self._draw_screws()

    def _draw_screws(self):
        if not self.screwed or self.state.board is None:
            self.stage.set_screws([], [])
            return
        grid = spoilboard.measured_grid()
        bed = BACKENDS[self.state.machine].bed
        try:
            reach = [(x, y) for (_i, _j, x, y) in spoilboard.reachable(grid, bed)]
            picks = spoilboard.pick_fasteners(
                grid, self.stock, bed, keepout=self.state.board.copper)
        except Exception:
            reach, picks = [], []
        self.stage.set_screws(picks, reach)

    def _draw_shorts(self, step):
        if step.op in ("traces", "top_traces") and self.state.board is not None:
            self.stage.set_shorts(self._shorts)
        else:
            self.stage.set_shorts([])

    def _set_legend(self, step):
        """Only what is actually on the canvas.

        A key listing colours the current view does not contain teaches the
        reader that the key is decoration, and then they stop reading it.
        """
        cutting = step.op in ("traces", "drill", "cutout", "airpass", "align",
                              "top_traces")
        legend = []
        if cutting:
            legend.append((theme.PATH, "cutting"))
            if self.travel_btn.isChecked():
                legend.append((theme.TRAVEL, "in the air"))
        legend.append((theme.OUTLINE, "board edge"))
        if self.state.board is not None and self.state.board.holes:
            legend.append((theme.HOLE, "hole"))
        legend.append((theme.COPPER, "copper"))
        if self._double:
            # The far face is only PAINTED in the X-ray frame, so listing it in
            # the bed frame would be a key entry for something not on screen.
            if self.stage.frame == "xray":
                legend.append((theme.PATH_FAR, "far face"))
            legend.append((theme.FIXTURE, "registration pin"))
        if self.screwed:
            legend.append((theme.FIXTURE, "screw head, true size"))
        if self._shorts and step.op in ("traces", "top_traces"):
            legend.append((theme.DANGER, "cannot be separated"))
        if self.level_page._points:
            legend.append((theme.PROBE, "probe point"))
        self.stage.set_legend(legend)

    # ------------------------------------------------------------ the checks
    def refresh_checks(self):
        st = self.state
        if st.board is None:
            self._checks, self._shorts = [], []
            self.inspector.checks.set_checks([])
            self.traveller.clear_finding()
            return
        try:
            self._shorts = isolation_bridges(st.board.copper,
                                             st.trace.effective_diameter())
        except Exception:
            self._shorts = []           # a DRC that crashes must not block work
        depths = diag.cut_depths(st.trace, st.drill, st.cutout)
        bounds = None
        geom = st.board.outline if st.board.outline is not None else st.board.copper
        if geom is not None and not geom.is_empty:
            bounds = geom.bounds
        try:
            checks = diag.preflight(
                depths=depths, bed=BACKENDS[st.machine].bed,
                design_bounds=bounds, holes=st.board.holes,
                bit_diameter=st.drill.bit_diameter, trace=st.trace,
                leveled=self.level_page.is_active(), shorts=self._shorts,
                thickness=self.inspector.setup.thickness.value())
        except Exception as e:
            self.report_error("The pre-flight checks could not run", e,
                              "Reload the board and try again. Nothing has "
                              "been written.")
            return
        checks += self._screw_checks()
        self._checks = checks
        self.inspector.checks.set_checks(checks)
        self._sync_banner()

    def _screw_checks(self):
        if not self.screwed:
            return []
        out = []
        lowest = min(self.state.trace.travel_z, self.state.drill.travel_z,
                     self.state.cutout.travel_z)
        problem = spoilboard.travel_z_problem(lowest)
        if problem:
            out.append(diag.Check("fail", "A rapid would hit a screw head",
                                  problem))
        else:
            out.append(diag.Check(
                "ok", "Lift clears the screw heads",
                f"lifting {lowest:g} mm, heads stand "
                f"{spoilboard.M4_HEAD_H:g} mm above the copper."))
        try:
            picks = spoilboard.pick_fasteners(
                spoilboard.measured_grid(), self.stock,
                BACKENDS[self.state.machine].bed,
                keepout=self.state.board.copper)
        except Exception:
            return out
        if len(picks) < 4:
            out.append(diag.Check(
                "warn", "Fewer than four places to put a screw",
                f"only {len(picks)} grid hole(s) take a screw head that lands "
                f"fully on copper and clear of the design. The stock may be "
                f"too small, or the board too close to its edge."))
        else:
            spread = spoilboard.spread_problem(picks, self.stock)
            if spread:
                out.append(diag.Check("warn", "The screws are bunched together",
                                      spread))
        return out

    def _sync_banner(self):
        if self._shorts:
            worst = min(s["gap"] for s in self._shorts)
            self.traveller.show_finding(
                "fail",
                f"{len(self._shorts)} spots will be shorted",
                f"Worst gap {worst:.2f} mm against a "
                f"{self.state.trace.effective_diameter():.2f} mm cutter. "
                f"Milling it more carefully will not fix it.",
                action="See the checks")
            return
        fails = [c for c in self._checks if c.level == "fail"]
        warns = [c for c in self._checks if c.level == "warn"]
        if fails:
            self.traveller.show_finding(
                "fail", fails[0].title, fails[0].detail, action="See the checks")
        elif warns:
            self.traveller.show_finding(
                "warn", f"{len(warns)} thing"
                        f"{'s' if len(warns) != 1 else ''} to look at",
                warns[0].title, action="See the checks")
        else:
            self.traveller.clear_finding()

    # ------------------------------------------------------------- actions
    def action_open(self):
        d = QFileDialog.getExistingDirectory(
            self, "Choose the folder KiCad plotted into",
            workspace.remembered_dir("gerber"))
        if d:
            self.load_folder(d)

    def action_open_demo(self):
        if not DEMO.exists():
            try:
                from gerber2rml.examples.calibration import write_coupon
                DEMO.mkdir(parents=True, exist_ok=True)
                write_coupon(DEMO)
            except Exception as e:
                self.report_error("The demo board could not be created", e,
                                  "It is generated on first use and needs the "
                                  "examples folder to be writable.")
                return
        self.load_folder(str(DEMO))

    def load_folder(self, folder):
        """Programmatic load — the dialog path and the tests both come here."""
        try:
            self.state.load(folder)
        except Exception as e:
            self.report_error(
                "That folder could not be read as a board", e,
                "SRM-CAM needs a copper layer, an Edge.Cuts outline and a "
                "drill file in one folder — the set KiCad's Plot and Generate "
                "Drill Files produce. If the folder holds a zip, unpack it "
                "first.")
            return
        from gerber2rml.loader import gerber_stem
        try:
            stem = gerber_stem(Path(folder))
            if stem:
                self.state.name = stem
        except Exception:
            pass
        workspace.remember_dir("gerber", folder)
        self._paths_cache = {}
        self._exported = {}
        self._export_dir = None
        self.traveller.clear_done()
        self.stage._fitted = False
        self.refresh_plan()
        self.refresh_checks()
        self.select_step("setup")
        self.stage.fit_work()
        self.say("ok", f"Loaded {self.state.name} — "
                       f"{len(self.state.board.holes)} holes.")

    def action_apply_preset(self):
        name = self.inspector.setup.preset.currentText()
        table = presets_mod.load_presets()
        if name not in table:
            return
        presets_mod.apply_preset(self.state, table[name])
        self._after_params()
        self.say("ok", f"Applied “{name}”.")

    def action_save_preset(self):
        name, ok = QInputDialog.getText(self, "Save this tool profile",
                                        "Call it what?")
        if not ok or not name.strip():
            return
        try:
            presets_mod.save_user_preset(name.strip(), self.state)
        except OSError as e:
            self.report_error("The profile could not be saved", e,
                              "It goes in your home folder, under "
                              ".gerber2rml/presets.json.")
            return
        self._load_presets(select=name.strip())
        self.say("ok", "Profile saved.")

    def _load_presets(self, select=None):
        combo = self.inspector.setup.preset
        combo.blockSignals(True)
        combo.clear()
        table = presets_mod.load_presets()
        for name in table:
            combo.addItem(name)
        if select and select in table:
            combo.setCurrentText(select)
        combo.blockSignals(False)
        # The built-in profile is the lab's numbers, so it opens applied rather
        # than waiting for someone to notice there is an Apply button.
        if table and self.state.board is None:
            presets_mod.apply_preset(self.state, next(iter(table.values())))

    def action_thickness(self, thickness, overshoot, auto):
        if auto:
            depth = thickness + overshoot
            self.state.drill.total_depth = depth
            self.state.cutout.total_depth = depth
        self._after_params()

    def action_place(self, x, y):
        self.state.set_placement(x, y)
        self._paths_cache = {}
        self._after_params()

    def action_stock(self, w, h):
        self.stock = (0.0, 0.0, w, h)
        self._draw_screws()
        self.stage.set_stock(self.stock if self.screwed else None)
        self.refresh_checks()

    def action_rotate(self, deg):
        self.state.set_rotation(deg)
        self._paths_cache = {}
        self._after_params()
        QTimer.singleShot(0, self.stage.fit_work)

    def action_machine(self, name):
        if name in BACKENDS:
            self.state.machine = name
            self._after_params()

    def action_mirror(self, on):
        self.state.mirror = on
        if self.state.gerber_dir is not None:
            try:
                self.state.load(self.state.gerber_dir)
            except Exception as e:
                self.report_error("The board could not be re-read", e)
                return
        self._paths_cache = {}
        self._after_params()

    def action_double_sided(self, on):
        self._double = bool(on)
        self._paths_cache = {}
        self.inspector.setup.registration.setVisible(
            tier.is_full() and self._double)
        self._after_params()
        # Queued, not immediate: _after_params defers the preview rebuild, and
        # the registration pins only become part of the work bounds once that
        # has run. Fitting first would frame the board and leave a dowel just
        # off the top of the canvas.
        QTimer.singleShot(0, self.stage.fit_work)
        if on:
            self.say("info", "The cut-out has moved to after the flip — it is "
                             "what frees the board from its registration.")

    def action_registration(self, kind):
        self._registration = kind or "dowel"
        self._paths_cache = {}
        self._after_params()

    def action_screws_toggled(self, on):
        self.screwed = bool(on)
        if on:
            # Only ever raises. A higher value someone set on purpose is kept.
            need = spoilboard.min_travel_z()
            raised = []
            for job, label in ((self.state.trace, "traces"),
                               (self.state.drill, "drill"),
                               (self.state.cutout, "cut-out")):
                if job.travel_z < need:
                    job.travel_z = need
                    raised.append(label)
            if raised:
                self.say("warn", f"Lift raised to {need:g} mm on "
                                 f"{', '.join(raised)} — the screw heads stand "
                                 f"{spoilboard.M4_HEAD_H:g} mm proud and the "
                                 f"old lift would have driven into one.")
        self._after_params()

    def action_toggle_done(self, key):
        self.traveller.set_done(key, not self.traveller.is_done(key))
        step = self.plan.by_key(key)
        if step is not None:
            self.inspector.show_step(step, self.plan)

    def action_fit(self):
        self.stage.fit_work()

    def action_reveal(self):
        key = self.traveller.current()
        step = self.plan.by_key(key) if key else None
        path = self._exported.get(step.file) if step and step.file else None
        if path is None:
            return
        self._reveal(path)

    def action_open_export_folder(self):
        if self._export_dir is None:
            self.say("warn", "Nothing exported yet.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._export_dir)))

    def _reveal(self, path):
        path = Path(path)
        if sys.platform.startswith("win"):
            try:
                subprocess.Popen(["explorer", "/select,", str(path)])
                return
            except OSError:
                pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def action_copy_checks(self):
        from gerber2rml.engine.diagnostics import format_report
        QApplication.clipboard().setText(format_report(self._checks))
        self.say("ok", "Findings copied.")

    def _copy_sheet(self):
        QApplication.clipboard().setText(self.sheet.text())
        self.say("ok", "Run plan copied.")

    def action_view_position(self):
        if not self.link.is_connected():
            self.say("warn", "Connect to the machine first.")
            return
        from gerber2rml.engine import spi_probe
        self.link.submit("view", lambda ser: spi_probe.jump_to_view(ser))
        self.say("info", "Moving the head forward — keep clear of the bed.")

    # -------------------------------------------------------------- export
    def action_export(self):
        st = self.state
        if st.board is None:
            self.say("warn", "Load a Gerber folder first.")
            return
        self.refresh_checks()
        if self._shorts and not dialogs.confirm_shorts(
                self, self._shorts, st.trace.effective_diameter()):
            self.select_step("checks")
            return
        if self._double and self._registration == "dowel":
            if not dialogs.confirm_irreversible(
                    self, "The dowel holes go into the bed",
                    "Step 1 drills two holes through the stock and on into the "
                    "sacrificial bed. Those holes stay in the bed afterwards — "
                    "that is what makes the flip register, and it is also why "
                    "this is the one cut you cannot undo by re-zeroing and "
                    "trying again.\n\nRun the dry run before it.",
                    "Write the files"):
                return
        d = QFileDialog.getExistingDirectory(
            self, "Where should the machine files go?",
            workspace.remembered_dir("out", "exports"))
        if not d:
            return
        workspace.remember_dir("out", d)
        self.export_to(d)

    def export_to(self, out_dir):
        """Write every file in the plan. The test suite calls this directly."""
        st = self.state
        level = self.level_page.height_map()
        try:
            if self._double:
                from gerber2rml.doublesided import build_double_sided
                written = build_double_sided(
                    st.gerber_dir, out_dir, st.name, trace=st.trace,
                    drill=st.drill, cutout=st.cutout, machine=st.machine,
                    offset=(st.place_x, st.place_y), rotate=st.rotate,
                    level=level, registration=self._registration,
                    board_thickness=self.inspector.setup.thickness.value())
            else:
                written = st.export(out_dir, level=level)
        except Exception as e:
            self.report_error(
                "The job could not be exported", e,
                "Nothing has been written. If the folder is on a network "
                "drive or inside Program Files, try somewhere under your "
                "Documents instead.")
            return []
        self._export_dir = Path(out_dir)
        self._exported = {Path(p).name: Path(p) for p in written}
        self.refresh_plan()
        self.sheet.show_plan(
            self.plan, name=st.name, out_dir=self._export_dir,
            machine=st.machine, leveled=level is not None,
            double_sided=self._double)
        self.centre.setCurrentWidget(self.sheet)
        total = self.plan.total_seconds
        self.say("ok", f"{len(written)} files written"
                       + (f" · about {format_duration(total)} of cutting"
                          if total else ""))
        return written

    def action_export_screws(self):
        st = self.state
        if st.board is None:
            self.say("warn", "Load a board first.")
            return
        grid = spoilboard.measured_grid()
        bed = BACKENDS[st.machine].bed
        try:
            picks = spoilboard.pick_fasteners(grid, self.stock, bed,
                                              keepout=st.board.copper)
        except Exception as e:
            self.report_error("The screw positions could not be worked out", e)
            return
        if not picks:
            self.say("warn", "No grid hole takes a screw head that lands on "
                             "this piece of copper clear of the design.")
            return
        default = (workspace.remembered_dir("out", "exports")
                   + f"/{st.name}_screws{BACKENDS[st.machine].ext}")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save the hold-down screw program", default,
            f"Machine program (*{BACKENDS[st.machine].ext})")
        if not path:
            return
        backend = BACKENDS[st.machine]
        try:
            paths = spoilboard.fastener_toolpaths(
                picks, copper_thickness=self.inspector.setup.thickness.value())
            Path(path).write_text(backend.render(
                paths, xy_feed=st.drill.xy_feed,
                plunge_feed=st.drill.plunge_feed,
                header=[f"{st.name} - hold-down screw clearance holes",
                        "run this FIRST, drop the screws in, then re-zero Z"]))
            Path(path).with_suffix(".txt").write_text(
                spoilboard.procedure(picks, grid), encoding="utf-8")
        except Exception as e:
            self.report_error("The screw program could not be written", e)
            return
        workspace.remember_dir("out", path)
        self.say("ok", f"{len(picks)} screw holes written, with the procedure "
                       f"beside them.")

    def action_export_fixture(self):
        st = self.state
        from gerber2rml.engine import bedfixture
        if not dialogs.confirm_irreversible(
                self, "This drills three holes in the sacrificial bed",
                "The bed fixture is cut once per spoilboard, by whoever owns "
                "the machine. It drills three Ø3 mm dowel-pin holes into the "
                "bed so every future piece of stock lands on the same work "
                "origin.\n\nIt is the right thing to do once and the wrong "
                "thing to do casually.",
                "Write the fixture program"):
            return
        _x, _y, w, h = self.stock
        default = (workspace.remembered_dir("out", "exports")
                   + f"/bed_fixture{BACKENDS[st.machine].ext}")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save the bed fixture program", default,
            f"Machine program (*{BACKENDS[st.machine].ext})")
        if not path:
            return
        backend = BACKENDS[st.machine]
        try:
            paths = bedfixture.fixture_toolpaths(w, h)
            Path(path).write_text(backend.render(
                paths, xy_feed=st.drill.xy_feed,
                plunge_feed=st.drill.plunge_feed))
            Path(path).with_suffix(".txt").write_text(
                bedfixture.procedure(w, h), encoding="utf-8")
        except Exception as e:
            self.report_error("The fixture program could not be written", e)
            return
        self.say("ok", "Fixture program written, with the procedure beside it.")

    def action_stream(self):
        if not self.link.is_connected():
            self.say("warn", "Streaming needs the machine link. Connect first.")
            return
        key = self.traveller.current()
        step = self.plan.by_key(key) if key else None
        if step is None or step.kind != "run":
            self.say("warn", "Pick a numbered step in the plan to stream.")
            return
        try:
            paths, _far, _w = self._toolpaths_for(step)
        except Exception as e:
            self.report_error("That step could not be built", e)
            return
        moves = sum(len(p) for p in paths)
        choice = dialogs.stream_dialog(self, move_count=moves)
        if not choice["go"]:
            return
        from gerber2rml.engine import spi_stream
        self.link.clear_abort()

        def op(ser):
            # A wet run starts and stops the tool itself, so the operator is
            # never asked to remember. The RPM is a start/stop token — this
            # machine ignores the value and runs at VPanel's slider setting.
            return spi_stream.stream_toolpaths(
                ser, paths, dry_run=choice["dry"],
                spindle_rpm=0 if choice["dry"] else 7000,
                should_abort=self.link.should_abort)

        self.link.submit("stream", op)
        self.say("warn", "Streaming. STOP drops the move in flight.")

    # ---------------------------------------------------------- setup files
    def action_save_setup(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save this setup",
            workspace.remembered_dir("session", "sessions")
            + f"/{self.state.name}.srmcam", "SRM-CAM setup (*.srmcam)")
        if not path:
            return
        from dataclasses import asdict
        data = {
            "version": 1, "name": self.state.name,
            "gerber_dir": str(self.state.gerber_dir or ""),
            "machine": self.state.machine, "mirror": self.state.mirror,
            "place": [self.state.place_x, self.state.place_y],
            "rotate": self.state.rotate,
            "trace": asdict(self.state.trace), "drill": asdict(self.state.drill),
            "cutout": asdict(self.state.cutout),
            "double_sided": self._double, "registration": self._registration,
            "screwed": self.screwed, "stock": list(self.stock),
            "thickness": self.inspector.setup.thickness.value(),
        }
        try:
            Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError as e:
            self.report_error("The setup could not be saved", e,
                              "Pick a folder you can write to.")
            return
        workspace.remember_dir("session", path)
        self.say("ok", "Setup saved.")

    def action_load_setup(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load a setup",
            workspace.remembered_dir("session", "sessions"),
            "SRM-CAM setup (*.srmcam);;All files (*)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            self.report_error(
                "That is not a setup file this app wrote", e,
                "Setup files end in .srmcam and are written by File ▸ Save the "
                "setup.")
            return
        from dataclasses import replace
        st = self.state
        st.name = data.get("name", st.name)
        st.machine = data.get("machine", st.machine)
        st.mirror = bool(data.get("mirror", st.mirror))
        for key, attr in (("trace", "trace"), ("drill", "drill"),
                          ("cutout", "cutout")):
            if key in data:
                try:
                    setattr(st, attr, replace(getattr(st, attr), **data[key]))
                except TypeError:
                    pass                 # a field this version does not have
        self._double = bool(data.get("double_sided", False))
        self._registration = data.get("registration", "dowel")
        self.screwed = bool(data.get("screwed", False))
        self.stock = tuple(data.get("stock", self.stock))
        folder = data.get("gerber_dir")
        if folder and Path(folder).is_dir():
            self.load_folder(folder)
        px, py = data.get("place", [0, 0])
        st.set_rotation(data.get("rotate", 0))
        st.set_placement(px, py)
        self._paths_cache = {}
        self.inspector.setup.thickness.setValue(data.get("thickness", 1.6))
        self.inspector.setup.double.setChecked(self._double)
        self.inspector.setup.screwed.setChecked(self.screwed)
        self.inspector.setup.sync()
        self._after_params()
        workspace.remember_dir("session", path)
        self.say("ok", "Setup loaded.")

    # ----------------------------------------------------------------- misc
    def _after_params(self):
        self.refresh_plan()
        self.refresh_checks()
        self.refresh_preview()
        self.inspector.setup.sync()

    def _on_frame(self, which):
        self.stage.set_frame(which)
        self.xray_act.setChecked(which == "xray")
        self._refresh_preview_now()

    def _toggle_xray(self):
        self.frame_switch.set_current("xray" if self.xray_act.isChecked()
                                      else "bed")
        self._on_frame("xray" if self.xray_act.isChecked() else "bed")

    def _toggle_travel(self):
        self.stage.set_travel_visible(self.travel_btn.isChecked())
        self.travel_act.setChecked(self.travel_btn.isChecked())
        self._refresh_preview_now()

    def _toggle_travel_menu(self):
        self.travel_btn.setChecked(self.travel_act.isChecked())
        self._toggle_travel()

    def _on_dragging(self, dx, dy):
        """Live feedback while a drag is in flight, and nothing else.

        The stage is already drawing the work at the offset; all this does is
        keep the placement numbers honest as it moves. Signals are blocked so
        that setting them does not kick off the recompute the drag is
        deliberately avoiding.
        """
        setup = self.inspector.setup
        for spin, val in ((setup.place_x, self.state.place_x + dx),
                          (setup.place_y, self.state.place_y + dy)):
            spin.blockSignals(True)
            spin.setValue(val)
            spin.blockSignals(False)
        self.coords.setText(f"x {self.state.place_x + dx:7.2f}   "
                            f"y {self.state.place_y + dy:7.2f}")

    def _on_drag(self, dx, dy):
        """The drag landed. This is the one expensive moment, and it is once."""
        self.state.set_placement(self.state.place_x + dx,
                                 self.state.place_y + dy)
        self._paths_cache = {}
        self.inspector.setup.sync()
        self.refresh_checks()
        self._refresh_preview_now()

    def _on_jog_click(self, x, y):
        if not self.link.is_connected():
            self.say("warn", "Not connected — there is nothing to jog.")
            return
        bx, by = self.stage.bed
        if not (0 <= x <= bx and 0 <= y <= by):
            self.say("warn", "That point is off the machine's travel.")
            return
        self.link.jog_to(x, y)
        self.say("info", f"Jogging to X{x:.2f} Y{y:.2f}.")

    def _on_hover(self, pos):
        self.coords.setText("" if pos is None
                            else f"x {pos[0]:7.2f}   y {pos[1]:7.2f}")

    def _on_region(self, x0, y0, x1, y1):
        self.rework_page.add_region(x0, y0, x1, y1)

    def action_help(self):
        d = dialogs.Sheet(self, "How this works", width=620)
        d.say("The rail on the left is the run plan — the same order, and the "
              "same files, that get written when you export. Click any step to "
              "see it on the bed and its settings on the right. Nothing is "
              "locked: real runs jump around.")
        d.say("Work down it: set up the job, look at the checks, then export. "
              "The machine bar at the bottom is always there, and so is STOP — "
              "Escape does the same thing from anywhere.")
        d.say("Step 0 is a dry run. The spindle never starts and the bit is "
              "held 5 mm up, so it cannot cut; it traces where the board is "
              "about to be machined. It is twenty seconds and it is the "
              "cheapest way there is to find out the stock is in the wrong "
              "place.")
        d.say("The cut-out runs last. It is what frees the board from the "
              "sheet it is registered in.")
        d.act("Close", kind="primary", on=d.accept, default=True)
        d.exec()

    def action_about(self):
        from gerber2rml import __version__ as ver
        d = dialogs.Sheet(self, "SRM-CAM", width=520)
        d.say(f"Version {ver} · the second interface.")
        d.say("Gerber and Excellon files from KiCad, turned into programs for "
              "a Roland SRM-20, plus the run plan that says what order to send "
              "them in.")
        d.say("The engine is shared with the original interface — the same "
              "toolpaths, the same exported bytes.", small=True)
        d.act("Close", kind="primary", on=d.accept, default=True)
        d.exec()

    def closeEvent(self, e):
        try:
            self.link.disconnect_from("closing")
        except Exception:
            pass
        super().closeEvent(e)
