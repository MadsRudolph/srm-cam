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

from PySide6.QtCore import Qt, QTimer, QUrl, QEvent
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



def _and_list(items):
    """``"a"`` / ``"a and b"`` / ``"a, b and c"`` — for a sentence, not a log."""
    items = list(items)
    if len(items) <= 1:
        return items[0] if items else ""
    return ", ".join(items[:-1]) + " and " + items[-1]


def _as_gui2_setup(data):
    """Return ``(setup, unreadable)`` for a setup written by either interface.

    The first interface saves the same job under different names — ``place_x``
    /``place_y`` for one ``place`` pair, ``rotation`` for ``rotate``, a ``jobs``
    mapping for the three operation blocks, and a ``stock`` *dict* carrying the
    sheet's corner as well as its size. Read straight into this interface those
    all miss, and because every read has a default, the job came up placed at
    the origin, unrotated, with default cutting parameters and no copper — and
    said "Setup loaded.".

    Translating rather than refusing, because these files are the lab's real
    setups and the two interfaces deliberately share one workspace.
    """
    if "place" in data or "trace" in data:
        return data, []                  # already ours
    out = dict(data)
    unreadable = []
    if "place_x" in data or "place_y" in data:
        out["place"] = [data.get("place_x", 0.0), data.get("place_y", 0.0)]
    if "rotation" in data:
        out["rotate"] = data["rotation"]
    jobs = data.get("jobs")
    if isinstance(jobs, dict):
        # "traces" there, "trace" here; drill and cutout keep their names.
        for theirs, ours in (("traces", "trace"), ("drill", "drill"),
                             ("cutout", "cutout")):
            block = jobs.get(theirs)
            if isinstance(block, dict):
                out[ours] = block
    elif jobs is not None:
        unreadable.append("the cutting parameters")
    stock = data.get("stock")
    if isinstance(stock, dict):
        try:
            out["stock"] = [float(stock.get("x", 0.0)), float(stock.get("y", 0.0)),
                            float(stock["w"]), float(stock["h"])]
        except (KeyError, TypeError, ValueError):
            unreadable.append("the copper sheet")
            out.pop("stock", None)
        else:
            out["show_stock"] = bool(stock.get("show", True))
    # `reg_method` is the one that chooses dowels or fiducials. `reg` is the
    # dowel SUB-mode (fresh-milled versus the pin grid) and says nothing about
    # which scheme is in use - reading it turned a saved fiducial job into a
    # dowel job, silently, which is a different board.
    if "reg_method" in data and "registration" not in data:
        out["registration"] = "fiducial" if data["reg_method"] == 1 else "dowel"
    fid = data.get("fid")
    if isinstance(fid, dict):
        if "fid_diameter" not in data:
            try:
                out["fid_diameter"] = float(fid["diameter"])
            except (KeyError, TypeError, ValueError):
                pass                   # older setups predate a settable hole
        try:
            out["fid_count"] = int(fid["count"])
        except (KeyError, TypeError, ValueError):
            pass
        try:
            out["fid_offset"] = float(fid["offset"])
        except (KeyError, TypeError, ValueError):
            pass
        # 0 on board, 1 in the waste, 2 the manual placement this interface
        # has no equivalent for - which falls back to the corner scheme rather
        # than silently drilling somewhere the operator did not pick.
        place = fid.get("place")
        if place in (0, 1):
            out["fid_placement"] = "waste" if place == 1 else "onboard"
        elif place == 2:
            out["fid_placement"] = "onboard"
            unreadable.append("the hand-placed reference holes")
    return out, unreadable


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
        # Bigger than the bit, on purpose. The engine's default is 0.8 mm —
        # the same as the bit that drills it and the same as the bit that must
        # descend INSIDE it to probe it, which is a hole no bit can enter.
        self._fid_diameter = 1.6
        self._fid_count = 4
        self._fid_placement = "onboard"    # "onboard" | "waste"
        self._fid_offset = 4.0
        # Where the flipped board REALLY landed, from the measured fiducials.
        # Everything drawn for the top side goes through it, so the picture is
        # of the board in front of you and not the one you meant to put down.
        self._top_fit = None
        self._fid_measured = []
        self._layout_base = None       # the layout at offset (0, 0)
        self._layout_key = None        # what that base was built from
        self._layout_placed = None     # ...translated to the placement
        self._layout_placed_key = None
        self._paths_cache = {}         # step key -> (paths, far, cut width)
        self._current_step = None
        self._last_pos = None
        self.stock = (0.0, 0.0, 100.0, 80.0)
        self.show_stock = True
        self.show_bed = True     # the spoilboard grid; see _draw_screws
        self._manual_screws = None   # None = let the app choose them
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
        self.stage.screw_picked.connect(self._on_screw_click)
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
        # An ApplicationShortcut is NOT enough. Qt refuses to deliver a
        # shortcut owned by this window while a modal dialog is up, so Escape
        # reached the dialog's own reject() and the machine kept moving --
        # measured, with a modal dialog focused: the stop handler was not
        # called at all. Every dialog in this interface is modal, and zero_z /
        # touch_off drive the tool for up to a minute on the worker thread
        # while the UI stays live, so that gap is exactly where it matters.
        #
        # An application-wide event filter sees the key first, whatever is
        # focused. It never consumes the event, so Escape still closes a
        # dialog as anyone would expect -- it stops the machine as well.
        self._esc_down = False
        # Taken off again in closeEvent: the filter lives on the shared
        # application rather than on this window, so a window that goes away
        # without removing it leaves the application dispatching every key to
        # it. (Not hooked to `destroyed` - that fires after the C++ object is
        # gone, and passing it back to Qt raises.)
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, obj, ev):
        # One press, one stop. A filter on the application sees the same key
        # at the focused widget and again as it propagates to its window, and
        # holding the key repeats it; without this the operator gets a row of
        # identical toasts for a single press.
        if ev.type() == QEvent.KeyRelease and ev.key() == Qt.Key_Escape:
            self._esc_down = False
        elif (ev.type() == QEvent.KeyPress and ev.key() == Qt.Key_Escape
                and not self._esc_down):
            self._esc_down = True
            if self.link.can_stop_something():
                self.bar._stop()
            elif QApplication.activeModalWidget() is None:
                # Nothing to stop and no dialog in the way: say what does stop
                # this machine. Suppressed under a dialog, where Escape means
                # "close this" and the guidance would just be noise.
                self.bar._stop()
        return super().eventFilter(obj, ev)

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
        self.bed_act = self._act(v, "Spoilboard screw grid", self._toggle_bed,
                                 "Ctrl+G", checkable=True, checked=True)
        v.addSeparator()
        self._act(v, "Watch this step in 3D…", self.action_sim3d, "Ctrl+3")
        v.addSeparator()
        self._act(v, "Lay a photo of the board on the bed…",
                  self.action_load_photo)
        self.photo_clear_act = self._act(v, "Take the photo off",
                                         self.action_clear_photo)
        self.photo_clear_act.setEnabled(False)

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
        m.addSeparator()
        self.mtest_act = self._act(m, "Machine test…", self.action_machine_test)
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
        for a in (self.stream_act, self.fixture_act, self.mtest_act):
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

    def _centring_target(self):
        """What "centre it" should centre the job ON, and what to call it.

        The bed is the wrong answer whenever the copper is a particular sheet
        in a particular place: centring on the travel puts the job in the
        middle of the MACHINE, which on a sheet clamped off to one side is a
        job centred on bare spoilboard. What the job has to land on is metal.

        Metal the spindle can also reach, so the sheet is clipped to the
        travel — the far corner of a sheet that overhangs the bed is not
        somewhere a board can be put.
        """
        bx, by = BACKENDS[self.state.machine].bed
        sx, sy, sw, sh = self.stock
        if sw <= 0 or sh <= 0:
            return (0.0, 0.0, bx, by), "the bed"
        cx0, cy0 = max(0.0, sx), max(0.0, sy)
        cx1, cy1 = min(bx, sx + sw), min(by, sy + sh)
        if cx1 - cx0 <= 0 or cy1 - cy0 <= 0:
            # The sheet is entirely out of reach; centring on it is meaningless.
            return (0.0, 0.0, bx, by), "the bed"
        clipped = (cx0 > sx or cy0 > sy or cx1 < sx + sw or cy1 < sy + sh)
        return ((cx0, cy0, cx1, cy1),
                "the reachable part of the copper" if clipped else "the copper")

    def action_autoplace(self):
        """Drop the whole job into the middle of the copper it has to be cut from.

        A board that nearly fills the sheet does not want nudging into place a
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
        (tx0, ty0, tx1, ty1), what_on = self._centring_target()
        bx, by = tx1 - tx0, ty1 - ty0
        w, h = x1 - x0, y1 - y0
        # Move so the extent is centred: the gap either side is (target - span)/2.
        self.state.set_placement(
            self.state.place_x + tx0 + (bx - w) / 2.0 - x0,
            self.state.place_y + ty0 + (by - h) / 2.0 - y0)
        self._paths_cache = {}
        self.inspector.setup.sync()
        self.refresh_checks()
        self._refresh_preview_now()
        self.stage.fit_work()
        mx, my = (bx - w) / 2.0, (by - h) / 2.0
        if mx < 0 or my < 0:
            over_x, over_y = max(0.0, -mx * 2), max(0.0, -my * 2)
            self.say("fail",
                     f"This job does not fit on {what_on} — it is over by "
                     f"{over_x:.1f} mm across and {over_y:.1f} mm up. It is "
                     f"centred, so the overhang is shared, but it cannot be "
                     f"cut as it is. Rotating it 90°, or a bigger piece of "
                     f"copper, may help.")
        else:
            what = "job" if not self._double else "job, dowels included,"
            self.say("ok", f"{w:.1f} × {h:.1f} mm {what} centred on {what_on} — "
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
        self._current_step = step        # what the 3D view and Stream act on
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
            return (self._fit_paths(
                        isolate(lay.top_copper, st.trace,
                                outline=lay.top_outline)),
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
               self._registration, self._fid_diameter,
               self._fid_count, self._fid_placement, self._fid_offset)
        if self._layout_base is None or self._layout_key != key:
            try:
                self._layout_base = layout_double_sided(
                    self.state.gerber_dir, offset=(0.0, 0.0),
                    rotate=self.state.rotate, registration=self._registration,
                    fiducials=self.fiducial_spec())
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
                        rotate=st.rotate, registration=self._registration,
                        fiducials=self.fiducial_spec())
                    self.stage.set_board(prev.bottom_copper, prev.outline,
                                         prev.holes, copper_far=prev.top_copper,
                                         align_holes=prev.align_holes)
                    return
                except Exception:
                    pass
            if step is not None and step.side == "top":
                # AS PLACED once the fiducials have been measured: the flip is
                # where the board actually is, not where a perfect flip would
                # have put it. Jog, snap and rework all read this picture, so
                # they have to agree with the metal.
                self.stage.set_board(
                    self._fit_geom(lay.top_copper),
                    self._fit_geom(lay.top_outline),
                    self._fit_holes(
                        reflect_holes(lay.holes, lay.axis, lay.flip_pos)),
                    align_holes=self._fit_holes(lay.align_holes))
            else:
                self.stage.set_board(lay.bottom_copper, lay.outline, lay.holes,
                                     align_holes=lay.align_holes)
        else:
            self.stage.set_board(st.board.copper, st.board.outline,
                                 st.board.holes)
        self._sync_stock()
        self._draw_screws()

    def _draw_screws(self):
        """The spoilboard's tapped holes, and the screws chosen out of them.

        These are two different facts and used to share one switch. The grid is
        a property of the bed — it is worth seeing while deciding where to put
        the copper, with no board loaded and nothing screwed down — whereas the
        picked fasteners only mean anything once there is a job to clear.
        """
        grid = spoilboard.measured_grid()
        bed = BACKENDS[self.state.machine].bed
        reach, picks = [], []
        if self.show_bed or self.screwed:
            try:
                # Every hole in the plate, including the outer mounting ring.
                # `grid.holes()` skips that ring because a screw may not use
                # it, and drawing that subset put the picture a full 10 mm
                # pitch in from the real plate in both axes — it read as a
                # grid that would not line up with the holes in front of you.
                # This is a picture of the spoilboard; which holes are usable
                # is what `picks` is for.
                reach = [grid.centre(i, j)
                         for j in range(grid.ny) for i in range(grid.nx)]
            except Exception:
                reach = []
        if self.screwed:
            if self._manual_screws is not None:
                picks = list(self._manual_screws)
            elif self.state.board is not None:
                try:
                    picks = spoilboard.pick_fasteners(
                        grid, self.stock, bed, keepout=self.state.board.copper)
                except Exception:
                    picks = []
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
        checks += self._stock_checks()
        checks += self._screw_checks()
        self._checks = checks
        self.inspector.checks.set_checks(checks)
        self._sync_banner()

    def _stock_checks(self):
        """Is the job on the copper, and is the copper on the machine?

        `preflight` checks the job against the BED, which is the machine's
        travel. Neither it nor anything else checked it against the SHEET, and
        the two are not the same once the copper is not on the fixture: a job
        can sit perfectly inside the travel and still hang off the edge of the
        metal. That is a pass cutting air, and if the bed levelling grid is
        laid over the same footprint it is also a probe point descending onto
        bare spoilboard with nothing to touch off against.
        """
        out = []
        sx, sy, sw, sh = self.stock
        bx, by = BACKENDS[self.state.machine].bed
        over = max(0.0, (sx + sw) - bx), max(0.0, (sy + sh) - by)
        under = max(0.0, -sx), max(0.0, -sy)
        if any(over) or any(under):
            bits = []
            if over[0]: bits.append(f"{over[0]:.1f} mm past the right of the travel")
            if over[1]: bits.append(f"{over[1]:.1f} mm past the back of the travel")
            if under[0]: bits.append(f"{under[0]:.1f} mm left of X0")
            if under[1]: bits.append(f"{under[1]:.1f} mm in front of Y0")
            out.append(diag.Check(
                "warn", "Part of the copper is out of reach",
                "the sheet sits " + " and ".join(bits) + ". The spindle cannot "
                "get there, so nothing may be placed on that part of it."))
        wb = self.work_bounds()
        if wb is None:
            return out
        x0, y0, x1, y1 = wb
        out_l, out_b = max(0.0, sx - x0), max(0.0, sy - y0)
        out_r, out_t = max(0.0, x1 - (sx + sw)), max(0.0, y1 - (sy + sh))
        worst = max(out_l, out_r, out_b, out_t)
        if worst > 0.0:
            edges = []
            if out_l: edges.append(f"{out_l:.2f} mm off the left edge")
            if out_r: edges.append(f"{out_r:.2f} mm off the right edge")
            if out_b: edges.append(f"{out_b:.2f} mm off the front edge")
            if out_t: edges.append(f"{out_t:.2f} mm off the back edge")
            out.append(diag.Check(
                "fail", "The job runs off the copper",
                "the work hangs " + " and ".join(edges) + " of the sheet. "
                "Move the job, or set the sheet's real size and corner under "
                "The copper."))
        else:
            out.append(diag.Check(
                "ok", "The job is on the copper",
                f"nearest edge has "
                f"{min(x0 - sx, sx + sw - x1, y0 - sy, sy + sh - y1):.1f} mm "
                f"to spare."))
        return out

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
        # A measured flip belongs to one physical board on the bed. Carrying it
        # onto the next one would draw the new board where the old one landed.
        # A setup restore re-applies its own saved fit after this call.
        self._top_fit = None
        self._fid_measured = []
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

    def action_stock(self, w, h, x=None, y=None, show=None):
        # The corner is kept unless a caller passes a new one: editing the
        # sheet size used to reset the sheet to the machine origin, which
        # silently moved a hand-clamped sheet back under the fixture's
        # assumption.
        cx, cy, _w, _h = self.stock
        self.stock = (cx if x is None else x, cy if y is None else y, w, h)
        if show is not None:
            self.show_stock = bool(show)
        self._draw_screws()
        self._sync_stock()
        self.refresh_checks()

    def _sync_stock(self):
        """Draw the sheet when asked to, not only when it is screwed down.

        Tying the outline to the screw checkbox meant the one case that most
        needs it — a sheet clamped by hand, away from the fixture — was the
        case that never drew it.
        """
        self.stage.set_stock(self.stock
                             if (self.show_stock or self.screwed) else None)

    def action_load_photo(self):
        """Warp a photo of the real board into machine coordinates.

        Answers a question the design cannot: where the board ACTUALLY is, and
        what state it is actually in. A rework box drawn over the photo lands
        on the damage rather than on where the Gerbers say the damage should
        be.
        """
        from PySide6.QtWidgets import QDialog as _QDialog
        if self.state.board is None:
            self.say("warn", "Load a board first — the photo is lined up "
                             "against its drilled holes.")
            return
        holes = list(self.state.board.holes or [])
        if len(holes) < 4:
            self.say("warn", "This board has fewer than four drilled holes, "
                             "so there is nothing to line a photo up on.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "A photo of the board on the bed",
            workspace.remembered_dir("photo", "photos"),
            "Images (*.jpg *.jpeg *.png *.bmp)")
        if not path:
            return
        workspace.remember_dir("photo", path)
        try:
            import numpy as np
            from PySide6.QtGui import QImage
            img_q = QImage(path)
            if img_q.isNull():
                raise ValueError("the file is not an image this app can read")
            conv = img_q.convertToFormat(QImage.Format_RGBA8888)
            ptr = conv.constBits()
            arr = np.frombuffer(ptr, dtype=np.uint8).reshape(
                conv.height(), conv.bytesPerLine() // 4, 4)[:, :conv.width(), :]
            img = np.ascontiguousarray(arr)
        except Exception as e:
            self.report_error("That photo could not be opened", e,
                              "Try a JPEG or PNG straight off the camera.")
            return

        from gerber2rml.gui2 import photo as photo_mod
        anchors = photo_mod.pick_anchor_holes(holes)
        dlg = photo_mod.PhotoAnchorDialog(
            self, photo_mod.to_qimage(img), anchors, holes=holes,
            outline=self.state.board.outline)
        if dlg.exec() != _QDialog.Accepted:
            return
        try:
            worst = self._apply_photo(img, dlg.photo_points(),
                                      dlg.machine_points())
        except Exception as e:
            self.report_error(
                "The photo could not be lined up", e,
                "Four clicks that are nearly in a line cannot define the fit. "
                "Try again picking holes nearer the corners of the board.")
            return
        level = "ok" if worst < 0.5 else "warn"
        self.say(level, "Photo laid on the bed — worst anchor is "
                        "%.2f mm out. Anything over about half a millimetre "
                        "means a click was off, or the board moved." % worst)

    def _apply_photo(self, img, photo_pts, machine_pts):
        """Fit, warp, and hand the result to the stage. Returns the worst
        residual in mm, which is the only honest measure of whether to trust
        what is now on screen."""
        from gerber2rml.engine.photofit import (fit_homography, residuals,
                                                warp_photo)
        from gerber2rml.gui2 import photo as photo_mod
        H = fit_homography(photo_pts, machine_pts)
        res = residuals(H, photo_pts, machine_pts)
        wb = self.work_bounds()
        if wb is None:
            bx, by = BACKENDS[self.state.machine].bed or (203.2, 152.4)
            wb = (0.0, 0.0, bx, by)
        m = 5.0
        rgba, extent = warp_photo(img, H, (wb[0] - m, wb[1] - m,
                                           wb[2] + m, wb[3] + m))
        self.stage.set_photo(photo_mod.to_qimage(rgba), extent)
        self.stage.set_photo_dim(0.55)
        self.photo_clear_act.setEnabled(True)
        return float(res.max())

    def action_clear_photo(self):
        self.stage.set_photo(None, None)
        self.stage.set_photo_dim(0.0)
        self.photo_clear_act.setEnabled(False)
        self.say("ok", "Photo taken off — back to the design.")

    def action_sim3d(self):
        """Orbit the selected step's toolpath and play the tool along it.

        The stage answers "where does this cut?"; this answers "how deep, and
        in what order?", which is the question a plunge or a missed retract
        actually shows up in. Reads the same cached toolpath the stage drew,
        so selecting a step and opening this cannot disagree.
        """
        step = self._current_step
        op = getattr(step, "op", None)
        if self.state.board is None:
            self.say("warn", "Load a board first — there is no toolpath to "
                             "watch yet.")
            return
        # The dry run belongs here too: it is the step people most want to
        # watch before committing, and it has a real toolpath.
        if op not in ("airpass", "traces", "top_traces", "drill", "cutout"):
            self.say("warn", "Pick a step that cuts — the dry run, traces, "
                             "drill or the cut-out. The hands-on steps have "
                             "no toolpath of their own.")
            return
        try:
            paths, _far, _w = self._toolpaths_for(step)
        except Exception as e:
            self.report_error("That step's toolpath could not be worked out", e,
                              "Try selecting the step on the rail first.")
            return
        if not paths:
            self.say("warn", "That step's toolpath is empty — nothing to "
                             "watch.")
            return
        try:
            from gerber2rml.gui2.sim3d import Simulation3DWindow
        except Exception as e:
            self.report_error(
                "The 3D view could not start", e,
                "It needs pyqtgraph and PyOpenGL. Run "
                "'python -m gerber2rml.doctor' to install the interface "
                "dependencies, then try again.")
            return
        bounds = self.work_bounds()
        self._sim_window = Simulation3DWindow(
            paths, title=f"{self.state.name or 'board'} — {step.title}",
            parent=self, board=bounds, bed=BACKENDS[self.state.machine].bed,
            thickness=self.inspector.setup.thickness.value())
        self._sim_window.show()
        self._sim_window.raise_()
        self._sim_window.activateWindow()

    def action_machine_test(self):
        """Which SPI commands this machine obeys — a diagnostic, not a step.

        The panel opens the port itself, so the live link has to let go of it
        first, exactly as the grid prober does. Handed back on close, so the
        readout and STOP come straight back.
        """
        from gerber2rml.gui2.machinetest import MachineTestDialog
        port = self.bar.current_port()
        if not port:
            self.say("warn", "No serial port to test. Plug the Arduino in and "
                             "use Machine ▸ Rescan the serial ports.")
            return
        was_linked = self.link.is_connected()
        if was_linked:
            self.link.disconnect_from("handing the port to the machine test")
        dlg = MachineTestDialog(port, self)
        dlg.exec()
        if was_linked:
            self.link.connect_to(port)

    def action_stock_corner_here(self):
        """Take the tool's current X and Y as the copper's front-left corner.

        The bed fixture puts that corner on the machine origin, but a sheet
        clamped by hand is wherever it landed, and typing a corner measured
        with a rule is the step people get wrong. Reading it off the machine
        is the same gesture as zeroing Z, and it is a pure read — no motion is
        commanded and the work origin is not touched.
        """
        if not self.link.is_connected():
            self.say("warn", "Connect to the machine first — the button is on "
                             "the bar at the bottom.")
            return
        pos = self.link.last_position
        if pos is None:
            self.say("warn", "No position from the machine yet. Give the "
                             "readout a moment and try again.")
            return
        x, y = round(pos[0], 2), round(pos[1], 2)
        _cx, _cy, w, h = self.stock
        self.action_stock(w, h, x, y, self.show_stock)
        self.inspector.setup.sync()
        self.say("ok", f"Copper corner set to X {x:.2f}, Y {y:.2f} — the "
                       f"sheet now sits {w:.0f} x {h:.0f} mm from there.")

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

    def set_top_fit(self, transform, measured=None):
        """Adopt (or clear) the measured flip, and redraw with it."""
        self._top_fit = transform
        if measured is not None:
            self._fid_measured = [tuple(p) for p in measured]
        self._paths_cache = {}
        self.refresh_preview()

    def _fit_paths(self, paths):
        if self._top_fit is None or not paths:
            return paths
        from gerber2rml.engine.fiducial import apply_to_toolpaths
        return apply_to_toolpaths(paths, self._top_fit)

    def _fit_holes(self, holes):
        if self._top_fit is None or not holes:
            return holes
        return [(*self._top_fit.apply(x, y), d) for (x, y, d) in holes]

    def _fit_geom(self, g):
        if self._top_fit is None or g is None:
            return g
        from shapely import affinity
        t = self._top_fit
        import math
        c, s_ = math.cos(t.theta) * t.scale, math.sin(t.theta) * t.scale
        return affinity.affine_transform(g, [c, -s_, s_, c, t.tx, t.ty])

    def fiducial_spec(self):
        """The fiducial geometry this job uses, as the engine wants it.

        One home for it: the layout, the X-ray preview, the export and the
        flip-fit page all have to agree about where the holes are and how big,
        and defaulting the spec separately in four places is how they stop
        agreeing.

        Everything here used to be the engine's default, which meant a job
        saved with holes in the waste came back with them drilled through the
        board — the same four reference holes, in a different place.
        """
        from gerber2rml.doublesided import FiducialSpec
        return FiducialSpec(count=self._fid_count,
                            placement=self._fid_placement,
                            edge_offset=self._fid_offset,
                            hole_diameter=self._fid_diameter)

    def action_fiducial_layout(self, count, placement, offset):
        self._fid_count = int(count)
        self._fid_placement = placement
        self._fid_offset = float(offset)
        self._layout_base = None
        self._layout_key = None
        self._paths_cache = {}
        self._after_params()
        self.refresh_preview()

    def action_fiducial_diameter(self, mm):
        self._fid_diameter = float(mm)
        self._layout_base = None          # geometry changed; drop the cache
        self._layout_key = None
        self._paths_cache = {}
        self._after_params()
        self.refresh_preview()

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
                    fiducials=self.fiducial_spec(),
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
        # Hand-picked holes win. The automatic pass will not offer a hole it
        # considers bad, and on a sheet where it can find none at all its
        # refusal is the only answer the operator gets - so the file has to
        # come from the same set that is drawn on the bed, not a second
        # opinion computed here.
        grid = spoilboard.measured_grid()      # also names the holes in the
                                              # procedure text, either way
        if self._manual_screws is not None:
            picks = list(self._manual_screws)
        else:
            bed = BACKENDS[st.machine].bed
            try:
                picks = spoilboard.pick_fasteners(grid, self.stock, bed,
                                                  keepout=st.board.copper)
            except Exception as e:
                self.report_error("The screw positions could not be worked out", e)
                return
        if not picks:
            self.say("warn", "No screw holes chosen, and no grid hole takes a "
                             "screw head that lands on this piece of copper "
                             "clear of the design. Tick 'Held down with M4 "
                             "screws' and choose them yourself on the bed.")
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
        except Exception as e:
            self.report_error(
                "The screw program could not be written", e,
                "Nothing has been written. If the folder is on a network "
                "drive or inside Program Files, try somewhere under your "
                "Documents instead.")
            return
        try:
            Path(path).with_suffix(".txt").write_text(
                spoilboard.procedure(picks, grid), encoding="utf-8")
        except Exception as e:
            # The program itself is on disk and is the part that matters, so
            # say what IS there rather than reporting a failure over a file
            # that was written.
            self.report_error(
                "The screw program is written, but not its procedure", e,
                f"{Path(path).name} is on disk and can be run. Only the "
                f"instructions beside it are missing.")
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
            "fid_diameter": self._fid_diameter,
            "fid_count": self._fid_count,
            "fid_placement": self._fid_placement,
            "fid_offset": self._fid_offset,
            "manual_screws": (None if self._manual_screws is None
                              else [list(p) for p in self._manual_screws]),
            "top_fit": ([self._top_fit.theta, self._top_fit.scale,
                         self._top_fit.tx, self._top_fit.ty]
                        if self._top_fit is not None else None),
            "fid_measured": [list(p) for p in (self._fid_measured or [])],
            # The probed surface. Nine points is nine physical touches and a
            # couple of minutes of machine time; a measurement that does not
            # survive closing the app is one nobody relies on.
            "level": self.level_page.state(),
            "show_stock": self.show_stock, "show_bed": self.show_bed,
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
        data, foreign = _as_gui2_setup(data)
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
        # 0.8 for setups written before it was settable, so an old job
        # reproduces exactly what it produced then.
        self._fid_diameter = float(data.get("fid_diameter", 0.8))
        self._fid_count = int(data.get("fid_count", 4))
        self._fid_placement = data.get("fid_placement", "onboard")
        self._fid_offset = float(data.get("fid_offset", 4.0))
        self.screwed = bool(data.get("screwed", False))
        stock = data.get("stock", self.stock)
        try:
            x, y, w, h = (float(v) for v in stock)
            self.stock = (x, y, w, h)
        except (TypeError, ValueError):
            # Not four numbers. Keep the sheet we had rather than storing
            # something the stage cannot unpack — a dict's keys, say.
            foreign.append("the copper sheet")
        self.show_stock = bool(data.get("show_stock", True))
        self.show_bed = bool(data.get("show_bed", self.show_bed))
        ms = data.get("manual_screws")
        self._manual_screws = (None if ms is None
                               else [(float(x), float(y)) for x, y in ms])
        self.bed_act.setChecked(self.show_bed)
        folder = data.get("gerber_dir")
        if folder and Path(folder).is_dir():
            self.load_folder(folder)
        # After load_folder, which names the job from the folder it read: the
        # name saved with the setup is the one the operator chose.
        if data.get("name"):
            st.name = data["name"]
        # ...and which also cleared the measured flip, so re-apply the saved
        # one here. The AS PLACED views, jog and rework all follow it, so a
        # restored job comes back describing the same physical board.
        tf = data.get("top_fit")
        if tf:
            try:
                from gerber2rml.engine.fiducial import Transform
                self._top_fit = Transform(*[float(v) for v in tf])
            except (TypeError, ValueError):
                foreign.append("the measured flip")
        self._fid_measured = [(float(x), float(y))
                              for x, y in (data.get("fid_measured") or [])]
        try:
            self.level_page.restore(data.get("level"))
        except Exception:
            foreign.append("the height map")
        px, py = data.get("place", [0, 0])
        st.set_rotation(data.get("rotate", 0))
        st.set_placement(px, py)
        self._paths_cache = {}
        self.inspector.setup.thickness.setValue(data.get("thickness", 1.6))
        self.inspector.setup.double.setChecked(self._double)
        self.inspector.setup.screwed.setChecked(self.screwed)
        self.inspector.setup.sync()
        self._after_params()
        self._sync_stock()
        self._draw_screws()
        workspace.remember_dir("session", path)
        if foreign:
            # Never "Setup loaded." over a job that is not the saved one. A
            # placement silently reset to the origin is a job that cuts in the
            # wrong place.
            self.say("warn", "Setup loaded, but " + _and_list(foreign)
                     + " could not be read from this file — check the job "
                       "before you cut.")
        else:
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

    def _toggle_bed(self):
        self.show_bed = self.bed_act.isChecked()
        self._draw_screws()
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

    def _on_screw_click(self, x, y):
        """Toggle the spoilboard hole nearest the click.

        Any hole may be chosen, including one the automatic pass rejected. The
        operator can see the bed and may have a reason the app does not know
        about, so a doubtful pick is reported and kept rather than refused —
        the same call the first interface makes.
        """
        grid = spoilboard.measured_grid()
        best, best_d2 = None, (grid.pitch / 2.0) ** 2
        for j in range(grid.ny):
            for i in range(grid.nx):
                hx, hy = grid.centre(i, j)
                d2 = (hx - x) ** 2 + (hy - y) ** 2
                if d2 <= best_d2:
                    best, best_d2 = (hx, hy), d2
        if best is None:
            self.say("warn", "No spoilboard hole there — click closer to one.")
            return
        current = list(self._manual_screws if self._manual_screws is not None
                       else self._auto_screws())
        key = (round(best[0], 3), round(best[1], 3))
        kept = [p for p in current if (round(p[0], 3), round(p[1], 3)) != key]
        if len(kept) == len(current):
            kept.append(best)
            problem = spoilboard.point_problem(
                best, self.stock,
                keepout=(self.state.board.copper
                         if self.state.board is not None else None))
            if problem:
                self.say("warn", "Screw at X%.1f Y%.1f %s. Kept — you can see "
                                 "the bed, but check it." % (best[0], best[1],
                                                             problem))
            else:
                self.say("ok", "Screw at X%.1f Y%.1f. %d chosen."
                         % (best[0], best[1], len(kept)))
        else:
            self.say("info", "Screw at X%.1f Y%.1f removed. %d left."
                     % (best[0], best[1], len(kept)))
        self._manual_screws = kept
        self._draw_screws()
        self.refresh_checks()

    def _auto_screws(self):
        try:
            return spoilboard.pick_fasteners(
                spoilboard.measured_grid(), self.stock,
                BACKENDS[self.state.machine].bed,
                keepout=(self.state.board.copper
                         if self.state.board is not None else None))
        except Exception:
            return []

    def action_pick_screws(self, on):
        self.set_stage_mode("screws" if on else "place")
        if on:
            self.say("info", "Click the spoilboard holes to screw through. "
                             "Click one again to drop it.")

    def action_reset_screws(self):
        self._manual_screws = None
        self._draw_screws()
        self.refresh_checks()
        self.say("ok", "Back to the holes the app would choose.")

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
        try:
            # The stop-key filter lives on the shared application, not on this
            # window, so it has to be taken off by hand or it outlives us.
            QApplication.instance().removeEventFilter(self)
        except Exception:
            pass
        super().closeEvent(e)
