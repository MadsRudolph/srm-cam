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
from gerber2rml.app.panel import PANEL_GAP_MM
from gerber2rml import platform as plat
from gerber2rml.backends import BACKENDS
from gerber2rml.engine import diagnostics as diag
from gerber2rml.engine import spoilboard

FOIL_MM = 0.035        # copper foil on 1.6 mm FR-4; what a cut must break

# How far the cutter pushes an unsupported board down, as a share of how far
# it arches between its fixings. The probe measured that arch at no force and
# the warp already cuts along it; what is left uncovered is the give under
# the cutter, and a 0.8 mm endmill at 4 mm/s does not push a board flat.
# Charging the whole arch cut a 0.15 mm trace 0.5 mm deep on a real board
# (2026-09-03). A quarter, capped: a sheet that arches more than this wants
# re-fixing, not a deeper cut.
FLEX_FRACTION = 0.25
FLEX_CAP_MM = 0.12


def fit_plane(points):
    """Least-squares ``z = ax + by + c`` through ``(x, y, z)`` points.

    Returns ``(a, b, c)``, or None when the points determine no single plane -
    fewer than three of them, or all on one line.
    """
    n = len(points)
    if n < 3:
        return None
    sx = sy = sz = sxx = syy = sxy = sxz = syz = 0.0
    for x, y, z in points:
        sx += x
        sy += y
        sz += z
        sxx += x * x
        syy += y * y
        sxy += x * y
        sxz += x * z
        syz += y * z
    m = [[sxx, sxy, sx, sxz],
         [sxy, syy, sy, syz],
         [sx, sy, float(n), sz]]
    scale = max(abs(v) for row in m for v in row) or 1.0
    for i in range(3):
        p = max(range(i, 3), key=lambda r: abs(m[r][i]))
        if abs(m[p][i]) <= 1e-9 * scale:
            return None                       # singular: collinear points
        m[i], m[p] = m[p], m[i]
        for r in range(i + 1, 3):
            f = m[r][i] / m[i][i]
            for c in range(i, 4):
                m[r][c] -= f * m[i][c]
    sol = [0.0, 0.0, 0.0]
    for i in (2, 1, 0):
        sol[i] = (m[i][3] - sum(m[i][c] * sol[c]
                                for c in range(i + 1, 3))) / m[i][i]
    return tuple(sol)


def flex_residual(points):
    """How much of a height map a plane cannot account for, in mm.

    Levelling cancels tilt exactly: warping every Z by the map cuts a sloped
    but rigid sheet to a constant depth. What it cannot cancel is the board
    moving away from the cutter, and in the map that shows up as curvature -
    what is left once the best-fit plane is subtracted.

    Three points define a plane perfectly, so they leave no residual. That is
    the honest answer rather than a shortcoming: three points carry no
    evidence of arch, and a probe that wants the margin to mean something
    needs a finer grid. Returns None if no plane can be fitted.
    """
    plane = fit_plane(points)
    if plane is None:
        return None
    a, b, c = plane
    res = [z - (a * x + b * y + c) for x, y, z in points]
    return max(res) - min(res)

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
        self._drawing = False          # a toolpath is being built right now
        self._redraw_after = False     # ...and a redraw was asked for meanwhile
        self._last_pos = None
        self.stock = (0.0, 0.0, 100.0, 80.0)
        # Whether the operator has SAID where the copper is. The default
        # sheet above is a placeholder for the picture; nothing that cuts
        # may treat its edges as real until a size or corner has been set.
        self._stock_set = False
        self.show_stock = True
        self.show_bed = True     # the spoilboard grid; see _draw_screws
        self._manual_screws = None   # None = let the app choose them
        # How the copper is held down, which decides whether the probed
        # surface is the surface that gets CUT. See _flex_margin.
        self._hold = "points"        # "bonded" | "points"
        # The extra depth for a board held at points: worked out from the
        # probe map, or typed. A number the operator has cut with beats any
        # estimate, and a board that keeps coming out deep is the case for it.
        self._flex_auto = True
        self._flex_mm = 0.0
        self.screwed = False
        # The job is named after the folder, or after every board on the
        # sheet, until the operator types a name; then it is theirs.
        self._custom_name = False

        self._build_ui()
        self._build_menus()
        self._sync_frame_options()
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
        self.stage.board_picked.connect(self.action_select_board)
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
        self.link.op_done.connect(self._on_op_done)
        self.link.linked.connect(self._on_linked)
        self.link.unlinked.connect(self._on_unlinked)
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
        self._act(f, "Add another board to the sheet…", self.action_add_board,
                  "Ctrl+Shift+O")
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
        self._act(v, "Lay the boards side by side", lambda: self.action_arrange())
        self._act(v, "Butt the boards together",
                  lambda: self.action_arrange(0.0))
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
        self._act(v, "Take one with a phone…", self.action_phone_photo)
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
        # Every board by the same amount, so a panel keeps its shape.
        self.state.move_all(tx0 + (bx - w) / 2.0 - x0,
                            ty0 + (by - h) / 2.0 - y0)
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
            what = ("job, dowels included," if self._double
                    else f"panel of {len(self.state.boards)} boards"
                    if self.state.is_panel else "job")
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
        sim = self._sim()
        if sim is not None:
            sim.set_live_position(x, y)

    def _on_op_done(self, name, _result):
        """A touch just measured where the copper is: the Z-reach check can
        be answered now instead of hedged."""
        if name in ("zero_z", "touch") and self.state.board is not None:
            self.refresh_checks()

    def _on_linked(self, _info):
        sim = self._sim()
        if sim is not None:
            sim.set_live_enabled(True)

    def _on_unlinked(self, _reason):
        self.stage.set_tool(None)
        sim = self._sim()
        if sim is not None:
            sim.set_live_enabled(False)
        # A probe run measures its grid from the last live position. After
        # a reconnect the first fresh reading is a poll away, and the stale
        # one was the LAST probe point - so a second run started in that
        # window was laid out from the wrong datum, off the board.
        self._last_pos = None
        if self.state.board is not None:
            self.refresh_checks()        # the surface is unknown again

    def _sync_frame_options(self):
        """The X-ray is the registration check between two faces. On a
        single-sided job it showed the same mirrored board under a badge
        saying it is not what gets cut - which it is."""
        on = bool(self._double)
        self.frame_switch.set_option_enabled("xray", on)
        self.xray_act.setEnabled(on)
        if not on and self.stage.frame == "xray":
            self.frame_switch.set_current("bed")
            self._on_frame("bed")

    def exported_path(self, filename):
        return self._exported.get(filename)

    def set_stage_mode(self, mode):
        """One mode at a time, and every control that claims one agrees.

        The boxes checkbox, the screw picker and the jog toggle each put the
        stage in a mode. Leaving the others ticked left three controls lit
        for one mode - and clearing the boxes tick fired its handler, which
        put the stage back in ``place`` under a jog toggle still lit, so the
        next click dragged the board instead of jogging.
        """
        self.stage.set_mode(mode)
        for box, owns in ((self.rework_page.add_chk, "box"),
                          (self.inspector.setup.pick_screws, "screws"),
                          (getattr(self.bar, "jog_btn", None), "jog")):
            if box is not None and mode != owns and box.isChecked():
                box.blockSignals(True)
                box.setChecked(False)
                box.blockSignals(False)

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
        cur = self._current_step
        if cur is not None and self.plan.by_key(cur.key) is None:
            # The step on screen is not in the plan any more - per-diameter
            # drills folded into one, or the flip and the top pass gone with
            # double-sided. The rail has already moved; the inspector and
            # the stage follow it rather than keep a page for a dead step.
            self._current_step = None
            self.select_step(self.traveller.current())
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
        geom = (st.board.outline if st.board.outline is not None
                and not st.board.outline.is_empty else st.board.copper)
        if geom is None or geom.is_empty:
            self.traveller.set_job(st.name, "no outline or copper to measure")
            return
        x0, y0, x1, y1 = geom.bounds
        bits = [f"{x1 - x0:.1f} × {y1 - y0:.1f} mm",
                f"{len(st.board.holes)} holes"]
        if st.is_panel:
            bits.insert(0, f"{len(st.boards)} boards")
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
        # Each face has its own measurement; show the one for the face this
        # step cuts.
        QTimer.singleShot(
            0, lambda: self.level_page.follow_step(self.current_side()))
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
        # processEvents() below lets a click land while a toolpath is being
        # built, and the click's own redraw was then overdrawn by this one
        # when it resumed - the rail on one step, the stage on another. One
        # draw at a time: a request that arrives during a build is honoured
        # after it, for whichever step the rail is on by then.
        if self._drawing:
            self._redraw_after = True
            return
        self._drawing = True
        try:
            self._draw_step_now(step)
        finally:
            self._drawing = False
        if self._redraw_after:
            self._redraw_after = False
            self._refresh_preview_now()

    def _draw_step_now(self, step):
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
                return (drill_single_bit(st.board.holes, self.cutting_drill())
                        if st.drill.single_bit
                        else drill_holes(st.board.holes, self.cutting_drill()),
                        None, st.drill.bit_diameter)
            if step.op == "cutout":
                return (cut_outline(st.board.outline, self.cutting_cutout(),
                                    stock=self.declared_stock()),
                        None, st.cutout.bit_diameter)
            return (isolate(st.board.copper, self.cutting_trace(),
                            outline=st.board.outline), None, width)
        lay = self._ds_layout()
        if lay is None:
            return [], None, width
        if step.op == "airpass":
            return air_path(lay.outline), None, 0.4
        if step.op == "align":
            aj = self._align_job()
            return drill_single_bit(lay.align_holes, aj), None, aj.bit_diameter
        if step.op == "drill":
            dj = self.cutting_drill()
            paths = (drill_single_bit(lay.holes, dj) if st.drill.single_bit
                     else drill_holes(lay.holes, dj))
            return paths, None, st.drill.bit_diameter
        if step.op == "cutout":
            return (cut_outline(lay.outline, self.cutting_cutout()),
                    None, st.cutout.bit_diameter)
        tj = self.cutting_trace()
        if step.op == "top_traces":
            return (self._fit_paths(
                        isolate(lay.top_copper, tj, outline=lay.top_outline)),
                    None, width)
        return (isolate(lay.bottom_copper, tj, outline=lay.outline),
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
                except Exception as e:
                    # Never the machine frame under a badge that says design.
                    self.frame_switch.set_current("bed")
                    self.xray_act.setChecked(False)
                    self.stage.set_frame("bed")
                    self.say("fail", f"The design X-ray could not be built "
                                     f"({e.__class__.__name__}: {e}). Showing "
                                     f"the bed frame instead.")
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
            self.stage.set_members(
                [(m.name, b.copper, b.outline, b.holes)
                 for m in st.boards for b in (m.board(),)], st.current)
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
        if self.state.is_panel:
            legend.append((theme.PRIMARY, "the board being moved"))
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
        dowel_depth = None
        if self._double and self._registration == "dowel":
            # The dowel holes go through the stock and on into the bed. They
            # are the deepest cut of a two-sided job, and a Z-reach check
            # that does not know about them passes a job the machine cannot
            # finish.
            from gerber2rml.doublesided import DOWEL_BED_DEPTH
            dowel_depth = (self.inspector.setup.thickness.value()
                           + DOWEL_BED_DEPTH)
        # The jobs as they will be CUT, margin included: the files carry the
        # deepened depth, so the reach check has to as well.
        depths = diag.cut_depths(self.cutting_trace(), self.cutting_drill(),
                                 self.cutting_cutout(), dowel_depth)
        # Everything that has to fit the travel, dowels included: on a
        # double-sided job the board's own bounds leave the registration pins
        # out, and a pin 6 mm off the back of the bed passed as "Fits the bed".
        bounds = self.job_extent()
        if bounds is None:
            geom = (st.board.outline if st.board.outline is not None
                    else st.board.copper)
            if geom is not None and not geom.is_empty:
                bounds = geom.bounds
        try:
            checks = diag.preflight(
                depths=depths, bed=BACKENDS[st.machine].bed,
                design_bounds=bounds, holes=st.board.holes,
                surface_z=self.link.surface_z,
                bit_diameter=st.drill.bit_diameter, trace=st.trace,
                leveled=self.level_page.is_active(), shorts=self._shorts,
                thickness=self.inspector.setup.thickness.value())
        except Exception as e:
            self.report_error("The pre-flight checks could not run", e,
                              "Reload the board and try again. Nothing has "
                              "been written.")
            return
        checks += self._stock_checks()
        checks += self._panel_checks()
        checks += self._two_sided_depth_check()
        checks += self._screw_checks()
        self._checks = checks
        self.inspector.checks.set_checks(checks)
        self._sync_banner()

    # Steps that actually CUT a face. Every step carries a `side`, but on the
    # ones that cut nothing it is just a default - `level` says "bottom" even
    # though levelling is done on whichever face is in front of you. Reading
    # it there made opening the levelling page silently switch the height map
    # back to the bottom, and the next probe overwrote a real measurement.
    _CUTTING_OPS = ("traces", "top_traces", "drill", "cutout", "airpass",
                    "align")

    def current_side(self):
        """The face the selected step CUTS, or None when it cuts nothing.

        None means "this step does not answer the question" - the caller
        should use whatever the operator has selected instead of being told
        the default.
        """
        if not self._double:
            return "bottom"
        step = self._current_step
        if step is None or getattr(step, "op", None) not in self._CUTTING_OPS:
            return None
        return getattr(step, "side", None) or "bottom"

    def _flex_margin(self):
        """Extra depth to cut through a board that will move under the cutter.

        The probe measures the surface with a static tool at almost no force.
        The cutter arrives spinning and pushing down. Where the board is held
        against the bed that makes no difference; where it is arched over air
        between two screws it does - the unsupported part deflects instead of
        being cut, and the trace is missed exactly where the height map is
        highest. That is not a fault in the map: the map is right about where
        the surface WAS.

        So the margin is the arch - but only the arch. A board can be a
        perfectly rigid sheet sitting on a slope, and then the map has a large
        range and there is nothing to deflect: the warp already cuts every
        point to the same depth. Counting that tilt as arch charges it twice,
        once in the warp and again in the margin, and on a sheet a
        millimetre out of level that buys most of a millimetre of extra depth
        for nothing. What deflects is what a plane CANNOT explain, so the
        margin is the residual - see :func:`flex_residual`.

        Bonded across the whole back - tape, not screws - there is nowhere for
        it to go, the probed surface IS the cut surface, and the margin is
        zero. Which is the better fixture, and why this is a setting rather
        than a constant.
        """
        if self._hold != "points":
            return 0.0
        if not self._flex_auto:
            return max(0.0, float(self._flex_mm))
        arch = self._flex_arch()
        if arch is None:
            return 0.0
        applied, span = arch
        if not applied:
            # The map is not being applied, so nothing cancels the tilt: the
            # whole range is what the cut has to reach through.
            return max(0.0, span + FOIL_MM)
        return max(0.0, min(span * FLEX_FRACTION, FLEX_CAP_MM) + FOIL_MM)

    def _flex_arch(self):
        """``(applied, span)`` from the bottom face's map, or None without one.

        ``applied`` says whether the map is warping the cut. If it is, ``span``
        is the arch - what a plane cannot explain, see :func:`flex_residual`;
        if not, it is the whole range, since nothing cancels the tilt.
        """
        # The bottom face's measurement, whichever face the rail is showing:
        # what gets exported must not depend on which row is highlighted.
        pts = self.level_page.points(side="bottom")
        if len(pts) < 3:
            return None
        zs = [z for _x, _y, z in pts]
        if self.level_page.height_map(side="bottom") is None:
            return False, max(zs) - min(zs)
        span = flex_residual(pts)
        if span is None:
            # The points are in a line, so no plane is determined and tilt
            # cannot be told from arch. Fall back to the raw range: too deep
            # beats not reaching the copper.
            span = max(zs) - min(zs)
        return True, span

    def flex_report(self):
        """What the setup page says about the extra depth."""
        arch = self._flex_arch()
        applied = bool(arch and arch[0])
        return {"margin": self._flex_margin(), "auto": self._flex_auto,
                "hold": self._hold, "applied": applied,
                "arch": arch[1] if applied else None,
                "range": arch[1] if (arch and not applied) else None,
                "capped": applied and arch[1] * FLEX_FRACTION > FLEX_CAP_MM}

    def action_flex(self, auto, mm):
        """The extra depth for a board held at points: from the map, or typed."""
        self._flex_auto = bool(auto)
        self._flex_mm = max(0.0, float(mm))
        self._paths_cache = {}
        self._after_params()

    def action_hold(self, how):
        self._hold = how or "points"
        self._paths_cache = {}
        self._after_params()

    def action_params_changed(self):
        """A cutting parameter was edited: nothing built from the old numbers
        may be shown again. The cache is keyed by step, and a step's key
        survives an edit to its bit or its depth; its toolpath does not."""
        self._paths_cache = {}
        self._after_params()

    def action_level_toggled(self):
        """Whether the map is applied changes the flex margin, the checks and
        the run plan's facts - all of it, not only the plan."""
        self._paths_cache = {}
        self._after_params()

    def _align_job(self):
        """The drill job the export gives the registration holes: through the
        stock and, for dowels, on into the bed. Previewing and streaming them
        with the plain drill job showed a 1.7 mm hole where the file makes a
        6.6 mm one - and streamed it."""
        from gerber2rml.doublesided import (_align_drill, _fiducial_align_drill,
                                            DowelSpec)
        t = self.inspector.setup.thickness.value()
        if self._registration == "fiducial":
            job, _d = _fiducial_align_drill(self.cutting_drill(),
                                            self.fiducial_spec(), t)
        else:
            job, _d = _align_drill(self.cutting_drill(), DowelSpec(), None, t)
        return job
        self.refresh_preview()

    def cutting_trace(self):
        """The trace job as it will actually be cut, margin included."""
        from dataclasses import replace
        m = self._flex_margin()
        if not m:
            return self.state.trace
        t = self.state.trace
        if t.tool_type == "vbit":
            # A V-bit's depth is back-solved from the width it is asked for,
            # so deepening cut_depth alone changed nothing. Ask for the width
            # the bit has at the deepened depth: the plunge goes down by the
            # margin and the trace widens with it, which is what the bit
            # profile then shows.
            return replace(t, cut_depth=t.cut_depth + m,
                           target_width=t.width_at_depth(
                               t.effective_cut_depth() + m))
        return replace(t, cut_depth=t.cut_depth + m)

    def cutting_drill(self):
        """The drill job as it will actually be cut.

        A board that springs away from an isolation cutter springs harder away
        from a drill, and the hole simply does not break through - which is
        how a job ends up flipped with half its holes blind. The margin goes
        on ``total_depth``: ``cut_depth`` is the peck increment and means
        something else.
        """
        from dataclasses import replace
        m = self._flex_margin()
        if not m:
            return self.state.drill
        d = self.state.drill
        return replace(d, total_depth=d.total_depth + m)

    def cutting_cutout(self):
        """The cut-out as it will actually be cut, margin included.

        Same reasoning, and the cut-out is the pass that has to sever the
        board completely: stopping short leaves it attached by a film that
        tears rather than cuts when the tabs are broken.
        """
        from dataclasses import replace
        m = self._flex_margin()
        if not m:
            return self.state.cutout
        c = self.state.cutout
        return replace(c, total_depth=c.total_depth + m)

    def _two_sided_depth_check(self):
        """What is left of the board where a channel on each face crosses.

        Isolation on a double-sided job cuts into the SAME piece of laminate
        from both faces. Each pass is checked against the copper it has to
        break, and neither knows about the other - so two passes that are
        individually sensible can meet in the middle, and the first anyone
        hears about it is a board that snaps along a trace.

        It matters here because the flex margin makes the cut deep on purpose:
        0.15 mm becomes 0.585 mm on a board arched over its screws, and twice
        that is most of a 1.5 mm laminate.
        """
        if not self._double or self.state.board is None:
            return []
        depth = self.cutting_trace().effective_cut_depth()
        thickness = self.inspector.setup.thickness.value()
        left = thickness - 2.0 * depth
        both = ("%.3f mm from each face into a %.2f mm board"
                % (depth, thickness))
        if left <= 0.0:
            return [diag.Check(
                "fail", "The two sides would meet in the middle",
                "cutting %s leaves nothing where a channel on the top crosses "
                "one on the bottom - the board would be cut through along "
                "those lines. Probe and bond the far side so it does not need "
                "the deep cut, or use thicker stock." % both)]
        if left < 0.40:
            return [diag.Check(
                "warn", "Only %.2f mm holds the board where the sides cross"
                        % left,
                "cutting %s leaves a %.2f mm web under a %.2f mm wide slot "
                "wherever a top channel crosses a bottom one. It holds, but it "
                "is where the board will crack if it is flexed. The far side "
                "does not have to be cut this deep: bond it flat, re-probe, "
                "and its margin goes to nothing."
                % (both, left, self.state.trace.effective_diameter()))]
        return [diag.Check(
            "ok", "The two sides do not meet",
            "cutting %s leaves %.2f mm of laminate where the channels cross."
            % (both, left))]

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
            from gerber2rml.engine.cutout import SHEET_EDGE_MM
            if self._stock_set and worst <= SHEET_EDGE_MM:
                # A hair over: the sheet's edge IS the board's edge there,
                # and the cut-out leaves that side out.
                out.append(diag.Check(
                    "warn", "The job reaches the edge of the copper",
                    "the work hangs " + " and ".join(edges) + " of the "
                    "sheet. The sheet's edge is the board's edge there, so "
                    "the cut-out skips that side and the board is short by "
                    "that much."))
            else:
                out.append(diag.Check(
                    "fail", "The job runs off the copper",
                    "the work hangs " + " and ".join(edges) + " of the sheet. "
                    "Move the job, or set the sheet's real size and corner "
                    "under The copper."))
        else:
            out.append(diag.Check(
                "ok", "The job is on the copper",
                f"nearest edge has "
                f"{min(x0 - sx, sx + sw - x1, y0 - sy, sy + sh - y1):.1f} mm "
                f"to spare."))
        return out

    def _panel_checks(self):
        """Do the boards on the sheet keep out of each other's way?

        Each cut-out runs one cutter width outside its outline. Two outlines
        closer than the bit are buffered into ONE shape by the engine and
        milled as one, so the boards come off the sheet joined; a little
        further apart the two channels meet, and any stock left between them
        is a sliver that can break loose and jam the cutter.
        """
        st = self.state
        if not st.is_panel:
            return []
        from gerber2rml.app.panel import clearances
        bit = self.cutting_cutout().bit_diameter
        comfortable = 2.0 * bit + 1.0
        a, b, gap, overlap = clearances(st.boards)[0]
        if overlap:
            return [diag.Check(
                "fail", "Two boards overlap",
                f"{a} and {b} sit on top of each other. Move one of them - "
                f"nothing can be cut like this.")]
        if gap <= bit + 1e-6:
            lost = (bit - gap) / 2.0
            return [diag.Check(
                "warn" if lost >= 0.2 else "ok",
                "Two boards share one cut",
                f"{a} and {b} are {gap:.2f} mm apart, so the cut-out runs "
                f"once between them, centred in the gap. Each loses "
                f"{lost:.2f} mm along that edge - the edge as drawn ends up "
                f"inside the cut.")]
        if gap < comfortable:
            strip = gap - 2.0 * bit
            if strip <= 0:
                return [diag.Check(
                    "ok", "The boards keep clear of each other",
                    f"{a} and {b} are {gap:.2f} mm apart; their cut-outs "
                    f"overlap and nothing is left between them.")]
            return [diag.Check(
                "warn", "Two boards are nearly touching",
                f"only {gap:.2f} mm between {a} and {b}. The cut-outs leave "
                f"a strip of stock {strip:.2f} mm wide between them, which "
                f"can break loose and jam the cutter. {comfortable:.1f} mm "
                f"or more is comfortable, or butt them together and share "
                f"one cut.")]
        return [diag.Check(
            "ok", "The boards keep clear of each other",
            f"the nearest pair, {a} and {b}, are {gap:.1f} mm apart.")]

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
        self._custom_name = False
        try:
            stem = gerber_stem(Path(folder))
            if stem:
                self.state.name = stem
        except Exception:
            pass
        workspace.remember_dir("gerber", folder)
        self._forget_output()
        self.stage._fitted = False
        self.refresh_plan()
        self.refresh_checks()
        self.select_step("setup")
        self.stage.fit_work()
        self.say("ok", f"Loaded {self.state.name} — "
                       f"{len(self.state.board.holes)} holes.")

    # ---------------------------------------------------- several boards
    def action_add_board(self):
        if self.state.board is None:
            self.action_open()
            return
        d = QFileDialog.getExistingDirectory(
            self, "Choose another board's Gerber folder",
            workspace.remembered_dir("gerber"))
        if d:
            self.add_folder(d)

    def add_folder(self, folder):
        """Put another board on the sheet, beside the ones already there.

        The dialog path and the tests both come here. With nothing loaded it
        is simply a load; on a double-sided job it is refused, because that
        job is one board registered to two holes and a second board has no
        place in that registration.
        """
        st = self.state
        if st.board is None:
            self.load_folder(folder)
            return
        if self._double:
            self.say("warn", "A double-sided job is one board. Untick "
                             "“copper on both faces” to put several boards "
                             "on the sheet.")
            return
        try:
            m = st.add_board(folder)
        except Exception as e:
            self.report_error(
                "That folder could not be read as a board", e,
                "SRM-CAM needs a copper layer, an Edge.Cuts outline and a "
                "drill file in one folder — the set KiCad's Plot and Generate "
                "Drill Files produce. If the folder holds a zip, unpack it "
                "first.")
            return
        workspace.remember_dir("gerber", folder)
        if not self._custom_name:
            st.name = self._auto_name()
        self._forget_output()
        self.refresh_plan()
        self.refresh_checks()
        self.select_step("setup")
        self.stage.fit_work()
        self.say("ok", f"{m.name} added — {len(st.boards)} boards on the "
                       f"sheet. Drag each one where it should go; the files "
                       f"cut them all in one run.")

    def action_remove_board(self, *, index=None):
        """Take the picked board (or ``index``) off the sheet.

        Keyword-only: a button's ``clicked`` carries its checked flag, and
        ``False`` is a perfectly good index for ``list.pop``, which is how
        the button took the first board off instead of the picked one.
        """
        st = self.state
        if not st.boards:
            return
        m = st.remove_board(st.current if index is None else index)
        if not self._custom_name:
            st.name = self._auto_name() if st.boards else "board"
        self._forget_output()
        self.refresh_plan()
        self.refresh_checks()
        self.select_step("setup")
        self.stage.fit_work()
        self.say("info", f"{m.name} taken off the sheet"
                         + (f" — {len(st.boards)} left." if st.boards else "."))

    def action_select_board(self, index):
        """Make one board of the panel the one the placement controls move.

        Nothing is regenerated: the boards have not moved, only which one the
        next edit applies to. The stage marks it and the setup page follows.
        """
        st = self.state
        if not 0 <= index < len(st.boards):
            return
        if index != st.current:
            st.select_board(index)
        self.stage.set_selected(index)
        self.inspector.setup.sync()

    def action_arrange(self, gap=None):
        """Line the boards up left to right - ``gap`` mm of waste between
        them, or butted together (0) so one cut separates each pair."""
        st = self.state
        if not st.is_panel:
            self.say("warn", "There is only one board on the sheet.")
            return
        gap = PANEL_GAP_MM if gap is None else float(gap)
        st.arrange(gap)
        self._paths_cache = {}
        self._after_params()
        QTimer.singleShot(0, self.stage.fit_work)
        if gap <= 0:
            self.say("ok", f"{len(st.boards)} boards butted together. One cut "
                           f"runs between each pair and separates them; each "
                           f"loses half a cutter width along that edge.")
        else:
            self.say("ok", f"{len(st.boards)} boards laid out left to right, "
                           f"{gap:g} mm apart.")

    def action_name(self, text):
        """The operator typed a job name: keep it, whatever boards come and go."""
        self.state.name = text.strip() or "board"
        self._custom_name = bool(text.strip())
        self.refresh_plan()

    def _auto_name(self):
        """Every board's name, joined: what the files are called unless the
        operator says otherwise."""
        return "+".join(m.name.replace(" ", "_") for m in self.state.boards) \
            or "board"

    def _forget_output(self):
        """The files on disk, and the ticks against them, no longer describe
        the job. Neither do a photo of the last board or the boxes drawn on
        it: the same argument that clears the measured flip on load."""
        self._paths_cache = {}
        self._exported = {}
        self._export_dir = None
        self.traveller.clear_done()
        self.rework_page._clear()
        if self.stage.has_photo():
            self.stage.set_photo(None, None)
            self.stage.set_photo_dim(0.0)
            self.photo_clear_act.setEnabled(False)

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
        self._stock_set = True
        if show is not None:
            self.show_stock = bool(show)
        self._draw_screws()
        self._sync_stock()
        self.refresh_checks()

    def declared_stock(self):
        """The copper sheet as ``(x0, y0, x1, y1)``, once the operator has set
        it, else None. Where a board edge lies on it there is nothing to
        cut, and the cut-out is told so."""
        if not self._stock_set:
            return None
        sx, sy, sw, sh = self.stock
        return (sx, sy, sx + sw, sy + sh)

    def _sync_stock(self):
        """Draw the sheet when asked to, not only when it is screwed down.

        Tying the outline to the screw checkbox meant the one case that most
        needs it — a sheet clamped by hand, away from the fixture — was the
        case that never drew it.
        """
        self.stage.set_stock(self.stock
                             if (self.show_stock or self.screwed) else None)

    def action_phone_photo(self):
        """Get the photo off a phone, then run the same anchoring as a file.

        Deliberately the same flow from there on: a photo is a photo, and a
        second path through the anchoring is a second place for it to be
        wrong.
        """
        from PySide6.QtWidgets import QDialog as _QDialog
        if self.state.board is None:
            self.say("warn", "Load a board first — the photo is lined up "
                             "against its drilled holes.")
            return
        try:
            from gerber2rml.gui2.phonephoto import PhonePhotoDialog
        except Exception as e:
            self.report_error(
                "The phone hand-off could not start", e,
                "It needs the 'qrcode' package. Run "
                "'python -m gerber2rml.doctor' to install the interface "
                "dependencies.")
            return
        dlg = PhonePhotoDialog(self, workspace.workspace_root() / "photos")
        if dlg.exec() != _QDialog.Accepted or not dlg.photo_path:
            return
        self.action_load_photo(photo_path=str(dlg.photo_path))

    def action_load_photo(self, photo_path=None):
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
        path = photo_path
        if path is None:
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
        # warp_photo hands back matplotlib's (x0, x1, y0, y1); the stage
        # wants the two corners. Passed straight through, the rectangle had
        # no width and the photo never appeared.
        px0, px1, py0, py1 = extent
        self.stage.set_photo(photo_mod.to_qimage(rgba), (px0, py0, px1, py1))
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
        old = getattr(self, "_sim_window", None)
        if old is not None:
            # One at a time. Reopening left the previous window up, alive
            # and titled with the earlier step.
            try:
                old.close()
                old.deleteLater()
            except RuntimeError:
                pass
        self._sim_window = Simulation3DWindow(
            paths, title=f"{self.state.name or 'board'} — {step.title}",
            parent=self, board=bounds, bed=BACKENDS[self.state.machine].bed,
            thickness=self.inspector.setup.thickness.value())
        # LIVE follows the machine while the link is up. The window has the
        # whole forward-only cursor; the first interface fed it and this one
        # never did, so the button stayed disabled with a tooltip blaming
        # the link.
        self._sim_window.set_live_enabled(self.link.is_connected())
        self._sim_window.show()
        self._sim_window.raise_()
        self._sim_window.activateWindow()

    def _sim(self):
        """The open 3D window, or None once it has been closed and deleted."""
        sim = getattr(self, "_sim_window", None)
        if sim is None:
            return None
        try:
            return sim if sim.isVisible() else None
        except RuntimeError:                   # deleted underneath us
            self._sim_window = None
            return None

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
        # The panel owns the port, but STOP and Escape still have to reach a
        # test that is driving the head: the bar's stop sets the link's abort
        # event, the panel's worker polls it, and the flag tells the bar
        # there is something to stop while the panel is up.
        self.link.clear_abort()
        self.link.mark_external(True)
        try:
            dlg = MachineTestDialog(port, self,
                                    should_abort=self.link.should_abort)
            dlg.exec()
        finally:
            self.link.mark_external(False)
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
        if self.state.boards:
            try:
                self.state.reload()
            except Exception as e:
                self.report_error("The board could not be re-read", e)
                return
        self._paths_cache = {}
        self._after_params()

    def action_double_sided(self, on):
        if on and self.state.is_panel:
            box = self.inspector.setup.double
            box.blockSignals(True)
            box.setChecked(False)
            box.blockSignals(False)
            self._double = False
            self.say("warn", f"Double-sided is for one board at a time — this "
                             f"sheet has {len(self.state.boards)}. Take the "
                             f"others off first.")
            return
        self._double = bool(on)
        self._paths_cache = {}
        self.inspector.setup.registration_field.setVisible(
            tier.is_full() and self._double)
        self._sync_frame_options()
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
        cmd = plat.reveal_command(path)
        if cmd is not None:
            try:
                subprocess.Popen(cmd)
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
        # Before the shorts question: two boards on top of each other short
        # everywhere, and there is no version of that job that cuts, so it is
        # refused rather than confirmed.
        blocking = [c for c in self._panel_checks() if c.level == "fail"]
        if blocking:
            self.say("fail", f"{blocking[0].title} — {blocking[0].detail}")
            self.select_step("checks")
            return
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
        # The BOTTOM face's map, explicitly. height_map() with no face
        # follows the selected step, so exporting with "Top traces"
        # highlighted handed the writer no map - or the top's - for the
        # bottom-frame files. What is written must not depend on which row
        # is lit.
        level = self.level_page.height_map(side="bottom")
        try:
            if self._double:
                from gerber2rml.doublesided import build_double_sided
                written = build_double_sided(
                    st.gerber_dir, out_dir, st.name, trace=self.cutting_trace(),
                    drill=self.cutting_drill(), cutout=self.cutting_cutout(),
                    machine=st.machine,
                    offset=(st.place_x, st.place_y), rotate=st.rotate,
                    level=level, registration=self._registration,
                    fiducials=self.fiducial_spec(),
                    board_thickness=self.inspector.setup.thickness.value())
            else:
                # The margin has to reach the FILE, not just the preview. The
                # state's own export uses its own trace job, so swap in the
                # one that carries it for the duration.
                from dataclasses import replace as _replace
                keep = (st.trace, st.drill, st.cutout)
                st.trace = self.cutting_trace()
                st.drill = self.cutting_drill()
                st.cutout = self.cutting_cutout()
                try:
                    written = st.export(out_dir, level=level,
                                        stock=self.declared_stock())
                finally:
                    st.trace, st.drill, st.cutout = keep
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
            double_sided=self._double,
            panel=st.panel_summary() if st.is_panel else None)
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
            "fid_diameter": self._fid_diameter, "hold": self._hold,
            "flex_auto": self._flex_auto, "flex_mm": self._flex_mm,
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
            "overshoot": self.inspector.setup.overshoot.value(),
            "auto_depth": self.inspector.setup.auto_depth.isChecked(),
            # Every board on the sheet, with its own placement. One entry is
            # the ordinary job, and `gerber_dir`/`place`/`rotate` above are
            # that board's too, so a setup written here still loads in the
            # first interface.
            "boards": [{"gerber_dir": str(m.gerber_dir), "name": m.name,
                        "place": [m.place_x, m.place_y], "rotate": m.rotate}
                       for m in self.state.boards],
            "current": self.state.current,
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
        machine = data.get("machine", st.machine)
        if machine in BACKENDS:
            st.machine = machine
        else:
            foreign.append("the file format")
        st.mirror = bool(data.get("mirror", st.mirror))
        for key, attr in (("trace", "trace"), ("drill", "drill"),
                          ("cutout", "cutout")):
            if key in data:
                try:
                    setattr(st, attr, replace(getattr(st, attr), **data[key]))
                except TypeError:
                    pass                 # a field this version does not have
        boards = data.get("boards") or []
        self._double = bool(data.get("double_sided", False))
        if self._double and len(boards) > 1:
            # A sheet of several boards is single-sided. A file that says
            # otherwise was edited by hand or written by a bug: the plan must
            # not run the two-sided path on it, and add_folder would refuse
            # the second board while the flag stood.
            self._double = False
            foreign.append("double-sided (a sheet of several boards is "
                           "single-sided)")
        self._registration = data.get("registration", "dowel")
        # 0.8 for setups written before it was settable, so an old job
        # reproduces exactly what it produced then.
        self._fid_diameter = float(data.get("fid_diameter", 0.8))
        self._hold = data.get("hold", "points")
        self._flex_auto = bool(data.get("flex_auto", True))
        try:
            self._flex_mm = max(0.0, float(data.get("flex_mm", 0.0)))
        except (TypeError, ValueError):
            self._flex_mm = 0.0
        self._fid_count = int(data.get("fid_count", 4))
        self._fid_placement = data.get("fid_placement", "onboard")
        self._fid_offset = float(data.get("fid_offset", 4.0))
        self.screwed = bool(data.get("screwed", False))
        stock = data.get("stock", self.stock)
        try:
            x, y, w, h = (float(v) for v in stock)
            self.stock = (x, y, w, h)
            self._stock_set = "stock" in data
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
        placed = True              # may the saved name and placement be applied?
        if len(boards) > 1:
            placed = self._restore_panel(boards, data.get("current", 0), foreign)
        elif folder and Path(folder).is_dir():
            self.load_folder(folder)
        elif folder or boards:
            # The board itself is missing. Everything below would otherwise
            # land on whatever was open before - renamed, moved to the saved
            # placement, cut with the saved numbers - under "Setup loaded.".
            foreign.append(f"the board (its folder {folder or ''} is gone)")
            placed = False
        # After load_folder, which names the job from the folder it read: the
        # name saved with the setup is the one the operator chose.
        if data.get("name") and placed:
            st.name = data["name"]
            self._custom_name = True
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
        if placed:
            px, py = data.get("place", [0, 0])
            st.set_rotation(data.get("rotate", 0))
            st.set_placement(px, py)
        self._paths_cache = {}
        setup = self.inspector.setup
        # Signals blocked: a thickness that differs from the spinbox fired the
        # auto-depth handler, which overwrote the drill and cut-out depths
        # restored above with ones derived from THIS session's overshoot.
        # Those two settings are saved with the setup as well now.
        for spin, val in ((setup.thickness, data.get("thickness", 1.6)),
                          (setup.overshoot,
                           data.get("overshoot", setup.overshoot.value()))):
            spin.blockSignals(True)
            spin.setValue(float(val))
            spin.blockSignals(False)
        setup.auto_depth.blockSignals(True)
        setup.auto_depth.setChecked(
            bool(data.get("auto_depth", setup.auto_depth.isChecked())))
        setup.auto_depth.blockSignals(False)
        setup.double.setChecked(self._double)
        setup.screwed.setChecked(self.screwed)
        setup.sync()
        self._sync_frame_options()
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

    def _restore_panel(self, boards, current, foreign):
        """Put every saved board back on the sheet where it was.

        A board whose folder has gone is reported and skipped rather than
        aborting the load: the rest of the sheet is still the job that was
        saved, and the missing one is named so it can be found.
        """
        st = self.state
        loaded, landed = 0, {}        # saved index -> where it ended up
        for k, b in enumerate(boards):
            bdir = str(b.get("gerber_dir", ""))
            bname = str(b.get("name", "") or "a board")
            if not Path(bdir).is_dir():
                foreign.append(f"{bname} (its folder is gone)")
                continue
            if loaded == 0:
                self.load_folder(bdir)
            else:
                self.add_folder(bdir)
            if len(st.boards) != loaded + 1:
                foreign.append(bname)         # the folder no longer reads
                continue
            landed[k] = loaded
            loaded += 1
            m = st.boards[-1]
            try:
                px, py = b.get("place", [m.place_x, m.place_y])
                m.place_x, m.place_y = float(px), float(py)
                m.rotate = int(b.get("rotate", 0)) % 360
            except (TypeError, ValueError):
                foreign.append(f"where {bname} sits")
            if b.get("name"):
                m.name = bname
        if not st.boards:
            return False
        st.rebuild()
        try:
            cur = int(current)
        except (TypeError, ValueError):
            cur = 0
        # The saved index counts the boards as they were saved; a skipped one
        # shifts everything after it down, so map it through where each
        # board landed rather than move the wrong one to the saved spot.
        cur = landed.get(cur, 0)
        st.select_board(cur if 0 <= cur < len(st.boards) else 0)
        self._paths_cache = {}
        return len(landed) == len(boards)

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
        if self.stage.frame != "bed":
            # The X-ray is the design frame: unmirrored, and placed where the
            # design overlay wants it. A click there is not a machine
            # position, and neither is the hole it would snap to.
            self.say("warn", "The X-ray is the design frame, not the "
                             "machine's. Switch back to “Bed — as cut” to jog.")
            return
        # Snap to the hole under the cursor. Clicking a hole means "go to that
        # hole", and nobody can place a cursor on its centre to a tenth of a
        # millimetre - which is the precision the hole itself is drilled to,
        # and the precision that matters when the next thing you do is probe
        # it or drop a pin in it.
        sx, sy = self.stage.snap_to_feature(x, y)
        snapped = (sx, sy) != (x, y)
        bx, by = self.stage.bed
        if not (0 <= sx <= bx and 0 <= sy <= by):
            self.say("warn", "That point is off the machine's travel.")
            return
        self.link.jog_to(sx, sy)
        if snapped:
            self.say("info", "Jogging to the hole at X%.2f Y%.2f — snapped "
                             "%.2f mm from where you clicked."
                     % (sx, sy, ((sx - x) ** 2 + (sy - y) ** 2) ** 0.5))
        else:
            self.say("info", f"Jogging to X{sx:.2f} Y{sy:.2f}.")

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
