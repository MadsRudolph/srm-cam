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

from PySide6.QtCore import Qt, QTimer, QUrl, QEvent, QThread, Signal
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QDesktopServices
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                               QLabel, QStackedWidget, QFileDialog, QApplication,
                               QInputDialog, QSizePolicy, QSplitter, QLineEdit,
                               QAbstractSpinBox, QTextEdit, QPlainTextEdit,
                               QAbstractItemView)

from dataclasses import replace

from gerber2rml.gui2.jogpad import KEY_DIRECTIONS
from gerber2rml.gui2 import undo
from gerber2rml.app.state import ProjectState
from gerber2rml.app.preview import toolpath_segments, traverse_segments
from gerber2rml.app import presets as presets_mod
from gerber2rml.app.panel import PANEL_GAP_MM
from gerber2rml import platform as plat
from gerber2rml.naming import clean_name
from gerber2rml.config import checked_job
from gerber2rml.backends import BACKENDS
from gerber2rml.engine import diagnostics as diag
from gerber2rml.engine import method as fab
from gerber2rml.engine import silkscreen
from gerber2rml.engine import soldermask
from gerber2rml.engine import stencil
from gerber2rml.engine import spoilboard
from gerber2rml.engine import xtool

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
from gerber2rml.gui2.machine import MachineLink, MachineBar, RunTracker
from gerber2rml.gui2.leveling import LevelPage
from gerber2rml.gui2.rework import ReworkPage
from gerber2rml.gui2.fiducial import FlipFitPage
from gerber2rml.gui2.boardfit import BoardFitPage
from gerber2rml.gui2.autorun import AutoRunPage
from gerber2rml.gui2.sheet import RunSheet, FEEDBACK_URL
from gerber2rml.config import DEFAULT_STOCK_MM

USER_GUIDE_URL = "https://madsrudolph.github.io/srm-cam/"

DEMO = Path(__file__).resolve().parents[2] / "examples" / "calibration"
FIXTURE = Path(__file__).resolve().parents[1] / "examples"



class _IsolationDeferred(Exception):
    """An isolation pass the stage asked for, to be built off the GUI thread."""

    def __init__(self, copper, job, outline):
        super().__init__("isolation deferred to the background")
        self.copper, self.job, self.outline = copper, job, outline


# Every isolation worker that has started and not been collected. A QThread
# whose Python object is dropped while it runs takes the process down; a
# window closed or deleted mid-build would do that. Held here instead, and
# waited for at exit.
_LIVE_WORKERS = set()


def _wait_live_workers():
    for w in list(_LIVE_WORKERS):
        w.wait()


import atexit                                           # noqa: E402
atexit.register(_wait_live_workers)


class _IsolationWorker(QThread):
    """``isolate()`` on its own thread. Touches no widget: it is handed the
    copper, a copy of the job and the outline, and hands back the paths."""
    done = Signal(object, object)          # paths, error text or None

    def __init__(self, copper, job, outline):
        super().__init__()
        self.args = (copper, job, outline)
        _LIVE_WORKERS.add(self)

    def run(self):
        from gerber2rml.engine.traces import isolate
        copper, job, outline = self.args
        try:
            paths = isolate(copper, job, outline=outline)
        except Exception as e:                  # noqa: BLE001 - re-raised on the GUI thread
            self.done.emit(None, f"{e.__class__.__name__}: {e}")
            return
        self.done.emit(paths, None)


# The quarter turns, and the same mirrored, as (a, b, d, e) of shapely's
# affine_transform, exactly: everything Rotate and Mirror can do to a board.
_QUARTER_TURNS = ((1, 0, 0, 1), (0, -1, 1, 0), (-1, 0, 0, -1), (0, 1, -1, 0),
                  (-1, 0, 0, 1), (1, 0, 0, -1), (0, 1, 1, 0), (0, -1, -1, 0))


def _moved_by(old, new, old_outline, new_outline, tol=1e-6):
    """The affine matrix (shapely's ``[a, b, d, e, xoff, yoff]``) that takes
    ``old`` to ``new`` and ``old_outline`` to ``new_outline`` - a move, a
    quarter turn or a mirror, and a move - else None. Vertex for vertex: anything but the
    same geometry moved or turned is not recognised, and is worked out
    afresh."""
    import shapely
    from shapely.affinity import affine_transform
    if old is None or new is None:
        return None
    if old is new and old_outline is new_outline:
        return [1, 0, 0, 1, 0.0, 0.0]
    if (old.is_empty or new.is_empty or old.geom_type != new.geom_type
            or shapely.get_num_coordinates(old)
            != shapely.get_num_coordinates(new)):
        return None
    a_empty = old_outline is None or old_outline.is_empty
    b_empty = new_outline is None or new_outline.is_empty
    if a_empty != b_empty or (not a_empty and (
            shapely.get_num_coordinates(old_outline)
            != shapely.get_num_coordinates(new_outline))):
        return None
    for a, b, d, e in _QUARTER_TURNS:
        turned = affine_transform(old, [a, b, d, e, 0.0, 0.0])
        dx = new.bounds[0] - turned.bounds[0]
        dy = new.bounds[1] - turned.bounds[1]
        m = [a, b, d, e, dx, dy]
        if not affine_transform(old, m).equals_exact(new, tol):
            continue
        if a_empty or affine_transform(old_outline, m).equals_exact(
                new_outline, tol):
            return m
    return None


def _translate_drc(found, m):
    """The copper checks' answer, carried by the matrix ``m``."""
    shorts, eaten, gaps, corners = found
    if m == [1, 0, 0, 1, 0.0, 0.0]:
        return list(shorts), list(eaten), gaps, corners
    from shapely.affinity import affine_transform
    a, b, d, e, xoff, yoff = m

    def move(marks):
        return [dict(k, x=a * k["x"] + b * k["y"] + xoff,
                     y=d * k["x"] + e * k["y"] + yoff) for k in marks]

    def geom(g):
        return None if g is None else affine_transform(g, m)
    return move(shorts), move(eaten), geom(gaps), geom(corners)


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
    if "reg" in data:
        out["dowel_mode"] = "grid" if data["reg"] == 1 else "fresh"
    if "dowel_edge" in data:
        out["dowel_edges"] = "leftright" if data["dowel_edge"] == 1 else "topbottom"
    # The first interface keeps these in line edits, so they are strings.
    # One that does not parse is left to the default rather than refused: a
    # blank pitch box should not cost the rest of the setup.
    for theirs, ours in (("grid_pitch", "grid_pitch"), ("grid_pin", "grid_pin"),
                         ("clr_large", "clear_large"),
                         ("clr_small", "clear_small"), ("bed_bite", "bed_bite")):
        if theirs in data:
            try:
                out[ours] = float(data[theirs])
            except (TypeError, ValueError):
                out.pop(ours, None)
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
        # 0 on board, 1 in the waste, 2 placed by hand. Hand-placed holes
        # only mean anything with their points; a file that has the mode but
        # not the points falls back to the corner scheme rather than silently
        # drilling somewhere the operator did not pick.
        place = fid.get("place")
        points = fid.get("points")
        if place in (0, 1):
            out["fid_placement"] = "waste" if place == 1 else "onboard"
        elif place == 2 and isinstance(points, list) and len(points) >= 2:
            out["fid_placement"] = "manual"
            out["fid_points"] = points
        elif place == 2:
            out["fid_placement"] = "waste"
            unreadable.append("the hand-placed reference holes")
        if "scale" in fid:
            out["fid_scale"] = bool(fid["scale"])
        if "flip" in fid:
            out["fid_flip"] = "horizontal" if fid["flip"] == 1 else "vertical"
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
        # Selectable, so a long warning can be copied rather than retyped.
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Click to dismiss")
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self._sticky = False

    # A warning that vanished after nine seconds, mid-sentence, could not be
    # read at all — so warnings and failures now stay until clicked away or
    # replaced, and hovering holds a transient one where it is.
    def enterEvent(self, e):
        self._timer.stop()
        super().enterEvent(e)

    def leaveEvent(self, e):
        if self.isVisible() and not self._sticky:
            self._timer.start(3000)
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        if e.button() == Qt.LeftButton and not self.hasSelectedText():
            self._timer.stop()
            self.hide()

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
        self.show()
        self.raise_()
        self._sticky = level in ("warn", "fail")
        if self._sticky:
            self._timer.stop()
        else:
            self._timer.start(5000)

    def fit_to(self, max_w):
        """Size for the wrapped text. adjustSize() on a word-wrapping label
        guesses the height from one width and the text came out clipped."""
        self.setMaximumWidth(max_w)
        w = min(max_w, self.sizeHint().width())
        self.resize(w, max(self.heightForWidth(w), self.minimumSizeHint().height()))


# Novice's whole rail, in order: keys of the one plan, in its own words.
NOVICE_RAIL = {"setup": ("Your board", "How it is made, one side or two"),
               "checks": ("Check it", "Can it be made as drawn?"),
               "autorun": (None, "Stock in the bracket, then Start")}


class MainWindow(QMainWindow):

    def __init__(self, parent=None):
        super().__init__(parent)
        from gerber2rml.gui2 import wheelguard
        wheelguard.install()                # however the window was made
        self.state = ProjectState()
        self.link = MachineLink(self)
        # Run tracking off the position poll, for the step the rail is on.
        self.tracker = RunTracker(self.link)
        self._last_xyz = None          # last live (x, y, z), machine mm
        # Design frame minus machine frame, mm. Non-zero only after "Align
        # the overlay to the bit": the drawn bit, click-to-jog and run
        # tracking are corrected by it; the exported job never is.
        self._overlay_trim = (0.0, 0.0)
        self._align_armed = False      # the next jog click sets the trim
        self.plan = None
        self._checks = []
        self._shorts = []
        self._eaten = []         # pads a cut-it-anyway pass takes most of
        self._gaps = None        # copper gaps too narrow for the cutter
        self._corners = None     # ...and inside corners it cannot reach into
        self._exported = {}
        self._export_dir = None
        self._double = False
        # The laser file for solder mask: off until asked for, and what the
        # last write made of it, for the setup page to go on saying.
        self._solder_mask = False
        self._mask_shrink = soldermask.DEFAULT_SHRINK
        self._mask_result = None
        # Its sibling for the silkscreen: the same, without a shrink.
        self._silkscreen = False
        self._silk_result = None
        # And the paste stencil, cut from steel foil on the same laser.
        self._stencil = False
        self._stencil_kerf = stencil.DEFAULT_KERF
        self._stencil_result = None
        # And PCB traces etched directly on the xTool F1 Ultra.
        self._laser_traces = False
        self._laser_offsets = xtool.DEFAULT_TRACE_OFFSETS
        self._laser_traces_result = None
        self._registration = "fiducial"     # the lab standard; dowels drill the bed
        # How the board's copper is made (engine/method.py): None until a
        # board says, and then the tool profile answers. Its source is shown
        # beside it: from KiCad, guessed from the gaps, or chosen here.
        self._method = None
        self._method_source = "profile"
        self._method_gap = None
        # A double-sided board set to the laser is milled single-sided (the
        # holes go through); what the tick said before, to give it back.
        self._double_before_laser = None
        # Bigger than the bit, on purpose. The engine's default is 0.8 mm —
        # the same as the bit that drills it and the same as the bit that must
        # descend INSIDE it to probe it, which is a hole no bit can enter.
        self._auto_top = False             # Automatic: the sheet is turned over
        self._fid_diameter = 1.6
        self._fid_count = 4
        self._fid_placement = "waste"      # "waste" | "onboard" | "manual"
        # The manual places are the board's own mounting holes, chosen by
        # the app (engine/mountfid.py), not pins dragged by hand.
        self._fid_mounting = False
        # The board is left in the sheet: Automatic mode cuts nothing round
        # its outline (gui2/autorun.py, "Leave the board in the sheet").
        self._no_cutout = False
        self._edge_memo, self._edge_notes = {}, {}   # see _edge_free
        self._fid_offset = 4.0
        # Which way the board is physically turned over. The fit cannot tell:
        # a rectangle of corner holes matches equally well either way, so a
        # wrong answer here mirrors the whole top side under a perfect RMS.
        self._fid_flip = "vertical"        # "vertical" (left-right) | "horizontal"
        self._fid_scale = False            # let the fit stretch the board too
        # Hand-placed reference holes: (x, y) mm from the framed board's
        # lower-left corner, in the design frame. Only read when the
        # placement is "manual"; seeded from the waste corners when it is
        # first chosen, then moved by dragging the pins on the stage.
        self._fid_points = []
        # The dowel registration, as the engine's DowelSpec wants it. The
        # sub-mode used to be dropped on load and the bed bite hard-coded.
        from gerber2rml.doublesided import (CLEAR_LARGE, CLEAR_SMALL,
                                            DOWEL_BED_DEPTH, GRID_PITCH,
                                            GRID_PIN)
        self._dowel_mode = "fresh"         # "fresh" | "grid"
        self._dowel_edges = "topbottom"    # "topbottom" | "leftright"
        self._grid_pitch = GRID_PITCH
        self._grid_pin = GRID_PIN
        self._clear_large = CLEAR_LARGE
        self._clear_small = CLEAR_SMALL
        self._bed_bite = DOWEL_BED_DEPTH
        # Where the flipped board REALLY landed, from the measured fiducials.
        # Everything drawn for the top side goes through it, so the picture is
        # of the board in front of you and not the one you meant to put down.
        self._top_fit = None
        self._fid_measured = []
        # Where a board made elsewhere (laser-etched, say) really sits, from
        # its measured pads: design -> bed. Only the drill-only step uses it.
        self._board_fit = None
        self._stock_turn = None       # the job turned to the found stock
        from gerber2rml.gui2 import machine as _machine
        _machine.SHOW_SIM = tier.is_full()
        self._layout_base = None       # the layout at offset (0, 0)
        self._layout_key = None        # what that base was built from
        self._layout_placed = None     # ...translated to the placement
        self._layout_placed_key = None
        self._paths_cache = {}         # step key -> (paths, far, cut width)
        self._drc_memo = None          # the copper checks, for a moved board
        self._iso_memo = []            # [(copper, outline, job, paths)]
        self._iso_worker = None        # an isolation pass being built
        self._iso_defer = False        # True: a slow isolation goes to it
        self._iso_failed = None        # ...and the one it could not build
        # Ctrl+Z for where the boards sit: every move, turn and mirror.
        self.placement_undo = undo.PlacementUndo(self._sync_undo)
        self._current_step = None
        self._drawing = False          # a toolpath is being built right now
        self._redraw_after = False     # ...and a redraw was asked for meanwhile
        self._last_pos = None
        self.stock = (0.0, 0.0) + DEFAULT_STOCK_MM
        # Whether the operator has SAID where the copper is. The default
        # sheet above is a placeholder for the picture; nothing that cuts
        # may treat its edges as real until a size or corner has been set.
        self._stock_set = False
        self.show_stock = True
        self.show_bed = True     # the spoilboard grid; see _draw_screws
        self._manual_screws = None   # None = let the app choose them
        # How the copper is held down, which decides whether the probed
        # surface is the surface that gets CUT. See _flex_margin.
        self._hold = "bonded"        # "bonded" | "points"; tape is the lab standard
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

        self.header = self._build_header()
        v.addWidget(self.header)
        v.addWidget(widgets.rule())

        # The rail is the whole job, across both machines: it stays on screen
        # whichever machine's page is beside it.
        body = QWidget()
        bh = QHBoxLayout(body)
        bh.setContentsMargins(0, 0, 0, 0)
        bh.setSpacing(0)
        self.traveller = Traveller()
        self.traveller.step_selected.connect(self.select_step)
        self.traveller.export_requested.connect(self.action_export)
        self.traveller.banner_action.connect(lambda: self.select_step("checks"))
        bh.addWidget(self.traveller)
        bh.addWidget(widgets.vrule())

        middle = QWidget()
        h = QHBoxLayout(middle)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        self.stage = Stage()
        self.stage.placement_changed.connect(self._on_drag)
        self.stage.placement_dragging.connect(self._on_dragging)
        self.stage.jog_requested.connect(self._on_jog_click)
        self.stage.jog_step_requested.connect(self._on_jog_step)
        self.stage.screw_picked.connect(self._on_screw_click)
        self.stage.hovered.connect(self._on_hover)
        self.stage.region_added.connect(self._on_region)
        self.stage.box_clicked.connect(self._on_box_click)
        self.stage.board_picked.connect(self.action_select_board)
        self.stage.pin_moved.connect(self._on_pin_moved)
        self.stage.measured.connect(self._on_measured)
        self.stage.pad_picked.connect(
            lambda x, y: self.boardfit_page.add_pad_near(x, y))
        self.stage.set_empty(
            "No board loaded",
            "File ▸ Open Gerber folder, or try the demo board")
        self.sheet = RunSheet()
        self.sheet.back.connect(lambda: self.centre.setCurrentWidget(self.stage))
        self.sheet.open_folder.connect(self.action_open_export_folder)
        self.sheet.copy_text.connect(self._copy_sheet)
        self.sheet.feedback.connect(
            lambda: QDesktopServices.openUrl(QUrl(FEEDBACK_URL)))
        self.centre = QStackedWidget()
        self.centre.addWidget(self.stage)
        self.centre.addWidget(self.sheet)
        # The stage and the inspector share a splitter: the inspector's pages
        # got long (Automatic mode), and a fixed 352 px meant scrolling.
        self.split = QSplitter(Qt.Horizontal)
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(6)
        # A 1 px rule to look at, 6 px to grab.
        self.split.setStyleSheet(
            "QSplitter::handle:horizontal { width: 6px; background: "
            "transparent; border-left: 1px solid %s; }" % theme.RULE)
        canvas = QWidget()
        cvl = QVBoxLayout(canvas)
        cvl.setContentsMargins(0, 0, 0, 0)
        cvl.setSpacing(0)
        cvl.addWidget(self._build_canvas_bar())
        cvl.addWidget(widgets.rule())
        cvl.addWidget(self.centre, 1)
        self.split.addWidget(canvas)
        h.addWidget(self.split, 1)

        self.inspector = Inspector(self)
        self.level_page = self.inspector.add_page("level", LevelPage(self))
        self.rework_page = self.inspector.add_page("rework", ReworkPage(self))
        self.flipfit_page = self.inspector.add_page("fitflip", FlipFitPage(self))
        self.boardfit_page = self.inspector.add_page("fitdrill",
                                                     BoardFitPage(self))
        self.autorun_page = self.inspector.add_page("autorun",
                                                    AutoRunPage(self))
        self.stage.stock_picked.connect(self.autorun_page.on_stock_click)
        self.stage.bracket_moved.connect(self.autorun_page.on_bracket_moved)
        self.stage.nogo_picked.connect(self.autorun_page.on_nogo_picked)
        self.autorun_page.finished.connect(
            lambda *_: self.inspector.step.sync_run())
        self.split.addWidget(self.inspector)
        self.split.setStretchFactor(0, 1)
        self.split.setStretchFactor(1, 0)
        try:
            want = int(workspace.setting("ui/inspector_w",
                                         theme.INSPECTOR_DEFAULT_W))
        except (TypeError, ValueError):
            want = theme.INSPECTOR_DEFAULT_W
        want = max(theme.INSPECTOR_W, min(theme.INSPECTOR_MAX_W, want))
        self.split.setSizes([10000, want])
        self.split.splitterMoved.connect(
            lambda *_: workspace.set_setting("ui/inspector_w",
                                             self.inspector.width()))
        # The mill and the laser are two pages of this one window, swapped by
        # the switch in the header: the mill's rail, stage, inspector and
        # machine bar on one, the laser page (bed, its inspector, its bar)
        # on the other. The laser page is made the first time it is shown.
        self.modes = QStackedWidget()
        self.cnc_body = QWidget()
        cv = QVBoxLayout(self.cnc_body)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        cv.addWidget(middle, 1)
        self.modes.addWidget(self.cnc_body)
        self.laser_view = None
        self._laser_token = None
        # A project of many boards, each ticked off (gui2/projectpage.py).
        from gerber2rml.gui2 import projectpage
        self.project_ctl = projectpage.ProjectController(self)
        self.modes.addWidget(self.project_ctl.page)
        self.traveller.on_done = self.project_ctl.on_done
        bh.addWidget(self.modes, 1)
        v.addWidget(body, 1)

        # The mill's bar spans the window, under the rail too: it is the
        # mill's STOP, and it needs the room. The laser page has its own.
        self.bar_rule = widgets.rule()
        v.addWidget(self.bar_rule)
        self.bar = MachineBar(self.link)
        self.bar.message.connect(self.say)
        self.bar.jog_mode_changed.connect(
            lambda on: self.set_stage_mode("jog" if on else "place"))
        self.bar.pad.xy_requested.connect(self._on_jog_step)
        self.link.position.connect(self._on_machine_position)
        self.link.op_done.connect(self._on_op_done)
        self.link.linked.connect(self._on_linked)
        self.link.unlinked.connect(self._on_unlinked)
        v.addWidget(self.bar)

        self.setCentralWidget(root)
        self.toast = Toast(root)

        # The status chips answer for five pages that are edited on their
        # own - level, flip fit, photo, rework, the link. Rather than have
        # each of them know about the strip, the strip looks once a second;
        # what it reads is a handful of attributes and a small table.
        self._chip_timer = QTimer(self)
        self._chip_timer.setInterval(1000)
        self._chip_timer.timeout.connect(self.refresh_chips)
        self._chip_timer.start()

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
        if ev.type() == QEvent.KeyPress and self._jog_key(ev):
            return True
        if ev.type() == QEvent.KeyRelease and ev.key() == Qt.Key_Escape:
            self._esc_down = False
        elif (ev.type() == QEvent.KeyPress and ev.key() == Qt.Key_Escape
                and not self._esc_down):
            self._esc_down = True
            view = getattr(self, "laser_view", None)
            if view is not None and view._worker_running():
                # Escape stops the laser as well, whichever page is up.
                view.stop()
                if not self.link.can_stop_something():
                    return super().eventFilter(obj, ev)
            if (view is not None and self.mode() == "laser"
                    and not self.link.can_stop_something()):
                # Nothing running on either machine; the mill's "no link to
                # stop" means nothing on the laser's page.
                return super().eventFilter(obj, ev)
            if self.link.can_stop_something():
                self.bar._stop()
            elif QApplication.activeModalWidget() is None:
                # Nothing to stop and no dialog in the way: say what does stop
                # this machine. Suppressed under a dialog, where Escape means
                # "close this" and the guidance would just be noise.
                self.bar._stop()
        return super().eventFilter(obj, ev)

    def _jog_key(self, ev):
        """With Keys lit on the jog pad, the arrows drive the machine wherever
        the focus is - except in a box being typed in, or under a dialog."""
        pad = getattr(getattr(self, "bar", None), "pad", None)
        if pad is None or not pad.keys_on():
            return False
        if self.mode() == "laser":
            return False           # the laser page's arrows move its job
        if ev.key() not in KEY_DIRECTIONS:
            return False
        if QApplication.activeModalWidget() is not None:
            return False
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QAbstractSpinBox, QTextEdit,
                              QPlainTextEdit, QAbstractItemView)):
            return False
        return pad.press_key(ev.key(), ev.modifiers())

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

        # How the board is made: one fact that decides the checks, the tool
        # and the jobs on the rail. Shown on both machines, and changed here
        # whatever KiCad or the guess said.
        from PySide6.QtWidgets import QMenu
        self.method_chip = widgets.ClickChip("No board", "idle")
        self.method_menu = QMenu(self)
        self.method_group = QActionGroup(self)
        self.method_group.setExclusive(True)
        self.method_acts = {}
        for mid in fab.IDS:
            a = QAction(fab.name(mid), self)
            a.setCheckable(True)
            a.setToolTip(fab.METHODS[mid].about)
            a.triggered.connect(lambda _c=False, m=mid: self.action_method(m))
            self.method_group.addAction(a)
            self.method_menu.addAction(a)
            self.method_acts[mid] = a
        self.method_menu.setToolTipsVisible(True)
        self.method_chip.menu = self.method_menu
        h.addWidget(self.method_chip)

        # Which machine: the switch names it, so the old "Roland SRM-20"
        # caption went (the header is full at 1280 px).
        h.addSpacing(theme.GAP_XS)
        self.mode_switch = widgets.Segmented([
            ("cnc", "CNC", "The Roland SRM-20 mill: mill the copper, drill and "
                           "cut the board out (Ctrl+1)"),
            ("laser", "Laser", "The xTool F1 Ultra fiber laser: copper traces, "
                               "solder mask, silkscreen and stencil (Ctrl+2)"),
            ("project", "Project", "Many boards, each ticked off step by "
                                   "step as it is made (Ctrl+3)")],
            "cnc")
        self.mode_switch.changed.connect(self.show_mode)
        h.addWidget(self.mode_switch)
        # Everything after the switch belongs to the mill's page; the laser
        # page has a header of its own.
        cnc_from = h.count()

        h.addStretch(1)
        # One glance at the measured state of the job, in the order the work
        # happens: is the bed measured, is the flip fitted, is a photo on,
        # is rework boxed. Each is a dim word until it is true, then a lit
        # word with its number - so a fact that is missing is missing
        # visibly. The first interface's strip had two more, the board and
        # the link; here both are already on screen at all times (the rail's
        # job line, the bar's chip), and the header has room for four chips
        # at 1280 px, not six.
        self.chips = {}
        for name, tip in (
                ("mesh", "The bed height map: lit once at least three "
                         "points are measured and the map is applied on "
                         "export. Shows the point count."),
                ("fit", "The measured flip of a double-sided board: lit once "
                        "the fiducials have been found and fitted. Shows "
                        "the rotation the fit found."),
                ("photo", "A photo of the milled board is laid over the "
                          "design, so uncut copper can be seen."),
                ("boxes", "Rework areas boxed for a second pass. Shows how "
                          "many.")):
            chip = widgets.Chip(name.capitalize(), "idle")
            chip.setToolTip(tip)
            self.chips[name] = chip
            h.addWidget(chip)
        h.addSpacing(theme.GAP_XS)
        self.coords = QLabel("")
        self.coords.setFont(theme.font("small", mono=True))
        self.coords.setStyleSheet(f"color: {theme.TEXT_3};")
        self.coords.setMinimumWidth(150)
        self.coords.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        h.addWidget(self.coords)
        self._cnc_header = [h.itemAt(i).widget() for i in range(cnc_from, h.count())
                            if h.itemAt(i).widget() is not None]
        # The tier is the window's, not the mill's: on both pages, and the
        # chip is the switch.
        self.tier_chip = widgets.ClickChip("Novice", "idle")
        self.tier_chip.setToolTip(
            "Which set of controls is on screen. Click to switch between "
            "Novice and Pro; Help ▸ What Novice and Pro differ by says "
            "exactly what Pro adds.")
        self.tier_chip.clicked.connect(self._toggle_tier)
        h.addWidget(self.tier_chip)
        return head

    def _build_canvas_bar(self):
        """The bed's own tools, above it: where the work sits (turn, mirror,
        centre, undo), the photo, and how it is drawn. The laser page has
        the same row above its bed."""
        from PySide6.QtWidgets import QMenu, QToolButton
        bar = QWidget()
        bar.setObjectName("panel")
        h = QHBoxLayout(bar)
        h.setContentsMargins(theme.GAP_M, theme.GAP_XS, theme.GAP_M,
                             theme.GAP_XS)
        h.setSpacing(theme.GAP_S)
        self.turn_left_btn = widgets.button(
            "Turn left", on=lambda: self.action_turn(90),
            tip="Turn the board a quarter turn anticlockwise (undoable).")
        self.turn_right_btn = widgets.button(
            "Turn right", on=lambda: self.action_turn(-90),
            tip="Turn the board a quarter turn clockwise (undoable).")
        self.mirror_btn = widgets.button(
            "Mirror", on=lambda: self.action_mirror(not self.state.mirror),
            tip="Mirror the design left to right. The bottom copper is cut "
                "from above, so it is mirrored by default; untick only for "
                "Gerbers that are already mirrored.")
        self.centre_btn = widgets.button(
            "Centre", on=lambda: self.action_autoplace("auto"),
            tip="Centre the job on the copper sheet once it is set, else on "
                "the bed. Ctrl+Z puts it back.")
        self.undo_btn = widgets.button("Undo", on=self.action_undo,
                                       enabled=False,
                                       tip="Take back the last change on the "
                                           "bed (Ctrl+Z).")
        for w in (self.turn_left_btn, self.turn_right_btn, self.mirror_btn,
                  self.centre_btn, self.undo_btn):
            h.addWidget(w)
        h.addSpacing(theme.GAP_S)
        h.addWidget(widgets.vrule())
        self.photo_btn = QToolButton()
        self.photo_btn.setText("Photo ▾")
        self.photo_btn.setPopupMode(QToolButton.InstantPopup)
        self.photo_btn.setToolTip("A photo of the milled board, laid over the "
                                  "design: for finding spots to fix.")
        self.photo_menu = QMenu(self.photo_btn)
        self.photo_btn.setMenu(self.photo_menu)
        h.addWidget(self.photo_btn)
        h.addStretch(1)
        self.frame_switch = widgets.Segmented(
            [("bed", "As cut",
              "Machine coordinates: exactly what the machine will do, in the "
              "frame VPanel and the position readout use."),
             ("xray", "X-ray",
              "The board as KiCad drew it — the top view, unmirrored — for "
              "finding a pad by looking at KiCad, and on a double-sided job "
              "for checking that the two faces register. This is NOT what "
              "gets cut.")], "bed")
        self.frame_switch.changed.connect(self._on_frame)
        h.addWidget(self.frame_switch)

        # Fit (Ctrl+0) and Travel moves are in the View menu: the bar has to
        # fit a laptop beside the rail and the inspector.
        self.travel_btn = widgets.button(
            "Travel moves", on=self._toggle_travel,
            tip="Show the moves where the bit is in the air. Useful for "
                "spotting a path that crosses the board when it should go "
                "around.")
        self.travel_btn.setCheckable(True)
        self.travel_btn.setChecked(True)
        self.travel_btn.setVisible(False)
        return bar

    def _build_menus(self):
        mb = self.menuBar()

        f = mb.addMenu("&File")
        self._act(f, "Open Gerber folder…", self.action_open, "Ctrl+O")
        self.add_board_act = self._act(f, "Add another board to the sheet…",
                                       self.action_add_board, "Ctrl+Shift+O")
        self._act(f, "Open the demo board", self.action_open_demo)
        self.dxf_act = self._act(f, "Open a DXF for the laser…",
                                 self.action_traces_laser_dxf)
        self.dxf_act.setToolTip("Copper traces drawn as a DXF, etched on the "
                                "laser without a Gerber folder.")
        f.addSeparator()
        self._act(f, "Save the setup…", self.action_save_setup, "Ctrl+S")
        self._act(f, "Load a setup…", self.action_load_setup)
        f.addSeparator()
        self.export_act = self._act(f, "Export the job…", self.action_export,
                                    "Ctrl+E")
        self.export_folder_act = self._act(f, "Open the export folder",
                                           self.action_open_export_folder)
        self._act(f, "Show the run sheet", self.action_show_sheet)
        f.addSeparator()
        self._act(f, "Quit", self.close, "Ctrl+Q")

        e = mb.addMenu("&Edit")
        # Window-wide, but a text or number field with the keyboard keeps its
        # own Ctrl+Z: Qt offers it the key first.
        self.undo_act = self._act(e, "Undo", self.action_undo,
                                  QKeySequence.Undo)
        self.redo_act = self._act(e, "Redo", self.action_redo)
        self.redo_act.setShortcuts([QKeySequence("Ctrl+Shift+Z"),
                                    QKeySequence("Ctrl+Y")])
        self._sync_undo()

        # Kept: a menu reached again through the menu bar's actions can be a
        # wrapper Qt has already let go of.
        v = self.view_menu = mb.addMenu("&View")
        self._act(v, "The CNC mill", lambda: self.show_mode("cnc"), "Ctrl+1")
        self._act(v, "The xTool laser", lambda: self.show_mode("laser"), "Ctrl+2")
        self._act(v, "The project", lambda: self.show_mode("project"), "Ctrl+3")
        v.addSeparator()
        self._act(v, "Fit the work", self.action_fit, "Ctrl+0")
        self._act(v, "Fit the whole bed", lambda: self.stage.fit(), "Ctrl+Shift+0")
        # The bed toolbar's Centre, for the keyboard.
        self._act(v, "Centre the job", lambda: self.action_autoplace("auto"),
                  "Ctrl+B")
        v.addSeparator()
        # The chip at the top right is the switch; these are the same, for
        # the keyboard and for the menu-minded.
        self.tier_group = QActionGroup(self)
        self.tier_group.setExclusive(True)
        self.essential_act = self._act(v, "Novice controls",
                                       lambda: self.set_tier(tier.ESSENTIAL),
                                       checkable=True)
        self.full_act = self._act(v, "Pro controls",
                                  lambda: self.set_tier(tier.FULL),
                                  checkable=True)
        for a in (self.essential_act, self.full_act):
            self.tier_group.addAction(a)
        v.addSeparator()
        self.xray_act = self._act(v, "Design X-ray", self._toggle_xray, "Ctrl+D",
                                  checkable=True)
        self.travel_act = self._act(v, "Travel moves", self._toggle_travel_menu,
                                    checkable=True, checked=True)
        self.bed_act = self._act(v, "Spoilboard screw grid", self._toggle_bed,
                                 "Ctrl+G", checkable=True, checked=True)
        self.trail_act = self._act(v, "Tool trail", self.action_trail,
                                   checkable=True, checked=True)
        self.trail_act.setToolTip(
            "Leave a fading trail of where the bit has been, so a pass can "
            "be followed by its tracks.")
        self.trail_clear_act = self._act(v, "Clear the trail",
                                         self.action_clear_trail)
        v.addSeparator()
        self._act(v, "Watch this step in 3D…", self.action_sim3d, "Ctrl+3")
        v.addSeparator()
        pm = self.photo_menu
        self._act(pm, "Lay a photo of the board on the bed…",
                  self.action_load_photo)
        self._act(pm, "Take one with a phone…", self.action_phone_photo)
        self.photo_clear_act = self._act(pm, "Take the photo off",
                                         self.action_clear_photo)
        self.photo_clear_act.setEnabled(False)
        self.photo_anchor_act = self._act(
            pm, "Choose which holes anchor the photo…", self.action_photo_anchors)
        # The photo's strength and the design's fade, as sliders in the menu
        # itself: the menu stays open while one is dragged and the bed
        # updates underneath. Greyed until there is a photo to adjust.
        from PySide6.QtWidgets import QWidgetAction
        from gerber2rml.gui2.photo import PhotoControls
        self.photo_controls = PhotoControls()
        self.photo_controls.opacity_changed.connect(self._on_photo_opacity)
        self.photo_controls.dim_changed.connect(self._on_photo_dim)
        self.photo_controls_act = QWidgetAction(self)
        self.photo_controls_act.setDefaultWidget(self.photo_controls)
        self.photo_controls_act.setEnabled(False)
        pm.addAction(self.photo_controls_act)
        # What the setup file keeps about the photo: the file and the anchor
        # pairs it was fitted on (the warp is re-done from them on load),
        # and the holes the operator chose to anchor on, if any.
        self._photo_overlay = None      # {path, photo_pts, machine_pts}
        self._photo_anchor_pts = None   # [(x, y)] chosen holes, machine mm
        self._photo_opacity = 1.0
        self._photo_dim = 0.55
        v.addSeparator()
        self.measure_act = self._act(v, "Measure — drag a ruler on the bed",
                                     self.action_measure, "Ctrl+M",
                                     checkable=True)
        self.measure_act.setToolTip(
            "Drag a line on the stage. Both ends snap to the board's corners, "
            "edges and hole centres, and to the copper sheet's corners, so "
            "corner-to-corner reads the board's true size.")
        self._act(v, "Simulate a file in 3D…", self.action_sim_file)

        m = mb.addMenu("&Machine")
        from gerber2rml.engine import rmlspool
        if rmlspool.MACOS:
            from gerber2rml.gui2 import macmill
            self._act(m, "Set up the mill on this Mac…",
                      lambda: macmill.setup_sheet(self))
        if rmlspool.LINUX:
            from gerber2rml.gui2 import linuxmill
            self._act(m, "Set up USB access…",
                      lambda: linuxmill.setup_sheet(self))
        if not rmlspool.WINDOWS:
            # Command Set and the spindle speed, which otherwise need VPanel
            # on a Windows PC. Not offered on Windows: the Roland driver owns
            # the device there and VPanel is at hand (engine/millsetup.py).
            from gerber2rml.gui2 import millsettings
            self._act(m, "The mill's settings…",
                      lambda: millsettings.settings_sheet(self))
            m.addSeparator()
        self._act(m, "Rescan the serial ports", self.bar.refresh_ports)
        self._act(m, "Connect / disconnect", self.bar._toggle_connect, "Ctrl+L")
        m.addSeparator()
        self._act(m, "Move the head to the View position",
                  self.action_view_position)
        m.addSeparator()
        self.track_act = self._act(m, "Track this step's run",
                                   self.action_track_run, checkable=True)
        self.track_act.setToolTip(
            "Follow the run on the mill from the bit's position: the bar "
            "shows how far it has got and how long is left. Press Run in "
            "VPanel, then this; or leave the next item on and it starts by "
            "itself.")
        self.autotrack_act = self._act(m, "Start tracking when the bit moves",
                                       self.action_autotrack, checkable=True,
                                       checked=True)
        self.autotrack_act.setToolTip(
            "Start following the selected step as soon as the bit has been "
            "moving for a moment, so nothing has to be pressed here when "
            "the run starts in VPanel. A jog from this app does not count.")
        # Following a run is simply on: it starts by itself when the bit
        # moves. The two switches stay as state, off the menu.
        for a in (self.track_act, self.autotrack_act):
            m.removeAction(a)
        m.addSeparator()
        self.align_act = self._act(m, "Align the overlay to the bit",
                                   self.action_align_overlay, checkable=True)
        self.align_act.setToolTip(
            "When the machine's work origin is not where the design sits on "
            "screen, the drawn bit lands beside the hole it is really in. "
            "Turn this on, then click the design point the bit is "
            "PHYSICALLY at. Only the picture, click-to-jog and run tracking "
            "are corrected; the exported files are untouched.")
        self.trim_clear_act = self._act(m, "Clear the overlay trim",
                                        self.action_clear_trim)
        self.trim_clear_act.setEnabled(False)
        m.addSeparator()
        self.screw_act = self._act(m, "Export the hold-down screw file…",
                                   self.action_export_screws)
        self.fixture_act = self._act(m, "Export the bed fixture (pin holes)…",
                                     self.action_export_fixture)
        m.addSeparator()
        m.addSeparator()
        self.mtest_act = self._act(m, "Machine test…", self.action_machine_test)
        m.addSeparator()
        h = mb.addMenu("&Help")
        self.guide_act = self._act(h, "User guide (web)…", self.action_user_guide,
                                   "F1")
        self.guide_act.setToolTip(USER_GUIDE_URL)
        self._act(h, "How this works", self.action_help)
        self.basics_act = self._act(h, "The machine, in five minutes",
                                    self.action_basics)
        self._act(h, "What Novice and Pro differ by…",
                  lambda: dialogs.about_tier(self))
        self.kicad_act = self._act(h, "Add the SRM-CAM buttons to KiCad…",
                                   self.action_setup_kicad_plugin)
        self.kicad_act.setToolTip("Adds three buttons to KiCad's PCB editor: "
                                  "show the build area, set the design rules "
                                  "for how the board is made, and send it "
                                  "here.")
        self.discord_act = self._act(h, "Join the Discord…",
                                     self.action_join_discord)
        self._act(h, "Give feedback…",
                  lambda: QDesktopServices.openUrl(QUrl(FEEDBACK_URL)))
        h.addSeparator()
        self.update_act = self._act(h, "Check for updates…",
                                    self.action_check_updates)
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
        if self.laser_view is not None and hasattr(self.laser_view,
                                                   "apply_tier"):
            self.laser_view.apply_tier()
        # A step Novice has no row for: back to the start of its three.
        if self._current_step is not None and not tier.is_full() \
                and self._current_step.key not in self._novice_keys():
            self.select_step("setup")

    def automatic(self):
        """Is the run on the rail? Always, in both tiers: Pro runs the same
        smart run as Novice, and has the steps as well."""
        return True

    def action_run_step(self, key):
        """Pro: one step of the plan, sent to the mill by itself - found,
        probed and cut as Mill it would, without the rest."""
        if not tier.is_full():
            return
        self.autorun_page.start(only=key)

    def _toggle_tier(self):
        self.set_tier(tier.ESSENTIAL if tier.is_full() else tier.FULL)

    # ------------------------------------------------------------ the method
    def method_id(self):
        """How the board's copper is made: ``fab.FLAT``, ``fab.BALL`` or
        ``fab.LASER``. Until a board has said, the tool profile says."""
        if self._method in fab.IDS:
            return self._method
        return fab.from_profile(self.state.trace.effective_diameter())

    @property
    def _traces_on_laser(self):
        """The copper is etched on the laser; the mill drills and cuts out."""
        return self.method_id() == fab.LASER

    def laser_method(self):
        return self.method_id() == fab.LASER

    def holes_drilled_first(self):
        """Does the mill drill this board's holes before the laser? On a
        laser board it does (Drill and cut out, then the laser); on any
        other, once a drilling step or the run is ticked off."""
        if self.state.board is None:
            return False
        if self.laser_method():
            return True
        done = [s.key for s in (self.plan or []) if s.op == "drill"
                or s.key == "autorun"]
        return any(self.traveller.is_done(k) for k in done)

    def check_width(self):
        """The narrowest gap between two nets this board's method can make:
        the trace cutter on the mill, the laser's floor on the laser."""
        if self.laser_method():
            return fab.FLOOR[fab.LASER]
        return self.state.trace.effective_diameter()

    def _method_key(self):
        return "method/" + self._sides_key().split("/", 1)[1]

    def action_method(self, mid, source="chosen", *, quiet=False):
        """Make the board ``mid``. Chosen here, it is remembered for the
        board's folder; a mill method brings its tool profile with it."""
        if mid not in fab.IDS:
            return
        old = self.method_id()
        self._method, self._method_source = mid, source
        if (source == "chosen" and self.remember_board_choices
                and self.state.board is not None):
            workspace.set_setting(self._method_key(), mid)
        if fab.is_mill(mid) and fab.from_profile(
                self.state.trace.effective_diameter()) != mid:
            self._apply_method_profile(mid)
        self._sync_laser_method(old, mid)
        self._drc_memo = None
        self._paths_cache = {}
        self._after_params()
        self._sync_method()
        if not quiet and old != mid:
            self.say("ok", f"{fab.name(mid)}: "
                           + ("the mill drills the holes and cuts the board "
                              "out with tabs; the copper is etched on the "
                              "laser." if mid == fab.LASER else
                              "the checks and the tool are this bit's now."))

    def _apply_method_profile(self, mid):
        """The first tool profile that is this method's, applied."""
        table = presets_mod.load_presets()
        for name, preset in table.items():
            bit = (preset.get("trace") or {}).get("bit_diameter")
            if fab.from_profile(bit) == mid:
                presets_mod.apply_preset(self.state, preset)
                self._apply_auto_depth()
                combo = self.inspector.setup.preset
                combo.blockSignals(True)
                combo.setCurrentText(name)
                combo.blockSignals(False)
                return True
        return False

    def _sync_laser_method(self, old, new):
        """A laser board is milled as a one-sided job: the holes and the
        cut-out go through, and both copper faces are the laser's."""
        page = getattr(self, "autorun_page", None)
        if new == fab.LASER and old != fab.LASER:
            if self._double:
                self._double_before_laser = True
                self.inspector.setup.double.setChecked(False)
        elif old == fab.LASER and new != fab.LASER:
            if self._double_before_laser:
                self.inspector.setup.double.setChecked(True)
            self._double_before_laser = None
        if page is not None:
            page.sync_method()

    def _detect_method(self):
        """What a board just opened is made with: what was chosen for it here
        before, else what KiCad stored, else the guess from its gaps."""
        st = self.state
        if st.board is None:
            return
        said = (workspace.setting(self._method_key(), "")
                if self.remember_board_choices else "")
        from gerber2rml.loader import gerber_stem
        try:
            stem = gerber_stem(Path(st.gerber_dir))
        except Exception:                               # noqa: BLE001
            stem = None
        kicad = fab.read_kicad(st.gerber_dir, stem) if st.gerber_dir else None
        self._method_gap = None
        if said in fab.IDS:
            mid, src = said, "chosen"
        elif kicad:
            mid, src = kicad, "kicad"
        else:
            mid, self._method_gap = fab.guess(st.board)
            src = "guessed"
        self.action_method(mid, src, quiet=True)
        if src == "guessed" and mid != fab.FLAT:
            self.say("info", f"Made on the {fab.METHODS[mid].short.lower()}, "
                             f"guessed from the narrowest gap between two "
                             f"nets ({self._method_gap:.2f} mm). Click the "
                             f"chip at the top to change it.")
        elif src == "kicad":
            self.say("info", f"{fab.name(mid)}, as set in KiCad.")

    def _sync_method(self):
        chip = getattr(self, "method_chip", None)
        if chip is None:
            return
        if self.state.board is None:
            chip.set("No board", "idle")
            chip.setToolTip("How the board is made. Open a board first.")
        else:
            mid = self.method_id()
            words = fab.SOURCE_WORDS.get(self._method_source, "")
            chip.set(f"{fab.METHODS[mid].short} · {words}",
                     "live" if mid == fab.LASER else "idle")
            gap = (f" Narrowest gap between two nets: "
                   f"{self._method_gap:.2f} mm." if self._method_gap else "")
            chip.setToolTip(f"{fab.name(mid)}, {words}. {fab.METHODS[mid].about}"
                            f"{gap}\nClick to choose another way to make it.")
        for mid, a in self.method_acts.items():
            a.setChecked(self.state.board is not None and mid == self.method_id())
        chip.setEnabled(self.state.board is not None)

    def _sync_sim_port(self):
        """The simulated mill is for trying things out, in Pro only."""
        from gerber2rml.gui2 import machine as _machine
        _machine.SHOW_SIM = tier.is_full()
        if hasattr(self.bar, "refresh_ports"):
            self.bar.refresh_ports()

    def _sync_tier(self):
        # A project of many boards is Pro's; Novice makes one board.
        if hasattr(self, "mode_switch"):
            self.mode_switch.set_option_visible("project", tier.is_full())
            if not tier.is_full() and self.mode() == "project":
                self.show_mode("cnc")
        from gerber2rml.gui2 import machine as _machine
        full = tier.is_full()
        self.tier_chip.set("Pro" if full else "Novice",
                           "live" if full else "idle")
        self.essential_act.setChecked(not full)
        self.full_act.setChecked(full)
        pinned = tier.pinned_tier() is not None
        self.essential_act.setEnabled(not pinned)
        self.full_act.setEnabled(not pinned)
        for a in (self.dxf_act, self.fixture_act, self.mtest_act,
                  self.align_act, self.trim_clear_act, self.export_act,
                  self.export_folder_act, self.add_board_act, self.screw_act,
                  self.track_act, self.autotrack_act):
            a.setVisible(full)
        self.export_act.setEnabled(full)       # and its Ctrl+E with it
        self.traveller.set_novice(not full)
        self.bar.offline_note.setText(
            _machine.OFFLINE_SIM_ONLY if self.bar.sim_only
            else _machine.OFFLINE_PRO if full else _machine.OFFLINE_NOVICE)
        self.autorun_page.sync_tier()
        self._sync_sim_port()
        # The fit and the boxes are Full-tier work; a chip saying "Fit —"
        # to someone who cannot reach the fit would be a control to explain.
        self.refresh_chips()

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

    def _centring_target(self, on="auto"):
        """What "centre it" should centre the job ON, and what to call it.

        The bed is the wrong answer whenever the copper is a particular sheet
        in a particular place: centring on the travel puts the job in the
        middle of the MACHINE, which on a sheet clamped off to one side is a
        job centred on bare spoilboard. What the job has to land on is metal.

        Metal the spindle can also reach, so the sheet is clipped to the
        travel — the far corner of a sheet that overhangs the bed is not
        somewhere a board can be put.

        ``on`` names the target outright: "bed" is the travel whatever the
        sheet says, "copper" is the sheet, and "auto" is the sheet whenever
        one has a size. The two explicit ones are in the View menu, because
        the operator knows which of the two they are looking at and should
        not have to guess which one a single button picked.
        """
        bx, by = BACKENDS[self.state.machine].bed
        sx, sy, sw, sh = self.stock
        if on == "bed" or sw <= 0 or sh <= 0:
            return (0.0, 0.0, bx, by), "the bed"
        cx0, cy0 = max(0.0, sx), max(0.0, sy)
        cx1, cy1 = min(bx, sx + sw), min(by, sy + sh)
        if cx1 - cx0 <= 0 or cy1 - cy0 <= 0:
            # The sheet is entirely out of reach; centring on it is meaningless.
            return (0.0, 0.0, bx, by), "the bed"
        clipped = (cx0 > sx or cy0 > sy or cx1 < sx + sw or cy1 < sy + sh)
        return ((cx0, cy0, cx1, cy1),
                "the reachable part of the copper" if clipped else "the copper")

    def action_autoplace(self, on="auto"):
        """Drop the whole job into the middle of the copper it has to be cut from.

        A board that nearly fills the sheet does not want nudging into place a
        millimetre at a time — it wants centring, once, with whatever margin is
        left shared equally on both sides. That margin is the honest measure of
        how much room there is to be wrong by, so it is what the confirmation
        reports.

        ``on`` is "bed", "copper" or "auto"; see :meth:`_centring_target`.
        """
        if self.state.board is None:
            self.say("warn", "Load a board first.")
            return
        if on == "copper" and not self._stock_set:
            # The placeholder sheet is a picture, not a fact. Centring on it
            # would put the job in the middle of a rectangle nobody measured.
            self.say("warn", "Say where the copper is first — its size, and "
                             "its corner if it is not on the fixture, under "
                             "The copper. Then centre on it.")
            return
        extent = self.job_extent()
        if extent is None:
            return
        x0, y0, x1, y1 = extent
        (tx0, ty0, tx1, ty1), what_on = self._centring_target(on)
        bx, by = tx1 - tx0, ty1 - ty0
        w, h = x1 - x0, y1 - y0
        # Move so the extent is centred: the gap either side is (target - span)/2.
        # Every board by the same amount, so a panel keeps its shape. Undoable
        # like every other move.
        self.remember()
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

    def work_extent(self):
        """Like :meth:`work_bounds`, with the reference holes of a fiducial
        job: all of it has to land on the stock, and they can be outside the
        board."""
        b = self.work_bounds()
        if b is None or not self._double or self._registration != "fiducial":
            return b
        lay = self._ds_layout()
        if lay is None or not lay.align_holes:
            return b
        xs = [x + s * d / 2.0 for x, _y, d in lay.align_holes for s in (-1, 1)]
        ys = [y + s * d / 2.0 for _x, y, d in lay.align_holes for s in (-1, 1)]
        return (min(b[0], *xs), min(b[1], *ys), max(b[2], *xs), max(b[3], *ys))

    def work_reach(self):
        """What has to be ON the copper, ``(x0, y0, x1, y1)`` machine mm.

        Cut out, that is the whole job: :meth:`work_extent`, outline and
        all. Left in the sheet, the outline is not cut and may hang off the
        piece - a board drawn bigger than the copper it is made on, slid
        until the part that matters is on it. Then only what is cut counts:
        the copper of both layers (the top is drawn where the design has
        it, as the bottom is), the holes, and the reference holes, each by
        where the tool's centre goes. The run measures the same from its
        toolpaths before it starts (engine/autorun.py, ``_reach``); this is
        the cheap version, for a check that is redrawn as the board is
        dragged.
        """
        ext = self.work_extent()
        board = self.state.board
        if ext is None or not self._no_cutout or board is None:
            return ext
        r = self.state.trace.effective_diameter() / 2.0
        boxes = []
        for g in (board.copper, getattr(board, "copper_top", None)):
            if g is not None and not g.is_empty:
                b = g.bounds
                boxes.append((b[0] - r, b[1] - r, b[2] + r, b[3] + r))
        for x, y, _d in (board.holes or []):
            boxes.append((x, y, x, y))
        if not boxes:
            return ext
        x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
        x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
        # The board's own frame to the bed's: a double-sided layout moves
        # the board to make room for its reference holes.
        wb = self.work_bounds()
        base = (board.outline if board.outline is not None
                else board.copper).bounds
        dx, dy = wb[0] - base[0], wb[1] - base[1]
        x0, y0, x1, y1 = x0 + dx, y0 + dy, x1 + dx, y1 + dy
        if self._double and self._registration == "fiducial":
            lay = self._ds_layout()
            for hx, hy, d in (lay.align_holes if lay is not None else []):
                x0, y0 = min(x0, hx - d / 2.0), min(y0, hy - d / 2.0)
                x1, y1 = max(x1, hx + d / 2.0), max(y1, hy + d / 2.0)
        # Never beyond the outline's own extent: copper a hair over the
        # board edge is the outline check's business, not this one's.
        return (max(x0, ext[0]), max(y0, ext[1]),
                min(x1, ext[2]), min(y1, ext[3]))

    def _on_machine_position(self, x, y, z, touch):
        # The bar shows the RAW machine readout, VPanel-equal. Everything
        # drawn on the design - the bit, its trail, the run tracking, the 3D
        # cursor - is in the design frame, so it takes the overlay trim.
        self._last_xyz = (x, y, z)
        tx, ty = self._overlay_trim
        dx, dy = x + tx, y + ty
        self._last_pos = (dx, dy)
        self.stage.set_tool((dx, dy), touch=touch)
        sim = self._sim()
        if sim is not None:
            sim.set_live_position(dx, dy)
        self._on_tracking(dx, dy, z)

    # ------------------------------------------------------- run tracking
    def _track_feeds(self, step):
        """(xy_feed, plunge_feed) mm/s for a step - the ones its file carries,
        so the readout lands on the estimate the rail showed."""
        job = {"traces": self.state.trace, "top_traces": self.state.trace,
               "drill": self.state.drill, "align": self.state.drill,
               "cutout": self.state.cutout}.get(step.op)
        if job is None:
            job = self.state.trace
        return job.xy_feed, job.plunge_feed

    def _arm_tracking(self, silent=False):
        """Follow the step the rail is on. True when armed; otherwise it has
        said why, unless ``silent`` (the auto-start must not nag on every
        poll)."""
        if self.plan is None or self.state.board is None:
            if not silent:
                self.say("warn", "Load a board first — there is no run to "
                                 "follow.")
            return False
        key = self.traveller.current()
        step = self.plan.by_key(key) if key else None
        if step is None or step.kind != "run":
            if not silent:
                self.say("warn", "Pick a numbered step in the plan; that is "
                                 "the run the bar will follow.")
            return False
        cached = self._paths_cache.get(step.key)
        try:
            # The stage built this toolpath when the step was selected; the
            # auto-start runs from the position poll and must not build an
            # isolation pass on the GUI thread in the middle of a run.
            paths = cached[0] if cached else self._toolpaths_for(step)[0]
        except Exception as e:
            if not silent:
                self.report_error("That step's toolpath could not be built, "
                                  "so its run cannot be followed", e)
            return False
        xy, plunge = self._track_feeds(step)
        total = self.tracker.arm(paths, xy, plunge, label=step.title)
        run = getattr(self.bar, "run", None)
        if run is not None:
            run.set_armed(step.title, total, self.link.is_connected())
        self.track_act.blockSignals(True)
        self.track_act.setChecked(True)
        self.track_act.blockSignals(False)
        return True

    def _disarm_tracking(self):
        self.tracker.disarm()
        run = getattr(self.bar, "run", None)
        if run is not None:
            run.clear()
        self.track_act.blockSignals(True)
        self.track_act.setChecked(False)
        self.track_act.blockSignals(False)

    def action_track_run(self, on):
        if not on:
            self._disarm_tracking()
            return
        if not self._arm_tracking():
            self._disarm_tracking()
            return
        if self.link.is_connected():
            self.say("info", f"Following {self.tracker.label} from the "
                             f"bit's position.")
        else:
            self.say("info", f"Following {self.tracker.label} once the "
                             f"machine is connected.")

    def action_autotrack(self, on):
        self.tracker.auto = bool(on)

    def _on_tracking(self, x, y, z):
        """One live position into the tracker, and its answer onto the bar."""
        def start():
            # A run that finished and a bit that moves again is the next
            # run: rebuild in place, as the first interface did.
            if self._arm_tracking(silent=True):
                self.say("info", f"The bit is moving — following "
                                 f"{self.tracker.label}.")
                return True
            return False
        result = self.tracker.feed(x, y, z, start=start)
        run = getattr(self.bar, "run", None)
        if result is None or run is None:
            return
        frac, _elapsed, remaining = result
        run.set_run(self.tracker.label, frac, remaining)

    # ----------------------------------------------- the overlay and the bit
    def action_align_overlay(self, on):
        """Arm the one-shot pick: the next click on the bed is where the bit
        physically is, and the difference becomes the overlay trim."""
        if not on:
            self._align_armed = False
            return
        if not self.link.is_connected() or self._last_xyz is None:
            self.say("warn", "Connect the machine and wait for a position "
                             "reading first; the trim is measured from "
                             "where the bit is.")
            self.align_act.setChecked(False)
            return
        self._align_armed = True
        self.bar.jog_btn.setChecked(True)
        self.set_stage_mode("jog")
        self.say("info", "Click the design point the bit is physically at — "
                         "the hole it is in, say. Nothing moves.")

    def action_clear_trim(self):
        self._set_trim(0.0, 0.0)
        self.say("ok", "Overlay trim cleared: the drawn bit is at the raw "
                       "machine position again.")

    def _set_trim(self, tx, ty):
        self._overlay_trim = (float(tx), float(ty))
        on = bool(tx or ty)
        self.trim_clear_act.setEnabled(on)
        self.trim_clear_act.setText(
            f"Clear the overlay trim (dX {tx:+.2f}, dY {ty:+.2f} mm)" if on
            else "Clear the overlay trim")
        # The crumbs were laid in the old frame; they would draw as a step.
        self.stage.clear_trail()
        if self._last_xyz is not None:
            x, y, z = self._last_xyz
            self.stage.set_tool((x + tx, y + ty))
            self._last_pos = (x + tx, y + ty)

    def _on_align_pick(self, x, y):
        self._align_armed = False
        self.align_act.setChecked(False)
        if self._last_xyz is None:
            self.say("warn", "No position from the machine yet; the trim "
                             "was not set.")
            return
        mx, my, _mz = self._last_xyz
        self._set_trim(x - mx, y - my)
        tx, ty = self._overlay_trim
        self.say("ok", f"Overlay trimmed by dX {tx:+.2f}, dY {ty:+.2f} mm. "
                       f"The picture, click-to-jog and run tracking follow "
                       f"it; the job itself is untouched.")

    def _on_jog_step(self, dx, dy):
        """An arrow on the jog pad, or an arrow key: move the head by (dx, dy)
        mm from where it is. Relative, so it is right whatever the overlay
        trim says - unlike a click, which names an absolute point."""
        if not self.link.is_connected():
            self.say("warn", "Not connected — there is nothing to jog.")
            return
        if self._last_xyz is None:
            self.say("warn", "Waiting for a position reading before "
                             "jogging.")
            return
        x, y, z = self._last_xyz
        nx, ny = x + dx, y + dy
        bx, by = self.stage.bed
        if not (0 <= nx <= bx and 0 <= ny <= by):
            self.say("warn", "That step would take the head off the "
                             "machine's travel.")
            return
        # A jog does not lift, so with the bit on the copper it would drag it
        # sideways: a still 0.8 mm bit does not survive that.
        if getattr(self.bar, "_touching", False):
            self.say("warn", "The bit is touching the copper. Raise it first: "
                             "Page Up.")
            return
        self.link.jog_by(dx, dy)
        # Advance the local position now, so quick taps are checked against
        # where they are heading, not all against the same stale XY.
        self._last_xyz = (nx, ny, z)

    def action_trail(self, on):
        self.stage.set_trail_visible(on)

    def action_clear_trail(self):
        self.stage.clear_trail()

    # ------------------------------------------------------- status chips
    def refresh_chips(self):
        """Bring the header's status chips up to date. Cheap, and called on a
        timer as well as from the handlers that change what it reads."""
        chips = getattr(self, "chips", None)
        if not chips:
            return
        try:
            n = len(self.level_page.points())
        except Exception:
            n = 0
        applied = n >= 3 and self.level_page.is_active()
        # Measured but not applied is the state that costs boards: the
        # number is there and the map is doing nothing. Amber, not green.
        chips["mesh"].set(f"Mesh {n}" if n else "Mesh",
                          "ok" if applied else "warn" if n >= 3 else "idle")
        fit = self._top_fit
        if fit is not None:
            import math
            chips["fit"].set(f"Fit {math.degrees(fit.theta):+.2f}°", "ok")
        else:
            chips["fit"].set("Fit", "idle")
        photo = self.stage.has_photo()
        chips["photo"].set("Photo", "ok" if photo else "idle")
        boxes = len(getattr(self.rework_page, "_regions", []) or [])
        chips["boxes"].set(f"Boxes {boxes}" if boxes else "Boxes",
                           "ok" if boxes else "idle")
        # A chip shows once it has something to say: four dim words were
        # 330 px of a header that has to fit a laptop.
        on_mill = self.mode() != "laser"
        lit = {"mesh": n > 0, "fit": fit is not None, "photo": photo,
               "boxes": bool(boxes)}
        for name, chip in chips.items():
            chip.setVisible(on_mill and lit[name])

    def _on_op_done(self, name, _result):
        """A touch just measured where the copper is: the Z-reach check can
        be answered now instead of hedged."""
        if name in ("zero_z", "touch") and self.state.board is not None:
            self.refresh_checks()

    def _on_linked(self, _info):
        sim = self._sim()
        if sim is not None:
            sim.set_live_enabled(True)
        self.refresh_chips()
        # Armed before the link was up: the readout said "connect", and now
        # it can count.
        if self.tracker.is_tracking() and getattr(self.bar, "run", None):
            self.bar.run.set_armed(self.tracker.label, self.tracker.total)

    def _on_unlinked(self, _reason):
        self.stage.set_tool(None)
        sim = self._sim()
        if sim is not None:
            sim.set_live_enabled(False)
        # No position, no run to follow; the trim was measured against a
        # position that is gone too.
        self._last_xyz = None
        self._disarm_tracking()
        self._align_armed = False
        self.align_act.setChecked(False)
        self.refresh_chips()
        # A probe run measures its grid from the last live position. After
        # a reconnect the first fresh reading is a poll away, and the stale
        # one was the LAST probe point - so a second run started in that
        # window was laid out from the wrong datum, off the board.
        self._last_pos = None
        if self.state.board is not None:
            self.refresh_checks()        # the surface is unknown again

    def _sync_frame_options(self):
        """The X-ray means two different things, and both are wanted.

        On a double-sided job it is the registration check: both faces in the
        design frame, where they are meant to overlay. On a single-sided job
        it is the first interface's "As designed (KiCad top)": the same
        mirrored board, viewed flipped, so a pad can be found by looking at
        KiCad. It used to be disabled there, which left most users with no
        way to check the layout against the one they drew.
        """
        self.frame_switch.set_option_enabled("xray", True)
        self.xray_act.setEnabled(True)
        self._sync_flip()

    def _sync_flip(self):
        """The view flip is the single-sided X-ray and nothing else: the
        double-sided X-ray builds real design-frame geometry instead."""
        self.stage.set_flip_x(self.stage.frame == "xray" and not self._double)

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
                          (getattr(self.bar, "jog_btn", None), "jog"),
                          (getattr(self, "measure_act", None), "measure"),
                          (getattr(getattr(self, "boardfit_page", None),
                                   "pick_chk", None), "pad"),
                          (getattr(getattr(self, "autorun_page", None),
                                   "pick_btn", None), "stock"),
                          (getattr(getattr(self, "autorun_page", None),
                                   "box_btn", None), "box"),
                          (getattr(getattr(self, "autorun_page", None),
                                   "nogo_btn", None), "box")):
            if box is not None and mode != owns and box.isChecked():
                box.blockSignals(True)
                box.setChecked(False)
                box.blockSignals(False)
        if mode == "jog":
            # The arrow keys jog the bit while the stage has the keyboard;
            # turning jog on hands it over, so they work at once.
            self.stage.setFocus()
        else:
            self._align_armed = False
            self.align_act.setChecked(False)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_toast()

    def _place_toast(self):
        if not self.toast.isVisible():
            return
        self.toast.fit_to(max(self.width() - theme.RAIL_W
                              - self.inspector.width() - 60, 260))
        x = theme.RAIL_W + 24
        y = self.height() - theme.BAR_H - self.toast.height() - 20
        self.toast.move(x, y)

    # ------------------------------------------------------------- the plan
    def refresh_plan(self):
        old_plan = self.plan
        holes, align = None, None
        if self._double and self.state.board is not None:
            lay = self._ds_layout()
            if lay is not None:
                holes, align = lay.holes, lay.align_holes
        self.plan = runplan.build(self.state, double_sided=self._double,
                                  registration=self._registration, holes=holes,
                                  align_holes=align, dowels=self.dowel_spec(),
                                  bed_bite=self._bed_bite,
                                  flip_axis=self.flip_axis(),
                                  autorun=True, method=self.method_id(),
                                  laser_jobs=self.laser_jobs())
        # A time worked out from a toolpath still in hand stays: renaming the
        # job rebuilt the plan and wiped every estimate on the rail.
        if old_plan is not None:
            for st_ in self.plan.steps:
                was = old_plan.by_key(st_.key)
                if (st_.seconds is None and was is not None
                        and was.seconds is not None
                        and st_.key in self._paths_cache):
                    st_.seconds = was.seconds
        if self._exported:
            self.plan.apply_estimates(
                {n: estimate_file_seconds(p) for n, p in self._exported.items()
                 if p.suffix == ".nc"})
        # Novice sees its few rows of the same plan: the run needs all of it.
        self.traveller.set_plan(self.plan, self.novice_rail())
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
        # The first rebuild runs before the pages exist.
        if getattr(self, "level_page", None) is not None:
            self.level_page.sync_job()      # tier, sidedness, registration
        self.traveller.set_export_enabled(
            self.state.board is not None,
            "" if self.state.board is not None
            else "Load a Gerber folder first.")

    def novice_rail(self):
        """Novice's rows of the plan, or None in Pro (the whole plan): its
        board, its check, the run on the mill, and the laser's rows."""
        if tier.is_full() or self.plan is None:
            return None
        rows = []
        for k, (t, d) in NOVICE_RAIL.items():
            step = self.plan.by_key(k)
            if step is not None:
                rows.append(replace(step, title=t or step.title, detail=d,
                                    note=""))
        return rows + [s for s in self.plan if s.group == "laser"]

    def _novice_keys(self):
        return {s.key for s in (self.novice_rail() or [])}

    def laser_jobs(self):
        """The laser's rows this board has: the copper on a laser board, and
        the mask, silkscreen and stencil its folder has layers for."""
        st = self.state
        if st.board is None:
            return ()
        folder = self._laser_board().gerber_dir
        memo = getattr(self, "_laser_jobs_memo", None)
        if memo is None or memo[0] != str(folder):
            have = []
            for kind, find in (("mask", soldermask.mask_layer_path),
                               ("silk", silkscreen.silk_layer_path),
                               ("stencil", stencil.paste_layer_path)):
                try:
                    if any(find(folder, side) for side in ("bottom", "top")):
                        have.append(kind)
                except Exception:                       # noqa: BLE001
                    pass
            memo = self._laser_jobs_memo = (str(folder), tuple(have))
        return (("traces",) if self.laser_method() else ()) + memo[1]

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
            self._sync_method()
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
        self._sync_method()

    def select_step(self, key):
        if self.plan is None:
            return
        step = self.plan.by_key(key)
        if step is None:
            return
        if key == "rework" and self.laser_method() and self.state.board:
            # A laser board's copper was etched, not milled: its spots are
            # fixed where they were made, with the laser's rework boxes.
            self.traveller.select(key)
            self._open_laser_kind("traces")
            view = self.laser_view
            if self.mode() == "laser" and view is not None:
                view.mode.set_current("rework")
                view._set_mode("rework")
            return
        if step.kind == "laser":
            # A laser row brings up the laser, on that job; the rail stays.
            self.traveller.select(key)
            self._open_laser_kind(key.split("_", 1)[1])
            if self.mode() != "laser":
                # It could not open (the reason was said): back where it was.
                cur = self._current_step
                self.traveller.select(cur.key if cur is not None else "setup")
            return
        if self.mode() == "laser":
            self.show_mode("cnc")
        # A mode a page put the bed in belongs to that page: leaving Fix
        # spots with its boxes armed made dragging the board on Your board
        # draw boxes instead.
        owners = {"box": ("rework", "autorun"), "pad": ("fitdrill",),
                  "stock": ("autorun",), "screws": ("setup",)}
        if key not in owners.get(self.stage.mode, (key,)):
            self.set_stage_mode("place")
        self._current_step = step        # what the 3D view acts on
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
        if step.op in ("traces", "drill", "cutout", "align",
                       "top_traces", "fitdrill"):
            cached = self._paths_cache.get(step.key)
            if cached is not None:
                # The SAME list objects go back to the stage, which lets it
                # recognise them and keep both its built QPainterPath and its
                # rendered raster. Handing it freshly-built equal lists would
                # cost a path rebuild and a full re-stroke for no reason.
                _p, _f, width, cuts, rapids, far = cached
                if self._iso_worker is None:
                    self.stage.set_busy("")
                self.stage.set_toolpaths(cuts, rapids, far=far, cut_width=width)
                self._draw_shorts(step)
                self._set_legend(step)
                return
            self.stage.set_busy("Working out the toolpath…")
            QApplication.processEvents()
            self._iso_defer = True
            try:
                try:
                    paths, far_paths, width = self._toolpaths_for(step)
                finally:
                    self._iso_defer = False
            except _IsolationDeferred as req:
                # Built on a worker; the redraw when it lands draws whatever
                # step is selected then. Nothing is drawn meanwhile: the old
                # pass is for a board that is no longer where it was.
                self.stage.set_toolpaths([], [])
                self._set_legend(step)
                self._isolate_in_background(req)
                return
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
            if self._iso_worker is None:
                self.stage.set_busy("")
            if (self._stock_turn is not None and step.side != "top"
                    and step.op != "fitdrill"):
                from gerber2rml.engine.fiducial import apply_to_toolpaths
                paths = apply_to_toolpaths(paths, self._stock_turn)
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
        if job is None:
            return
        secs = estimate_toolpaths_seconds(paths, job.xy_feed, job.plunge_feed)
        step.seconds = secs
        self.traveller.refresh_step(step.key, self.plan)
        if self.inspector.stack.currentWidget() is self.inspector.step:
            self.inspector.step.est.set("~" + format_duration(secs))

    def _toolpaths_for(self, step):
        """(paths, far_side_paths, cut_width) for one step, in the machine frame."""
        from gerber2rml.engine.drill import drill_single_bit, drill_holes
        from gerber2rml.engine.cutout import cut_outline
        st = self.state
        width = st.trace.effective_diameter()
        if not self._double:
            if step.op == "fitdrill":
                from gerber2rml.engine.boardfit import warp_holes
                holes = st.board.holes
                if self._board_fit is not None:
                    holes = warp_holes(holes, self._board_fit)
                dj = self.cutting_drill()
                return (drill_single_bit(holes, dj) if st.drill.single_bit
                        else drill_holes(holes, dj), None, st.drill.bit_diameter)
            if step.op == "drill":
                return (drill_single_bit(st.board.holes, self.cutting_drill())
                        if st.drill.single_bit
                        else drill_holes(st.board.holes, self.cutting_drill()),
                        None, st.drill.bit_diameter)
            if step.op == "cutout":
                return (cut_outline(st.board.outline, self.cutting_cutout(),
                                    stock=self.declared_stock()),
                        None, st.cutout.bit_diameter)
            return (self._edge_free(
                        step.key,
                        self._isolated(st.board.copper, self.cutting_trace(),
                                       st.board.outline),
                        st.board.outline, st.board.copper,
                        getattr(st.board, "copper_nets", None)),
                    None, width)
        lay = self._ds_layout()
        if lay is None:
            return [], None, width
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
            top = self._edge_free(
                step.key, self._isolated(lay.top_copper, tj, lay.top_outline),
                lay.top_outline, lay.top_copper,
                self._nets_aligned(getattr(st.board, "copper_top_nets", None),
                                   st.board.copper_top, lay.top_copper))
            return self._fit_paths(top), None, width
        return (self._edge_free(
                    step.key, self._isolated(lay.bottom_copper, tj,
                                             lay.outline),
                    lay.outline, lay.bottom_copper,
                    self._nets_aligned(getattr(st.board, "copper_nets", None),
                                       st.board.copper, lay.bottom_copper)),
                None, width)

    # Copper with more vertices than this is isolated off the GUI thread
    # when the stage asks for it: a ground-poured board is a second or more
    # of shapely, and the window froze for all of it. A small board is done
    # before a "working" note could be read, so it is drawn at once.
    BACKGROUND_COORDS = 8000
    ISO_MEMO = 6                   # isolation passes kept

    def _isolated(self, copper, job, outline):
        """``isolate(copper, job, outline=outline)``, remembered.

        A pure function of the three, so the answer for the same copper
        object, outline object and an equal job can be handed back - after
        a drill or cut-out edit, a step switch, or a pass the background
        built. Asked from the stage (``_iso_defer``) for copper that has not
        been isolated and is slow to, it raises :class:`_IsolationDeferred`
        instead, and the stage has it built in the background."""
        for c, o, j, paths in reversed(self._iso_memo):
            if c is copper and o is outline and j == job:
                # A copy, list for list, as a fresh build would be: whatever
                # the caller does to its lists stays out of the memo. The
                # moves themselves are frozen.
                return [list(tp) for tp in paths]
        failed = self._iso_failed
        if (self._iso_defer and self._iso_slow(copper)
                and not (failed is not None and failed[0] is copper
                         and failed[1] is outline and failed[2] == job)):
            raise _IsolationDeferred(copper, job, outline)
        from gerber2rml.engine.traces import isolate
        paths = isolate(copper, job, outline=outline)
        self._remember_isolation(copper, job, outline, paths)
        return paths

    def _iso_slow(self, copper):
        import shapely
        try:
            return shapely.get_num_coordinates(copper) > self.BACKGROUND_COORDS
        except Exception:                       # noqa: BLE001 - just build it
            return False

    def _remember_isolation(self, copper, job, outline, paths):
        import copy
        self._iso_memo.append((copper, outline, copy.deepcopy(job),
                               [list(tp) for tp in paths]))
        del self._iso_memo[:-self.ISO_MEMO]

    def _isolate_in_background(self, request):
        """Build ``request``'s isolation on a worker; redraw when it lands.

        One worker at a time. When it finishes, its pass is remembered and
        the stage redraws whatever step is selected by then: if the board
        moved or a setting changed meanwhile, that redraw misses the memo
        and starts the next build - the latest wins, and a stale pass is
        never drawn."""
        if self._iso_worker is not None:
            return                  # the redraw after it picks up this one
        import copy
        job = copy.deepcopy(request.job)    # the GUI may edit the original
        worker = _IsolationWorker(request.copper, job, request.outline)
        # A bound method of this window: the call is queued onto the GUI
        # thread, never run on the worker's.
        worker.done.connect(self._isolation_landed)
        self._iso_worker = worker
        worker.start()

    def _isolation_landed(self, paths, err):
        worker = self._iso_worker
        if worker is None:
            return
        worker.wait()
        _LIVE_WORKERS.discard(worker)
        self._iso_worker = None
        copper, job, outline = worker.args
        self.stage.set_busy("")
        if err is not None:
            # Built again on the GUI thread, where the failure is reported
            # the way every other toolpath failure is.
            self._iso_failed = (copper, outline, job)
        else:
            self._remember_isolation(copper, job, outline, paths)
        # The step on the stage now - the rail's row on the full tier, and on
        # the essential tier, whose three rows stand for several steps, the
        # step that was last asked for.
        step = self._current_step
        if (step is not None and self.plan is not None
                and self.plan.by_key(step.key) is not None):
            self._draw_step(self.plan.by_key(step.key))
        else:
            self._refresh_preview_now()

    def _toolpath_busy(self):
        """True while an isolation pass is being built in the background."""
        return self._iso_worker is not None

    def _wait_toolpaths(self, timeout_s=120.0):
        """Block until the background build (and the redraw it triggers) is
        done. For tests and for leaving the window; the GUI never needs it."""
        import time
        end = time.monotonic() + timeout_s
        while self._iso_worker is not None and time.monotonic() < end:
            self._iso_worker.wait(50)
            QApplication.processEvents()

    def _edge_free(self, key, paths, outline, copper, nets):
        """An isolation pass without the part along the board's edge, when
        the board is left in the sheet - and only when leaving it out is
        proved to join no nets (engine/bracket.py, ``leave_edge``).

        Here, where the toolpaths are made, so that the picture on the bed,
        the time estimate, the exported file and the automatic run are all
        the same passes. Proved by milling both versions out of the sheet on
        paper and comparing which nets share a piece of copper: if leaving
        the edge uncut joins any that the whole pass keeps apart, the whole
        pass is used and the checks say why. Without net names in the
        Gerbers every piece of copper counts as its own net, which is the
        careful reading: a track that would be left joined to the pour
        keeps the edge pass.
        """
        if not self._no_cutout or outline is None or outline.is_empty:
            self._edge_notes.pop(key, None)
            return paths
        from gerber2rml.engine.bracket import joined_nets, leave_edge
        band = self.state.trace.effective_diameter()
        memo_key = (key, outline.bounds, copper.bounds, round(band, 4),
                    len(paths), sum(len(tp) for tp in paths))
        hit = self._edge_memo.get(key)
        if hit is not None and hit[0] == memo_key:
            return hit[1]
        trimmed, uncut = leave_edge(paths, outline, band)
        result = paths
        if uncut <= 0.0:
            self._edge_notes.pop(key, None)
        else:
            sheet = outline.buffer(5.0)     # the copper beyond the outline
            r = band / 2.0
            before = [set(j) for j in joined_nets(copper, nets, paths,
                                                  sheet, r)]
            joined = [j for j in joined_nets(copper, nets, trimmed, sheet, r)
                      if not any(set(j) <= b for b in before)]
            self._edge_notes[key] = (uncut, joined)
            if not joined:
                result = trimmed
        self._edge_memo[key] = (memo_key, result)
        return result

    def _edge_checks(self):
        """What became of the isolation along the board's edge."""
        out = []
        for key, (uncut, joined) in sorted(self._edge_notes.items()):
            if joined:
                out.append(diag.Check(
                    "warn", "The edge pass is kept",
                    "the board is left in the sheet, but leaving out the "
                    "isolation along its edge would put these on one piece "
                    "of copper: %s. So that pass is cut as usual."
                    % "; ".join(" + ".join(j) for j in joined)))
            else:
                out.append(diag.Check(
                    "ok", "The board's edge is left uncut",
                    "%.0f mm of isolation along the board's edge is left "
                    "out: the board stays in the sheet, so there is no edge "
                    "to isolate from. Milled out on paper, it joins no "
                    "nets." % uncut))
        return out[:1] if out and all(c.level == "ok" for c in out) else out

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
               self._registration, self.fiducial_spec(), self.dowel_spec())
        if self._layout_base is None or self._layout_key != key:
            try:
                self._layout_base = layout_double_sided(
                    self.state.gerber_dir, offset=(0.0, 0.0),
                    rotate=self.state.rotate, registration=self._registration,
                    dowels=self.dowel_spec(), fiducials=self.fiducial_spec())
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
                        dowels=self.dowel_spec(), fiducials=self.fiducial_spec())
                    self.stage.set_board(prev.bottom_copper, prev.outline,
                                         prev.holes, copper_far=prev.top_copper,
                                         align_holes=prev.align_holes)
                    self.stage.set_pin_drag(self._pins_draggable())
                    return
                except Exception as e:
                    # Never the machine frame under a badge that says design.
                    self.frame_switch.set_current("bed")
                    self.xray_act.setChecked(False)
                    self.stage.set_frame("bed")
                    self.say("fail", f"The design X-ray could not be built "
                                     f"({e.__class__.__name__}: {e}). Showing "
                                     f"the bed frame instead.")
            if step is not None and (step.side == "top" or (
                    self._auto_top and step.key == "autorun")):
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
                # The top view is the board AFTER the flip, warped to a
                # measured fit: a pin dragged there has no single place to
                # go back to in the design. Drag them on a bottom-side step
                # or in the X-ray.
                self.stage.set_pin_drag(False)
            else:
                # Turned with the stock once the run has found it: the cuts
                # are, and a design drawn square under them looks skewed.
                t = self._stock_turn
                if t is not None:
                    self.stage.set_board(
                        self._warp_geom(lay.bottom_copper, t),
                        self._warp_geom(lay.outline, t),
                        [(*t.apply(x, y), d) for x, y, d in lay.holes],
                        align_holes=[(*t.apply(x, y), d)
                                     for x, y, d in lay.align_holes])
                    self.stage.set_pin_drag(False)
                else:
                    self.stage.set_board(lay.bottom_copper, lay.outline,
                                         lay.holes, align_holes=lay.align_holes)
                    self.stage.set_pin_drag(self._pins_draggable())
        elif (step is not None and step.op == "fitdrill"
              and self._board_fit is not None):
            # The board where its pads were measured, not where the design
            # put it: the holes drawn, the drill path and a click-to-jog all
            # have to agree with the copper on the bed.
            from gerber2rml.engine.boardfit import warp_holes
            t = self._board_fit
            self.stage.set_pin_drag(False)
            self.stage.set_members([], 0)
            self.stage.set_board(self._warp_geom(st.board.copper, t),
                                 self._warp_geom(st.board.outline, t),
                                 warp_holes(st.board.holes, t))
        elif self._stock_turn is not None:
            t = self._stock_turn
            self.stage.set_pin_drag(False)
            self.stage.set_members([], 0)
            self.stage.set_board(self._warp_geom(st.board.copper, t),
                                 self._warp_geom(st.board.outline, t),
                                 [(*t.apply(x, y), d)
                                  for x, y, d in st.board.holes])
        else:
            self.stage.set_pin_drag(False)
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
        # Novice has no Traces step to look at: its "Check it" is where the
        # finding is read, so that is where the marks are.
        here = (step.op in ("traces", "top_traces")
                or (step.key == "checks" and not tier.is_full()))
        if here and self.state.board is not None:
            self.stage.set_shorts(self._shorts)
            self.stage.set_gaps(self._gaps)
        else:
            self.stage.set_shorts([])
            self.stage.set_gaps(None)

    def _set_legend(self, step):
        """Only what is actually on the canvas.

        A key listing colours the current view does not contain teaches the
        reader that the key is decoration, and then they stop reading it.
        """
        cutting = step.op in ("traces", "drill", "cutout", "align",
                              "top_traces", "fitdrill")
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
        if (self._gaps is not None and not self._gaps.is_empty
                and step.op in ("traces", "top_traces")):
            legend.append((theme.DANGER_LO, "gap too narrow for the cutter"))
        if self.level_page._points:
            legend.append((theme.PROBE, "probe point"))
        self.stage.set_legend(legend)

    # ------------------------------------------------------------ the checks
    def _cut_copper(self):
        """The bottom copper in the frame the stage draws and the job cuts:
        the double-sided layout's when there is one, else the board's own."""
        if self._double:
            try:
                lay = self._ds_layout()
            except Exception:                   # noqa: BLE001 - no layout yet
                lay = None
            copper = getattr(lay, "bottom_copper", None)
            if copper is not None and not copper.is_empty:
                return copper
        return self.state.board.copper

    def _cut_nets(self, copper):
        """The net names for ``copper``'s polygons, or None when they cannot
        be trusted to line up: the board's list is in its own copper's order,
        and the double-sided layout's copper is a second copy of it, moved.
        It is used only when polygon for polygon they are the same shapes."""
        return self._nets_aligned(
            getattr(self.state.board, "copper_nets", None),
            self.state.board.copper, copper)

    @staticmethod
    def _nets_aligned(nets, mine, theirs):
        """``nets`` (in the order of ``mine``'s polygons) if ``theirs`` is
        the same polygons in the same order, moved; else None."""
        if nets is None or mine is None or theirs is None:
            return None
        a = list(getattr(mine, "geoms", []))
        b = list(getattr(theirs, "geoms", []))
        if len(nets) != len(a) or len(a) != len(b):
            return None
        if any(abs(p.area - q.area) > 1e-6 for p, q in zip(a, b)):
            return None
        return nets

    def refresh_checks(self):
        st = self.state
        if st.board is None:
            self._checks, self._shorts, self._gaps = [], [], None
            self._corners = None
            self.inspector.checks.set_checks([])
            self.traveller.clear_finding()
            return
        # The copper where it is DRAWN and cut. A double-sided job's layout
        # moves the board over to make room for its reference holes, and marks
        # worked out on the unmoved board landed beside it on the stage.
        copper = self._cut_copper()
        (self._shorts, self._eaten, self._gaps,
         self._corners) = self._copper_drc(copper)
        dowel_depth = None
        if (self._double and self._registration == "dowel"
                and self._dowel_mode == "fresh"):
            # Fresh dowel holes go through the stock and on into the bed. They
            # are the deepest cut of a two-sided job, and a Z-reach check
            # that does not know about them passes a job the machine cannot
            # finish. Grid pins are already in the bed: those holes only
            # clear the stock, and the drill check covers that.
            dowel_depth = (self.inspector.setup.thickness.value()
                           + self._bed_bite)
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
                eaten=self._eaten, method=self.method_id(),
                thickness=self.inspector.setup.thickness.value())
        except Exception as e:
            # The banner is drawn from the shorts, which were worked out above
            # and are still good. Leaving on the early return left it saying
            # what the LAST run of these checks found - a stale headline about
            # a setting the operator has since changed, which is worse than no
            # headline at all.
            self._checks = []
            self._sync_banner()
            self.report_error("The pre-flight checks could not run", e,
                              "Reload the board and try again. Nothing has "
                              "been written.")
            return
        checks += self._gap_checks()
        checks += self._stock_checks()
        checks += self._edge_checks()
        checks += self._nogo_checks()
        # The run page draws where the surface will be touched; that moves
        # with the board, and this is what runs when the board has moved.
        page = getattr(self, "autorun_page", None)
        if page is not None:
            page._show_touches()
        checks += self._panel_checks()
        checks += self._two_sided_depth_check()
        checks += self._screw_checks()
        self._checks = checks
        self.inspector.checks.set_checks(checks)
        self._sync_banner()

    def _copper_drc(self, copper):
        """``(shorts, eaten, gaps, corners)`` for ``copper`` as it is cut.

        The copper against itself: a second of shapely on a ground-poured
        board, and the same answer wherever the board sits. A board that
        has only MOVED - dragged, nudged, typed, placed by the run page,
        turned a quarter or mirrored - gets the last answer moved with it;
        anything else (another bit, another board) works it out again."""
        st = self.state
        outline = st.board.outline
        nets = self._cut_nets(copper)
        laser = self.laser_method()
        key = (repr(st.trace), laser)
        memo = self._drc_memo
        if memo is not None and memo[0] == key and memo[1] == nets:
            moved = _moved_by(memo[2], copper, memo[3], outline)
            if moved is not None:
                return _translate_drc(memo[4], moved)
        bit = self.check_width()
        try:
            shorts = isolation_bridges(copper, bit, nets=nets)
        except Exception:
            shorts = []                 # a DRC that crashes must not block work
        if laser:
            # The laser clears round every copper edge, so no gap is too
            # narrow for it to enter; only one under its floor is a short.
            found = (shorts, [], None, None)
            self._drc_memo = (key, nets, copper, outline, found)
            return found
        eaten = []
        if shorts and st.trace.cut_pinches:
            try:
                from gerber2rml.engine.pinch import pinch_losses
                eaten = pinch_losses(copper, st.trace)
            except Exception:
                eaten = []              # ...and neither must this one
        try:
            from gerber2rml.analysis import find_narrow_gaps
            from gerber2rml.engine.drc import EXACT_FIT_MM
            # Less the exact-fit allowance: a gap the cutter's own width is
            # cut down its middle, not left red.
            from gerber2rml.analysis import split_narrow_gaps
            gaps, corners = split_narrow_gaps(
                find_narrow_gaps(copper, outline, bit - EXACT_FIT_MM), copper)
        except Exception:
            gaps, corners = None, None
        found = (shorts, eaten, gaps, corners)
        self._drc_memo = (key, nets, copper, outline, found)
        return found

    def _gap_checks(self):
        """Copper gaps too narrow for the cutter to enter.

        A different failure from a short. A short is two NETS closer than the
        bit, which no cut can fix. A sliver is any clearance narrower than
        the bit — between two pads of one net as often as not — and the
        cutter simply never goes there, so the copper is left joined. Where
        such a sliver happens to lie between different nets it IS the short
        the check above reports; where it does not, it is copper that was
        meant to be cleared and will not be, which matters for solder
        bridging and for a design that relied on the gap.
        """
        gaps = self._gaps
        corners = getattr(self, "_corners", None)
        bit = self.state.trace.effective_diameter()
        out = []
        if corners is not None and not corners.is_empty:
            k = len(corners.geoms) if hasattr(corners, "geoms") else 1
            out.append(diag.Check(
                "ok",
                f"{k} inside corner{'s' if k != 1 else ''} left as copper",
                f"where a track meets another at an angle, the round "
                f"{bit:.2f} mm cutter cannot reach into the point. That "
                f"copper stays, as part of the track it is the corner of: "
                f"nothing is joined that was apart."))
        if gaps is None or gaps.is_empty:
            return out
        n = len(gaps.geoms) if hasattr(gaps, "geoms") else 1
        return out + [diag.Check(
            "warn",
            f"{n} copper gap{'s' if n != 1 else ''} too narrow to isolate",
            f"drawn red on the traces view: clearance narrower than the "
            f"{bit:.2f} mm cutter, which cannot enter it, so the copper "
            f"either side stays joined. A smaller bit clears them; so does "
            f"widening the gap in KiCad. Between two nets this is the "
            f"short reported above.")]

    # Steps that actually CUT a face. Every step carries a `side`, but on the
    # ones that cut nothing it is just a default - `level` says "bottom" even
    # though levelling is done on whichever face is in front of you. Reading
    # it there made opening the levelling page silently switch the height map
    # back to the bottom, and the next probe overwrote a real measurement.
    _CUTTING_OPS = ("traces", "top_traces", "drill", "cutout",
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
        self._hold = how or "bonded"
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
        from gerber2rml.doublesided import _align_drill, _fiducial_align_drill
        t = self.inspector.setup.thickness.value()
        if self._registration == "fiducial":
            job, _d = _fiducial_align_drill(self.cutting_drill(),
                                            self.fiducial_spec(), t)
        else:
            job, _d = _align_drill(self.cutting_drill(), self.dowel_spec(),
                                   None, t, self._bed_bite)
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
        # Left in the sheet, the outline is not cut: only the work counts.
        wb = self.work_reach() if self._no_cutout else self.work_bounds()
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
            from gerber2rml.engine.autorun import spans_stock
            across, along = spans_stock(x1 - x0, y1 - y0, sw, sh)
            # Bigger than the sheet one way and on it the other: the sheet's
            # edges are the board's edges that way, and Run it puts the
            # strip that hangs off where it loses no copper (run._flush).
            spanning = (self._stock_set and not self._double
                        and not self._no_cutout
                        and ((across and not (out_b or out_t))
                             or (along and not (out_l or out_r))))
            if spanning and worst > SHEET_EDGE_MM:
                out.append(diag.Check(
                    "warn", "The board is bigger than the copper",
                    "the work hangs " + " and ".join(edges) + " of the "
                    "sheet. The sheet's edges are the board's edges that "
                    "way: the cut-out leaves them out, and the board comes "
                    "out short by what hangs off. Run it puts that strip on "
                    "the side where it cuts no copper in two, and refuses "
                    "if there is none."))
            elif self._stock_set and worst <= SHEET_EDGE_MM:
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

    def _cut_edges(self, copper, board):
        """The copper edges an isolation pass runs along. All of them - or,
        for a board left in the sheet, all but those along the board's own
        edge, where nothing is cut any more (:meth:`_edge_free`)."""
        edges = copper.boundary
        if (self._no_cutout and board.outline is not None
                and not board.outline.is_empty
                and not any(j for _u, j in self._edge_notes.values())):
            band = self.state.trace.effective_diameter()
            # A pass is the cutter's radius off the copper it isolates: one
            # within ``band`` of the board's edge belongs to copper within
            # band + radius of it.
            edges = edges.difference(
                board.outline.boundary.buffer(band * 1.5))
        return edges

    def _nogo_checks(self):
        """Is any of the work in a no-go zone?

        The run refuses such a job when it starts, from its real toolpaths
        (engine/autorun.py, ``_check_nogo``). That is the last word, and it
        comes late: after the board has been placed, the clamps put on and
        Start pressed. This says it while the board can still be dragged.

        Measured from the geometry, so that it can be redrawn with every
        drag: a cut runs along the EDGE of copper, so it is the copper's
        edges that count - a pour may lie under a clamp untouched - plus
        every hole and reference hole. Both layers, each where the design
        has it. The clearance is the run's own.
        """
        page = getattr(self, "autorun_page", None)
        zones = page.nogo() if page is not None else []
        board = self.state.board
        if not zones or board is None or self.work_bounds() is None:
            return []
        from shapely.geometry import Point, box
        from gerber2rml.engine.autorun import NOGO_CLEAR_MM
        r = self.state.trace.effective_diameter() / 2.0
        wb = self.work_bounds()
        base = (board.outline if board.outline is not None
                else board.copper).bounds
        dx, dy = wb[0] - base[0], wb[1] - base[1]
        hard, soft = [], []
        for n, z in enumerate(zones, 1):
            # In the board's own frame, grown to where the cutter's EDGE
            # may not come: the tool's radius is in the cut, not the zone.
            g = NOGO_CLEAR_MM + r
            # A box, or one of the cam clamps - a disc, with its own
            # clearance (engine/nogo.py). Taking a clamp for a box raised
            # an IndexError here the moment one was marked.
            from shapely import affinity
            from gerber2rml.engine.nogo import (is_clamp, zone_bounds,
                                                zone_shape)
            zone = affinity.translate(zone_shape(z, g), -dx, -dy)
            zb = zone_bounds(z)
            where = ("clamp %d (at X %.0f, Y %.0f)" % (n, z[0], z[1])
                     if is_clamp(z) else
                     "zone %d (X %.0f-%.0f, Y %.0f-%.0f)" % (
                         n, zb[0], zb[2], zb[1], zb[3]))
            edges = [name for name, geom in (
                ("bottom copper", board.copper),
                ("top copper", getattr(board, "copper_top", None)))
                if geom is not None and not geom.is_empty
                and self._cut_edges(geom, board).intersects(zone)]
            what = []
            holes = sum(1 for x, y, _d in (board.holes or [])
                        if zone.intersects(Point(x, y)))
            if holes:
                what.append("%d hole%s" % (holes, "" if holes == 1 else "s"))
            if self._double and self._registration == "fiducial":
                lay = self._ds_layout()
                refs = sum(1 for hx, hy, _d in
                           (lay.align_holes if lay is not None else [])
                           if zone.intersects(Point(hx - dx, hy - dy)))
                if refs:
                    what.append("%d reference hole%s"
                                % (refs, "" if refs == 1 else "s"))
            if edges and not self._no_cutout:
                what = edges + what
            elif edges:
                soft.append("%s: %s" % (where, ", ".join(edges)))
            if what:
                hard.append("%s: %s" % (where, ", ".join(what)))
        out = []
        if hard:
            out.append(diag.Check(
                "fail", "Work lies in a no-go zone",
                "; ".join(hard) + ". The bit would hit what is there, and "
                "the run will refuse to start. Move the board or the clamp, "
                "or delete the zone (right-click it) if nothing is there."
                + ("" if self._no_cutout else
                   " With Leave the board in the sheet, isolation under a "
                   "clamp is left uncut instead, where that joins no nets.")))
        if soft:
            # Left in the sheet, isolation under a clamp is not cut: the
            # run takes that length out, leads the bit round, and proves on
            # paper that no two nets end up on one piece of copper - a
            # pour's own outline along the board's edge is the usual case.
            # It refuses only if they would.
            out.append(diag.Check(
                "warn", "Isolation in a no-go zone will be left uncut",
                "; ".join(soft) + ". The run leaves out the isolation "
                "there and goes round - if that joins no nets, which it "
                "checks before it cuts anything, and stops if it would. A "
                "ground pour's edge along the board's edge joins nothing."))
        if not out:
            out.append(diag.Check(
                "ok", "The work is clear of the no-go zones",
                "%d zone%s on the bed, nothing to cut within %.0f mm of one."
                % (len(zones), "" if len(zones) == 1 else "s",
                   NOGO_CLEAR_MM)))
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
        # The screws that will actually be there: the hand-picked ones when
        # there are any, else the ones drawn on the bed.
        points = (list(self._manual_screws) if self._manual_screws is not None
                  else picks)
        out += self._screw_toolpath_check(points)
        out += self._hand_picked_screw_check(points)
        return out

    def _pass_sweeps(self):
        """What each cutting pass actually removes, as ``{op: geometry}``.

        The copper keep-out that picks the screws is a stand-in: "not on the
        copper" is cheap, and right in practice, but it is not "not where the
        cutter goes". The cut-out runs OUTSIDE the outline, in the waste,
        which is exactly where a screw is put — and a screw inside that band
        passed the keep-out. This is the exact version: every pass's real
        toolpaths, each buffered by its own cutter radius. It reads the same
        cache the stage draws from, so a pass already on screen costs
        nothing, and one that is not is built once and left for the stage.

        A pass that cannot be built comes back as None so the caller can say
        it was not checked rather than pretend it passed.
        """
        from shapely.ops import unary_union
        from gerber2rml.toolpath import sweep
        sweeps = {}
        for step in (self.plan or []):
            if step.op not in ("traces", "top_traces", "drill", "cutout",
                               "align"):
                continue
            cached = self._paths_cache.get(step.key)
            if cached is not None:
                paths, width = cached[0], cached[2]
            else:
                try:
                    paths, far_paths, width = self._toolpaths_for(step)
                except Exception:
                    sweeps[step.op] = None
                    continue
                cuts, rapids = toolpath_segments(paths)
                rapids = rapids + traverse_segments(paths)
                far = toolpath_segments(far_paths)[0] if far_paths else []
                self._paths_cache[step.key] = (paths, far_paths, width,
                                               cuts, rapids, far)
            r = max(float(width or 0.0), 0.1) / 2.0
            parts = []
            for tp in paths:
                pts = [(m.x, m.y) for m in tp if not m.rapid]
                if pts:
                    parts.append(sweep(pts, r))
            sweeps[step.op] = unary_union(parts) if parts else None
        return sweeps

    _OP_NAMES = {"traces": "traces", "top_traces": "top traces",
                 "drill": "drill", "cutout": "cut-out", "align": "dowel holes"}

    def _screw_toolpath_check(self, points):
        """Every screw head against every pass. Exact, and the last word."""
        from shapely.geometry import Point
        if not points or self.state.board is None:
            return []
        try:
            sweeps = self._pass_sweeps()
        except Exception as e:
            return [diag.Check(
                "warn", "The screws could not be checked against the toolpaths",
                f"the toolpaths would not build ({e.__class__.__name__}), so "
                f"whether a cutter reaches a screw head is unknown. Select "
                f"each cutting step on the rail to see which one fails.")]
        hits = []
        for (x, y) in points:
            head = Point(x, y).buffer(spoilboard.M4_HEAD_D / 2.0)
            for op, geom in sweeps.items():
                if geom is not None and geom.intersects(head):
                    hits.append(f"X {x:.1f} Y {y:.1f} is in the "
                                f"{self._OP_NAMES.get(op, op)} path")
        if hits:
            return [diag.Check(
                "fail", "The cutter would hit a screw head",
                "; ".join(hits) + ". Move that screw to another hole (tick "
                "Pick the screw holes and click a different one), or move "
                "the job on the sheet.")]
        checked = [self._OP_NAMES.get(op, op) for op, g in sweeps.items()
                   if g is not None]
        unchecked = [self._OP_NAMES.get(op, op) for op, g in sweeps.items()
                     if g is None]
        detail = (f"checked against the real {_and_list(checked)} "
                  f"toolpaths, each as wide as its cutter." if checked
                  else "there are no cutting toolpaths to check yet.")
        if unchecked:
            detail += (f" The {_and_list(unchecked)} toolpath did not build, "
                       f"so it was not checked.")
        return [diag.Check("ok", "No pass reaches a screw head", detail)]

    def _hand_picked_screw_check(self, points):
        """Hand-picked holes are allowed anywhere on the grid, so a doubtful
        choice is reported here — a finding that stays on the checks page —
        rather than in a toast that has gone by the time the export is
        pressed. The automatic picks never need this: they were chosen to
        pass it."""
        if self._manual_screws is None:
            return []
        keep = self.state.board.copper if self.state.board is not None else None
        bad = []
        for pt in points:
            why = spoilboard.point_problem(pt, self.stock, keepout=keep)
            if why:
                bad.append(f"X {pt[0]:.1f} Y {pt[1]:.1f} {why}")
        if not points:
            return [diag.Check(
                "fail", "No screws are chosen",
                "every hole has been unpicked. Pick at least one on the bed, "
                "or press Back to the app's choice.")]
        if bad:
            return [diag.Check(
                "warn", "A hand-picked screw needs a look",
                "; ".join(bad) + ". You can see the bed and the app cannot, "
                "so it is kept — but check it before the copper goes down.")]
        return [diag.Check(
            "ok", "The hand-picked screws are all usable",
            f"{len(points)} chosen by hand, each landing fully on copper and "
            f"clear of the design.")]

    def _sync_banner(self):
        if self._shorts and self.laser_method():
            worst = min(s["gap"] for s in self._shorts)
            self.traveller.show_finding(
                "fail",
                f"{len(self._shorts)} spots too close for the laser",
                f"Worst gap {worst:.2f} mm between two nets; the laser needs "
                f"at least {self.check_width():.2f} mm to separate them.",
                action="See the checks")
            return
        if self._shorts:
            worst = min(s["gap"] for s in self._shorts)
            width = self.state.trace.effective_diameter()
            if self.state.trace.cut_pinches:
                # Cutting them anyway was asked for: the banner reports the
                # price, not a fault.
                self.traveller.show_finding(
                    "warn",
                    f"{len(self._shorts)} narrow gaps cut through",
                    f"Worst gap {worst:.2f} mm against a {width:.2f} mm "
                    f"cutter, so up to {(width - worst) / 2.0:.2f} mm comes "
                    f"off the pads either side. Nothing is left shorted.",
                    action="See the checks")
                return
            self.traveller.show_finding(
                "fail",
                f"{len(self._shorts)} spots will be shorted",
                f"Worst gap {worst:.2f} mm against a {width:.2f} mm cutter. "
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
            self._detect_sides()
            self._detect_method()
            self.autorun_page.board_opened()

    def show_auto_face(self, top):
        """Automatic mode has one step on the rail and two faces: once the
        sheet is turned over, the bed shows the top, and the first side's
        height map goes, because it describes a surface that is now underneath."""
        if top == self._auto_top:
            return
        self._auto_top = top
        if top:
            self.stage.set_level_mesh(None, None, 0.0)
            self.stage.set_probe_points([])
        self.refresh_preview()

    def _detect_sides(self):
        """Only a double-sided board has copper on both layers. Copper, not
        files: KiCad can plot an empty F.Cu for a single-sided board. Opening a
        folder decides this; the box still overrules it afterwards."""
        board = self.state.board
        if board is None or self.state.is_panel:
            return
        top = board.copper_top
        two = (top is not None and not top.is_empty
               and board.copper is not None and not board.copper.is_empty)
        # What the operator said about THIS board last time beats the guess:
        # F.Cu is also where people draw wire links on a single-sided board,
        # and a board sent from KiCad again must not turn double-sided again.
        said = (workspace.setting(self._sides_key(), "")
                if self.remember_board_choices else "")
        self._detecting_sides = True
        try:
            if said in ("single", "double"):
                self.inspector.setup.double.setChecked(said == "double")
                if two and said == "single":
                    self.say("info", "Copper on both layers, but you set this "
                                     "board up as single-sided: kept so.")
                return
            self.inspector.setup.double.setChecked(two)
        finally:
            self._detecting_sides = False
            self._restore_reference_holes()
        if two:
            self.say("info", "Copper on both layers: set up as double-sided. "
                             "Untick it on Your board if the top is not "
                             "milled; that is remembered for this board.")

    def _sides_key(self):
        """The setting that remembers one board folder's single/double."""
        import hashlib
        folder = str(workspace.remembered_dir("gerber") or "")
        return "sides/" + hashlib.sha1(folder.encode("utf-8")).hexdigest()[:16]

    def set_no_cutout(self, on):
        """Leave the board in the sheet, or cut it out as usual."""
        self._no_cutout = bool(on)
        # The isolation along the board's edge is cut or not by this: the
        # passes on the bed are another set of passes now.
        self._paths_cache = {}
        self._edge_memo, self._edge_notes = {}, {}
        if self.remember_board_choices and self.state.board is not None:
            workspace.set_setting(self._nocut_key(),
                                  "yes" if on else "no")

    def _nocut_key(self):
        return "nocut/" + self._sides_key().split("/", 1)[1]

    def _refs_key(self):
        """...and where that board's reference holes go."""
        return "refs/" + self._sides_key().split("/", 1)[1]

    def _restore_reference_holes(self):
        """A board opened again gets the reference holes it had: the waste,
        inside the corners, or its own mounting holes."""
        if not self.remember_board_choices:
            return
        self._no_cutout = workspace.setting(self._nocut_key(), "") == "yes"
        said = workspace.setting(self._refs_key(), "")
        self._restoring_refs = True
        try:
            if said == "mounting":
                self.use_mounting_holes(quiet=True)
            elif said in ("waste", "onboard") and (
                    said != self._fid_placement or self._fid_mounting):
                self.action_fiducial_layout(4, said, self._fid_offset)
        finally:
            self._restoring_refs = False
        self.inspector.setup.sync()

    # Whether what the operator says about a board - single or double
    # sided, where its reference holes go - is remembered for its folder and
    # given back when it is opened again. On in the app (gui2/app.py); off
    # for a window built by anything else, so a test or a script neither
    # reads nor leaves choices in the user's settings.
    remember_board_choices = False

    def open_from_outside(self, path):
        """A board or setup handed over by the KiCad plugin or a second
        launch (gui2/handoff.py). Returns False, and loads nothing, while a
        run is going: swapping the board under a cutting mill is not an
        "open". Otherwise it is exactly File ▸ Open (or Load setup)."""
        page = getattr(self, "autorun_page", None)
        if page is not None and getattr(page, "_thread", None) is not None:
            self.say("warn", "A run is in progress, so the board from KiCad "
                             "was not loaded. Send it again when it is done.")
            QApplication.alert(self)
            return False
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()
        QApplication.alert(self)
        if str(path).lower().endswith(".srmcam"):
            self.load_setup(path)
        else:
            self.load_folder(path)
            self._detect_sides()
            self._detect_method()
            self.autorun_page.board_opened()
        return True

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
        self._detect_method()
        self.autorun_page.board_opened()

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
        self._auto_top = False
        # A measured flip belongs to one physical board on the bed. Carrying it
        # onto the next one would draw the new board where the old one landed.
        # A setup restore re-applies its own saved fit after this call.
        self._top_fit = None
        self._fid_measured = []
        self._stock_turn = None
        # The last board's mounting holes are not this board's.
        self._leave_mounting_holes()
        self._no_cutout = False
        self._edge_memo, self._edge_notes = {}, {}
        # The last board's method is not this one's: the tool says, until
        # the board does (_detect_method, on an open).
        if self._method == fab.LASER:
            self._sync_laser_method(fab.LASER, fab.from_profile(
                self.state.trace.effective_diameter()))
        self._method, self._method_source = None, "profile"
        self._method_gap = None
        from gerber2rml.loader import gerber_stem
        self._custom_name = False
        try:
            stem = gerber_stem(Path(folder))
            if stem:
                self.state.name = clean_name(stem)
        except Exception:
            pass
        workspace.remember_dir("gerber", folder)
        self._forget_output()
        self.stage._fitted = False
        self.refresh_plan()
        self.refresh_checks()
        self.select_step("setup")
        self.stage.fit_work()
        self.autorun_page.board_loaded()
        # Not opened from the project: it lets go of the board it had.
        self.project_ctl.board_loaded_elsewhere()
        # The last board's moves are not this one's, and where the board
        # first lands is the start of its history, not a step in it.
        self.placement_undo.clear()
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
        self.remember()
        # Rows as wide as the copper from where the first board is, when the
        # copper is known: a row past the sheet's edge is no layout.
        width = None
        if self._stock_set:
            # Rows from the sheet's corner, as wide as the sheet.
            sx, sy, sw, _sh = self.stock
            x0, y0 = st.boards[0].bounds()[:2]
            st.move_all(sx + 2.0 - x0, sy + 2.0 - y0)
            width = max(sw - 4.0, 1.0)
        st.arrange(gap, width)
        page = getattr(self, "autorun_page", None)
        if page is not None and page.bracket() and self._stock_set:
            page.place_in_corner()          # the panel into the bracket
        self._paths_cache = {}
        self._after_params()
        QTimer.singleShot(0, self.stage.fit_work)
        reach = self.work_extent()
        if self._stock_set and reach is not None:
            sx, sy, sw, sh = self.stock
            if (reach[2] > sx + sw + 1e-6 or reach[3] > sy + sh + 1e-6
                    or reach[0] < sx - 1e-6 or reach[1] < sy - 1e-6):
                self.say("warn", f"The {len(st.boards)} boards need "
                                 f"{reach[2] - reach[0]:.0f} × "
                                 f"{reach[3] - reach[1]:.0f} mm and do not "
                                 f"fit on the {sw:.0f} × {sh:.0f} mm sheet. "
                                 f"Use a bigger sheet or take a board off.")
                return
        if gap <= 0:
            self.say("ok", f"{len(st.boards)} boards butted together. One cut "
                           f"runs between each pair and separates them; each "
                           f"loses half a cutter width along that edge.")
        else:
            self.say("ok", f"{len(st.boards)} boards laid out left to right, "
                           f"{gap:g} mm apart.")

    def action_name(self, text):
        """The operator typed a job name: keep it, whatever boards come and go."""
        self.state.name = clean_name(text.strip())
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
        self._mask_result = None
        self._silk_result = None
        self._stencil_result = None
        self._laser_traces_result = None
        self.traveller.clear_done()
        self.rework_page._clear()
        # Pads of the last board, measured on the last piece of copper.
        self.boardfit_page.set_pads([])
        if self.stage.has_photo():
            self._drop_photo()
        # The chosen anchor holes are holes of THIS board, at its placement.
        self._photo_anchor_pts = None
        self.stage.set_photo_anchors(None)

    def action_apply_preset(self):
        name = self.inspector.setup.preset.currentText()
        table = presets_mod.load_presets()
        if name not in table:
            return
        presets_mod.apply_preset(self.state, table[name])
        self._apply_auto_depth()
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

    def _apply_auto_depth(self):
        """Drill and cut-out depth from the board's thickness, when Your
        board says so: a profile's own depth must not quietly win over the
        number on the screen."""
        setup = getattr(getattr(self, "inspector", None), "setup", None)
        if setup is None or not setup.auto_depth.isChecked():
            return
        depth = round(setup.thickness.value() + setup.overshoot.value(), 4)
        self.state.drill.total_depth = depth
        self.state.cutout.total_depth = depth

    def action_thickness(self, thickness, overshoot, auto):
        if auto:
            depth = thickness + overshoot
            self.state.drill.total_depth = depth
            self.state.cutout.total_depth = depth
        self._after_params()

    # -- undo -----------------------------------------------------------
    def placement_snapshot(self):
        """Where every board sits, as undo keeps it: the mirror, and each
        board's name, corner and turn."""
        st = self.state
        return (bool(st.mirror),
                tuple((m.name, round(m.place_x, 6), round(m.place_y, 6),
                       int(m.rotate) % 360) for m in st.boards))

    def edit_snapshot(self):
        """Everything put on the mill's bed by hand, as undo keeps it: where
        the boards sit, the rework boxes, the no-go zones and clamps, the
        recut boxes of a run, the bracket, the screws chosen and the
        reference holes. Compared with ``==``, never looked inside."""
        rw = getattr(self, "rework_page", None)
        ar = getattr(self, "autorun_page", None)

        def rows(seq):
            return tuple(tuple(r) for r in seq)
        return (self.placement_snapshot(),
                (rows(rw._regions), tuple(rw._follow)) if rw is not None else None,
                rows(ar._nogo) if ar is not None else None,
                rows(ar._boxes) if ar is not None else None,
                ar._bracket if ar is not None else None,
                None if self._manual_screws is None else rows(self._manual_screws),
                rows(self._fid_points))

    def remember(self, merge=None):
        """Record the bed as it is, just ahead of a change, for Undo."""
        self.placement_undo.push(self.edit_snapshot(), merge=merge)

    def _restore_edit(self, snap):
        """Put the bed back as ``snap`` has it. False when the sheet holds
        other boards now - that step cannot be applied."""
        place, rework, nogo, boxes, bracket, screws, fids = snap
        now = self.edit_snapshot()
        if place != now[0] and not self._restore_placement(place):
            return False
        self.placement_undo.restoring = True
        try:
            rw, ar = self.rework_page, self.autorun_page
            if rework is not None and rework != now[1]:
                rw._regions = [tuple(r) for r in rework[0]]
                rw._follow = list(rework[1])
                rw._rebuild_table()
                rw._push()
            if nogo is not None and nogo != now[2]:
                ar._nogo = [tuple(z) for z in nogo]
                ar._show_nogo()
            if boxes is not None and boxes != now[3]:
                ar._boxes = [tuple(b) for b in boxes]
                ar._show_boxes()
            if bracket is not None and bracket != now[4]:
                ar.set_bracket(bracket)
            if screws != now[5]:
                self._manual_screws = (None if screws is None
                                       else [tuple(p) for p in screws])
                self._draw_screws()
            if fids != now[6]:
                self._fid_points = [list(p) for p in fids]
                self._layout_base = None
                self._layout_key = None
                self._paths_cache = {}
                self._after_params()
                self.refresh_preview()
            self.refresh_checks()
        finally:
            self.placement_undo.restoring = False
        return True

    def _restore_placement(self, snap):
        """Put the boards back as ``snap`` has them. False when the sheet
        holds other boards now - that step cannot be applied."""
        mirror, boards = snap
        st = self.state
        if [m.name for m in st.boards] != [b[0] for b in boards]:
            return False
        self.placement_undo.restoring = True
        try:
            if bool(st.mirror) != mirror:
                self.action_mirror(mirror)
                box = self.inspector.setup.mirror
                box.blockSignals(True)
                box.setChecked(mirror)
                box.blockSignals(False)
            for m, (_n, x, y, r) in zip(st.boards, boards):
                m.place_x, m.place_y, m.rotate = x, y, r
            st._sync()
            # Put back by hand is placed by hand: centring must not move it.
            self.autorun_page.board_dragged()
            self._paths_cache = {}
            self._after_params()
        finally:
            self.placement_undo.restoring = False
        return True

    def _step_placement(self, back):
        stack = self.placement_undo
        while True:
            now = self.edit_snapshot()
            snap = stack.undo(now) if back else stack.redo(now)
            if snap is None:
                self.say("warn", "Nothing to undo." if back
                         else "Nothing to redo.")
                return
            if self._restore_edit(snap):
                self.say("ok", "Undone." if back else "Redone.")
                return
            # A step from before a board was added or taken off: it no
            # longer fits the sheet; skip it.

    def action_undo(self):
        self._step_placement(True)

    def action_redo(self):
        self._step_placement(False)

    def _sync_undo(self):
        can_undo = self.placement_undo.can_undo()
        can_redo = self.placement_undo.can_redo()
        # On the laser page its own Ctrl+Z is the one: two live actions on
        # one key and Qt runs neither.
        laser = getattr(self, "laser_view", None)
        on_mill = laser is None or self.modes.currentWidget() is not laser
        for name, on in (("undo_act", can_undo), ("redo_act", can_redo)):
            act = getattr(self, name, None)
            if act is not None:
                act.setEnabled(on and on_mill)
        btn = getattr(self, "undo_btn", None)
        if btn is not None:
            btn.setEnabled(can_undo)

    def action_move_job(self, dx, dy):
        """Slide the whole job - every board on the sheet - by (dx, dy):
        how the bracket and the run put it in place, keeping a panel's
        shape."""
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            return
        self.remember("place")
        self.state.move_all(dx, dy)
        self._paths_cache = {}
        self._after_params()

    def action_place(self, x, y):
        # A held spin arrow or a row of typed digits is one step.
        self.remember("place")
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
        # The cut-out leaves out what lies on the sheet's edge, so it is the
        # one toolpath the sheet changes: drop it, or the preview keeps a ring
        # the cut no longer has.
        for s in (self.plan.steps if self.plan is not None else []):
            if s.op == "cutout":
                self._paths_cache.pop(s.key, None)
        if show is not None:
            self.show_stock = bool(show)
        self._draw_screws()
        self._sync_stock()
        # One sheet: Your board and the run page show the same size.
        page = getattr(self, "autorun_page", None)
        if page is not None:
            page.show_size(w, h)
        insp = getattr(self, "inspector", None)
        if insp is not None and getattr(insp, "setup", None) is not None:
            setup = insp.setup
            for spin, val in ((setup.stock_x, self.stock[0]),
                              (setup.stock_y, self.stock[1]),
                              (setup.stock_w, w), (setup.stock_h, h)):
                if abs(spin.value() - val) > 1e-9:
                    spin.blockSignals(True)
                    spin.setValue(val)
                    spin.blockSignals(False)
        self.refresh_checks()

    def action_show_sheet(self):
        """The run sheet of the last export, again - with any file written
        since on its own page (rework, a fitted drill, the top traces)."""
        args = getattr(self, "_sheet_args", None)
        if args is None or self.plan is None:
            self.say("warn", "Export the job first: the run sheet is the "
                             "export's.")
            return
        args = dict(args)
        args["extra"] = list(args.get("extra") or []) + list(
            getattr(self, "_side_files", []) or [])
        self.sheet.show_plan(self.plan, **args)
        self.centre.setCurrentWidget(self.sheet)
        if self.mode() == "laser":
            self.show_mode("cnc")

    def record_files(self, paths, heading):
        """A file written on a page of its own goes forward like the export's:
        ticked on the rail when it is a step's file, and listed on the run
        sheet under ``heading``."""
        paths = [Path(p) for p in (paths or [])]
        if not paths:
            return
        for p in paths:
            self._exported[p.name] = p
        if self._export_dir is None:
            self._export_dir = paths[0].parent
        if not hasattr(self, "_side_files"):
            self._side_files = []
        self._side_files.append((heading, (paths, [])))
        if self.plan is not None:
            self.traveller.set_exported(
                {s.key for s in self.plan if s.file and s.file in self._exported})

    def action_show_stock(self, on):
        self.show_stock = bool(on)
        self._sync_stock()

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
        # A phone photographs the whole machine. Cropped to the copper, the
        # holes are bigger on screen and the clicks land better.
        from gerber2rml.gui2.phonephoto import autocrop_to_copper
        path = autocrop_to_copper(str(dlg.photo_path))
        if path != str(dlg.photo_path):
            self.say("info", "Cropped the photo to the copper.")
        self.action_load_photo(photo_path=path)

    def decode_photo(self, path, max_dim=None):
        """An image file as an HxWx4 uint8 array, at full size unless
        ``max_dim`` bounds the longer side. Full size is the default because
        the anchor clicks and the warp are made on the same array, and the
        photo detector needs every pixel the camera took."""
        import numpy as np
        from PySide6.QtGui import QImage
        img_q = QImage(str(path))
        if img_q.isNull():
            raise ValueError("the file is not an image this app can read")
        if max_dim and max(img_q.width(), img_q.height()) > max_dim:
            img_q = img_q.scaled(max_dim, max_dim, Qt.KeepAspectRatio,
                                 Qt.SmoothTransformation)
        conv = img_q.convertToFormat(QImage.Format_RGBA8888)
        ptr = conv.constBits()
        arr = np.frombuffer(ptr, dtype=np.uint8).reshape(
            conv.height(), conv.bytesPerLine() // 4, 4)[:, :conv.width(), :]
        # An explicit copy, not ascontiguousarray: when the rows have no
        # padding the slice is already contiguous and comes back as a VIEW
        # of the QImage's pixels, which are freed with it on return - the
        # warp then read freed memory and the process went down.
        return arr.copy()

    def photo_overlay(self):
        """The photo on the bed as the setup file sees it, or None."""
        return dict(self._photo_overlay) if self._photo_overlay else None

    def photo_anchors(self, holes):
        """The holes the next photo is fitted on: the operator's own picks
        while they still match holes on screen, else the automatic corners.
        Returns ``(anchors, chosen)``."""
        from gerber2rml.gui2 import photo as photo_mod
        picked = photo_mod.snap_picks(self._photo_anchor_pts, holes)
        if picked:
            return picked, True
        return photo_mod.pick_anchor_holes(holes), False

    def action_photo_anchors(self):
        """Choose the holes a photo is fitted on, by hand.

        The automatic pick takes the corner-most holes, which is right when
        the board has dowel or fiducial holes and wrong on a single-sided
        board, whose corner holes may be tiny or impossible to tell apart in
        a photo. Here any four or more holes the operator can recognise
        again are clicked on the design, numbered on the bed, and asked for
        in that order by the photo dialog.
        """
        from PySide6.QtWidgets import QDialog as _QDialog
        from gerber2rml.gui2 import photo as photo_mod
        if self.state.board is None:
            self.say("warn", "Load a board first — the anchors are its "
                             "drilled holes.")
            return
        holes = list(self.state.board.holes or [])
        if len(holes) < 4:
            self.say("warn", "This board has fewer than four drilled holes, "
                             "so there is nothing to line a photo up on.")
            return
        dlg = photo_mod.HolePickDialog(
            self, holes, outline=self.state.board.outline,
            preset=self._photo_anchor_pts)
        if dlg.exec() != _QDialog.Accepted:
            return
        self._photo_anchor_pts = dlg.anchors()
        self.stage.set_photo_anchors(self._photo_anchor_pts)
        n = len(self._photo_anchor_pts)
        self.say("ok", f"{n} anchor holes chosen — they are numbered on the "
                       f"bed. Lay the photo on and click them in that order.")

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
            img = self.decode_photo(path)
        except Exception as e:
            self.report_error("That photo could not be opened", e,
                              "Try a JPEG or PNG straight off the camera.")
            return

        from gerber2rml.gui2 import photo as photo_mod
        anchors, chosen = self.photo_anchors(holes)
        if self._photo_anchor_pts and not chosen:
            # The picks no longer sit on holes: the board was moved or
            # swapped since. Saying so beats silently asking for corners
            # the operator did not choose.
            self.say("warn", "The anchor holes you chose no longer match "
                             "this board's holes, so the corner-most ones "
                             "are used instead.")
        dlg = photo_mod.PhotoAnchorDialog(
            self, photo_mod.to_qimage(img), anchors, holes=holes,
            outline=self.state.board.outline)
        if dlg.exec() != _QDialog.Accepted:
            return
        try:
            worst = self._apply_photo(img, dlg.photo_points(),
                                      dlg.machine_points(), path)
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

    def _apply_photo(self, img, photo_pts, machine_pts, path=""):
        """Fit, warp, and hand the result to the stage. Returns the worst
        residual in mm, which is the only honest measure of whether to trust
        what is now on screen. ``path`` is remembered so the setup file and
        the photo detector can go back to the file."""
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
        self.stage.set_photo_opacity(self._photo_opacity)
        self.stage.set_photo_dim(self._photo_dim)
        self.photo_controls.set_values(self._photo_opacity, self._photo_dim)
        self.photo_clear_act.setEnabled(True)
        self.photo_controls_act.setEnabled(True)
        self._photo_overlay = {
            "path": str(path or ""),
            "photo_pts": [[float(u), float(v)] for u, v in photo_pts],
            "machine_pts": [[float(x), float(y)] for x, y in machine_pts]}
        return float(res.max())

    def _drop_photo(self):
        self._photo_overlay = None
        self.stage.set_photo(None, None)
        self.stage.set_photo_dim(0.0)
        self.photo_clear_act.setEnabled(False)
        self.photo_controls_act.setEnabled(False)

    def action_clear_photo(self):
        self._drop_photo()
        self.say("ok", "Photo taken off — back to the design.")

    def _on_photo_opacity(self, amount):
        self._photo_opacity = float(amount)
        self.stage.set_photo_opacity(amount)

    def _on_photo_dim(self, amount):
        self._photo_dim = float(amount)
        if self.stage.has_photo():
            self.stage.set_photo_dim(amount)

    def _photo_state(self, setup_path):
        """The photo as the setup file keeps it. The file is copied beside
        the setup, so the setup survives the photo being moved or deleted -
        a phone hand-off drops it in a folder nobody tidies on purpose."""
        d = {"anchors": [list(p) for p in (self._photo_anchor_pts or [])],
             "opacity": self._photo_opacity, "dim": self._photo_dim}
        po = self._photo_overlay
        if not po:
            return d
        d.update(po)
        src = Path(po.get("path") or "")
        if src.is_file():
            copy = setup_path.with_name(
                f"{setup_path.stem}_photo{src.suffix.lower()}")
            try:
                if src.resolve() != copy.resolve():
                    import shutil
                    shutil.copy2(src, copy)
                d["copy"] = copy.name
            except OSError:
                pass                        # best effort, never blocks a save
        return d

    def _restore_photo(self, data, foreign, setup_path):
        """Put a saved photo back: the anchors first, then the fit re-done
        from the saved pairs on the original file or the copy beside the
        setup. A photo that is gone is reported, not fatal."""
        if not isinstance(data, dict):
            return
        pts = []
        for p in data.get("anchors") or []:
            try:
                pts.append((float(p[0]), float(p[1])))
            except (TypeError, ValueError, IndexError):
                continue
        self._photo_anchor_pts = pts or None
        self.stage.set_photo_anchors(self._photo_anchor_pts)
        try:
            self._photo_opacity = max(0.0, min(1.0, float(
                data.get("opacity", self._photo_opacity))))
            self._photo_dim = max(0.0, min(1.0, float(
                data.get("dim", self._photo_dim))))
        except (TypeError, ValueError):
            pass
        self.photo_controls.set_values(self._photo_opacity, self._photo_dim)
        if not data.get("photo_pts"):
            return
        src = Path(str(data.get("path") or ""))
        if not src.is_file():
            copy = data.get("copy")
            src = setup_path.with_name(str(copy)) if copy else None
            if src is None or not src.is_file():
                foreign.append("the photo (its file is gone)")
                return
        try:
            img = self.decode_photo(src)
            self._apply_photo(img, [tuple(p) for p in data["photo_pts"]],
                              [tuple(p) for p in data["machine_pts"]], src)
        except Exception:
            foreign.append("the photo")

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
        if (op not in ("traces", "top_traces", "drill", "cutout")
                and self.plan is not None and step is not None
                and step.key in ("autorun", "setup", "checks")):
            # The run and the board are the whole job: show its first cut.
            # (Novice has no step rows, and its button lives on the run.)
            step = next((s for s in self.plan.run_steps
                         if s.op in ("traces", "drill", "cutout")), step)
            op = getattr(step, "op", None)
        if op not in ("traces", "top_traces", "drill", "cutout"):
            self.say("warn", "Pick a step that cuts — the traces, the "
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
        self.open_sim3d(paths, f"{self.state.name or 'board'} — {step.title}")

    def open_sim3d(self, paths, title):
        """Open the 3D view on ``paths``. The rework page calls this with the
        pass clipped to its boxes, so what plays is only the re-cut."""
        try:
            from gerber2rml.gui2.sim3d import Simulation3DWindow
        except Exception as e:
            self.report_error(
                "The 3D view could not start", e,
                "It needs pyqtgraph and PyOpenGL. Run "
                "'python -m gerber2rml.doctor' to install the interface "
                "dependencies, then try again.")
            return
        self._open_sim(Simulation3DWindow, paths, title,
                       board=self.work_bounds())

    def _open_sim(self, Simulation3DWindow, paths, title, *, board=None):
        """One 3D window at a time, fed the live position while linked."""
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
            paths, title=title, parent=self, board=board,
            bed=BACKENDS[self.state.machine].bed,
            thickness=self.inspector.setup.thickness.value())
        # LIVE follows the machine while the link is up. The window has the
        # whole forward-only cursor; the first interface fed it and this one
        # never did, so the button stayed disabled with a tooltip blaming
        # the link.
        self._sim_window.set_live_enabled(self.link.is_connected())
        self._sim_window.show()
        self._sim_window.raise_()
        self._sim_window.activateWindow()

    def action_sim_file(self, path=None):
        """Open any exported .nc/.rml and play it in 3D.

        The stage and the step simulation show what the engine MEANS to
        write. This shows what a file actually says, which is the only way to
        check a file after the fact — one from last week, one someone edited,
        one the first interface wrote — before it is sent to the machine.
        """
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Choose a machine file to watch",
                workspace.remembered_dir("out", "exports"),
                "Machine files (*.nc *.rml *.gcode *.g);;All files (*)")
            if not path:
                return
            workspace.remember_dir("out", path)
        try:
            from gerber2rml.engine.gcode_parse import parse_file
            paths = parse_file(path)
        except Exception as e:
            self.report_error(
                f"{Path(path).name} could not be read as a machine file", e,
                "It should be a .nc (G-code) or .rml file this program or "
                "the original interface exported. A file from another CAM "
                "tool may use words this reader does not know.")
            return
        if not paths or not any(paths):
            self.say("warn", f"{Path(path).name} has no tool moves in it — "
                             f"nothing to watch.")
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
        # No board outline: the file may not belong to the board that is
        # loaded, and drawing this board under someone else's toolpath would
        # be a picture of a job that does not exist.
        self._open_sim(Simulation3DWindow, paths,
                       f"{Path(path).name} — as written")

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
        self.remember()
        self.state.set_rotation(deg)
        self._paths_cache = {}
        self._after_params()
        QTimer.singleShot(0, self.stage.fit_work)

    def action_turn(self, delta):
        """A quarter turn more, either way, from where it is now."""
        self.action_rotate((self.state.rotate + delta) % 360)

    def action_machine(self, name):
        if name in BACKENDS:
            self.state.machine = name
            self._after_params()

    def action_mirror(self, on):
        self.remember()
        self.state.mirror = on
        self._mask_result = None
        self._stencil_result = None
        self._laser_traces_result = None
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
        if self.remember_board_choices \
                and not getattr(self, "_detecting_sides", False) \
                and self.state.board is not None:
            workspace.set_setting(self._sides_key(),
                                  "double" if on else "single")
        self._mask_result = None
        self._silk_result = None
        self._laser_traces_result = None
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
            # positional: None marks a hole not measured
            self._fid_measured = [None if p is None else tuple(p)
                                  for p in measured]
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
        return self._warp_geom(g, self._top_fit)

    def set_stock_turn(self, transform):
        """The turn the autonomous run gave the job to match the stock it
        found (None: square to the bed). Drawing only - the run applies it
        to what it cuts itself."""
        self._stock_turn = transform
        self._paths_cache = {}
        self.refresh_preview()

    def set_board_fit(self, transform):
        """Adopt (or clear) the fit of a board made elsewhere, and redraw."""
        if transform == self._board_fit:
            return
        self._board_fit = transform
        self._paths_cache.pop("fitdrill", None)
        self.refresh_preview()

    @staticmethod
    def _warp_geom(g, t):
        if t is None or g is None:
            return g
        from shapely import affinity
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
        manual = self._fid_placement == "manual"
        return FiducialSpec(count=self._fid_count,
                            placement=self._fid_placement,
                            edge_offset=self._fid_offset,
                            hole_diameter=self._fid_diameter,
                            allow_scale=bool(self._fid_scale),
                            flip_axis=self._fid_flip,
                            points=(tuple(tuple(p) for p in self._fid_points)
                                    if manual else ()))

    def dowel_spec(self):
        """The dowel geometry this job uses, as the engine wants it. One home,
        for the same reason as :meth:`fiducial_spec`: the layout, the align
        drill, the export, the dowels-only export and the plan all read it."""
        from gerber2rml.doublesided import DowelSpec
        return DowelSpec(mode=self._dowel_mode, placement=self._dowel_edges,
                         pitch_x=self._grid_pitch, pitch_y=self._grid_pitch,
                         grid_pin=self._grid_pin,
                         clearance_large=self._clear_large,
                         clearance_small=self._clear_small)

    def flip_axis(self):
        """Which line the board turns over about: "vertical" is a left-right
        flip, "horizontal" a top-bottom one. Dowels fix it by which edges
        they sit beyond; fiducials leave it to the operator's word."""
        from gerber2rml.doublesided import _axis_of
        if self._registration == "fiducial":
            return self._fid_flip
        return _axis_of(self.dowel_spec())

    def reference_holes(self):
        """Where the reference holes are, as the choice the operator made:
        "waste", "onboard", "mounting" or "manual"."""
        return "mounting" if self._fid_mounting else self._fid_placement

    def mounting_holes(self):
        """The board's own holes that can be the reference holes, as
        ``([[x, y], ...], diameter)`` - design frame, from the framed board
        box's lower-left, which is what a manual FiducialSpec takes - or
        None when the board has none that will do."""
        from gerber2rml.doublesided import (preview_layout_double_sided,
                                            FiducialSpec)
        from gerber2rml.engine import mountfid
        st = self.state
        if st.board is None or st.gerber_dir is None:
            return None
        try:
            lay = preview_layout_double_sided(
                st.gerber_dir, dowels=self.dowel_spec(),
                offset=(st.place_x, st.place_y), rotate=st.rotate,
                registration="fiducial",
                fiducials=FiducialSpec(placement="onboard"))
        except Exception:                       # noqa: BLE001 - not a board
            return None
        picked = mountfid.pick(lay.holes, lay.outline.bounds,
                               bit_mm=st.drill.bit_diameter)
        if not picked:
            return None
        fx0, fy0 = lay.frame0
        return [[x - fx0, y - fy0] for x, y, _d in picked], picked[0][2]

    def use_mounting_holes(self, quiet=False):
        """Make the board's mounting holes the reference holes. False, and
        nothing changed, when it has none that will do."""
        from gerber2rml.engine import mountfid
        got = self.mounting_holes()
        if got is None:
            if not quiet:
                lo = mountfid.min_diameter(self.state.drill.bit_diameter)
                self.say("warn", "This board has no holes that can be the "
                                 "reference holes. It takes at least two of "
                                 "one size, %.1f to %.1f mm across, at "
                                 "opposite ends of the board."
                                 % (lo, mountfid.MAX_D))
            return False
        self._fid_points, self._fid_diameter = got
        self._fid_count = len(self._fid_points)
        self._fid_placement = "manual"
        self._fid_mounting = True
        self._fid_changed()
        if not quiet:
            self.say("ok", "%d of the board's own %.1f mm holes are the "
                           "reference holes: nothing extra is drilled."
                           % (self._fid_count, self._fid_diameter))
        return True

    def _leave_mounting_holes(self):
        """Back to drilled reference holes: their own size and count."""
        if self._fid_mounting:
            self._fid_mounting = False
            self._fid_points = []
            self._fid_count = 4
            self._fid_diameter = round(self.state.drill.bit_diameter + 0.8, 2)
            self._fid_placement = "waste"

    def _fid_changed(self):
        self._layout_base = None
        self._layout_key = None
        self._paths_cache = {}
        self._after_params()
        self.refresh_preview()

    def action_fiducial_layout(self, count, placement, offset):
        if self.remember_board_choices \
                and not getattr(self, "_restoring_refs", False) \
                and self.state.board is not None:
            workspace.set_setting(self._refs_key(), placement)
        if placement == "mounting":
            if not self.use_mounting_holes():
                self.inspector.setup.sync()      # the box goes back
            return
        if self._fid_mounting:
            self._leave_mounting_holes()
            count = self._fid_count
        self._fid_count = int(count)
        self._fid_placement = placement
        self._fid_offset = float(offset)
        if placement == "manual" and len(self._fid_points) != self._fid_count:
            # Start where the waste corners would have put them, so the
            # first thing on screen is a sensible layout to pull about
            # rather than four pins on top of each other at the origin.
            self._seed_fid_points()
            self.say("info", "Drag the gold pins on the stage to where the "
                             "holes should go — anywhere with copper under "
                             "them. The offset is not used.")
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

    def action_fiducial_flip(self, axis):
        """The operator's word on which way the board was turned. It changes
        the layout (the top face is reflected about it), the plan's flip
        step and the fit's nominal points, so everything is rebuilt."""
        self._fid_flip = "horizontal" if axis == "horizontal" else "vertical"
        self._layout_base = None
        self._layout_key = None
        self._paths_cache = {}
        self._after_params()
        self.refresh_preview()
        page = getattr(self, "flipfit_page", None)
        if page is not None:
            page.sync_from_job()

    def action_fiducial_scale(self, on):
        """Whether the fit may stretch the board. Kept on the job so that a
        saved setup reproduces the same fit, not only the same holes."""
        self._fid_scale = bool(on)

    def _seed_fid_points(self):
        """Manual reference holes start where the waste corners would put
        them, converted to board-relative design-frame coordinates."""
        from gerber2rml.doublesided import (preview_layout_double_sided,
                                            FiducialSpec)
        st = self.state
        if st.board is None or st.gerber_dir is None:
            return
        spec = FiducialSpec(count=self._fid_count, placement="waste",
                            edge_offset=self._fid_offset,
                            hole_diameter=self._fid_diameter,
                            flip_axis=self._fid_flip)
        try:
            lay = preview_layout_double_sided(
                st.gerber_dir, dowels=self.dowel_spec(),
                offset=(st.place_x, st.place_y), rotate=st.rotate,
                registration="fiducial", fiducials=spec)
        except Exception as e:
            self.report_error(
                "The reference holes could not be placed", e,
                "The corner layout they start from could not be built. "
                "Check the board loads as double-sided first.")
            return
        fx0, fy0 = lay.frame0
        self._fid_points = [[x - fx0, y - fy0] for (x, y, _d) in lay.align_holes]

    def _pins_draggable(self):
        """Whether the pins on the stage may be dragged: only hand-placed
        reference holes move, and only in a view whose frame can be turned
        back into a design-frame point (see :meth:`_on_pin_moved`)."""
        return (self._double and self._registration == "fiducial"
                and self._fid_placement == "manual"
                and not self._fid_mounting
                and self.state.board is not None)

    def _on_pin_moved(self, index, x, y):
        """A reference hole was dragged on the stage. The stage speaks the
        frame it is drawing in; the point is stored board-relative in the
        design frame, which is what the engine's FiducialSpec wants.

        In the X-ray that is a translation. In the bed frame the layout was
        built from the MIRRORED board, so the point is reflected back across
        the framed box along the flip direction - the inverse of what
        ``_place_fiducials(mirrored=True)`` does on the way out.
        """
        from gerber2rml.doublesided import _frame
        if not self._pins_draggable() or index >= len(self._fid_points):
            return
        st = self.state
        if self.stage.frame == "xray":
            from gerber2rml.doublesided import preview_layout_double_sided
            try:
                lay = preview_layout_double_sided(
                    st.gerber_dir, offset=(st.place_x, st.place_y),
                    rotate=st.rotate, registration="fiducial",
                    dowels=self.dowel_spec(), fiducials=self.fiducial_spec())
            except Exception:
                return
            fx0, fy0 = lay.frame0
            px, py = x - fx0, y - fy0
        else:
            lay = self._ds_layout()
            if lay is None:
                return
            fx0, fy0 = lay.frame0
            gx0, gy0, gx1, gy1 = _frame([g for g in (lay.bottom_copper,
                                                     lay.outline)
                                         if g is not None and not g.is_empty])
            w, h = gx1 - gx0, gy1 - gy0
            rx, ry = x - fx0, y - fy0
            if self._fid_flip == "horizontal":
                px, py = rx, h - ry
            else:
                px, py = w - rx, ry
        self.remember("pin%d" % index)
        self._fid_points[index] = [px, py]
        self._layout_base = None
        self._layout_key = None
        self._paths_cache = {}
        self._after_params()
        self.refresh_preview()
        self.say("info", f"Reference hole {index + 1} is now {px:+.2f}, "
                         f"{py:+.2f} mm from the board's lower-left corner.")

    def action_registration(self, kind):
        self._registration = kind or "fiducial"
        self._paths_cache = {}
        self._after_params()

    def action_dowels(self, mode, edges, pitch, pin, clear_large, clear_small,
                      bed_bite):
        """Everything about the dowel registration, in one call, because the
        inspector's controls all read the same DowelSpec and the layout is
        rebuilt either way. The clearances widen the holes without moving
        their centres (the engine promises that), so a re-cut lands back on
        the existing holes; the bite only changes depth."""
        self._dowel_mode = "grid" if mode == "grid" else "fresh"
        self._dowel_edges = "leftright" if edges == "leftright" else "topbottom"
        self._grid_pitch = float(pitch)
        self._grid_pin = float(pin)
        self._clear_large = float(clear_large)
        self._clear_small = float(clear_small)
        self._bed_bite = float(bed_bite)
        self._layout_base = None
        self._layout_key = None
        self._paths_cache = {}
        self._after_params()
        self.refresh_preview()

    def action_export_dowels_only(self):
        """Write only the dowel-hole program, over the top of the one a full
        export wrote. For the test-fit loop: a pin that binds wants a touch
        more clearance, a pin that does not seat wants a deeper bite, and
        neither should cost re-running the traces."""
        st = self.state
        if st.board is None:
            self.say("warn", "Load a Gerber folder first.")
            return
        if not (self._double and self._registration == "dowel"):
            self.say("warn", "Dowels-only is for a double-sided job registered "
                             "on dowel pins.")
            return
        from gerber2rml.doublesided import build_align_only
        out = self.export_dir()
        if out is None:
            out = QFileDialog.getExistingDirectory(
                self, "Which folder holds this job's files?",
                workspace.remembered_dir("out", "exports"))
            if not out:
                return
        try:
            path = build_align_only(
                st.gerber_dir, out, st.name, drill=self.cutting_drill(),
                dowels=self.dowel_spec(), machine=st.machine,
                offset=(st.place_x, st.place_y), rotate=st.rotate,
                board_thickness=self.inspector.setup.thickness.value(),
                bed_depth=self._bed_bite)
        except Exception as e:
            self.report_error(
                "The dowel-hole program could not be written", e,
                "Nothing has been changed. Check the folder still holds this "
                "job's files and is not read-only.")
            return
        workspace.remember_dir("out", str(path))
        self._export_dir = Path(out)
        self._exported[path.name] = path
        self.refresh_plan()
        self.say("ok", f"{path.name} rewritten - the dowel holes only. Keep the "
                       f"same XY origin so it lands on the existing holes.")

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
        # The bar's View button: where the automatic run shows the board.
        self.link.go_to_view()
        self.say("info", "Moving to the view position - keep clear of the "
                         "bed.")

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
        # Only when they are actually going to be left shorted. With the
        # narrow-gap passes on they are cut, and the price (pad, not nets) is
        # on the checks page and the banner.
        # A laser board's mill files drill and cut out: no copper is milled,
        # so there is nothing for a short to spoil in them.
        if (self._shorts and not st.trace.cut_pinches
                and not self.laser_method()
                and not dialogs.confirm_shorts(
                    self, self._shorts, st.trace.effective_diameter())):
            self.select_step("checks")
            return
        if self._double and self._registration == "dowel":
            if not dialogs.confirm_irreversible(
                    self, "The dowel holes go into the bed",
                    "Step 1 drills two holes through the stock and on into the "
                    "sacrificial bed. Those holes stay in the bed afterwards — "
                    "that is what makes the flip register, and it is also why "
                    "this is the one cut you cannot undo by re-zeroing and "
                    "trying again.",
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
                    dowels=self.dowel_spec(), bed_depth=self._bed_bite,
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
                                        stock=self.declared_stock(),
                                        traces=not self.laser_method())
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
        # The machine files are on disk; from here nothing may undo that. A
        # picture and a summary beside them, and a line in the tool ledger,
        # are worth having and not worth failing an export over.
        extras = self._write_export_extras(self._export_dir)
        wear = self._note_tool_wear()
        # The laser's files go with the mill's: one for every laser row the
        # board has, so the rail and the folder say the same job.
        kinds = self.laser_jobs()
        ltraces = (self.write_laser_traces_to(self._export_dir)
                   if self._laser_traces or "traces" in kinds else None)
        mask = (self.write_mask_to(self._export_dir)
                if self._solder_mask or "mask" in kinds else None)
        silk = (self.write_silk_to(self._export_dir)
                if self._silkscreen or "silk" in kinds else None)
        paste = (self.write_stencil_to(self._export_dir)
                 if self._stencil or "stencil" in kinds else None)
        self.refresh_plan()
        self._sheet_args = dict(
            name=st.name, out_dir=self._export_dir, machine=st.machine,
            leveled=level is not None, double_sided=self._double,
            panel=st.panel_summary() if st.is_panel else None, mask=mask,
            silk=silk,
            extra=[("For the laser: copper traces", ltraces),
                   ("For the laser: paste stencil", paste)])
        self._side_files = []
        self.action_show_sheet()
        total = self.plan.total_seconds
        self.say("warn" if "WORN" in wear or (ltraces and ltraces[1])
                 or (mask and mask[1])
                 or (silk and silk[1]) or (paste and paste[1]) else "ok",
                 f"{len(written)} files written"
                 + (f" · about {format_duration(total)} of cutting"
                    if total else "")
                 + (" · plus a picture and a summary of the board"
                    if extras else "")
                 + (" · plus the laser traces file" if ltraces and ltraces[0] else "")
                 + (" · plus the solder mask file" if mask and mask[0] else "")
                 + (" · plus the silkscreen file" if silk and silk[0] else "")
                 + (" · plus the stencil file" if paste and paste[0] else "")
                 + wear
                 + (f" · Laser traces: {ltraces[1][0]}" if ltraces and ltraces[1] else "")
                 + (f" · Solder mask: {mask[1][0]}" if mask and mask[1] else "")
                 + (f" · Silkscreen: {silk[1][0]}" if silk and silk[1] else "")
                 + (f" · Stencil: {paste[1][0]}" if paste and paste[1] else ""))
        return written

    # -------------------------------------------------------- the laser file
    def action_solder_mask(self, on):
        self._solder_mask = bool(on)
        level, text = self.mask_status()
        if on and level == "warn":
            self.say("warn", text)

    def action_mask_shrink(self, value):
        self._mask_shrink = float(value)
        self._mask_result = None

    def mask_status(self):
        """``(level, text)`` for the setup page: what the last write made,
        else what one would, else why it could not."""
        st = self.state
        if st.gerber_dir is None:
            return "info", "Load a Gerber folder first."
        if self._mask_result is not None:
            paths, notes = self._mask_result
            bits = [f"Wrote {p.name}" for p in paths] + notes
            return ("warn" if notes else "info"), ". ".join(bits)
        missing = [m.gerber_dir for m in st.boards
                   if soldermask.mask_layer_path(m.gerber_dir) is None]
        if missing:
            return "warn", (
                f"No B.Mask Gerber in {missing[0].name}. In KiCad's Plot "
                f"dialog tick B.Mask as well, plot into the same folder, and "
                f"load it again.")
        where = "one file per board" if st.is_panel else "one file"
        how = ("Mirrored once, so do not flip it in the laser software."
               if self._double or st.mirror else
               "Not mirrored, because Mirror for bottom-up milling is off.")
        when = ("Written with the export, and at Start in a run."
                if tier.is_full() else "Written when you press Start.")
        return "info", (f"Reads B.Mask and Edge.Cuts from the Gerber folder: "
                        f"{where}. {how} {when}")

    def write_mask_to(self, out_dir):
        """Write the laser file or files into ``out_dir``.

        Returns ``(paths, notes)``. Never raises: this runs after the machine
        files are on disk or on the way to a run, and a board with no B.Mask
        plotted must not cost either of those. ``notes`` carries what went
        wrong, and what the operator should know about what went right.
        """
        st = self.state
        paths, notes = [], []
        # A panel can hold the same board twice; that is one drawing. Each
        # board on the sheet goes on the laser cut out, so each has its own.
        seen = set()
        for m in st.boards:
            if m.gerber_dir in seen:
                continue
            seen.add(m.gerber_dir)
            name = clean_name(m.name) if st.is_panel else st.name
            try:
                done = soldermask.write_mask_files(
                    m.gerber_dir, out_dir, name, shrink=self._mask_shrink,
                    mirror=st.mirror, double_sided=self._double)
            except soldermask.MaskError as e:
                notes.append(str(e))
                continue
            except Exception as e:
                notes.append(f"{name}'s file could not be written: {e}")
                continue
            for path, art in done:
                paths.append(path)
                self._exported[path.name] = path
                notes += art.warnings()
        self._mask_result = (paths, notes)
        return paths, notes

    def action_write_mask(self):
        if self.state.board is None:
            self.say("warn", "Load a Gerber folder first.")
            return
        d = QFileDialog.getExistingDirectory(
            self, "Where should the laser file go?",
            workspace.remembered_dir("out", "exports"))
        if not d:
            return
        workspace.remember_dir("out", d)
        paths, notes = self.write_mask_to(d)
        if notes:
            self.say("warn", notes[0])
        else:
            self.say("ok", f"Wrote {', '.join(p.name for p in paths)} "
                           f"· Mirroring is in the name: do not flip it again "
                           f"in the laser software.")

    # ---------------------------------------------------- the silkscreen file
    def action_silkscreen(self, on):
        self._silkscreen = bool(on)
        level, text = self.silk_status()
        if on and level == "warn":
            self.say("warn", text)

    def silk_status(self):
        """``(level, text)`` for the setup page: what the last write made,
        else what one would, else why it could not."""
        st = self.state
        if st.gerber_dir is None:
            return "info", "Load a Gerber folder first."
        if self._silk_result is not None:
            paths, notes = self._silk_result
            bits = [f"Wrote {p.name}" for p in paths] + notes
            return ("warn" if notes else "info"), ". ".join(bits)
        missing = [m.gerber_dir for m in st.boards
                   if silkscreen.silk_layer_path(m.gerber_dir) is None]
        if missing:
            return "warn", (
                f"No F.Silkscreen Gerber in {missing[0].name}. In KiCad's Plot "
                f"dialog tick F.Silkscreen as well, plot into the same folder, "
                f"and load it again.")
        where = "one file per board" if st.is_panel else "one file"
        bottom = (" A double-sided job also gets B.Silkscreen, mirrored, when "
                  "the folder has any." if self._double else "")
        when = ("Written with the export, and at Start in a run."
                if tier.is_full() else "Written when you press Start.")
        return "info", (f"Reads F.Silkscreen and Edge.Cuts from the Gerber "
                        f"folder: {where}. Not mirrored: the component side "
                        f"lies face up on the laser.{bottom} {when}")

    def write_silk_to(self, out_dir):
        """Write the silkscreen file or files into ``out_dir``.

        Returns ``(paths, notes)`` and never raises, for the same reason as
        :meth:`write_mask_to`: the machine files come first.
        """
        st = self.state
        paths, notes = [], []
        seen = set()
        for m in st.boards:
            if m.gerber_dir in seen:
                continue
            seen.add(m.gerber_dir)
            name = clean_name(m.name) if st.is_panel else st.name
            try:
                done = silkscreen.write_silk_files(
                    m.gerber_dir, out_dir, name, double_sided=self._double)
            except silkscreen.SilkError as e:
                notes.append(str(e))
                continue
            except Exception as e:
                notes.append(f"{name}'s silkscreen file could not be written: {e}")
                continue
            for path, art in done:
                paths.append(path)
                self._exported[path.name] = path
                notes += art.warnings()
        self._silk_result = (paths, notes)
        return paths, notes

    def action_write_silk(self):
        if self.state.board is None:
            self.say("warn", "Load a Gerber folder first.")
            return
        d = QFileDialog.getExistingDirectory(
            self, "Where should the silkscreen file go?",
            workspace.remembered_dir("out", "exports"))
        if not d:
            return
        workspace.remember_dir("out", d)
        paths, notes = self.write_silk_to(d)
        if notes:
            self.say("warn", notes[0])
        else:
            self.say("ok", f"Wrote {', '.join(p.name for p in paths)} "
                           f"· The face and the mirroring are in the name.")

    # ------------------------------------------------- the solder paste stencil
    def action_stencil(self, on):
        self._stencil = bool(on)
        level, text = self.stencil_status()
        if on and level == "warn":
            self.say("warn", text)

    def action_stencil_kerf(self, value):
        self._stencil_kerf = float(value)
        self._stencil_result = None

    def _stencil_sides(self):
        """The faces that get a stencil: the milled bottom, mirrored like the
        copper; a double-sided job's top as well, as plotted."""
        sides = [("bottom", bool(self.state.mirror) or self._double)]
        if self._double:
            sides.append(("top", False))
        return sides

    def _stencil_arts(self, gerber_dir):
        """``(arts, notes)`` for one board: every face with paste on it."""
        arts, notes = [], []
        for side, mirror in self._stencil_sides():
            try:
                arts.append(stencil.build_stencil(
                    gerber_dir, side=side, kerf=self._stencil_kerf, mirror=mirror))
            except stencil.StencilError as e:
                notes.append(str(e))
        if not arts and not self._double:
            # A board made elsewhere has its parts on the top: F.Paste, drawn
            # as plotted, since that face lies up when the stencil goes on.
            try:
                arts.append(stencil.build_stencil(
                    gerber_dir, side="top", kerf=self._stencil_kerf, mirror=False))
            except stencil.StencilError as e:
                notes.append(str(e))
        # A face with no paste is normal when another face has some.
        return arts, ([] if arts else notes[:1])

    def stencil_status(self):
        st = self.state
        if st.gerber_dir is None:
            return "info", "Load a Gerber folder first."
        if self._stencil_result is not None:
            paths, notes = self._stencil_result
            bits = [f"Wrote {p.name}" for p in paths] + notes
            return ("warn" if notes else "info"), ". ".join(bits)
        missing = [m.gerber_dir for m in st.boards
                   if stencil.paste_layer_path(m.gerber_dir) is None
                   and stencil.paste_layer_path(m.gerber_dir, "top") is None]
        if missing:
            return "warn", (
                f"No paste Gerber in {missing[0].name}. In KiCad's Plot dialog "
                f"tick B.Paste (and F.Paste for a double-sided board), plot into "
                f"the same folder, and load it again.")
        return "info", (
            "Reads B.Paste and Edge.Cuts: the holes for 0.1 mm steel foil, each "
            "half a kerf smaller per side, mirrored like the copper. Cut it on "
            "the xTool from here, or put the DXF in XCS.")

    def write_stencil_to(self, out_dir):
        """Write the stencil DXF or DXFs into ``out_dir``. ``(paths, notes)``;
        never raises, like :meth:`write_mask_to`."""
        st = self.state
        paths, notes, seen = [], [], set()
        for m in st.boards:
            if m.gerber_dir in seen:
                continue
            seen.add(m.gerber_dir)
            name = clean_name(m.name) if st.is_panel else st.name
            try:
                arts, why = self._stencil_arts(m.gerber_dir)
                notes += why
                for art in arts:
                    path = stencil.write_stencil_dxf(art, out_dir, name)
                    paths.append(path)
                    self._exported[path.name] = path
                    notes += art.warnings()
            except Exception as e:
                notes.append(f"{name}'s stencil file could not be written: {e}")
        self._stencil_result = (paths, notes)
        return paths, notes

    def action_write_stencil(self):
        if self.state.board is None:
            self.say("warn", "Load a Gerber folder first.")
            return
        d = QFileDialog.getExistingDirectory(
            self, "Where should the stencil file go?",
            workspace.remembered_dir("out", "exports"))
        if not d:
            return
        workspace.remember_dir("out", d)
        paths, notes = self.write_stencil_to(d)
        if notes:
            self.say("warn", notes[0])
        else:
            self.say("ok", f"Wrote {', '.join(p.name for p in paths)} "
                           f"· Import it into XCS to place it on the foil.")

    # -------------------------------------------------------- the laser traces
    def action_laser_traces(self, on):
        self._laser_traces = bool(on)
        level, text = self.laser_traces_status()
        if on and level == "warn":
            self.say("warn", text)

    def action_laser_offsets(self, value):
        self._laser_offsets = max(1, int(value))
        self._laser_traces_result = None

    def _traces_sides(self):
        sides = [("bottom", bool(self.state.mirror) or self._double)]
        if self._double:
            sides.append(("top", False))
        return sides

    def _traces_arts(self, gerber_dir):
        arts, notes = [], []
        for side, mirror in self._traces_sides():
            try:
                arts.append(xtool.build_laser_traces(
                    gerber_dir, side=side, mirror=mirror,
                    offsets=self._laser_offsets))
            except xtool.TracesError as e:
                notes.append(str(e))
        if not arts and not self._double:
            try:
                arts.append(xtool.build_laser_traces(
                    gerber_dir, side="top", mirror=False,
                    offsets=self._laser_offsets))
            except xtool.TracesError as e:
                notes.append(str(e))
        return arts, ([] if arts else notes[:1])

    def laser_traces_status(self):
        st = self.state
        if st.gerber_dir is None:
            return "info", "Load a Gerber folder first."
        if self._laser_traces_result is not None:
            paths, notes = self._laser_traces_result
            bits = [f"Wrote {p.name}" for p in paths] + notes
            return ("warn" if notes else "info"), ". ".join(bits)
        missing = [m.gerber_dir for m in st.boards
                   if xtool.copper_layer_path(m.gerber_dir) is None
                   and xtool.copper_layer_path(m.gerber_dir, "top") is None]
        if missing:
            return "warn", (
                f"No copper Gerber in {missing[0].name}. Plot B.Cu (or F.Cu) "
                f"and Edge.Cuts into the same folder, and load it again.")
        return "info", (
            "Reads B.Cu (or F.Cu), Edge.Cuts and drills: FlatCAM-style "
            "concentric isolation rings, dozens of times faster than XCS fill.")

    def write_laser_traces_to(self, out_dir):
        """Write the laser traces DXF or DXFs into ``out_dir``."""
        st = self.state
        paths, notes, seen = [], [], set()
        for m in st.boards:
            if m.gerber_dir in seen:
                continue
            seen.add(m.gerber_dir)
            name = clean_name(m.name) if st.is_panel else st.name
            try:
                arts, why = self._traces_arts(m.gerber_dir)
                notes += why
                for art in arts:
                    path = xtool.write_traces_dxf(art, out_dir, name)
                    paths.append(path)
                    self._exported[path.name] = path
                    notes += art.warnings()
            except Exception as e:
                notes.append(f"{name}'s traces file could not be written: {e}")
        self._laser_traces_result = (paths, notes)
        return paths, notes

    def action_write_laser_traces(self):
        if self.state.board is None:
            self.say("warn", "Load a Gerber folder first.")
            return
        d = QFileDialog.getExistingDirectory(
            self, "Where should the laser traces file go?",
            workspace.remembered_dir("out", "exports"))
        if not d:
            return
        workspace.remember_dir("out", d)
        paths, notes = self.write_laser_traces_to(d)
        if notes:
            self.say("warn", notes[0])
        else:
            self.say("ok", f"Wrote {', '.join(p.name for p in paths)}.")

    def _laser_board(self):
        st = self.state
        k = getattr(self, "_laser_member", None)
        if k is not None:
            return st.boards[k]
        return st.boards[st.current] if st.is_panel else st.boards[0]

    def _panel_laser_art(self, kind, *, side=None):
        """The whole sheet as one laser job: every board's art, where the
        board sits on the sheet. The sheet comes off the mill in one piece
        (the boards on their tabs), so it is etched in one piece, lined up on
        all the holes at once. A job seen from the other face (the
        silkscreen, from the top) has the layout mirrored with it."""
        from shapely.affinity import rotate as _rot, translate as _tr
        from shapely.ops import unary_union
        st = self.state
        parts, notes = [], []
        try:
            for i, m in enumerate(st.boards):
                self._laser_member = i
                try:
                    art = self._laser_art_for(kind, side=side)
                except (xtool.TracesError, soldermask.MaskError,
                        silkscreen.SilkError, stencil.StencilError,
                        ValueError) as e:
                    notes.append(f"{m.name}: {e}")
                    continue
                parts.append((m, art))
        finally:
            self._laser_member = None
        if not parts:
            raise ValueError(notes[0] if notes else "No board on the sheet "
                             "has this layer.")
        px0 = min(m.bounds()[0] for m in st.boards)
        py0 = min(m.bounds()[1] for m in st.boards)
        px1 = max(m.bounds()[2] for m in st.boards)
        flipped = parts[0][1].mirrored != bool(st.mirror)

        def place(art, m):
            rot = (m.rotate % 360) * (-1 if flipped else 1)
            x0, y0, x1, y1 = m.bounds()
            tx = (px1 - x1) if flipped else (x0 - px0)
            ty = y0 - py0

            def geom(g):
                if g is None:
                    return None
                g = _rot(g, rot, origin=(0, 0)) if rot else g
                return g

            out = geom(art.outline)
            ox, oy = out.bounds[0], out.bounds[1]

            def move(g):
                g = geom(g)
                return None if g is None else _tr(g, tx - ox, ty - oy)

            def point(x, y):
                from shapely.geometry import Point
                q = move(Point(x, y))
                return q.x, q.y
            return dict(
                apertures=[move(a) for a in (art.apertures or [])],
                outline=move(art.outline),
                features=[move(f) for f in (art.features or [])],
                copper=move(art.copper),
                drills=[(*point(x, y), d) for x, y, d in (art.drills or [])])

        placed = [place(a, m) for m, a in parts]
        first = parts[0][1]
        coppers = [p["copper"] for p in placed if p["copper"] is not None]
        return xtool.LaserArt(
            kind=first.kind,
            apertures=[a for p in placed for a in p["apertures"]],
            outline=unary_union([p["outline"] for p in placed]),
            mirrored=first.mirrored, side=first.side, kerf=first.kerf,
            note=f"{len(parts)} boards on one sheet"
                 + (f" · {first.note}" if first.note else ""),
            notes=notes + [n for _m, a in parts for n in (a.notes or [])],
            features=[f for p in placed for f in p["features"]],
            copper=unary_union(coppers) if coppers else None,
            drills=[d for p in placed for d in p["drills"]],
            flipped=first.flipped)

    def _open_laser(self, art, name):
        """The laser page with ``art`` on it, in this window."""
        self._laser_page(art, name, jobs=self._laser_art_for)
        self._laser_token = self._laser_job_token()
        self.show_mode("laser")

    def _laser_page(self, art=None, name="stencil", jobs=None, dxf=None):
        """The laser page, made the first time; ``art`` is shown on it."""
        from gerber2rml.gui2.stencil_laser import StencilLaserDialog
        if self.laser_view is None:
            self.laser_view = StencilLaserDialog(art, self, name=name, jobs=jobs,
                                                 dxf=dxf, embedded=True)
            self.modes.addWidget(self.laser_view)
            # The rail follows the page's own job tabs.
            self.laser_view.kind_changed.connect(self._on_laser_kind)
        elif art is not None:
            self.laser_view.show_job(art, name, jobs=jobs, dxf=dxf)
        return self.laser_view

    def _laser_job_token(self):
        """What the laser jobs are built from: when it changes, the page
        needs the jobs again."""
        st = self.state
        if st.board is None:
            return None
        boards = tuple((str(m.gerber_dir), round(m.place_x, 3),
                        round(m.place_y, 3), m.rotate) for m in st.boards)
        # The ring count is the laser page's own (its recipe): not here.
        return (boards, bool(st.mirror), bool(self._double),
                self._mask_shrink)

    def show_mode(self, mode):
        """``"cnc"`` or ``"laser"``: which machine the window is set up for.
        The laser page follows the board loaded here; a job running on the
        laser carries on while the mill's page is up."""
        if mode == "project" and not tier.is_full():
            return                          # Pro's page
        if mode == "laser":
            token = self._laser_job_token()
            page = self.laser_view
            stale = token is not None and token != self._laser_token
            if page is None or (stale and not page._worker_running()):
                prefer = page.kind if page is not None and not page._empty else None
                if token is None or not self._load_laser_job(prefer):
                    self._laser_page()      # the page on its own, or as it was
            page = self.laser_view
            self.modes.setCurrentWidget(page)
            page.view.setFocus()
        elif mode == "project":
            self.project_ctl.page.refresh()
            self.modes.setCurrentWidget(self.project_ctl.page)
        else:
            self.modes.setCurrentWidget(self.cnc_body)
        on_laser = mode in ("laser", "project")
        self.mode_switch.set_current(mode)
        for w in self._cnc_header:
            w.setVisible(not on_laser)
        # The mill's STOP stays in sight while the mill is running.
        page = getattr(self, "autorun_page", None)
        running = (page is not None and getattr(page, "_thread", None) is not None) \
            or self.link.can_stop_something()
        self.bar.setVisible(not on_laser or running)
        self.bar_rule.setVisible(not on_laser or running)
        self.refresh_chips()                # ...which show only when lit
        self._sync_undo()                   # one Ctrl+Z at a time

    def _on_laser_kind(self, kind):
        key = f"laser_{kind}"
        if self.plan is not None and self.plan.by_key(key) is not None:
            self.traveller.select(key)

    def mode(self):
        cur = self.modes.currentWidget()
        if cur is self.laser_view:
            return "laser"
        if cur is self.project_ctl.page:
            return "project"
        return "cnc"

    def _load_laser_job(self, prefer=None):
        """The selected board's laser jobs on the page, ``prefer`` first.
        False when the board has none (the reason is said)."""
        st = self.state
        m = self._laser_board()
        last_err = None
        order = ([prefer] if prefer else []) + [
            k for k in ("traces", "mask", "silk", "stencil") if k != prefer]
        for kind in order:
            try:
                art = self._laser_art_for(kind)
            except (xtool.TracesError, soldermask.MaskError, silkscreen.SilkError,
                    stencil.StencilError, ValueError) as e:
                last_err = str(e)
                continue
            self._laser_page(art, st.name, jobs=self._laser_art_for)
            self._laser_token = self._laser_job_token()
            return True
        self.say("warn", last_err or "No laser-ready Gerber layers in this folder.")
        return False

    @staticmethod
    def _raw_outline(folder):
        from gerber2rml.loader import _find_layer
        edge = _find_layer(folder, "*-Edge_Cuts.*", "*.gm1")
        return soldermask._read_outline(edge) if edge else None

    def _laser_art_for(self, kind, *, side=None):
        """Build the :class:`xtool.LaserArt` for ``kind`` on the selected board."""
        st = self.state
        if st.board is None:
            raise ValueError("Load a Gerber folder first.")
        if st.is_panel and getattr(self, "_laser_member", None) is None:
            return self._panel_laser_art(kind, side=side)
        m = self._laser_board()
        if kind == "traces":
            if side is not None:
                return xtool.build_laser_traces(
                    m.gerber_dir, side=side,
                    mirror=(bool(st.mirror) or self._double) if side == "bottom" else False,
                    offsets=self._laser_offsets)
            arts, notes = self._traces_arts(m.gerber_dir)
            if not arts:
                raise xtool.TracesError(notes[0] if notes else "No copper on this board.")
            return arts[0]
        if kind == "mask":
            # Either face: the top one (F.Mask) as drawn, turned over on the
            # bed like its copper; the bottom one mirrored like the mill's.
            side = side or "bottom"
            mirror = (bool(st.mirror) or self._double) if side == "bottom" else False
            art = soldermask.build_mask(m.gerber_dir, side=side,
                                        shrink=self._mask_shrink, mirror=mirror)
            try:
                feats = xtool.drill_features(m.gerber_dir, mirror,
                                             self._raw_outline(m.gerber_dir))
            except Exception:                       # noqa: BLE001 - Align only
                feats = []
            openings, holes_only = xtool.drop_hole_only(art.openings, feats)
            notes = art.warnings() + ([
                f"{holes_only} opening{'s' if holes_only != 1 else ''} over a bare "
                f"hole (a mounting hole) left out: the beam would only go "
                f"through it."] if holes_only else [])
            return xtool.LaserArt(
                kind="mask", apertures=openings, outline=art.outline,
                mirrored=art.mirrored, notes=notes, features=feats,
                side=side, note=f"shrunk {art.shrink:g} mm a side")
        if kind == "silk":
            art = silkscreen.build_silk(m.gerber_dir)
            try:
                feats = xtool.drill_features(m.gerber_dir, art.mirrored,
                                             self._raw_outline(m.gerber_dir))
            except Exception:                       # noqa: BLE001 - Align only
                feats = []
            return xtool.LaserArt(
                kind="silk", apertures=art.shapes, outline=art.outline,
                mirrored=art.mirrored, notes=art.warnings(), features=feats)
        if kind == "stencil":
            arts, notes = self._stencil_arts(m.gerber_dir)
            if not arts:
                raise stencil.StencilError(notes[0] if notes else "No paste on this board.")
            return arts[0]
        raise ValueError(f"Unknown laser job kind: {kind}")

    def _open_laser_kind(self, kind):
        st = self.state
        if st.board is None:
            self.say("warn", "Load a Gerber folder first.")
            return
        m = self._laser_board()
        try:
            art = self._laser_art_for(kind)
        except (xtool.TracesError, soldermask.MaskError, silkscreen.SilkError,
                stencil.StencilError, ValueError) as e:
            self.say("warn", str(e))
            return
        page = self.laser_view
        if (page is not None and self._laser_token == self._laser_job_token()
                and not page._empty):
            self.show_mode("laser")         # same board: keep the page as it is
            page.switch_kind(kind)
            return
        self._open_laser(art, st.name)

    def action_open_laser_hub(self):
        """The laser page, on the job it was last on (traces first)."""
        self.show_mode("laser")

    def action_traces_laser_dxf(self):
        """Copper traces on the xTool from a DXF drawing, no Gerber folder."""
        from gerber2rml.engine import dxf_traces
        picked, _ = QFileDialog.getOpenFileName(
            self, "Copper traces DXF", workspace.remembered_dir("dxf", ""),
            "DXF drawings (*.dxf);;All files (*)")
        if not picked:
            return
        self.open_laser_dxf(Path(picked))

    def open_laser_dxf(self, path):
        """Copper traces from a DXF drawing, on the laser page."""
        from gerber2rml.engine import dxf_traces
        path = Path(path)
        workspace.remember_dir("dxf", str(path.parent))
        try:
            art = dxf_traces.build_dxf_traces(path)
        except xtool.TracesError as e:
            self.say("warn", str(e))
            return
        jobs = self._laser_art_for if self.state.board is not None else None
        self._laser_page(art, path.name, jobs=jobs, dxf=path)
        self._laser_token = self._laser_job_token()
        self.show_mode("laser")

    def action_traces_laser(self):
        """The copper traces on the xTool: FlatCAM-style concentric isolation."""
        self._open_laser_kind("traces")

    def action_mask_laser(self):
        """The solder mask on the xTool: the openings filled with the
        RemoveSolderMask recipe, aligned on the drilled holes."""
        self._open_laser_kind("mask")

    def action_silk_laser(self):
        """The silkscreen on the xTool: the artwork filled, aligned on the
        drilled holes. The component side, as KiCad drew it: not mirrored."""
        self._open_laser_kind("silk")

    def action_cut_stencil(self):
        """The laser window for the selected board's stencil."""
        self._open_laser_kind("stencil")

    def _write_export_extras(self, out_dir):
        """A picture of the stage and a board summary next to the machine
        files, so the folder says what was cut without opening the app.
        Returns the paths written; never raises."""
        from gerber2rml.report import board_summary
        st = self.state
        out = []
        try:
            png = Path(out_dir) / f"{st.name}_preview.png"
            # The stage as it is now, whichever step is lit: that is the
            # picture the operator was looking at when they pressed Export.
            if self.stage.grab().save(str(png), "PNG"):
                out.append(png)
        except Exception:
            pass
        try:
            md = Path(out_dir) / f"{st.name}_summary.md"
            md.write_text(board_summary(st.board, st.name), encoding="utf-8")
            out.append(md)
        except Exception:
            pass
        for p in out:
            self._exported[p.name] = p
        return out

    def _note_tool_wear(self):
        """Add this export's trace cutting to the per-tool ledger, and say
        how far the bit has come. Empty when there is nothing to say."""
        try:
            from gerber2rml.engine import toolwear
            job = self.state.trace
            key = f"{job.tool_type} {job.effective_diameter():.2f}mm"
            dist = 0.0
            for step in (self.plan or []):
                if step.op not in ("traces", "top_traces"):
                    continue
                cached = self._paths_cache.get(step.key)
                paths = (cached[0] if cached is not None
                         else self._toolpaths_for(step)[0])
                dist += toolwear.cut_distance_mm(paths)
            # The same file the first interface keeps, in the shared
            # workspace: one bit, one ledger, whichever interface cut with it.
            ledger = workspace.workspace_root() / "tool_wear.json"
            toolwear.record(key, dist, path=ledger)
            return toolwear.wear_note(key, path=ledger)
        except Exception:
            return ""

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

    # ---------------------------------------------------------- setup files
    def action_save_setup(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save this setup",
            workspace.remembered_dir("session", "sessions")
            + f"/{self.state.name}.srmcam", "SRM-CAM setup (*.srmcam)")
        if not path:
            return
        try:
            self.write_setup(path)
        except OSError as e:
            self.report_error("The setup could not be saved", e,
                              "Pick a folder you can write to.")
            return
        workspace.remember_dir("session", path)
        self.say("ok", "Setup saved.")

    def write_setup(self, path):
        """Write this job's setup to ``path`` (.srmcam). Raises OSError."""
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
            "laser_traces": self._laser_traces, "laser_offsets": self._laser_offsets,
            "solder_mask": self._solder_mask, "mask_shrink": self._mask_shrink,
            "silkscreen": self._silkscreen,
            "stencil": self._stencil, "stencil_kerf": self._stencil_kerf,
            # How the board is made, and where that came from; the stock in
            # the bracket or found anywhere, and whether the board is cut
            # out. A setup that left these out loaded as "Setup loaded." on
            # a different job.
            "method": self._method, "method_source": self._method_source,
            "stock_where": self.autorun_page.where.currentData(),
            "centre": self.autorun_page.centre_chk.isChecked(),
            "no_cutout": self._no_cutout,
            "fid_diameter": self._fid_diameter, "hold": self._hold,
            "flex_auto": self._flex_auto, "flex_mm": self._flex_mm,
            "fid_count": self._fid_count,
            "fid_placement": self._fid_placement,
            "fid_mounting": self._fid_mounting,
            "fid_offset": self._fid_offset,
            "fid_flip": self._fid_flip, "fid_scale": self._fid_scale,
            "fid_points": [list(p) for p in self._fid_points],
            "dowel_mode": self._dowel_mode, "dowel_edges": self._dowel_edges,
            "grid_pitch": self._grid_pitch, "grid_pin": self._grid_pin,
            "clear_large": self._clear_large, "clear_small": self._clear_small,
            "bed_bite": self._bed_bite,
            "manual_screws": (None if self._manual_screws is None
                              else [list(p) for p in self._manual_screws]),
            "top_fit": ([self._top_fit.theta, self._top_fit.scale,
                         self._top_fit.tx, self._top_fit.ty]
                        if self._top_fit is not None else None),
            "fid_measured": [None if p is None else list(p)
                             for p in (self._fid_measured or [])],
            # The probed surface. Nine points is nine physical touches and a
            # couple of minutes of machine time; a measurement that does not
            # survive closing the app is one nobody relies on.
            "level": self.level_page.state(),
            "rework": self.rework_page.state(),
            # The photo on the bed, and the holes it was fitted on. The
            # boxes above were drawn against it; restored without it they
            # are boxes on a design, with nothing to say why they are there.
            "photo": self._photo_state(Path(path)),
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
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")

    def action_load_setup(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load a setup",
            workspace.remembered_dir("session", "sessions"),
            "SRM-CAM setup (*.srmcam);;All files (*)")
        if path:
            self.load_setup(path)

    def load_setup(self, path):
        """Load a .srmcam setup - from the dialog, or one the app was
        started with (double-click, Open with)."""
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
            if isinstance(data.get(key), dict):
                job, refused = checked_job(getattr(st, attr), data[key])
                setattr(st, attr, job)
                if refused:
                    # Unknown to this version, or a value that would hurt the
                    # machine: kept out, and said so.
                    foreign.append("%s: %s" % (key, ", ".join(refused)))
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
        self._fid_placement = data.get("fid_placement", "waste")
        self._fid_offset = float(data.get("fid_offset", 4.0))
        # Defaults for setups written before these were saved: the values
        # the export used then, so an old job reproduces what it produced.
        self._fid_flip = ("horizontal" if data.get("fid_flip") == "horizontal"
                          else "vertical")
        self._fid_scale = bool(data.get("fid_scale", False))
        try:
            self._fid_points = [[float(x), float(y)]
                                for x, y in (data.get("fid_points") or [])]
        except (TypeError, ValueError):
            self._fid_points = []
            foreign.append("the hand-placed reference holes")
        if self._fid_placement == "manual" and len(self._fid_points) < 2:
            # Hand-placed holes without their places are not a placement.
            self._fid_placement = "waste"
            foreign.append("the hand-placed reference holes")
        self._fid_mounting = (bool(data.get("fid_mounting", False))
                              and self._fid_placement == "manual")
        self._dowel_mode = "grid" if data.get("dowel_mode") == "grid" else "fresh"
        self._dowel_edges = ("leftright" if data.get("dowel_edges") == "leftright"
                             else "topbottom")
        from gerber2rml.doublesided import (CLEAR_LARGE, CLEAR_SMALL,
                                            DOWEL_BED_DEPTH, GRID_PITCH,
                                            GRID_PIN)
        for attr, key, default in (("_grid_pitch", "grid_pitch", GRID_PITCH),
                                   ("_grid_pin", "grid_pin", GRID_PIN),
                                   ("_clear_large", "clear_large", CLEAR_LARGE),
                                   ("_clear_small", "clear_small", CLEAR_SMALL),
                                   ("_bed_bite", "bed_bite", DOWEL_BED_DEPTH)):
            try:
                setattr(self, attr, float(data.get(key, default)))
            except (TypeError, ValueError):
                setattr(self, attr, default)
        self.screwed = bool(data.get("screwed", False))
        self._laser_traces = bool(data.get("laser_traces", False))
        try:
            self._laser_offsets = max(1, int(
                data.get("laser_offsets", xtool.DEFAULT_TRACE_OFFSETS)))
        except (TypeError, ValueError):
            self._laser_offsets = xtool.DEFAULT_TRACE_OFFSETS
        self._solder_mask = bool(data.get("solder_mask", False))
        self._silkscreen = bool(data.get("silkscreen", False))
        try:
            self._mask_shrink = max(0.0, float(
                data.get("mask_shrink", soldermask.DEFAULT_SHRINK)))
        except (TypeError, ValueError):
            self._mask_shrink = soldermask.DEFAULT_SHRINK
        stock = data.get("stock", self.stock)
        try:
            x, y, w, h = (float(v) for v in stock)
            self.stock = (x, y, w, h)
            self._stock_set = "stock" in data
            self.autorun_page.show_size(w, h)
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
            st.name = clean_name(data["name"])
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
        self._fid_measured = [None if p is None else (float(p[0]), float(p[1]))
                              for p in (data.get("fid_measured") or [])]
        try:
            self.level_page.restore(data.get("level"))
            # The boxes are the work; a restart used to lose them.
            self.rework_page.restore(data.get("rework"))
        except Exception:
            foreign.append("the height map")
        if placed:
            self._restore_photo(data.get("photo"), foreign, Path(path))
        if placed:
            px, py = data.get("place", [0, 0])
            st.set_rotation(data.get("rotate", 0))
            st.set_placement(px, py)
            self.autorun_page.board_placed()
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
        self._stencil = bool(data.get("stencil", False))
        try:
            self._stencil_kerf = max(0.0, float(
                data.get("stencil_kerf", stencil.DEFAULT_KERF)))
        except (TypeError, ValueError):
            self._stencil_kerf = stencil.DEFAULT_KERF
        page = self.autorun_page
        where = data.get("stock_where")
        i = page.where.findData(where) if where else -1
        if i >= 0 and tier.is_full():
            page.where.setCurrentIndex(i)
        if "centre" in data:
            page.centre_chk.setChecked(bool(data["centre"]))
        if "no_cutout" in data:
            self.set_no_cutout(bool(data["no_cutout"]))
            page._sync_nocut()
        if data.get("method") in fab.IDS:
            self.action_method(data["method"],
                               data.get("method_source") or "chosen",
                               quiet=True)
        setup.sync()
        # The measuring page reads the flip and the scale flag on show; a
        # setup loaded while it is hidden must not leave it saying the old
        # answer until the next show.
        self.flipfit_page.sync_from_job()
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
        # The KiCad plugin checks a board's rules against this cutter.
        from gerber2rml.gui2 import kicadsetup
        kicadsetup.sync_tools(self)

    def _on_frame(self, which):
        self.stage.set_frame(which)
        self._sync_flip()
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
        # Dragged somewhere is where it should go: centring would undo it.
        self.autorun_page.board_dragged()
        self.remember()
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
                # Kept, and recorded: the reason stays on the checks page
                # (see _hand_picked_screw_check) after this toast has gone.
                self.say("warn", "Screw at X%.1f Y%.1f %s. Kept — you can see "
                                 "the bed, but check it. It stays listed "
                                 "under the checks." % (best[0], best[1],
                                                        problem))
            else:
                self.say("ok", "Screw at X%.1f Y%.1f. %d chosen."
                         % (best[0], best[1], len(kept)))
        else:
            self.say("info", "Screw at X%.1f Y%.1f removed. %d left."
                     % (best[0], best[1], len(kept)))
        self.remember()
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
        self.remember()
        self._manual_screws = None
        self._draw_screws()
        self.refresh_checks()
        self.say("ok", "Back to the holes the app would choose.")

    def action_measure(self, on):
        """The ruler is a stage mode like jog and the screw picker, so turning
        it on turns the others off through the same one place."""
        self.set_stage_mode("measure" if on else "place")
        if on:
            self.say("info", "Drag from one corner of the board to another — "
                             "the ends snap to corners, edges and holes. "
                             "Ctrl+M again to put the ruler away.")

    def _on_measured(self, reading):
        if reading is None:
            return
        length, dx, dy = reading
        self.say("info", f"{length:.2f} mm — {dx:.2f} mm across, "
                         f"{dy:.2f} mm up the bed.")

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
        if self._align_armed:
            # Not a jog: the click says where the bit already is.
            self._on_align_pick(sx, sy)
            return
        # The click is a point on the drawn design; the machine target is
        # that point with the overlay trim taken back off.
        tx, ty = self._overlay_trim
        sx, sy = sx - tx, sy - ty
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
        # Hovering the stage in jog mode is enough for the arrow keys to
        # jog: you are looking at the bit, not hunting for a widget to
        # click into first.
        if (pos is not None and self.stage.mode == "jog"
                and not self.stage.hasFocus()):
            self.stage.setFocus()

    def _on_region(self, x0, y0, x1, y1):
        # The run's check before the cut-out borrows the boxes while it
        # waits; every other time they are Rework's.
        if self.autorun_page.nogo_btn.isChecked():
            self.autorun_page.add_nogo(x0, y0, x1, y1)
        elif self.autorun_page.box_btn.isChecked():
            self.autorun_page.add_box(x0, y0, x1, y1)
        else:
            self.rework_page.add_region(x0, y0, x1, y1)

    def _on_box_click(self, x, y):
        # A click while marking clamps puts one there; elsewhere it is
        # nothing, as it always was.
        if self.autorun_page.nogo_btn.isChecked():
            self.autorun_page.add_clamp(x, y)

    def action_help(self):
        d = dialogs.Sheet(self, "How this works", width=620)
        d.say("The rail on the left is the run plan — the same order, and the "
              "same files, that get written when you export. Click any step to "
              "see it on the bed and its settings on the right. Nothing is "
              "locked: real runs jump around.")
        d.say("Work down it: set up the job, look at the checks, then export. "
              "The machine bar at the bottom is always there, and so is STOP — "
              "Escape does the same thing from anywhere.")
        d.say("The cut-out runs last. It is what frees the board from the "
              "sheet it is registered in.")
        d.act("Close", kind="primary", on=d.accept, default=True)
        d.exec()

    def action_basics(self):
        from gerber2rml.gui2 import basics
        basics.machine_basics(self).exec()

    def action_user_guide(self):
        """F1. The step-by-step guide with photos, in the browser."""
        if not QDesktopServices.openUrl(QUrl(USER_GUIDE_URL)):
            d = dialogs.Sheet(self, "The guide is on the web", width=520)
            d.say("A browser could not be opened from here. The guide is at:")
            d.say(USER_GUIDE_URL, mono=True)
            d.act("Close", kind="primary", on=d.accept, default=True)
            d.exec()

    # -------------------------------------------------------------- kicad
    def action_setup_kicad_plugin(self):
        from gerber2rml.gui2 import kicadsetup
        kicadsetup.setup(self)

    def maybe_offer_kicad_plugin(self):
        """Launch-time offers, one after the other: the Discord invite (once
        per invite round), then the KiCad buttons (once per plugin version,
        when KiCad is here). Called by app.py."""
        from gerber2rml.gui2 import community, kicadsetup
        try:
            community.maybe_invite(self)
        except Exception:                       # noqa: BLE001 - a nicety
            pass
        try:
            kicadsetup.maybe_offer(self)
        except Exception:                       # noqa: BLE001 - a nicety
            pass

    def action_join_discord(self):
        from gerber2rml.gui2 import community
        community.open_discord(self)

    # ------------------------------------------------------------ updates
    def action_check_updates(self):
        from gerber2rml.gui2 import updatecheck
        updatecheck.check_now(self)

    def start_update_check(self):
        """The quiet launch probe. Called by app.py once the window is up;
        never by the tests, which must not touch the network."""
        from gerber2rml.gui2 import updatecheck
        try:
            self._update_probe = updatecheck.start_probe(
                self, lambda r: updatecheck.announce(self, r))
        except Exception:                       # noqa: BLE001 - a nicety
            pass

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
        if self.laser_view is not None and self.laser_view._worker_running():
            self.show_mode("laser")
            self.laser_view._say("The laser is still running: press STOP first.",
                                 warn=True)
            e.ignore()
            return
        page = getattr(self, "autorun_page", None)
        if page is not None and getattr(page, "_thread", None) is not None:
            # The same rule as the laser: a running mill is stopped first,
            # not left to finish a job nobody is watching.
            self.select_step("autorun")
            self.say("warn", "The mill is still running: press STOP first.")
            e.ignore()
            return
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
        worker = self._iso_worker
        if worker is not None:
            # A QThread destroyed while it runs takes the process with it.
            try:
                worker.done.disconnect()
            except Exception:
                pass
            worker.wait()
            _LIVE_WORKERS.discard(worker)
            self._iso_worker = None
        super().closeEvent(e)
