"""gerber2rml desktop app: load Gerbers, edit variables, preview, export RML."""
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QPushButton,
    QLineEdit, QComboBox, QTabWidget, QCheckBox, QLabel, QFileDialog, QMessageBox,
    QSplitter, QGroupBox, QStyle, QFormLayout, QDoubleSpinBox, QScrollArea,
    QSpinBox, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QListWidget, QStackedWidget, QProgressBar, QDialog, QDialogButtonBox, QSlider
)
from PySide6.QtCore import Qt, QThread, Signal, QMutex
from PySide6.QtGui import QPalette, QColor
from pathlib import Path
import math
import sys
import time

from gerber2rml.app.state import ProjectState
from gerber2rml.app.preview import toolpath_segments
from gerber2rml import __version__
from gerber2rml.backends import BACKENDS
from gerber2rml.gui.form import DataclassForm
from gerber2rml.gui.canvas import PreviewCanvas
from gerber2rml.gui.tour import TourController
from gerber2rml.gui import mode as uimode

# The user guide. Published from website/ by .github/workflows/pages.yml, and
# linked from the README — tests/test_window.py asserts the two agree.
USER_GUIDE_URL = "https://madsrudolph.github.io/srm-cam/index.html"

_OPS = ["traces", "drill", "cutout"]


class _ProbeWorker(QThread):
    """Runs the SPI grid probe off the GUI thread; emits one result per point."""
    result = Signal(dict)
    corrected = Signal(list)      # final drift-corrected results (re-fills the table)
    drift = Signal(float)         # reference drift span over the run (um)
    done = Signal(str)            # "" on success, else an error message

    def __init__(self, port, points, retouch_every=0):
        super().__init__()
        self._port, self._points = port, points
        self._retouch_every = retouch_every
        self._abort = False

    def abort(self):
        """Request a STOP: the next read bails and the firmware lifts the tool."""
        self._abort = True

    def run(self):
        from gerber2rml.engine.spi_probe import probe_grid
        try:
            drift_log = []
            res = probe_grid(self._port, self._points,
                             on_result=lambda d: self.result.emit(d),
                             should_abort=lambda: self._abort,
                             retouch_every=self._retouch_every,
                             drift_log=drift_log)
            if self._abort:
                self.done.emit("aborted")
                return
            if any("z_raw" in r for r in res):
                # live emits showed raw values; re-publish the drift-corrected set
                zs = [e["z"] for e in drift_log]
                self.drift.emit(float(max(zs) - min(zs)))
                self.corrected.emit(res)
            if len(res) < len(self._points):    # stopped early (deep touch / no datum)
                last = res[-1] if res else {"id": -1, "error": "stopped"}
                self.done.emit(
                    f"STOPPED at point {last['id'] + 1}: {last.get('error', '?')}. "
                    f"The bit lifted — check the probe wiring and that the surface "
                    f"is found before this point.")
                return
            missed = [r["id"] + 1 for r in res if r.get("z") is None]
            self.done.emit(f"missed:{','.join(map(str, missed))}" if missed else "")
        except Exception as e:                 # serial/timeout/parse -> report to UI
            self.done.emit(str(e))


class _StreamWorker(QThread):
    """EXPERIMENTAL: streams toolpaths over SPI off the GUI thread."""
    progress = Signal(int, int)
    done = Signal(str)            # "" on success, else an error message

    def __init__(self, port, toolpaths, speed=-1, dry_run=True):
        super().__init__()
        self._port, self._tps = port, toolpaths
        self._speed, self._dry = speed, dry_run
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        from gerber2rml.engine import spi_probe, spi_stream
        try:
            ser = spi_probe.open_link(self._port)
        except Exception as e:
            self.done.emit(str(e))
            return
        try:
            spi_stream.stream_toolpaths(
                ser, self._tps, speed=self._speed, dry_run=self._dry,
                on_progress=lambda i, n: self.progress.emit(i, n),
                should_abort=lambda: self._abort)
            self.done.emit("")
        except Exception as e:
            self.done.emit(str(e))
        finally:
            try:
                ser.close()
            except Exception:
                pass


class _FidFindWorker(QThread):
    """Auto-probes one fiducial hole center (firmware v2 'H' hole tests)."""
    found = Signal(int, float, float)
    failed = Signal(int, str)

    def __init__(self, port, row, x_mm, y_mm):
        super().__init__()
        self._port, self._row = port, row
        self._x, self._y = x_mm, y_mm
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        import time as _t
        from gerber2rml.engine import fidfind, spi_probe
        try:
            ser = spi_probe.open_link(self._port)
        except Exception as e:
            self.failed.emit(self._row, str(e))
            return
        try:
            ack = None
            for _ in range(3):
                ser.write(b"D\n")
                ack = spi_probe._read_line(ser, _t.monotonic() + 3.0)
                if ack and ack.startswith("D"):
                    break
            if not (ack and ack.startswith("D")):
                self.failed.emit(self._row, f"no datum ack (got {ack!r})")
                return
            # surface reference: touch the copper 2.5 mm west of the hole so
            # the firmware knows where the surface is (H descends 0.2 mm past
            # it at most)
            ser.write(b"P 999 -2500 0\n")
            line = spi_probe._read_line(ser, _t.monotonic() + 90.0,
                                        lambda: self._abort)
            if not (line and line.startswith("R")):
                self.failed.emit(
                    self._row,
                    f"no surface contact 2.5 mm west of the start point "
                    f"(got {line!r}) — that spot must be copper")
                return
            cx, cy = fidfind.find_hole_center(
                ser, self._x, self._y, should_abort=lambda: self._abort)
            self.found.emit(self._row, cx, cy)
        except Exception as e:
            spi_probe.send_abort(ser)
            self.failed.emit(self._row, str(e))
        finally:
            try:
                ser.close()
            except Exception:
                pass


class _DROPoller(QThread):
    """Holds the Arduino link open and polls live position (~4 Hz) for the DRO."""
    position = Signal(float, float, float, bool)   # x, y, z mm + probe touching
    touch_done = Signal(bool, float, float, float)  # ok, x, y, z (mm) of surface
    zero_done = Signal(bool, float)                 # ok, new origin z (mm)
    failed = Signal(str)

    def __init__(self, port):
        super().__init__()
        self._port, self._run = port, True
        self._lock = QMutex()
        self._pending_move = None       # (x_um, y_um) queued jog target
        self._pending_touch = False     # queued touch-off request
        self._pending_zero = False      # queued machine-origin Z zero (W)
        self._abort = False             # STOP: lift the tool and stop polling

    def request_abort(self):
        """STOP: drop any queued motion; the loop sends ``!`` (lift) and exits."""
        self._lock.lock()
        self._abort = True
        self._pending_move = None
        self._pending_touch = False
        self._pending_zero = False
        self._lock.unlock()

    def request_move(self, x_um, y_um):
        """Queue a click-to-jog target (thread-safe); last click wins."""
        self._lock.lock()
        self._pending_move = (int(x_um), int(y_um))
        self._lock.unlock()

    def request_touchoff(self):
        """Queue a probe-down-to-surface touch-off."""
        self._lock.lock()
        self._pending_touch = True
        self._lock.unlock()

    def request_zero(self):
        """Queue a machine-origin Z zero: verified touch-off, then the firmware
        writes origin Z = the copper surface (firmware v2 ``W``)."""
        self._lock.lock()
        self._pending_zero = True
        self._lock.unlock()

    def run(self):
        from gerber2rml.engine import spi_probe
        try:
            ser = spi_probe.open_link(self._port)
        except Exception as e:
            self.failed.emit(str(e)); return
        try:
            while self._run:
                self._lock.lock()
                mv = self._pending_move
                to = self._pending_touch
                zo = self._pending_zero
                ab = self._abort
                self._pending_move = None
                self._pending_touch = False
                self._pending_zero = False
                self._lock.unlock()
                if ab:
                    spi_probe.send_abort(ser)                 # lift the tool, then stop
                    break
                try:
                    if mv is not None:
                        spi_probe.jog_to(ser, mv[0], mv[1])   # lifts then travels XY
                    elif zo:
                        r = spi_probe.zero_z(ser, should_abort=lambda: self._abort)
                        if r is not None:
                            self.zero_done.emit(True, r[2])
                        else:
                            self.zero_done.emit(False, 0.0)
                    elif to:
                        r = spi_probe.touch_off(ser, should_abort=lambda: self._abort)
                        if r is not None:
                            self.touch_done.emit(True, r[0], r[1], r[2])
                        else:
                            self.touch_done.emit(False, 0.0, 0.0, 0.0)
                    else:
                        p = spi_probe.query_position(ser)
                        if p is not None:
                            self.position.emit(*p)
                except Exception:
                    pass
                self.msleep(60 if (self._pending_move or self._pending_touch
                                   or self._pending_zero) else 250)
        finally:
            try:
                ser.close()
            except Exception:
                pass

    def stop(self):
        self._run = False
        self.wait(3000)


class _FiducialAlignDialog(QDialog):
    """Enter or capture the probed X/Y of each fiducial after the flip, preview
    the fit quality (RMS), and accept to export the warped top traces.

    ``nominal`` is the list of (x, y) top-frame fiducial positions (where a
    perfect flip lands them). Capture pulls the parent's live DRO position."""

    def __init__(self, parent, nominal, initial=None):
        super().__init__(parent)
        self.setWindowTitle("Fiducial alignment")
        self._parent = parent
        self._nominal = nominal
        v = QVBoxLayout(self)
        v.addWidget(QLabel(
            "Probe each fiducial on the flipped board and enter (or Capture) its\n"
            "measured X/Y. Nominal = where a perfect flip would put it."))
        self.table = QTableWidget(len(nominal), 6)
        self.table.setHorizontalHeaderLabels(["nom X", "nom Y", "meas X",
                                              "meas Y", "", ""])
        # name each fiducial by where it sits (bottom-left, top-right, ...) so
        # the operator matches physical holes to rows without a decoder ring
        cx = sum(x for x, _y in nominal) / len(nominal)
        cy = sum(y for _x, y in nominal) / len(nominal)
        self.table.setVerticalHeaderLabels([
            ("top" if y >= cy else "bottom") + ("-right" if x >= cx else "-left")
            for (x, y) in nominal])
        initial = initial or []
        for r, (nx, ny) in enumerate(nominal):
            for c, val in ((0, nx), (1, ny)):
                it = QTableWidgetItem(f"{val:.3f}")
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(r, c, it)
            # pre-fill this run's earlier measurements so probe-then-refit
            # doesn't mean typing (or re-jogging) everything again
            mx = f"{initial[r][0]:.3f}" if r < len(initial) else ""
            my = f"{initial[r][1]:.3f}" if r < len(initial) else ""
            self.table.setItem(r, 2, QTableWidgetItem(mx))
            self.table.setItem(r, 3, QTableWidgetItem(my))
            btn = QPushButton("Capture")
            btn.clicked.connect(lambda _=False, row=r: self._capture(row))
            self.table.setCellWidget(r, 4, btn)
            ab = QPushButton("Auto")
            ab.setToolTip(
                "Find this fiducial's center electrically: jog the tool "
                "roughly over the HOLE first (2-3 mm up, spindle OFF, touch "
                "clips on), then Auto walks the hole edges with shallow touch "
                "tests and bisects the true center to ~0.05 mm. Needs "
                "firmware v2 and copper 2.5 mm west of the hole.")
            ab.clicked.connect(lambda _=False, row=r: self._auto_probe(row))
            self.table.setCellWidget(r, 5, ab)
        self._auto_busy = False
        self._fid_worker = None
        self._dro_was_on = False
        # 6 columns now (Capture + Auto) — size the table and the dialog so
        # the Auto column is actually visible instead of clipped off-screen
        self.table.resizeColumnsToContents()
        width = sum(self.table.columnWidth(c) for c in range(6))
        width += self.table.verticalHeader().width() + 60
        self.resize(max(width, 560), 380)
        v.addWidget(self.table)
        self.fit_lbl = QLabel("Fit: —")
        v.addWidget(self.fit_lbl)
        fit_btn = QPushButton("Compute fit")
        fit_btn.clicked.connect(self._show_fit)
        v.addWidget(fit_btn)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._accept_if_valid)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _capture(self, row):
        xyz = getattr(self._parent, "_tool_xyz", None)
        if xyz is None:
            QMessageBox.warning(self, "Not connected",
                                "Connect the machine to capture the live position.")
            return
        x, y, _z = xyz
        self.table.setItem(row, 2, QTableWidgetItem(f"{x:.3f}"))
        self.table.setItem(row, 3, QTableWidgetItem(f"{y:.3f}"))

    def _auto_probe(self, row):
        p = self._parent
        xyz = getattr(p, "_tool_xyz", None)
        if p._dro is None or xyz is None:
            QMessageBox.warning(self, "Not connected",
                                "Connect the machine and click-jog the tool "
                                "over the fiducial hole first.")
            return
        if self._auto_busy:
            return
        if QMessageBox.question(
                self, "Auto-probe fiducial",
                f"Tool ~2-3 mm ABOVE the '{self.table.verticalHeaderItem(row).text()}' "
                f"fiducial HOLE, spindle OFF, touch clips on?\n\nIt will touch "
                f"the copper 2.5 mm west of here for a surface reference, then "
                f"walk the hole edges (~1 min).") != QMessageBox.Yes:
            return
        self._auto_busy = True
        self._dro_was_on = p._pause_dro()
        port = p.level_port_combo.currentText().strip() or "COM5"
        self._fid_worker = _FidFindWorker(port, row, xyz[0], xyz[1])
        self._fid_worker.found.connect(self._on_auto_found)
        self._fid_worker.failed.connect(self._on_auto_failed)
        self._fid_worker.start()

    def _on_auto_found(self, row, x, y):
        self.table.setItem(row, 2, QTableWidgetItem(f"{x:.3f}"))
        self.table.setItem(row, 3, QTableWidgetItem(f"{y:.3f}"))
        self._finish_auto()
        self._show_fit()                       # live feedback as rows fill in

    def _on_auto_failed(self, row, msg):
        QMessageBox.warning(self, "Auto-probe failed", msg)
        self._finish_auto()

    def _finish_auto(self):
        self._auto_busy = False
        if self._dro_was_on:
            self._dro_was_on = False
            self._parent._start_dro()

    def measured(self):
        """The filled-in (x, y) measured rows, in order; rows left blank are skipped."""
        out = []
        for r in range(self.table.rowCount()):
            mx, my = self.table.item(r, 2), self.table.item(r, 3)
            if mx and my and mx.text().strip() and my.text().strip():
                try:
                    out.append((float(mx.text()), float(my.text())))
                except ValueError:
                    pass
        return out

    def _show_fit(self):
        import math
        from gerber2rml.engine.fiducial import fit_transform, rms
        m = self.measured()
        if len(m) < 2:
            self.fit_lbl.setText("Fit: need at least 2 measured points")
            return
        try:
            allow = self._parent.fid_scale_chk.isChecked()
            t = fit_transform(self._nominal[:len(m)], m, allow_scale=allow)
            err = rms(t, self._nominal[:len(m)], m)
        except ValueError as e:
            self.fit_lbl.setText(f"Fit failed: {e}")
            return
        self.fit_lbl.setText(
            f"Fit: RMS {err * 1000:.0f} um · rot {math.degrees(t.theta):.3f}° · "
            f"scale {t.scale:.5f}  (n={len(m)})")

    def _accept_if_valid(self):
        if len(self.measured()) < 2:
            QMessageBox.warning(self, "Not enough points",
                                "Enter at least 2 measured fiducials.")
            return
        self.accept()


class _UpdateProbe(QThread):
    """Ask GitHub what the newest release is, off the UI thread.

    A lab PC behind a captive portal can take the whole timeout to fail, and
    nobody should watch a blank window while that happens.
    """
    checked = Signal(object)

    def __init__(self, version, parent=None):
        super().__init__(parent)
        self._version = version

    def run(self):
        from gerber2rml.engine import updates
        try:
            self.checked.emit(updates.check(self._version))
        except Exception:                       # noqa: BLE001 - best effort
            pass


class MainWindow(QMainWindow):
    _REWORK_COLORS = ["#ff5252", "#42a5f5", "#66bb6a", "#ffa726",
                      "#ab47bc", "#26c6da", "#ec407a", "#d4e157"]

    def __init__(self):
        super().__init__()
        # The title bar is where someone reads which version they are running.
        # (gerber2rml is the Python package name; SRM-CAM is the product.)
        self.setWindowTitle(f"SRM-CAM {__version__}")
        self.resize(1100, 750)
        self._set_app_icon()
        self.state = ProjectState()

        # Professional-only widgets. Tagged with self._pro() at the point they
        # are laid out (so a form row can hide its label too) and shown/hidden
        # together by _apply_mode(). Novice is the same UI with these put away
        # — never a second code path, so the two modes cannot drift apart.
        self._pro_items = []

        # Ensure the per-user workspace (Documents/SRM-CAM/{sessions,exports,
        # photos}) exists; every file dialog starts in its matching folder.
        try:
            from gerber2rml.gui.workspace import workspace_root
            workspace_root()
        except Exception:
            pass                        # a read-only home dir never blocks launch

        # Workflow state chips (right side of the status bar): a glance answers
        # "what's set up and what's missing" — board, mesh, fit, photo, boxes,
        # machine link. Poll-driven (cheap attribute reads) so no event wiring
        # can go stale.
        self._chip_labels = {}
        from PySide6.QtCore import QTimer
        self._chip_timer = QTimer(self)
        self._chip_timer.setInterval(1500)
        self._chip_timer.timeout.connect(self._update_chips)
        self._chip_timer.start()

        # Toolbar / Top Controls
        self.load_btn = QPushButton("Load Gerber folder...")
        self.load_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self.load_btn.clicked.connect(self._on_load_clicked)
        
        self.export_btn = QPushButton("Export toolpaths...")
        self.export_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        self.export_btn.clicked.connect(self._on_export_clicked)

        self.diag_btn = QPushButton("Diagnostics")
        self.diag_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation))
        self.diag_btn.setToolTip(
            "Pre-flight checks before cutting: does it fit the bed, does the "
            "deepest cut fit the SRM-20 Z range (probe Z first), holes vs bit. "
            "Run this before a full-bed job.")
        self.diag_btn.clicked.connect(self._on_diagnostics)

        self.feedcard_btn = QPushButton("Feed card")
        self.feedcard_btn.setToolTip(
            "Dial in the XY feed on scrap: export the feed-ladder test card "
            "(one block per feed, value engraved next to it), cut it, then "
            "photograph it and let the app score every block and recommend "
            "the fastest clean feed.")
        self.feedcard_btn.clicked.connect(self._on_feed_card)

        self.guide_btn = QPushButton("Guide")
        self.guide_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogHelpButton))
        self.guide_btn.setToolTip("Replay the guided walkthrough of the whole workflow.")

        self.save_setup_btn = QPushButton("Save setup...")
        self.save_setup_btn.setToolTip(
            "Save the WHOLE setup to a file: the loaded board, placement, rotation, "
            "all job/double-sided/stock settings and the probed height map. Reload "
            "it after a restart/update to pick up exactly where you left off.")
        self.save_setup_btn.clicked.connect(self._on_save_setup)
        self.load_setup_btn = QPushButton("Load setup...")
        self.load_setup_btn.setToolTip("Restore a setup saved with 'Save setup'.")
        self.load_setup_btn.clicked.connect(self._on_load_setup)

        self.export_img_btn = QPushButton("Export image")
        self.export_img_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon))
        self.export_img_btn.clicked.connect(self._on_export_image)

        self.sim3d_btn = QPushButton("Simulate 3D")
        self.sim3d_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.sim3d_btn.clicked.connect(self._on_simulate_3d)
        self.sim_file_btn = QPushButton("Open && simulate file...")
        self.sim_file_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self.sim_file_btn.clicked.connect(self._on_simulate_file)
        self._sim_window = None   # keep a ref so the window isn't GC'd

        self.name_edit = QLineEdit(self.state.name)
        from PySide6.QtWidgets import QSizePolicy
        self.machine_combo = QComboBox()
        self.machine_combo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.machine_combo.setMinimumWidth(100)
        self.machine_combo.addItems(list(BACKENDS.keys()))
        self.mirror_chk = QCheckBox("Mirror (bottom-up)"); self.mirror_chk.setChecked(True)
        self.mirror_chk.setToolTip(
            "Single-sided only: mill the bottom copper mirrored (board is flipped "
            "onto the bed). Greyed out in double-sided mode — there the View "
            "selector (Both/Bottom/Top) picks the frame and mirroring is applied "
            "per side automatically.")
        self.mirror_chk.toggled.connect(self._on_mirror_toggled)
        self.double_sided_chk = QCheckBox("Double-sided")
        self.double_sided_chk.toggled.connect(self._on_double_sided_toggled)
        self._ds_cache = None   # (gerber_dir, layout) so live edits don't re-read disk
        self._ds_mcache = None  # machine-frame layout cache (single-side rework/preview)
        # Measured top-side placement (engine.fiducial.Transform) from the last
        # fiducial fit: where the flipped board REALLY sits. When set, the Top
        # views render AS PLACED — warped by it — so click-to-jog, snapping,
        # rework boxes and run tracking land on the physical board.
        self._top_fit = None
        self._rework_regions = []  # [{bbox, depth, follow, color}] multi-region rework

        # single-sided preview orientation: the milled (mirrored) cut, or the
        # KiCad design view for a sanity check. Affects ONLY the preview.
        self.frame_combo = QComboBox()
        self.frame_combo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.frame_combo.setMinimumWidth(100)
        self.frame_combo.addItems(["As milled (mirrored)", "As designed (KiCad top)"])
        self.frame_combo.setToolTip(
            "Preview orientation only - the exported job is always 'as milled'.\n"
            "'As designed' flips the view to match your KiCad layout so you can "
            "check it; it does not change the output.")
        self.frame_combo.currentIndexChanged.connect(self.generate_preview)

        # draw the machine work area and flag designs that don't fit it
        self.show_bed_chk = QCheckBox("Show bed (fit check)")
        self.show_bed_chk.setChecked(True)
        self.show_bed_chk.toggled.connect(self.generate_preview)

        # place the whole job on the bed (origin = front-left home corner)
        self.place_x_spin = QDoubleSpinBox()
        self.place_y_spin = QDoubleSpinBox()
        for sp, ax in ((self.place_x_spin, "right (+X)"), (self.place_y_spin, "back (+Y)")):
            # allow negative: the board sits ~2 mm in from home, so a small negative
            # value reclaims that margin / pulls a design back off the far edge.
            sp.setRange(-500.0, 500.0); sp.setSingleStep(1.0); sp.setDecimals(1)
            sp.setSuffix(" mm")
            sp.setToolTip(f"Move the whole job {ax} on the bed from the front-left "
                          f"home (negative = toward/past home; off-bed shows red)")
            sp.valueChanged.connect(self.generate_preview)
        self._place_row = QWidget()
        _pl = QHBoxLayout(self._place_row); _pl.setContentsMargins(0, 0, 0, 0)
        _pl.addWidget(QLabel("X")); _pl.addWidget(self.place_x_spin)
        _pl.addWidget(QLabel("Y")); _pl.addWidget(self.place_y_spin)

        # drag the design around the bed with the mouse
        self.move_chk = QCheckBox("Move on bed (drag)")
        self.move_chk.toggled.connect(self._on_move_toggled)

        # rotate the whole job in 90 deg steps (reorients the exported cut)
        self._rotation = 0
        self.rotate_btn = QPushButton("Rotate 90°")
        self.rotate_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        self.rotate_btn.setToolTip(
            "Rotate the whole board 90° - this reorients the ACTUAL exported "
            "toolpaths, not just the view. Works for single- and double-sided "
            "(the dowels rotate with the board).")
        self.rotate_btn.clicked.connect(self._on_rotate)
        self.rotate_lbl = QLabel("0°")

        # measure (ruler): drag a line that snaps to the board edges/corners/holes
        self.measure_chk = QCheckBox("Measure (ruler)")
        self.measure_chk.setToolTip(
            "Drag a ruler over the preview; it snaps to the board's corners, "
            "edges and hole centres and shows length + dx/dy. Drag corner-to-"
            "corner to read off the board size.")
        self.measure_chk.toggled.connect(self._on_measure_toggled)

        # ---- Copper stock: draw the physical piece of copper to align onto ----
        self.stock_w_spin = QDoubleSpinBox(); self.stock_h_spin = QDoubleSpinBox()
        for sp, ax in ((self.stock_w_spin, "width"), (self.stock_h_spin, "height")):
            sp.setRange(0.0, 300.0); sp.setSingleStep(1.0); sp.setDecimals(1)
            sp.setSuffix(" mm")
            sp.setToolTip(f"Measured {ax} of the copper stock you're milling onto")
            sp.valueChanged.connect(self._update_stock_preview)
        self._stock_wh_row = QWidget()
        _sw = QHBoxLayout(self._stock_wh_row); _sw.setContentsMargins(0, 0, 0, 0)
        _sw.addWidget(QLabel("W")); _sw.addWidget(self.stock_w_spin)
        _sw.addWidget(QLabel("H")); _sw.addWidget(self.stock_h_spin)

        self.stock_x_spin = QDoubleSpinBox(); self.stock_y_spin = QDoubleSpinBox()
        for sp in (self.stock_x_spin, self.stock_y_spin):
            sp.setRange(0.0, 500.0); sp.setSingleStep(1.0); sp.setDecimals(1)
            sp.setSuffix(" mm")
            sp.setToolTip("Front-left corner of the copper on the bed (machine X/Y)")
            sp.valueChanged.connect(self._update_stock_preview)
        self._stock_xy_row = QWidget()
        _sx = QHBoxLayout(self._stock_xy_row); _sx.setContentsMargins(0, 0, 0, 0)
        _sx.addWidget(QLabel("X")); _sx.addWidget(self.stock_x_spin)
        _sx.addWidget(QLabel("Y")); _sx.addWidget(self.stock_y_spin)

        self.stock_show_chk = QCheckBox("Show copper stock")
        self.stock_show_chk.setToolTip(
            "Draw the measured copper piece on the bed so you can line the design "
            "(and dowels) up inside it. Turns red if the job spills off the copper.")
        self.stock_show_chk.toggled.connect(self._update_stock_preview)
        # Professional-only: it reads the live tool position over the machine
        # link, and Novice hides that link entirely — offering it there is a
        # button that cannot work. Novice places the design with 'Center
        # design' and the drag controls, which need no hardware.
        self.stock_here_btn = self._pro(QPushButton("Corner = tool"))
        self.stock_here_btn.setToolTip(
            "Set the copper's front-left corner to the live tool position — jog the "
            "bit to the corner of the copper, then click. Needs the machine connected.")
        self.stock_here_btn.clicked.connect(self._on_stock_corner_from_tool)
        self.stock_center_btn = QPushButton("Center design")
        self.stock_center_btn.setToolTip(
            "Move the design so it's centred on the copper stock — a starting point "
            "you can then nudge with the drag/placement controls.")
        self.stock_center_btn.clicked.connect(self._on_center_design_on_stock)

        # ---- Bed leveling: probe grid -> measured Z table -> warp on export ----
        self.level_chk = QCheckBox("Apply bed leveling on export")
        self.level_chk.setToolTip(
            "Warp every job's Z to follow the measured surface, so traces cut to "
            "depth even on a bed that isn't perfectly flat.")
        self.level_nx_spin = QSpinBox(); self.level_nx_spin.setRange(2, 8)
        self.level_nx_spin.setValue(3); self.level_nx_spin.setPrefix("nx ")
        self.level_ny_spin = QSpinBox(); self.level_ny_spin.setRange(2, 8)
        self.level_ny_spin.setValue(3); self.level_ny_spin.setPrefix("ny ")
        self.level_grid_btn = QPushButton("Build grid")
        self.level_grid_btn.setToolTip(
            "Lay out an nx x ny probe grid over the placed board and fill the table.")
        self.level_grid_btn.clicked.connect(self._on_build_level_grid)
        self.level_export_btn = QPushButton("Export probe files...")
        self.level_export_btn.setToolTip(
            "Write one G-code program per probe point (queue them in VPanel) + a "
            "checklist. Press Continue in VPanel to step point-to-point.")
        self.level_export_btn.clicked.connect(self._on_export_probe_files)
        self.level_save_btn = QPushButton("Save CSV")
        self.level_save_btn.setToolTip("Save the probe grid (X, Y, dz) to a CSV file.")
        self.level_save_btn.clicked.connect(self._on_save_level_grid)
        self.level_load_btn = QPushButton("Load CSV")
        self.level_load_btn.setToolTip(
            "Load a probe grid (X, Y, dz) CSV back into the table - e.g. one you "
            "saved with 'Save CSV' before a restart/update. You can then Resume "
            "probing or apply leveling.")
        self.level_load_btn.clicked.connect(self._on_load_level_grid)
        self.level_clear_btn = QPushButton("Clear Z")
        self.level_clear_btn.setToolTip(
            "Clear the measured Z values so you can re-probe (keeps the X/Y grid). "
            "Also turns off leveling and the height-map overlay.")
        self.level_clear_btn.clicked.connect(self._on_clear_level)
        self.level_top_btn = QPushButton("Export top traces (leveled)")
        self.level_top_btn.setEnabled(False)        # double-sided only
        self.level_top_btn.setToolTip(
            "TOP-side leveling (do this AFTER milling the bottom and flipping):\n"
            "set View to 'Top', Build grid, Clear Z, probe the flipped board, then "
            "click this to re-write <name>_top_traces warped to that surface.")
        self.level_top_btn.clicked.connect(self._on_export_top_traces)
        # auto-probe over the SRM-20 SPI link (Arduino running srm20_spi_probe.ino)
        # Serial port for the Arduino link — shared by the DRO connect and the
        # SPI probe. Shown in the machine dock; keeps its historical name.
        self.level_port_combo = QComboBox()
        self.level_port_combo.setMaximumWidth(90)
        self.level_port_combo.setToolTip(
            "Serial port of the Arduino (Device Manager > Ports). Used by both "
            "Connect (live DRO) and the SPI bed probe.")
        self.level_port_combo.setEditable(True)
        try:
            import serial.tools.list_ports
            ports = [p.device for p in serial.tools.list_ports.comports()]
            if ports:
                self.level_port_combo.addItems(ports)
            else:
                self.level_port_combo.addItem("COM5")
        except Exception:
            self.level_port_combo.addItem("COM5")
        self.level_probe_btn = QPushButton("Probe over SPI")
        self.level_probe_btn.setToolTip(
            "Auto-probe the grid via the Arduino over SPI and fill the Z column. "
            "Jog the tool ~2-3 mm above the first grid point first, with the prober "
            "sketch running and the Arduino Serial Monitor CLOSED.")
        self.level_probe_btn.clicked.connect(self._on_probe_spi)
        self.level_retouch_spin = QSpinBox()
        self.level_retouch_spin.setRange(0, 20)
        self.level_retouch_spin.setValue(6)
        self.level_retouch_spin.setPrefix("drift chk ")
        self.level_retouch_spin.setSpecialValueText("drift chk off")
        self.level_retouch_spin.setToolTip(
            "Re-touch the reference point after every N probed points and correct "
            "the whole grid for Z drift (spindle warm-up, board settling). This is "
            "what catches a mesh row measured 'low' minutes after the others. "
            "0 = off. Needs firmware v2 on the Arduino (reflash "
            "hardware/srm20_spi_probe).")
        self.level_check_btn = QPushButton("Mesh check")
        self.level_check_btn.setToolTip(
            "Sanity-check the measured mesh: flag points no smooth board surface "
            "can explain (flaky touches), recommend a cut depth that survives "
            "this mesh's uncertainty, and suggest where the grid is too coarse "
            "(with one click to insert the missing probe rows).")
        self.level_check_btn.clicked.connect(self._on_mesh_check)
        self.level_gridshow_chk = QCheckBox("Show grid")
        self.level_gridshow_chk.setToolTip(
            "Overlay the planned probe points (numbered) on the preview, so you "
            "can see where it will probe before measuring.")
        self.level_gridshow_chk.toggled.connect(lambda _on: self._update_grid_overlay())
        self.level_show_chk = QCheckBox("Show height map")
        self.level_show_chk.setToolTip(
            "Overlay the probed surface as a tilt/warp heatmap on the preview.")
        self.level_show_chk.toggled.connect(lambda _on: self._update_level_overlay())
        self.level_3d_btn = QPushButton("3D view")
        self.level_3d_btn.setToolTip(
            "Open the probed surface as a rotatable 3D mesh (OctoPrint-style).")
        self.level_3d_btn.clicked.connect(self._on_bed_3d)

        # ---- live machine link: DRO banner + tool overlay ----
        # Emergency STOP: abort any probing/touch-off/jog, lift the tool, and
        # drop the link. Always enabled so it works even mid-probe.
        self.stop_btn = QPushButton("STOP")
        self.stop_btn.setObjectName("stopBtn")
        self.stop_btn.setToolTip(
            "Abort immediately: stop probing/jogging, lift the bit to safe Z, and "
            "disconnect. Use if the tool is heading into the board or bed.")
        self.stop_btn.clicked.connect(self._on_emergency_stop)

        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setCheckable(True)
        self.connect_btn.setToolTip(
            "Open the Arduino link and show live X/Y/Z + the tool position on the "
            "preview. Uses the same port as probing; Serial Monitor must be closed.")
        self.connect_btn.toggled.connect(self._on_connect_toggled)
        self.jog_chk = QCheckBox("Click to jog")
        self.jog_chk.setEnabled(False)        # only meaningful while connected
        self.jog_chk.setToolTip(
            "Click a point on the preview to move the tool there (lifts ~5 mm "
            "first, then travels XY). Clicks snap to the nearest drill hole or "
            "dowel/fiducial pin when one is close — Ctrl+click for the exact "
            "clicked position. Needs the machine connected.")
        self.jog_chk.toggled.connect(self._on_jog_mode_toggled)
        self.trail_chk = QCheckBox("Trail")
        self.trail_chk.setChecked(True)
        self.trail_chk.setToolTip(
            "Leave a fading amber breadcrumb trail of where the bit has already "
            "travelled, so you can follow its tracks during a rework pass.")
        self.trail_chk.toggled.connect(
            lambda on: self.preview.set_tool_trail_visible(on))
        self.trail_clear_btn = QPushButton("Clear trail")
        self.trail_clear_btn.setToolTip("Wipe the breadcrumb trail and start fresh.")
        self.trail_clear_btn.clicked.connect(lambda: self.preview.clear_tool_trail())
        self.zero_btn = QPushButton("Probe Z")
        self.zero_btn.setEnabled(False)
        self.zero_btn.setToolTip(
            "Lower the bit from here until it touches the plate, stop at the "
            "surface, and set that Z as the work-surface zero. Needs the touch "
            "clips connected; start a few mm above the surface.")
        self.zero_btn.clicked.connect(self._on_probe_z)
        self.machine_zero_btn = QPushButton("Zero Z on machine")
        self.machine_zero_btn.setEnabled(False)
        self.machine_zero_btn.setToolTip(
            "Verified touch-off, then the FIRMWARE writes origin Z = the copper "
            "surface (v2 'W' command) and lifts 2 mm - no VPanel round-trip.\n"
            "NOTE: this sets the origin VPanel displays (User CS). Check "
            "VPanel's G54 Z once before trusting it for NC jobs.")
        self.machine_zero_btn.clicked.connect(self._on_machine_zero)
        self.stream_btn = QPushButton("Stream (exp.)")
        self.stream_btn.setEnabled(False)
        self.stream_btn.setToolTip(
            "EXPERIMENTAL: stream the picked op's toolpaths over the SPI link "
            "move-by-move (no VPanel file player). ALWAYS starts as a DRY RUN "
            "with Z held 2 mm above the origin — nothing can cut. A wet run "
            "additionally needs the spindle started in VPanel by hand and the "
            "raw speed value calibrated on dry runs first.")
        self.stream_btn.clicked.connect(self._on_stream_job)
        self.align_btn = QPushButton("Align overlay")
        self.align_btn.setCheckable(True)
        self.align_btn.setEnabled(False)      # only meaningful while connected
        self.align_btn.setToolTip(
            "Fix the live overlay when the machine's work origin (G54) is not "
            "where the design sits on screen: arm this, then click the design "
            "point the bit is PHYSICALLY at (e.g. the hole it is drilling). "
            "Display + click-to-jog + progress tracking only — exports and job "
            "coordinates are untouched. Ctrl+click on the canvas clears the trim.")
        self.align_btn.toggled.connect(self._on_align_mode_toggled)
        self._overlay_trim = (0.0, 0.0)   # design frame - machine frame (mm)
        self._z_zero = None         # captured surface Z (machine mm), or None
        self._touching = False      # last reported probe contact state
        self.dro_label = QLabel("○  machine offline")
        self.dro_label.setStyleSheet(
            "color:#888; font-family:Consolas,monospace; font-size:13px; padding:4px 10px;")
        self.touch_label = QLabel("bit ○")        # contact indicator (D7 probe)
        self.touch_label.setToolTip(
            "Whether the bit is touching the (probe-wired) plate. Needs the touch "
            "clips connected to mean anything.")
        self.touch_label.setStyleSheet(
            "color:#888; font-family:Consolas,monospace; font-size:13px; padding:4px 10px;")
        # ---- live run-progress bar (driven by the DRO position) ----
        self.run_op_combo = QComboBox()
        self.run_op_combo.addItems(["Traces", "Drill", "Cut-out"])
        self.run_op_combo.setToolTip(
            "Which job is running on the mill — its estimated time drives the bar.")
        self.run_rework_chk = QCheckBox("selection")
        self.run_rework_chk.setToolTip(
            "Track the rework selection (the clipped 2nd pass) instead of the whole "
            "job. Needs an active 'Select area' box.")
        self.run_track_btn = QPushButton("Track run")
        self.run_track_btn.setCheckable(True)
        self.run_track_btn.setToolTip(
            "Start tracking progress from the live tool position. Connect the "
            "machine, hit Run in VPanel, then press this — the bar follows the bit "
            "and counts down the time left.")
        self.run_track_btn.toggled.connect(self._on_track_run)
        self.run_auto_chk = QCheckBox("Auto")
        self.run_auto_chk.setChecked(True)
        self.run_auto_chk.setToolTip(
            "Start tracking automatically when the bit begins moving (a run starts "
            "in VPanel), so you don't have to press 'Track run'. Uses the op picked "
            "on the left.")
        self._run_finished = False        # current run reached 100%
        self._run_motion = 0              # consecutive 'moving' DRO reads (auto-start)
        self._run_last_pos = None         # last pos used for the motion test
        self._last_jog_t = 0.0            # time of the last jog (suppresses auto-start)
        self.run_bar = QProgressBar()
        self.run_bar.setRange(0, 100)
        self.run_bar.setValue(0)
        self.run_bar.setTextVisible(True)
        self.run_eta_lbl = QLabel("—")
        self.run_eta_lbl.setStyleSheet(
            "color:#aab; font-family:Consolas,monospace; font-size:13px; padding:0 8px;")
        self._run_progress = None   # engine.progress.RunProgress while tracking

        self._dro = None            # _DROPoller when connected
        self._tool_xyz = None       # last good (x, y, z) mm
        self._dro_rejects = 0       # consecutive implausible reads (re-sync guard)
        self._dro_was_on = False    # restore the link after a probe run
        self.level_table = QTableWidget(0, 3)
        self.level_table.setHorizontalHeaderLabels(["X (mm)", "Y (mm)", "Z (mm)"])
        self.level_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.level_table.verticalHeader().setVisible(False)
        self.level_table.setMaximumHeight(220)

        # stock thickness (mm): drawn as the 3D slab, used for the dowel depth,
        # and (when auto-depth is on) the drill/cut-out depth.
        self.thickness_spin = QDoubleSpinBox()
        self.thickness_spin.setRange(0.1, 10.0); self.thickness_spin.setSingleStep(0.1)
        self.thickness_spin.setDecimals(2); self.thickness_spin.setValue(1.6)
        self.thickness_spin.setSuffix(" mm")
        self.thickness_spin.setToolTip(
            "Measured PCB stock thickness - shown as the 3D slab, used for the "
            "double-sided dowel depth, and (with auto-depth) the drill/cut-out depth")
        self.thickness_spin.valueChanged.connect(self._on_depth_source_changed)

        # auto-depth: drill + cut-out depth = stock thickness + breakthrough, so
        # measuring the board sets how deep it drills and cuts out.
        self.auto_depth_chk = QCheckBox("Auto depth = stock +")
        self.auto_depth_chk.setChecked(True)
        self.auto_depth_chk.toggled.connect(self._on_depth_source_changed)
        self.breakthrough_spin = QDoubleSpinBox()
        self.breakthrough_spin.setRange(0.0, 3.0); self.breakthrough_spin.setSingleStep(0.05)
        self.breakthrough_spin.setDecimals(2); self.breakthrough_spin.setValue(0.1)
        self.breakthrough_spin.setSuffix(" mm")
        self.breakthrough_spin.setToolTip(
            "How far PAST the board the drill and cut-out go, into the spoilboard")
        self.breakthrough_spin.valueChanged.connect(self._on_depth_source_changed)
        self._auto_depth_row = QWidget()
        _ad = QHBoxLayout(self._auto_depth_row); _ad.setContentsMargins(0, 0, 0, 0)
        _ad.addWidget(self.auto_depth_chk); _ad.addWidget(self.breakthrough_spin)

        # which side(s) to show in the double-sided preview
        self.view_combo = QComboBox()
        self.view_combo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.view_combo.setMinimumWidth(100)
        self.view_combo.addItems(["Both sides", "Bottom", "Top"])
        self.view_combo.setEnabled(False)   # only meaningful when double-sided
        self.view_combo.currentIndexChanged.connect(self.generate_preview)

        # double-sided registration: fresh-milled dowels vs grid-seated pins
        self.reg_combo = QComboBox()
        self.reg_combo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.reg_combo.setMinimumWidth(100)
        self.reg_combo.addItems(["Fresh-milled dowels (1.9+3.1mm)",
                                 "Grid-seated pins (M4 grid)"])
        self.reg_combo.setEnabled(False)
        self.reg_combo.currentIndexChanged.connect(self._on_reg_changed)
        # which edge pair carries the dowels (sets the flip axis)
        self.place_combo = QComboBox()
        self.place_combo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.place_combo.setMinimumWidth(100)
        self.place_combo.addItems(["Top & bottom (flip left-right)",
                                   "Left & right (flip top-bottom)"])
        self.place_combo.setToolTip(
            "Which two edges the dowels sit beyond. Put them on whichever edge "
            "pair has the most waste room for the pins.")
        self.place_combo.setEnabled(False)
        self.place_combo.currentIndexChanged.connect(self._on_reg_changed)
        self.grid_pitch_edit = QLineEdit(f"{14.2}")
        self.grid_pitch_edit.setToolTip("Grid hole-to-hole spacing (mm)")
        self.grid_pitch_edit.editingFinished.connect(self._on_reg_changed)
        self.grid_pin_edit = QLineEdit(f"{4.0}")
        self.grid_pin_edit.setToolTip("Grid dowel diameter = grid hole size (mm)")
        self.grid_pin_edit.editingFinished.connect(self._on_reg_changed)
        self._grid_row = QWidget()
        _grid_row_l = QHBoxLayout(self._grid_row)
        _grid_row_l.setContentsMargins(0, 0, 0, 0)
        _grid_row_l.addWidget(QLabel("pitch")); _grid_row_l.addWidget(self.grid_pitch_edit)
        _grid_row_l.addWidget(QLabel("pin")); _grid_row_l.addWidget(self.grid_pin_edit)
        self._grid_row.setEnabled(False)   # enabled only in grid mode
        # fresh-mode: oversize the milled dowel holes PER PIN (kerf differs by
        # diameter — dialed in on the fit-test coupon: big +0.20, small +0.15).
        from gerber2rml.doublesided import CLEAR_LARGE, CLEAR_SMALL
        self.fresh_clear_large_edit = QLineEdit(f"{CLEAR_LARGE}")
        self.fresh_clear_large_edit.setToolTip(
            "Fresh dowels: mm added to the BIG (3.1 mm) hole. 0.20 seats the big "
            "pin snug on this machine. Bump if it binds during a test cut.")
        self.fresh_clear_large_edit.editingFinished.connect(self._on_reg_changed)
        self.fresh_clear_small_edit = QLineEdit(f"{CLEAR_SMALL}")
        self.fresh_clear_small_edit.setToolTip(
            "Fresh dowels: mm added to the SMALL (1.9 mm) hole. 0.15 seats the "
            "small pin snug — a touch tighter than the big one.")
        self.fresh_clear_small_edit.editingFinished.connect(self._on_reg_changed)
        # how deep the dowel holes bite into the sacrificial bed BELOW the stock
        self.fresh_bed_spin = QDoubleSpinBox()
        self.fresh_bed_spin.setRange(0.0, 12.0); self.fresh_bed_spin.setSingleStep(0.5)
        self.fresh_bed_spin.setDecimals(1); self.fresh_bed_spin.setValue(5.0)
        self.fresh_bed_spin.setSuffix(" mm")
        self.fresh_bed_spin.setToolTip(
            "How far the dowel holes go INTO the wood/bed below the stock. The pins "
            "seat in this; if they don't bite deep enough, raise this and re-cut "
            "just the dowels ('Cut dowels only').")
        self.align_only_btn = QPushButton("Cut dowels only...")
        self.align_only_btn.setToolTip(
            "Export ONLY the dowel-hole G-code (no traces/drills/cutout). Use to "
            "test-fit the rods or deepen the bed bite, then re-cut just the holes. "
            "Keep the SAME XY origin so the re-cut lands on the existing holes.")
        self.align_only_btn.clicked.connect(self._on_export_align_only)
        self._fresh_row = QWidget()
        _fresh_row_l = QHBoxLayout(self._fresh_row)
        _fresh_row_l.setContentsMargins(0, 0, 0, 0)
        _fresh_row_l.addWidget(QLabel("clr L"))
        _fresh_row_l.addWidget(self.fresh_clear_large_edit)
        _fresh_row_l.addWidget(QLabel("S"))
        _fresh_row_l.addWidget(self.fresh_clear_small_edit)
        _fresh_row_l.addWidget(QLabel("bed"))
        _fresh_row_l.addWidget(self.fresh_bed_spin)
        _fresh_row_l.addWidget(self.align_only_btn)
        self._fresh_row.setEnabled(False)   # enabled only in fresh mode

        # ---- registration METHOD: dowel pins (above) vs fiducial holes ----
        self.regmethod_combo = QComboBox()
        self.regmethod_combo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.regmethod_combo.setMinimumWidth(100)
        self.regmethod_combo.addItems(["Dowel pins", "Fiducial holes"])
        self.regmethod_combo.setEnabled(False)
        self.regmethod_combo.setToolTip(
            "Dowel pins: drill 2 holes into the bed, seat pins, flip onto them "
            "(mechanical, proven). Fiducial holes: drill 2-4 stock-only corner "
            "holes, flip, probe them, and the top traces are warped to the measured "
            "fit (no bed drilling, re-alignable any time).")
        self.regmethod_combo.currentIndexChanged.connect(self._on_reg_changed)
        self.fid_count_spin = QSpinBox(); self.fid_count_spin.setRange(2, 4)
        self.fid_count_spin.setValue(4)
        self.fid_count_spin.setToolTip("How many corner fiducial holes (2-4).")
        self.fid_count_spin.valueChanged.connect(self._on_reg_changed)
        self.fid_place_combo = QComboBox()
        self.fid_place_combo.addItems(["On board", "In waste", "Manual (drag pins)"])
        # manual fiducial positions, board-relative design-frame mm (lower-left
        # of the framed board box = (0, 0)); seeded from the corner placement
        # when Manual is first selected, then edited by dragging the gold pins.
        self._fid_points = []
        self.fid_place_combo.setToolTip(
            "On board: holes inset inside the corners (permanent, works full-bed). "
            "In waste: holes outset beyond the board (clean board, bigger stock). "
            "Manual: drag the gold pins on the preview to place each hole freely "
            "— for large boards where the corner schemes don't fit the stock.")
        self.fid_place_combo.currentIndexChanged.connect(self._on_reg_changed)
        self.fid_offset_spin = QDoubleSpinBox()
        self.fid_offset_spin.setRange(0.5, 30.0); self.fid_offset_spin.setSingleStep(0.5)
        self.fid_offset_spin.setDecimals(1); self.fid_offset_spin.setValue(4.0)
        self.fid_offset_spin.setSuffix(" mm")
        self.fid_offset_spin.setToolTip("Inset (on board) / outset (waste) from each corner.")
        self.fid_offset_spin.valueChanged.connect(self._on_reg_changed)
        self.fid_scale_chk = QCheckBox("scale")
        self.fid_scale_chk.setToolTip(
            "Also fit uniform scale (absorbs thermal/measurement scale). Off = "
            "rigid rotation+translation, like the dowel constraint.")
        self.fid_align_btn = QPushButton("Fit & export top...")
        self.fid_align_btn.setToolTip(
            "After milling the bottom, flipping and re-placing the board: enter or "
            "capture the probed X/Y of each fiducial; the top traces are warped to "
            "the best-fit transform and exported. Shows the RMS fit error.")
        self.fid_align_btn.clicked.connect(self._on_fiducial_align)
        self.fid_flip_combo = QComboBox()
        self.fid_flip_combo.addItems(["Flip left-right", "Flip top-bottom"])
        self.fid_flip_combo.setToolTip(
            "Which way you physically flip the board. IMPORTANT with corner "
            "fiducials: the fiducial rectangle is symmetric, so the fit reports "
            "a tiny RMS for BOTH directions — it cannot detect a wrong choice. "
            "Pick the one you actually did, then jog-verify a drilled hole in "
            "the AS PLACED Top view before cutting.")
        self.fid_flip_combo.currentIndexChanged.connect(self._on_reg_changed)
        self._fid_row = QWidget()
        _fid_row_l = QHBoxLayout(self._fid_row)
        _fid_row_l.setContentsMargins(0, 0, 0, 0)
        _fid_row_l.addWidget(QLabel("n")); _fid_row_l.addWidget(self.fid_count_spin)
        _fid_row_l.addWidget(self.fid_place_combo)
        _fid_row_l.addWidget(self.fid_offset_spin)
        _fid_row_l.addWidget(self.fid_flip_combo)
        _fid_row_l.addWidget(self.fid_scale_chk)
        _fid_row_l.addWidget(self.fid_align_btn)
        self._fid_row.setEnabled(False)   # enabled only in fiducial mode

        from gerber2rml.app.presets import load_presets
        self._presets = load_presets()
        self.preset_combo = QComboBox()
        self.preset_combo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.preset_combo.setMinimumWidth(100)
        self.preset_combo.addItems(list(self._presets.keys()))
        self.apply_preset_btn = QPushButton("Apply")
        self.apply_preset_btn.clicked.connect(self.apply_selected_preset)
        self.save_preset_btn = QPushButton("Save...")
        self.save_preset_btn.clicked.connect(self._on_save_preset)

        # Rework (2nd pass): box-select an area of the previewed toolpath and
        # export NC for just that part, to re-cut traces left not fully isolated.
        self.select_chk = QCheckBox("Add areas")
        self.select_chk.setToolTip("Drag boxes over each spot to re-cut; each box "
                                   "is added to the list below.")
        self.select_chk.toggled.connect(self._on_select_toggled)
        self.clear_sel_btn = QPushButton("Clear all")
        self.clear_sel_btn.clicked.connect(self._clear_rework)
        # Default depth for the NEXT box you draw — independent of the original job
        # so you can re-cut a missed area deeper; edit any box's depth in the table.
        self.rework_depth_spin = QDoubleSpinBox()
        self.rework_depth_spin.setRange(0.0, 5.0)
        self.rework_depth_spin.setSingleStep(0.01)
        self.rework_depth_spin.setDecimals(3)
        self.rework_depth_spin.setValue(0.15)
        self.rework_depth_spin.setSuffix(" mm")
        self.rework_depth_spin.setToolTip(
            "Default depth for the NEXT box you draw. Edit any box's depth in the "
            "table. Raise past the trace depth to be sure stubborn copper cuts "
            "through. With each box's 'lvl' on, the probed offset keeps that depth "
            "uniform across the board's warp.")
        self.rework_level_chk = QCheckBox("Follow height map")
        self.rework_level_chk.setChecked(True)
        self.rework_level_chk.setToolTip(
            "Default for new boxes: warp the box to the probed surface so its depth "
            "stays uniform over the board's warp. Toggle per box ('lvl') in the "
            "table. Needs a probed/loaded height map (>=3 points).")
        self.rework_table = QTableWidget(0, 5)
        self.rework_table.setHorizontalHeaderLabels(["#", "size (mm)", "depth", "lvl", ""])
        self.rework_table.horizontalHeader().setStretchLastSection(True)
        self.rework_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.export_sel_btn = QPushButton("Export rework NC...")
        self.export_sel_btn.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        self.export_sel_btn.clicked.connect(self._on_export_selected)
        # Always enabled: a greyed-out button can't explain itself (a real
        # operator lost time to this). Clicking with a missing precondition
        # shows exactly what to fix (regions / op tab / side selection).
        self.export_sel_btn.setToolTip(
            "Write the rework pass for the drawn boxes. Needs: one or more "
            "boxes, the Traces or Cutout preview, and (double-sided) View set "
            "to Bottom or Top — clicking tells you what's missing.")

        # Photo overlay: warp a phone photo of the board on the bed into the
        # machine frame (homography from clicked hole anchors) and draw it
        # under the toolpaths — rework boxes land on the REAL copper instead
        # of on memory of a walk to the machine.
        self.photo_load_btn = QPushButton("Load photo...")
        self.photo_load_btn.setToolTip(
            "Overlay a photo of the board on the bed: pick an image, click the "
            "4 highlighted anchor holes in it, and the photo is warped to line "
            "up with the preview exactly.")
        self.photo_load_btn.clicked.connect(self._on_load_photo)
        self.photo_anchor_btn = QPushButton("Anchors...")
        self.photo_anchor_btn.setToolTip(
            "Choose WHICH drilled holes anchor the photo. By default the 4 "
            "corner-most holes are used, which is right when the board has "
            "dowel/fiducial holes — a single-sided board has none, and its "
            "corner holes may be tiny or impossible to tell apart in a photo. "
            "Here you click any 4+ ordinary drill holes you can recognise "
            "again; they're numbered on the preview and the photo dialog asks "
            "for them in that order.")
        self.photo_anchor_btn.clicked.connect(self._on_pick_photo_anchors)
        self.photo_phone_btn = QPushButton("Phone...")
        self.photo_phone_btn.setToolTip(
            "Take the board photo with your phone and beam it straight in: "
            "shows a QR code, the phone opens a take-photo page, and the "
            "shot lands here — no cables, no cloud. Phone and PC must be on "
            "the same network (on eduroam: use the phone's hotspot).")
        self.photo_phone_btn.clicked.connect(self._on_phone_photo)
        self.photo_clear_btn = QPushButton("Clear")
        self.photo_clear_btn.clicked.connect(self._on_clear_photo)
        self.photo_alpha_slider = QSlider(Qt.Horizontal)
        self.photo_alpha_slider.setRange(0, 100)
        self.photo_alpha_slider.setValue(55)
        self.photo_alpha_slider.setToolTip("Photo overlay opacity")
        self.photo_alpha_slider.valueChanged.connect(self._on_photo_alpha)
        self.trace_dim_slider = QSlider(Qt.Horizontal)
        self.trace_dim_slider.setRange(0, 100)
        self.trace_dim_slider.setValue(100)
        self.trace_dim_slider.setToolTip(
            "Toolpath/copper opacity — slide left to fade the traces so the "
            "photo underneath reads clearly (rework boxes stay full strength)")
        self.trace_dim_slider.valueChanged.connect(self._on_trace_dim)
        self.detect_rework_btn = QPushButton("Detect from photo")
        self.detect_rework_btn.setToolTip(
            "Walk every isolation channel and check the aligned photo for "
            "stretches with NO visible cut at all — each becomes a proposed "
            "rework box (at the current New-box depth). Review the boxes and "
            "delete false alarms before exporting.\n\nLIMITS: a too-SHALLOW "
            "cut still looks like a channel in any photo — judge depth "
            "failures with Probe boxes / Mesh check instead. Needs the photo "
            "overlay loaded and the traces preview visible; shoot as straight-"
            "down and evenly lit as possible.")
        self.detect_rework_btn.clicked.connect(self._on_detect_rework)
        self.probe_boxes_btn = QPushButton("Probe boxes")
        self.probe_boxes_btn.setToolTip(
            "Probe each rework box center over SPI and compare against the "
            "leveling mesh: where the real surface sits HIGHER than the mesh "
            "believed (the reason the spot needs rework), the box is deepened "
            "by exactly the difference. Jog above the mesh reference point "
            "(leveling grid point 1) first, spindle OFF.")
        self.probe_boxes_btn.clicked.connect(self._on_probe_rework_boxes)
        self._photo_overlay = None      # {path, photo_pts, machine_pts, alpha}
        self._photo_anchor_pts = None   # operator-chosen anchor holes [(x, y)]

        # Live cross-section of the active trace tool (V-bit width/depth math
        # made visible). Created before the forms: _sync_vbit_fields feeds it.
        from gerber2rml.gui.bitviz import BitProfileWidget
        self.bit_viz = BitProfileWidget()

        # Operation parameters (hidden, managed by presets)
        self.forms = {"traces": DataclassForm(self.state.trace,
                                              choices={"tool_type": ["flat", "vbit"]}),
                      "drill": DataclassForm(self.state.drill),
                      "cutout": DataclassForm(self.state.cutout)}
        for op in _OPS:
            self.forms[op].valueChanged.connect(self.generate_preview)
        # A V-bit derives its depth from the target width, so grey out the fields
        # that no longer apply and show the derived depth live.
        self.forms["traces"].valueChanged.connect(self._sync_vbit_fields)
        self._sync_vbit_fields()

        # Preview mode toggle
        from PySide6.QtWidgets import QTabBar
        self.tabs = QTabBar()
        for op in _OPS:
            self.tabs.addTab(op.capitalize())
        self.tabs.currentChanged.connect(self.generate_preview)

        # Load / Export are the primary actions -> accent style
        self.load_btn.setObjectName("primaryBtn")
        self.export_btn.setObjectName("primaryBtn")

        def _row(*ws, stretch_first=False):
            box = QWidget(); h = QHBoxLayout(box)
            h.setContentsMargins(0, 0, 0, 0); h.setSpacing(8)
            for i, x in enumerate(ws):
                h.addWidget(x, 1 if (stretch_first and i == 0) else 0)
            return box

        def _group(title):
            g = QGroupBox(title); f = QFormLayout(g)
            f.setSpacing(8); f.setContentsMargins(14, 16, 14, 12)
            f.setLabelAlignment(Qt.AlignRight)
            return g, f

        # ---------- Runplan spine (GUI 2.0) ----------
        # The sidebar IS the run plan: the steps in machining order, each
        # routing to the page/op/side it needs. NEVER blocking — every step
        # is clickable at any time; it's a map, not a gate.
        # (label, stacked page, op tab index or None, DS view or None)
        self._SPINE = [
            ("1 · Setup board",    0, None, None),
            ("2 · Bed leveling",   2, None, None),
            ("3 · Registration",   1, None, None),
            ("4 · Drill",          0, 1,    "Bottom"),
            ("5 · Bottom traces",  0, 0,    "Bottom"),
            ("6 · Cutout",         0, 2,    "Bottom"),
            ("7 · Flip + align",   1, None, None),
            ("8 · Top traces",     0, 0,    "Top"),
            ("Rework",             3, None, None),
            ("3D viewer",          4, None, None),
        ]
        # Novice runs one board, one side: load it, drill, cut the traces, cut
        # it out, look at it in 3D before committing. Bed leveling, the flip
        # and rework are the steps that need a second bit of judgement, so they
        # are the ones Professional adds back.
        self._PRO_STEPS = {1, 2, 6, 7, 8}
        # ...and with them gone the "1 2 3 4 ... 8" numbering would read
        # "1 4 5 6 10", so Novice gets its own labels for the steps it keeps.
        self._NOVICE_LABELS = {
            0: "1 · Set up board",
            3: "2 · Drill",
            4: "3 · Traces",
            5: "4 · Cut out",
            9: "5 · Check in 3D",
        }
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(180)
        self.sidebar.addItems([s[0] for s in self._SPINE])

        self.stacked_widget = QStackedWidget()
        self.sidebar.currentRowChanged.connect(self._on_spine_changed)

        def _make_page(help_text=""):
            p = QWidget()
            vl = QVBoxLayout(p)
            vl.setContentsMargins(14, 14, 14, 14)
            vl.setSpacing(12)
            
            if help_text:
                lbl = QLabel(help_text)
                lbl.setWordWrap(True)
                lbl.setObjectName("helpText")
                vl.addWidget(lbl)
                
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.NoFrame)
            scroll.setWidget(p)
            self.stacked_widget.addWidget(scroll)
            return vl

        l_proj = _make_page("Load your Gerber files, select a preset toolpath profile, and position the board on the bed. Switch preview modes below to see how the board will be milled.")
        l_double = _make_page("Configure how the board is flipped to mill the second side. You can use fresh-milled dowel holes or a pre-installed M4 pin grid for perfect registration.")
        l_level = _make_page("Compensate for an uneven bed or bowed PCB. Probe the copper surface to generate a height map so the engraving depth remains perfectly consistent.")
        l_rework = _make_page("Missed some copper isolation? Select an area in the 3D preview and generate toolpaths only for that specific region to clear remaining shorts.")
        l_3dview = _make_page("Open the 3D views. They open in their own windows, so "
                              "use these to re-open one after you close it. The "
                              "toolpath simulations need a loaded board; the bed view "
                              "needs a probed (or loaded) height map. The 3D views "
                              "require PyOpenGL.")

        # Per-page "Guide" buttons jump straight into that section's mini-tour,
        # so you don't have to walk the whole core flow to reach it. Wired to the
        # TourController once it exists (end of __init__).
        def _page_guide(layout, label):
            b = QPushButton(label)
            b.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogHelpButton))
            b.setToolTip("Show the guided walkthrough for this section.")
            layout.addWidget(b)
            return b
        self.guide_double_btn = self._pro(_page_guide(l_double, "Guide: Double-sided"))
        self.guide_level_btn = self._pro(_page_guide(l_level, "Guide: Bed leveling"))
        self.guide_rework_btn = self._pro(_page_guide(l_rework, "Guide: Rework"))

        self.sidebar.setCurrentRow(0)

        # ===== BASIC: the things you set every time =====
        board_group, bl = _group("Board")
        bl.addRow(_row(self.load_btn, self.export_btn))
        # Diagnostics stays in Novice on purpose — it is the pre-flight check
        # that catches a job that won't fit the bed or the Z range, and hiding
        # a safety net from beginners would be exactly backwards.
        bl.addRow(_row(self.diag_btn, self._pro(self.feedcard_btn)))
        bl.addRow(_row(self.save_setup_btn, self.load_setup_btn))
        bl.addRow("Name", self.name_edit)
        # The preset IS the Novice interface to feeds and depths: the lab owner
        # curates the profiles (see gerber2rml/app/presets.py) and a student
        # picks one. Saving a new profile is a Professional act.
        bl.addRow("Preset", _row(self.preset_combo, self.apply_preset_btn,
                                 self._pro(self.save_preset_btn),
                                 stretch_first=True))
        bl.addRow("Tool", self.bit_viz)
        bl.addRow("Stock", self.thickness_spin)
        bl.addRow("", self._auto_depth_row)
        l_proj.addWidget(board_group)

        ops_group = QGroupBox("Preview Mode")
        _ol = QVBoxLayout(ops_group); _ol.setContentsMargins(10, 14, 10, 10)
        _ol.addWidget(self.tabs)
        l_proj.addWidget(ops_group)

        # ===== JOB PARAMETERS (the forms presets fill — now editable) =====
        # NOTE: not a checkable QGroupBox — unchecking one DISABLES all
        # children (Qt built-in), which would stomp the forms' own per-field
        # enable logic (auto-depth, V-bit greying). A toolbutton toggles
        # visibility instead.
        from PySide6.QtWidgets import QToolButton
        self.params_group = QGroupBox("Job parameters")
        self.params_group.setToolTip(
            "Edit the active cut parameters directly — bit, depths, feeds, "
            "V-bit geometry. Presets fill these fields; tweak here and "
            "Save... to keep your own preset. Changes update the preview "
            "immediately.")
        self.params_toggle = QToolButton()
        self.params_toggle.setText("Edit values")
        self.params_toggle.setCheckable(True)
        self.params_toggle.setArrowType(Qt.RightArrow)
        self.params_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.params_tabs = QTabWidget()
        for op in _OPS:
            self.params_tabs.addTab(self.forms[op], op.capitalize())
        _jl = QVBoxLayout(self.params_group)
        _jl.setContentsMargins(10, 14, 10, 10)
        _jl.addWidget(self.params_toggle)
        _jl.addWidget(self.params_tabs)
        self.params_tabs.setVisible(False)

        def _params_toggled(on):
            self.params_tabs.setVisible(on)
            self.params_toggle.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        self.params_toggle.toggled.connect(_params_toggled)
        l_proj.addWidget(self._pro(self.params_group))

        # ===== VIEW / PLACEMENT =====
        view_group, vl = _group("View / machine")
        vl.addRow("Machine", self.machine_combo)
        vl.addRow("Preview", self.frame_combo)
        vl.addRow("", self.mirror_chk)
        vl.addRow("", self.show_bed_chk)
        vl.addRow(_row(self.sim3d_btn, self.sim_file_btn))
        vl.addRow(_row(self.export_img_btn))
        # Output format, mirroring and preview frame all default correctly for
        # the SRM-20; getting one of them wrong scraps a board. The 3D views in
        # here are reachable from the "Check in 3D" step instead.
        l_proj.addWidget(self._pro(view_group))

        place_group, pl = _group("Placement on bed")
        pl.addRow("Place", self._place_row)
        pl.addRow("Rotate", _row(self.rotate_btn, self.rotate_lbl, stretch_first=False))
        pl.addRow("", self.move_chk)
        pl.addRow("", self.measure_chk)
        l_proj.addWidget(place_group)

        stock_group, sg = _group("Copper stock")
        sg.addRow("Size", self._stock_wh_row)
        sg.addRow("Corner", self._stock_xy_row)
        sg.addRow("", _row(self.stock_here_btn, self.stock_center_btn))
        sg.addRow("", self.stock_show_chk)
        l_proj.addWidget(stock_group)
        l_proj.addStretch(1)

        # ===== BED LEVELING =====
        level_group = QGroupBox("Bed leveling")
        _ll = QVBoxLayout(level_group); _ll.setContentsMargins(14, 16, 14, 12); _ll.setSpacing(8)
        _ll.addWidget(self.level_chk)
        _ll.addWidget(_row(self.level_nx_spin, self.level_ny_spin,
                           self.level_grid_btn, self.level_export_btn,
                           self.level_save_btn, self.level_load_btn,
                           self.level_clear_btn))
        # the serial port selector lives in the machine dock (shared with the
        # DRO connect); probing reads it from there
        _ll.addWidget(_row(self.level_probe_btn, self.level_retouch_spin,
                           self.level_check_btn,
                           self.level_gridshow_chk, self.level_show_chk,
                           self.level_3d_btn, stretch_first=False))
        _ll.addWidget(self.level_table)
        _ll.addWidget(_row(self.level_top_btn))
        l_level.addWidget(self._pro(level_group))
        l_level.addStretch(1)

        # ===== DOUBLE-SIDED =====
        ds_group = QGroupBox("Double-sided")
        _dl = QVBoxLayout(ds_group); _dl.setContentsMargins(14, 16, 14, 12); _dl.setSpacing(8)
        _dl.addWidget(self.double_sided_chk)
        self._ds_controls = QWidget()
        _dsf = QFormLayout(self._ds_controls)
        _dsf.setContentsMargins(0, 6, 0, 0); _dsf.setSpacing(8)
        _dsf.setLabelAlignment(Qt.AlignRight)
        _dsf.addRow("View", self.view_combo)
        _dsf.addRow("Method", self.regmethod_combo)
        _dsf.addRow("Reg.", self.reg_combo)
        _dsf.addRow("Dowels", self.place_combo)
        _dsf.addRow("Grid", self._grid_row)
        _dsf.addRow("Fresh", self._fresh_row)
        _dsf.addRow("Fiducial", self._fid_row)
        self._dsf = _dsf                         # kept so rows can be shown/hidden
        self._ds_controls.setVisible(False)
        _dl.addWidget(self._ds_controls)
        l_double.addWidget(self._pro(ds_group))
        l_double.addStretch(1)

        # ===== REWORK =====
        rework_group = QGroupBox("Rework (2nd pass)")
        _rl = QVBoxLayout(rework_group); _rl.setContentsMargins(14, 16, 14, 12); _rl.setSpacing(8)
        _rl.addWidget(_row(self.select_chk, self.clear_sel_btn, stretch_first=True))
        _rl.addWidget(_row(QLabel("New-box depth"), self.rework_depth_spin,
                           stretch_first=True))
        _rl.addWidget(self.rework_level_chk)
        _rl.addWidget(_row(QLabel("Photo"), self.photo_anchor_btn,
                           self.photo_load_btn, self.photo_phone_btn,
                           self.photo_alpha_slider, self.photo_clear_btn,
                           stretch_first=True))
        _rl.addWidget(_row(QLabel("Traces"), self.trace_dim_slider,
                           self.detect_rework_btn, stretch_first=True))
        _rl.addWidget(self.rework_table)
        _rl.addWidget(_row(self.export_sel_btn, self.probe_boxes_btn,
                           stretch_first=True))
        l_rework.addWidget(self._pro(rework_group))
        l_rework.addStretch(1)

        # ===== 3D VIEWER (a hub to re-open the windowed 3D views) =====
        view3d_group = QGroupBox("3D views")
        _v3 = QVBoxLayout(view3d_group); _v3.setContentsMargins(14, 16, 14, 12); _v3.setSpacing(8)
        self.view3d_sim_btn = QPushButton("Simulate 3D (toolpaths)")
        self.view3d_sim_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.view3d_sim_btn.setToolTip("Open the 3D toolpath simulation for the current job (needs a loaded board).")
        self.view3d_sim_btn.clicked.connect(self._on_simulate_3d)
        self.view3d_file_btn = QPushButton("Open && simulate file...")
        self.view3d_file_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self.view3d_file_btn.setToolTip("Pick an exported .nc/.rml and simulate it in 3D.")
        self.view3d_file_btn.clicked.connect(self._on_simulate_file)
        self.view3d_bed_btn = QPushButton("3D bed / height-map view")
        self.view3d_bed_btn.setToolTip("Open the probed surface as a 3D mesh (needs a probed or loaded height map).")
        self.view3d_bed_btn.clicked.connect(self._on_bed_3d)
        _v3.addWidget(self.view3d_sim_btn)
        _v3.addWidget(self.view3d_file_btn)
        _v3.addWidget(self.view3d_bed_btn)
        l_3dview.addWidget(view3d_group)
        l_3dview.addStretch(1)

        self._settings_container = QWidget()
        sc_layout = QHBoxLayout(self._settings_container)
        sc_layout.setContentsMargins(0, 0, 0, 0)
        sc_layout.setSpacing(0)
        sc_layout.addWidget(self.sidebar)
        sc_layout.addWidget(self.stacked_widget)
        # The panel is sized to the current page's field content by
        # _autofit_panel (on show + each page switch) so fields are never pushed
        # off-screen
        # behind a horizontal scrollbar.

        self.preview = PreviewCanvas()
        self.preview.on_region_added = self._on_region_added
        self.preview.on_move_delta = self._on_move_delta
        self.preview.on_jog_to = self._on_jog_to
        self.preview.on_align_pick = self._on_align_pick
        self.preview.on_pin_moved = self._on_fid_pin_moved
        self.preview.on_jog_step = self._on_jog_step
        # The panel collapse toggle lives on the viewer's control bar.
        self.preview.on_toggle_panel = self._on_toggle_panel
        self.panel_toggle = self.preview.panel_btn   # alias for autofit/state checks

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._settings_container)
        splitter.addWidget(self.preview)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setCollapsible(0, True)      # panel may be hidden by the toggle
        splitter.setCollapsible(1, False)     # preview can never collapse
        self._splitter = splitter             # _size_settings_panel sets its sizes

        # Machine dock (GUI 2.0 phase 2): everything about the physical machine
        # in one persistent strip at the BOTTOM, visible from every page —
        # connect + port, live DRO, probe, jog, align overlay, run tracking,
        # STOP. The machine doesn't stop existing when you switch pages.
        machine_bar = QWidget()
        machine_bar.setObjectName("machineBar")
        _mb = QHBoxLayout(machine_bar)
        _mb.setContentsMargins(8, 2, 8, 2)
        # Guide stays for everyone — it is how a first-timer gets going.
        # Everything else on this strip drives the mill over the serial link;
        # a Novice sends the exported files from VPanel and never touches it,
        # so the whole row of machine controls goes away with the mode.
        _mb.addWidget(self.guide_btn)
        _mb.addWidget(self._pro(self.dro_label))
        _mb.addWidget(self._pro(self.touch_label))
        _mb.addStretch(1)
        _mb.addWidget(self._pro(self.trail_chk))
        _mb.addWidget(self._pro(self.trail_clear_btn))
        _mb.addWidget(self._pro(self.zero_btn))
        _mb.addWidget(self._pro(self.machine_zero_btn))
        _mb.addWidget(self._pro(self.stream_btn))
        _mb.addWidget(self._pro(self.align_btn))
        _mb.addWidget(self._pro(self.jog_chk))
        _mb.addWidget(self._pro(QLabel("port")))
        _mb.addWidget(self._pro(self.level_port_combo))
        _mb.addWidget(self._pro(self.connect_btn))
        _mb.addWidget(self._pro(self.stop_btn))

        # Run-progress row: the dock's second line.
        progress_bar_row = QWidget()
        progress_bar_row.setObjectName("progressBar")
        _pb = QHBoxLayout(progress_bar_row)
        _pb.setContentsMargins(8, 2, 8, 2)
        _pb.addWidget(QLabel("Run:"))
        _pb.addWidget(self.run_op_combo)
        _pb.addWidget(self.run_rework_chk)
        _pb.addWidget(self.run_auto_chk)
        _pb.addWidget(self.run_track_btn)
        _pb.addWidget(self.run_bar, 1)
        _pb.addWidget(self.run_eta_lbl)

        central = QWidget()
        _cv = QVBoxLayout(central)
        _cv.setContentsMargins(0, 0, 0, 0)
        _cv.setSpacing(0)
        _cv.addWidget(splitter, 1)
        _cv.addWidget(machine_bar)
        _cv.addWidget(self._pro(progress_bar_row))
        self.setCentralWidget(central)
        self.statusBar().showMessage("Ready", 5000)

        # open with the first preset applied (FR-4 conservative) so the form
        # values match the selected preset in the dropdown
        self.apply_selected_preset()
        self.sidebar.currentRowChanged.connect(self._autofit_panel)
        self._build_mode_menu()
        self._build_kicad_menu()
        self._apply_mode()               # Novice on a fresh install
        self._autofit_panel()
        self.move_chk.setChecked(True)   # move-on-bed drag on by default

        # First-launch guided walkthrough (replayable via the Guide button).
        self.tour = TourController(self)
        self.guide_btn.clicked.connect(lambda: self.tour.start())
        self.guide_double_btn.clicked.connect(lambda: self.tour.start_branch("Double-sided"))
        self.guide_level_btn.clicked.connect(lambda: self.tour.start_branch("Bed leveling"))
        self.guide_rework_btn.clicked.connect(lambda: self.tour.start_branch("Rework"))
        self._build_help_menu()          # after the tour: it links to it

    _MIN_PREVIEW = 380          # px of preview to keep when a page is very wide

    def _autofit_panel(self, *_):
        """Size the settings panel to fit the CURRENT page's field content, so its
        fields are never pushed off-screen behind a horizontal scrollbar — and
        narrow pages give the preview more room. Pages differ a lot (the
        Bed-Leveling probe table is far wider than the others), so a single fixed
        width can't serve them; this re-fits on every page switch. Width is read
        from the live (styled) size hints, so it adapts to the stylesheet/DPI. A
        page wider than the window keeps ``_MIN_PREVIEW`` px for the preview and
        scrolls the remainder."""
        if not hasattr(self, "_splitter"):      # called early during __init__
            return
        if self.panel_toggle.isChecked():       # panel collapsed -> nothing to size
            return
        inner = self.stacked_widget.currentWidget().widget()
        gutter = self.style().pixelMetric(QStyle.PM_ScrollBarExtent) + 8
        need = self.sidebar.minimumWidth() + inner.sizeHint().width() + gutter
        total = self._splitter.width() or self.width() or 1400
        panel_w = max(360, min(need, total - self._MIN_PREVIEW))
        self._settings_container.setMinimumWidth(min(need, panel_w))
        self._splitter.setSizes([panel_w, max(self._MIN_PREVIEW, total - panel_w)])

    def showEvent(self, event):
        # Re-fit once real geometry exists (splitter width is 0 before first show).
        super().showEvent(event)
        self._autofit_panel()

    def _sync_state(self):
        self.state.name = self.name_edit.text() or "board"
        self.state.machine = self.machine_combo.currentText()
        self.state.mirror = self.mirror_chk.isChecked()
        self.state.trace = self.forms["traces"].value()
        self.state.drill = self.forms["drill"].value()
        self.state.cutout = self.forms["cutout"].value()
        self.state.set_placement(self.place_x_spin.value(), self.place_y_spin.value())

    def _on_mirror_toggled(self):
        if self.state.gerber_dir is not None:
            try:
                self.load_folder(self.state.gerber_dir)
                self.generate_preview()
            except Exception as e:
                QMessageBox.critical(self, "Reload failed", str(e))

    def load_folder(self, folder):
        self._sync_state()
        self.state.load(folder)
        self.preview._view_limits = None        # new board -> fit (clear any zoom)
        self._top_fit = None                    # placement is per-physical-board
        # (a setup restore re-applies its saved fit after this call)
        self._photo_overlay = None              # photo is of one physical setup
        self._on_clear_photo_anchors()          # anchors are that board's holes
        self.preview.set_photo(None)
        self.trace_dim_slider.setValue(100)     # un-dim: no photo to see through
        if self._rework_regions:                # boxes belong to that board too
            self._rework_regions = []
            self._refresh_rework()
        # any successful load clears the DEMO badge — this covers Load setup /
        # session restore too, not just the Load Gerber folder button. The
        # launch-time preload re-sets the badge right after this call.
        self.preview.set_demo(False)

    def _dowel_spec(self):
        """Build a DowelSpec from the registration controls."""
        from gerber2rml.doublesided import DowelSpec, CLEAR_LARGE, CLEAR_SMALL
        mode = "grid" if self.reg_combo.currentIndex() == 1 else "fresh"

        def _f(edit, default):
            try:
                return float(edit.text())
            except ValueError:
                return default
        pitch = _f(self.grid_pitch_edit, 14.2)
        placement = "leftright" if self.place_combo.currentIndex() == 1 else "topbottom"
        return DowelSpec(mode=mode, placement=placement, pitch_x=pitch, pitch_y=pitch,
                         grid_pin=_f(self.grid_pin_edit, 4.0),
                         clearance_large=_f(self.fresh_clear_large_edit, CLEAR_LARGE),
                         clearance_small=_f(self.fresh_clear_small_edit, CLEAR_SMALL))

    def _double_sided_layout(self):
        """Design-frame layout for the PREVIEW (both layers registered, holes on
        pads, top plain). The export uses the machine-frame layout separately.
        Cached by folder + registration choice so live edits don't re-read disk."""
        from gerber2rml.doublesided import preview_layout_double_sided
        reg = self._registration_mode()
        spec = self._dowel_spec()
        fid = self._fiducial_spec_from_ui()
        off = (self.state.place_x, self.state.place_y)
        key = (str(self.state.gerber_dir), reg, spec.mode, spec.placement,
               spec.pitch_x, spec.grid_pin, spec.clearance_large, spec.clearance_small,
               fid.count, fid.placement, fid.edge_offset, fid.points,
               fid.flip_axis, off, self.state.rotate)
        if self._ds_cache is None or self._ds_cache[0] != key:
            self._ds_cache = (key, preview_layout_double_sided(
                self.state.gerber_dir, dowels=spec, offset=off,
                rotate=self.state.rotate, registration=reg, fiducials=fid))
        return self._ds_cache[1]

    def _machine_layout(self):
        """Machine-frame layout — the board exactly as each side is cut (bottom
        mirrored, top reflected). Single-side preview and rework use this so an
        on-screen box maps to the real toolpath coordinates, not the design-frame
        X-ray used by the 'Both sides' registration view."""
        from gerber2rml.doublesided import layout_double_sided
        reg = self._registration_mode()
        spec = self._dowel_spec()
        fid = self._fiducial_spec_from_ui()
        off = (self.state.place_x, self.state.place_y)
        key = (str(self.state.gerber_dir), reg, spec.mode, spec.placement,
               spec.pitch_x, spec.grid_pin, spec.clearance_large, spec.clearance_small,
               fid.count, fid.placement, fid.edge_offset, fid.points,
               fid.flip_axis, off, self.state.rotate)
        if self._ds_mcache is None or self._ds_mcache[0] != key:
            self._ds_mcache = (key, layout_double_sided(
                self.state.gerber_dir, dowels=spec, offset=off,
                rotate=self.state.rotate, registration=reg, fiducials=fid))
        return self._ds_mcache[1]

    def _ds_side(self):
        """For a double-sided board, the single side selected in View ('Bottom'
        or 'Top'), or None for 'Both sides' / single-sided boards. Rework needs a
        single side because each side is a separate job in its own frame."""
        if not self.double_sided_chk.isChecked():
            return None
        v = self.view_combo.currentText()
        return v if v in ("Bottom", "Top") else None

    def _ds_side_toolpaths(self, op, side):
        """Machine-frame toolpaths for one side of a double-sided board — exactly
        what that side's exported job cuts, so a rework box clips against the real
        paths and the result runs in the same frame as the full job. The Top side
        is warped by the measured fiducial fit when one exists, matching the
        as-placed export — so top-side rework and run tracking follow the board's
        REAL position, not the nominal flip."""
        from gerber2rml.engine.traces import isolate
        from gerber2rml.engine.cutout import cut_outline
        mlay = self._machine_layout()
        if op == "cutout":
            return cut_outline(mlay.outline, self.state.cutout)
        if side == "Top":
            return self._top_fit_paths(
                isolate(mlay.top_copper, self.state.trace, outline=mlay.top_outline))
        return isolate(mlay.bottom_copper, self.state.trace, outline=mlay.outline)

    # ---- Novice / Professional mode ---------------------------------------
    def _pro(self, widget, form=None):
        """Tag ``widget`` as Professional-only and hand it straight back, so it
        can be wrapped inline at the point it is laid out.

        Pass ``form`` when the widget is a field in a QFormLayout row that has
        a label — hiding the field on its own would strand the label next to
        empty space.
        """
        # The marker is what the tour reads to tell "hidden because Novice"
        # apart from "on a stacked page that isn't showing right now" — Qt
        # hides the latter explicitly too, so plain visibility can't separate
        # them (see TourController._is_put_away).
        widget.setProperty("proOnly", True)
        self._pro_items.append((widget, form))
        return widget

    def _build_mode_menu(self):
        """The Mode menu. Deliberately a plain menu item, not a password: this
        manages how much UI a beginner faces, it does not defend anything."""
        from PySide6.QtGui import QAction, QActionGroup
        menu = self.menuBar().addMenu("&Mode")
        group = QActionGroup(self)
        group.setExclusive(True)

        self.act_novice = QAction("&Novice", self, checkable=True)
        self.act_novice.setToolTip(
            "Load Gerbers, pick a profile, export the three files. Everything "
            "else is put away.")
        self.act_pro = QAction("&Professional", self, checkable=True)
        self.act_pro.setToolTip(
            "Every control: job parameters, double-sided, bed leveling, "
            "rework, machine link.")
        for act, m in ((self.act_novice, uimode.NOVICE), (self.act_pro, uimode.PRO)):
            group.addAction(act)
            menu.addAction(act)
            act.triggered.connect(lambda _checked=False, m=m: self._on_mode_chosen(m))

        menu.addSeparator()
        self.act_whats_hidden = QAction("What's hidden in Novice?", self)
        self.act_whats_hidden.triggered.connect(self._show_mode_help)
        menu.addAction(self.act_whats_hidden)

        if uimode.forced_mode():
            # SRM_CAM_MODE pins the mode for this machine — show which one is
            # active but don't pretend it can be changed from here.
            for act in (self.act_novice, self.act_pro):
                act.setEnabled(False)
            menu.setTitle("&Mode (locked)")

    # ---- the KiCad build-area plugin -------------------------------------
    #
    # A board that does not fit the SRM-20 is normally discovered at the
    # machine, with the layout finished. KiCad has no idea what an SRM-20 is,
    # so we ship a small plugin that draws the build area in the PCB editor —
    # and install it from here, because the path it goes to depends on the OS
    # and the KiCad version, which is not a thing to talk a first-semester
    # student through.

    _KICAD_DECLINED_KEY = "kicad/declined_plugin_version"

    def _app_settings(self):
        from PySide6.QtCore import QSettings
        return QSettings("SRM-CAM", "SRM-CAM")

    def _kicad_plugin_dirs(self):
        from gerber2rml.engine import kicadplugin
        dirs = []
        for root in kicadplugin.config_roots():
            dirs.extend(kicadplugin.plugin_dirs(root))
        return dirs

    def _build_help_menu(self):
        """A Help menu whose first item is the guide itself.

        The step-by-step guide is what turns "I have Gerbers" into "I have a
        board". A student who has to go and find the URL will not.
        """
        from PySide6.QtGui import QAction, QKeySequence
        menu = self.menuBar().addMenu("&Help")
        guide = QAction("SRM-CAM &user guide (web)...", self)
        guide.setShortcut(QKeySequence.HelpContents)          # F1
        guide.setToolTip(USER_GUIDE_URL)
        guide.triggered.connect(self._on_open_user_guide)
        menu.addAction(guide)
        menu.addSeparator()
        tour = QAction("Replay the guided tour", self)
        tour.triggered.connect(lambda: self.tour.start())
        menu.addAction(tour)
        menu.addSeparator()
        upd = QAction("Check for &updates...", self)
        upd.setToolTip("See whether a newer SRM-CAM has been released.")
        upd.triggered.connect(self._on_check_updates)
        menu.addAction(upd)

    _UPDATE_DISMISSED_KEY = "updates/dismissed_version"

    def start_update_check(self):
        """Quiet background check at launch.

        In a thread, because a lab PC behind a captive portal can take the
        full timeout to fail and the window must not wait for it. Never
        speaks unless there is genuinely a newer release.
        """
        try:
            self._update_probe = _UpdateProbe(__version__, self)
            self._update_probe.checked.connect(self._on_update_checked)
            self._update_probe.start()
        except Exception:
            pass                     # a background nicety, never a blocker

    def _on_update_checked(self, result):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        from gerber2rml.engine import updates

        settings = self._app_settings()
        seen = settings.value(self._UPDATE_DISMISSED_KEY) or None
        if not updates.should_announce(result, seen):
            return

        if self.tour.active:
            # first launch already opens the tour; a dialog on top of it is the
            # worst possible first five seconds. Say it quietly, ask next time.
            self.statusBar().showMessage(
                f"{result.message}  (Help -> Check for updates)", 15000)
            return

        settings.setValue(self._UPDATE_DISMISSED_KEY, result.latest)
        ans = QMessageBox.question(
            self, "Update available",
            result.message + "\n\nOpen the download page?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if ans == QMessageBox.Yes:
            QDesktopServices.openUrl(QUrl(result.url))

    def _on_check_updates(self):
        """Ask GitHub whether a newer release exists, and offer the download.

        Not a self-updater: a frozen app cannot safely overwrite itself while
        running, and a lab PC's install is often not the student's to replace.
        This finds out and points at the download; the install is their click.
        """
        from PySide6.QtCore import Qt, QUrl
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtWidgets import QApplication
        from gerber2rml import __version__
        from gerber2rml.engine import updates

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            result = updates.check(__version__)
        finally:
            QApplication.restoreOverrideCursor()

        if result.status != updates.UPDATE:
            # up to date, or we could not find out — both are just information
            QMessageBox.information(self, "Check for updates", result.message)
            return

        notes = result.notes.strip()
        if len(notes) > 600:
            notes = notes[:600].rstrip() + "…"
        body = result.message + (f"\n\nWhat's new:\n{notes}" if notes else "")
        ans = QMessageBox.question(
            self, "Update available",
            body + "\n\nOpen the download page?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if ans == QMessageBox.Yes:
            QDesktopServices.openUrl(QUrl(result.url))

    def _on_open_user_guide(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        if not QDesktopServices.openUrl(QUrl(USER_GUIDE_URL)):
            QMessageBox.information(
                self, "User guide",
                "Could not open a browser. The guide is at:\n\n"
                + USER_GUIDE_URL)

    def _build_kicad_menu(self):
        from PySide6.QtGui import QAction
        menu = self.menuBar().addMenu("&KiCad")
        act = QAction("Set up the build-area plugin...", self)
        act.setToolTip("Add a button to KiCad's PCB editor that draws the "
                       "SRM-20's build area and says whether your board fits.")
        act.triggered.connect(self._on_setup_kicad_plugin)
        menu.addAction(act)

    def maybe_offer_kicad_plugin(self):
        """Launch-time offer, asked once per plugin version.

        Best-effort throughout: a machine with no KiCad, an unreadable config
        folder or a locked-down profile must not stop the app from starting.
        """
        from gerber2rml.engine import kicadplugin
        try:
            bundled = kicadplugin.bundled_version()
            dirs = self._kicad_plugin_dirs()
            declined = self._app_settings().value(self._KICAD_DECLINED_KEY) or None
            if not kicadplugin.should_offer(dirs, bundled, declined):
                return
        except Exception:
            return

        ans = QMessageBox.question(
            self, "KiCad plugin",
            "KiCad is installed on this PC. Would you like to add the SRM-20 "
            "build-area button to its PCB editor?\n\n"
            "It draws the mill's build area on User.Drawings and tells you "
            "whether your board fits — while there is still time to change it, "
            "rather than at the machine.\n\n"
            "You can do this later from the KiCad menu.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if ans != QMessageBox.Yes:
            self._app_settings().setValue(self._KICAD_DECLINED_KEY, bundled)
            return
        self._on_setup_kicad_plugin()

    def _on_setup_kicad_plugin(self):
        """Install the plugin into every KiCad version found on this machine.

        Every version rather than the newest: a PC that has been upgraded keeps
        both trees, and the student opens whichever shortcut is on the desktop.
        """
        from gerber2rml.engine import kicadplugin
        dirs = self._kicad_plugin_dirs()
        if not dirs:
            roots = ", ".join(str(r) for r in kicadplugin.config_roots())
            QMessageBox.information(
                self, "KiCad not found",
                "No KiCad installation was found on this PC.\n\n"
                f"Looked in: {roots}\n\n"
                "Install KiCad first, then run this again. SRM-CAM itself "
                "does not need KiCad — it only reads the Gerbers KiCad "
                "exports.")
            return

        done, failed = [], []
        for d in dirs:
            try:
                done.append(kicadplugin.install(kicadplugin.bundled_source(), d))
            except Exception as e:                       # permissions, mostly
                failed.append(f"{d}\n    {e}")

        if not done:
            QMessageBox.critical(
                self, "Could not install",
                "The plugin could not be copied into KiCad:\n\n"
                + "\n".join(failed))
            return

        where = "\n".join(f"    {p}" for p in done)
        note = ("\n\nSome locations failed:\n" + "\n".join(failed)) if failed else ""
        QMessageBox.information(
            self, "KiCad plugin installed",
            "Installed to:\n" + where +
            "\n\nRestart KiCad, then find it in the PCB editor under "
            "Tools -> External Plugins -> Show SRM-20 build area." + note)
        # they have it now; a future version asks again on its own merits
        self._app_settings().remove(self._KICAD_DECLINED_KEY)

    def _on_mode_chosen(self, mode):
        uimode.set_mode(mode)
        self._apply_mode()

    def _show_mode_help(self):
        """List what Novice puts away. A beginner should never have to wonder
        whether the thing they half-remember is gone or just tucked out of the
        way, and a teacher should be able to answer that without a manual."""
        hidden = "".join(f"\u2022  {line}\n" for line in uimode.HIDDEN_IN_NOVICE)
        QMessageBox.information(
            self, "Novice mode",
            "Novice mode shows the shortest path from Gerbers to three files "
            "you can send from VPanel:\n\n"
            "    load  ->  drill  ->  traces  ->  cut out  ->  export\n\n"
            "It puts these away:\n\n"
            + hidden +
            "\nNothing is removed and nothing behaves differently - the same "
            "settings export the same files in either mode. Switch to "
            "Professional from this menu whenever you need the rest.")

    def _apply_mode(self):
        """Show or hide everything the current mode governs.

        Called once at startup and again on every switch. Idempotent: it sets
        state from the mode rather than toggling, so it can be re-run freely.
        """
        pro = uimode.is_pro()

        for widget, form in self._pro_items:
            if form is not None:
                try:
                    form.setRowVisible(widget, pro)      # Qt 6.4+
                except (AttributeError, TypeError):
                    widget.setVisible(pro)               # older Qt: field only
            else:
                widget.setVisible(pro)

        for row in range(self.sidebar.count()):
            hidden = (not pro) and row in self._PRO_STEPS
            self.sidebar.setRowHidden(row, hidden)
            label = (self._SPINE[row][0] if pro
                     else self._NOVICE_LABELS.get(row, self._SPINE[row][0]))
            self.sidebar.item(row).setText(label)

        if not pro:
            # A double-sided job needs the flip and align steps to be run
            # safely, and Novice does not have them. Leaving the checkbox on
            # would export a job whose second half has no UI behind it.
            if self.double_sided_chk.isChecked():
                self.double_sided_chk.setChecked(False)
                self.statusBar().showMessage(
                    "Novice mode is single-sided — double-sided turned off. "
                    "Switch to Professional to mill both sides.", 10000)
            # Never leave someone parked on a step they can no longer see.
            if self.sidebar.currentRow() in self._PRO_STEPS:
                self.sidebar.setCurrentRow(0)

        act = self.act_pro if pro else self.act_novice
        act.setChecked(True)
        self._autofit_panel()

    def _on_toggle_panel(self, collapsed):
        """Hide the settings panel for a full-width preview, or restore it.
        Triggered by the viewer's panel button (which manages its own label)."""
        self._settings_container.setVisible(not collapsed)
        if not collapsed:
            self._autofit_panel()        # restore at the current page's fit width

    def _set_ds_row(self, widget, vis):
        """Show/hide a Double-Sided form row (label + field), tolerant of Qt
        versions without QFormLayout.setRowVisible."""
        try:
            self._dsf.setRowVisible(widget, vis)
        except (AttributeError, TypeError):
            widget.setVisible(vis)

    def _registration_mode(self):
        """'fiducial' if the Method combo selects fiducial holes, else 'dowel'."""
        return "fiducial" if self.regmethod_combo.currentIndex() == 1 else "dowel"

    def _select_registration(self, mode):
        """Set the registration method programmatically ('dowel'|'fiducial')."""
        self.regmethod_combo.setCurrentIndex(1 if mode == "fiducial" else 0)
        self._update_ds_controls()

    def _on_spine_changed(self, row):
        """A runplan step was clicked: route to its page and pre-select the op
        tab / double-sided side it works in. Pure navigation — never blocks."""
        if not (0 <= row < len(self._SPINE)):
            return
        _label, page, op_idx, ds_view = self._SPINE[row]
        self.stacked_widget.setCurrentIndex(page)
        if op_idx is not None:
            self.tabs.setCurrentIndex(op_idx)
        if ds_view is not None and self.double_sided_chk.isChecked():
            self.view_combo.setCurrentText(ds_view)

    def _goto_page(self, page):
        """Select the first spine step that lives on stacked ``page`` (tour +
        programmatic navigation; rows no longer equal page indexes)."""
        for row, (_l, p, _o, _v) in enumerate(self._SPINE):
            if p == page:
                self.sidebar.setCurrentRow(row)
                return
        self.stacked_widget.setCurrentIndex(page)

    def _travel_check(self, toolpaths):
        """Compare toolpath XY extents against the machine bed. Returns None
        when everything is reachable, else a human suggestion of how far to
        slide the board (the 2026-07-03 lesson: a crooked fiducial flip can
        push a job partly outside the machine's travel while every fiducial
        still measures fine)."""
        bed = BACKENDS[self.state.machine].bed
        if not bed or not toolpaths:
            return None
        xs = [m.x for tp in toolpaths for m in tp]
        ys = [m.y for tp in toolpaths for m in tp]
        over = []
        if min(xs) < 0:
            over.append(f"slide the board {abs(min(xs)):.1f} mm RIGHT")
        if max(xs) > bed[0]:
            over.append(f"slide the board {max(xs) - bed[0]:.1f} mm LEFT")
        if min(ys) < 0:
            over.append(f"slide the board {abs(min(ys)):.1f} mm BACK")
        if max(ys) > bed[1]:
            over.append(f"slide the board {max(ys) - bed[1]:.1f} mm FORWARD")
        if not over:
            return None
        return (f"Job spans X {min(xs):.1f}..{max(xs):.1f}, "
                f"Y {min(ys):.1f}..{max(ys):.1f} mm but the bed is "
                f"{bed[0]:.1f} x {bed[1]:.1f} mm - " + " and ".join(over)
                + ", then re-capture the fiducials and re-probe.")

    # ---- GUI 2.0 phase 3: single frame resolver ---------------------------
    def _resolve_frame(self):
        """The ONE place that decides what frame the canvas shows.

        Returns ``(mode, side)``: mode is ``"bed"`` (machine coordinates, as
        cut/as placed — where jog, snap, rework and the probe grid are
        truthful) or ``"xray"`` (un-mirrored design inspection); ``side`` is
        ``"Bottom"``/``"Top"`` for double-sided bed views, else ``None``.

        Phase-3 seam: initially derived from the legacy controls
        (double_sided_chk + view_combo), so behaviour is unchanged while the
        branch points migrate onto this. The frame_switch control replaces
        the derivation in a later step.
        """
        if not self.double_sided_chk.isChecked():
            return ("bed", None)
        side = self._ds_side()
        return ("bed", side) if side is not None else ("xray", None)

    _FID_PLACEMENTS = ("onboard", "waste", "manual")

    def _fiducial_spec_from_ui(self):
        from gerber2rml.doublesided import FiducialSpec
        placement = self._FID_PLACEMENTS[self.fid_place_combo.currentIndex()]
        return FiducialSpec(
            count=self.fid_count_spin.value(),
            placement=placement,
            edge_offset=self.fid_offset_spin.value(),
            allow_scale=self.fid_scale_chk.isChecked(),
            flip_axis=("horizontal" if self.fid_flip_combo.currentIndex() == 1
                       else "vertical"),
            points=(tuple(tuple(p) for p in self._fid_points)
                    if placement == "manual" else ()))

    def _seed_fid_points(self):
        """Start manual fiducials where the corner placement would put them:
        compute a waste-corner layout and convert its pins to board-relative
        coordinates. Called when Manual is selected with no (or a mismatched
        number of) stored points."""
        from gerber2rml.doublesided import preview_layout_double_sided, FiducialSpec
        if self.state.board is None or self.state.gerber_dir is None:
            return
        spec = FiducialSpec(count=self.fid_count_spin.value(), placement="waste",
                            edge_offset=self.fid_offset_spin.value())
        lay = preview_layout_double_sided(
            self.state.gerber_dir, dowels=self._dowel_spec(),
            offset=(self.state.place_x, self.state.place_y),
            rotate=self.state.rotate, registration="fiducial", fiducials=spec)
        fx0, fy0 = lay.frame0
        self._fid_points = [[x - fx0, y - fy0] for (x, y, _d) in lay.align_holes]

    def _on_fid_pin_moved(self, index, x, y):
        """A gold pin was dragged on the preview (manual fiducial mode): store
        its new board-relative position and rebuild the preview so the layouts
        (and the export) pick it up."""
        if (self._FID_PLACEMENTS[self.fid_place_combo.currentIndex()] != "manual"
                or index >= len(self._fid_points)):
            return
        lay = self._double_sided_layout()
        fx0, fy0 = lay.frame0
        self._fid_points[index] = [x - fx0, y - fy0]
        self.generate_preview()
        px, py = self._fid_points[index]
        self.statusBar().showMessage(
            f"Fiducial {index + 1} -> ({px:+.2f}, {py:+.2f}) mm from the board's "
            "lower-left corner", 8000)

    def _update_ds_controls(self):
        """Reveal the registration controls only when double-sided is on, show the
        dowel rows or the fiducial row per the Method, and enable the grid/fresh
        fields only for the matching dowel sub-mode."""
        ds = self.double_sided_chk.isChecked()
        self._ds_controls.setVisible(ds)            # hide the sub-controls until on
        fiducial = self._registration_mode() == "fiducial"
        for w in (self.view_combo, self.regmethod_combo):
            w.setEnabled(ds)                        # were disabled at init; enable with DS
        for w in (self.reg_combo, self.place_combo):
            w.setEnabled(ds and not fiducial)
        is_grid = self.reg_combo.currentIndex() == 1
        self._grid_row.setEnabled(ds and not fiducial and is_grid)
        self._fresh_row.setEnabled(ds and not fiducial and not is_grid)
        self._fid_row.setEnabled(ds and fiducial)
        # dowel rows only in dowel mode; the fiducial row only in fiducial mode
        for w in (self.reg_combo, self.place_combo, self._grid_row, self._fresh_row):
            self._set_ds_row(w, not fiducial)
        self._set_ds_row(self._fid_row, fiducial)

    def _on_double_sided_toggled(self, checked):
        self._update_ds_controls()
        self.level_top_btn.setEnabled(checked)   # top-side leveling is DS-only
        self._autofit_panel()                    # the revealed controls widen the page
        self.generate_preview()

    def _on_reg_changed(self, *_):
        self._update_ds_controls()
        self._autofit_panel()                    # dowel/grid/fresh/fiducial rows differ in width
        manual = self.fid_place_combo.currentIndex() == 2
        self.fid_offset_spin.setEnabled(not manual)   # offset is corner-mode only
        if (manual and self._registration_mode() == "fiducial"
                and self.double_sided_chk.isChecked()
                and len(self._fid_points) != self.fid_count_spin.value()):
            self._seed_fid_points()              # start from the corner positions
            self.statusBar().showMessage(
                "Manual fiducials: drag the gold pins on the preview to place "
                "them (anywhere with stock under them).", 10000)
        if self.double_sided_chk.isChecked():
            self.generate_preview()

    @staticmethod
    def _poly_xy(poly):
        """Exterior (x, y) vertices of a shapely polygon (largest part of a
        MultiPolygon), or None."""
        if poly is None or poly.is_empty:
            return None
        if poly.geom_type == "MultiPolygon":
            poly = max(poly.geoms, key=lambda p: p.area)
        return list(poly.exterior.coords)[:-1] if poly.geom_type == "Polygon" else None

    def _snap_geometry(self):
        """Board outline vertices + hole centres for the ruler to snap to, in the
        current placed/rotated frame. (None, None) if no board is loaded."""
        b = self.state.board
        if b is None:
            return None, None
        return self._poly_xy(b.outline), b.holes

    # ---- measured top-side placement (fiducial fit) ------------------------
    def _top_fit_paths(self, paths):
        """Warp toolpaths by the measured top placement (identity when unset)."""
        if self._top_fit is None:
            return paths
        from gerber2rml.engine.fiducial import apply_to_toolpaths
        return apply_to_toolpaths(paths, self._top_fit)

    def _top_fit_holes(self, holes):
        if self._top_fit is None:
            return holes
        return [(*self._top_fit.apply(x, y), d) for (x, y, d) in holes]

    def _top_fit_geom(self, g):
        if self._top_fit is None or g is None:
            return g
        from shapely.affinity import affine_transform
        t = self._top_fit
        c, s = math.cos(t.theta), math.sin(t.theta)
        return affine_transform(g, [t.scale * c, -t.scale * s,
                                    t.scale * s, t.scale * c, t.tx, t.ty])

    def _preview_double_sided(self, op):
        """Show the registered board with the two dowel/alignment holes so the
        operator can check the flip registration and pin placement before
        milling. The View selector picks bottom (cyan), top (magenta), or both
        overlaid; the dowels are always shown. Board holes are shown on the
        drill tab only."""
        from gerber2rml.engine.traces import isolate
        mode, side = self._resolve_frame()
        self.preview.set_pin_drag(False)   # re-enabled by the X-ray branch below
        if mode == "bed" and op == "drill":
            # Machine-frame drill view: the holes exactly as they are cut on the
            # bed (bottom-up mirror), so click-to-jog lands ON a physical hole.
            # The X-ray drill view shows the un-mirrored design frame, where the
            # bottom holes are reflected about the flip axis — only the on-axis
            # dowels coincide, which reads as "the holes are mirrored".
            from gerber2rml.doublesided import reflect_holes
            mlay = self._machine_layout()
            if side == "Top":
                # after the flip the holes appear reflected into the top frame;
                # a measured fiducial fit then places them where the board
                # REALLY sits (AS PLACED), so jog-to-hole is physically true.
                # Pins reflect too — dowels sit ON the axis so it never showed,
                # but manual fiducials are asymmetric and MUST be reflected
                # before the fit or they render mirrored off the board.
                holes = self._top_fit_holes(
                    reflect_holes(mlay.holes, mlay.axis, mlay.flip_pos))
                outline = self._top_fit_geom(mlay.top_outline)
                copper = (self._top_fit_geom(mlay.top_copper), "#ff55ff")
                pins = self._top_fit_holes(
                    reflect_holes(mlay.align_holes, mlay.axis, mlay.flip_pos))
            else:
                holes = mlay.holes
                outline, copper = mlay.outline, (mlay.bottom_copper, "#00ffff")
                pins = mlay.align_holes
            cuts, rapids = toolpath_segments(self._drill_toolpaths(holes))
            self.preview.set_board_outline(self._poly_xy(outline))
            self.preview.show_segments(cuts, rapids, holes=holes,
                                       pins=pins, copper=[copper])
            return
        if mode == "bed" and op != "drill":
            # Single side: show it in the MACHINE frame (as actually cut) so a
            # rework box maps to real toolpath coordinates. Keep the channel
            # contract: Bottom -> bottom cuts, Top -> top cuts. The Top side is
            # additionally warped by the measured fiducial fit when one exists
            # (the toolpaths come pre-warped from _ds_side_toolpaths).
            mlay = self._machine_layout()
            cuts, rapids = toolpath_segments(self._ds_side_toolpaths(op, side))
            # The board's own drill holes ride along as reference data (not
            # drawn): 2 dowels are too few features to anchor a rework photo,
            # and this is the view rework is drawn on.
            if side == "Top":
                from gerber2rml.doublesided import reflect_holes
                self.preview.set_board_outline(
                    self._poly_xy(self._top_fit_geom(mlay.top_outline)))
                self.preview.show_segments(
                    [], [], top_cuts=cuts,
                    ref_holes=self._top_fit_holes(
                        reflect_holes(mlay.holes, mlay.axis, mlay.flip_pos)),
                    pins=self._top_fit_holes(
                        reflect_holes(mlay.align_holes, mlay.axis, mlay.flip_pos)),
                    copper=[(self._top_fit_geom(mlay.top_copper), "#ff55ff")])
            else:
                self.preview.set_board_outline(self._poly_xy(mlay.outline))
                self.preview.show_segments(cuts, rapids, ref_holes=mlay.holes,
                                           pins=mlay.align_holes,
                                           copper=[(mlay.bottom_copper, "#00ffff")])
            return
        # Both sides (or the drill tab): design-frame X-ray for registration.
        lay = self._double_sided_layout()
        self.preview.set_board_outline(self._poly_xy(lay.outline))
        view = self.view_combo.currentText()
        bottom_cuts, bottom_rapids, top_cuts = [], [], []
        copper = []
        if view in ("Both sides", "Bottom"):
            copper.append((lay.bottom_copper, "#00ffff"))
        if view in ("Both sides", "Top"):
            copper.append((lay.top_copper, "#ff55ff"))
        if op == "cutout":
            # The edge cut is one job around the outline (run from the bottom
            # side), not a per-layer isolation — show it instead of the traces.
            from gerber2rml.engine.cutout import cut_outline
            bottom_cuts, bottom_rapids = toolpath_segments(
                cut_outline(lay.outline, self.state.cutout))
        else:
            if view in ("Both sides", "Bottom"):
                bottom_cuts, bottom_rapids = toolpath_segments(
                    isolate(lay.bottom_copper, self.state.trace, outline=lay.outline))
            if view in ("Both sides", "Top"):
                top_cuts, _ = toolpath_segments(
                    isolate(lay.top_copper, self.state.trace, outline=lay.outline))
        holes = lay.holes if op == "drill" else None
        self.preview.show_segments(bottom_cuts, bottom_rapids, holes=holes,
                                   top_cuts=top_cuts, pins=lay.align_holes,
                                   copper=copper)
        # manual fiducials are dragged in THIS (design-frame) view only — the
        # single-side machine-frame views stay read-only
        self.preview.set_pin_drag(
            self._registration_mode() == "fiducial"
            and self.fid_place_combo.currentIndex() == 2)

    def _drill_status(self):
        """Human summary of the hole diameters and what export will produce,
        so the operator can see which bits are needed before exporting."""
        from gerber2rml.engine.drill import group_holes_by_diameter, format_diameter
        groups = group_holes_by_diameter(self.state.board.holes)
        if not groups:
            return "No drill holes found."
        summary = ", ".join(f"{format_diameter(d)}mm x{len(h)}" for d, h in groups)
        bit = self.state.drill.bit_diameter
        if self.state.drill.single_bit:
            n_int = sum(len(h) for d, h in groups if d > bit + 1e-3)
            n_small = sum(len(h) for d, h in groups if d < bit - 1e-3)
            msg = (f"Holes: {summary}  ->  1 file, {format_diameter(bit)}mm bit "
                   f"({n_int} interpolated)")
            if n_small:
                msg += f"  WARNING: {n_small} hole(s) smaller than the bit -> oversized"
            return msg
        return f"Holes: {summary}  ->  {len(groups)} drill files (one bit each)"

    def _apply_preview_frame(self):
        """Set the preview's orientation badge (and a view-only flip) so it's
        always obvious whether you're looking at the design or the mirrored
        as-milled cut. Never changes the exported geometry."""
        AMBER, GREEN = "#ffb000", "#33cc88"
        ds = self.double_sided_chk.isChecked()
        # Mirror + preview-frame are single-sided controls; in double-sided mode
        # the frame resolver owns the frame, so grey these out rather than let
        # them look like they do something.
        self.mirror_chk.setEnabled(not ds)
        mode, side = self._resolve_frame()
        if ds:
            self.frame_combo.setEnabled(False)
            if mode == "xray":
                self.preview.set_frame(
                    "AS DESIGNED  ·  X-ray, both layers register", GREEN)
            elif side == "Bottom":
                self.preview.set_frame("AS MILLED  ·  bottom (mirrored)", AMBER)
            elif self._top_fit is not None:
                self.preview.set_frame("AS PLACED  ·  top (fiducial fit)", GREEN)
            else:
                self.preview.set_frame("AS MILLED  ·  top (reflected)", AMBER)
            return
        mirror = self.mirror_chk.isChecked()
        self.frame_combo.setEnabled(mirror)   # only meaningful when mirroring
        if not mirror:
            self.preview.set_frame("AS DESIGNED  ·  top (no mirror)", GREEN)
        elif self.frame_combo.currentIndex() == 1:
            self.preview.set_frame("AS DESIGNED  ·  KiCad top view", GREEN,
                                   flip_x=True)
        else:
            self.preview.set_frame("AS MILLED  ·  mirrored (bottom-up)", AMBER)

    def generate_preview(self):
        if self.state.board is None:
            self.preview.set_estimate("")
            return
        self._sync_state()
        self._apply_preview_frame()
        self.preview.set_pin_drag(False)      # only the DS X-ray view re-enables it
        bed = BACKENDS[self.state.machine].bed if self.show_bed_chk.isChecked() else None
        self.preview.set_bed(bed)
        oxy, holes = self._snap_geometry()
        self.preview.set_snap_geometry(oxy, holes)
        self.preview.set_board_outline(oxy)        # draw the board edge (single-sided)
        t0 = time.time()
        op = _OPS[self.tabs.currentIndex()]
        gap_warning = False
        if self.double_sided_chk.isChecked():
            self._preview_double_sided(op)
            msg = (f"Double-sided preview (both sides + dowels) in {time.time() - t0:.2f}s"
                   if op != "drill" else self._drill_status())
            self.statusBar().showMessage(msg, 8000)
            side = self._ds_side()
            if op == "cutout":
                # the edge cut is the same single job whichever view is selected
                self.preview.set_estimate(self._est_text(
                    self._ds_side_toolpaths(op, side), self.state.cutout))
            elif op == "drill" and side is not None:
                self.preview.set_estimate(self._est_text(
                    self._drill_toolpaths(self._machine_layout().holes),
                    self.state.drill))
            elif side is not None and op != "drill":
                job = self.state.trace if op == "traces" else self.state.cutout
                self.preview.set_estimate(self._est_text(self._ds_side_toolpaths(op, side), job))
            else:
                self.preview.set_estimate("—")   # both-sides registration view
            return
        if op == "drill":
            cuts, rapids = toolpath_segments(self.state.toolpaths("traces"))
            self.preview.show_segments(cuts, rapids, holes=self.state.board.holes,
                                       copper=[(self.state.board.copper, "#00ffff")])
            drill_tps = self._drill_toolpaths(self.state.board.holes)
            est = self._estimate_str(drill_tps, self.state.drill)
            self.preview.set_estimate(self._est_text(drill_tps, self.state.drill))
            self.statusBar().showMessage(self._drill_status() + est, 8000)
            return
        tps = self.state.toolpaths(op)
        cuts, rapids = toolpath_segments(tps)
        # The drill holes ride along as reference data (not drawn): they are
        # the only photo-overlay anchors a single-sided board has, and rework
        # is registered from this view, not the drill one.
        self.preview.show_segments(cuts, rapids,
                                   ref_holes=self.state.board.holes)
        job = self.state.trace if op == "traces" else self.state.cutout
        est = self._estimate_str(tps, job)
        self.preview.set_estimate(self._est_text(tps, job))
        if op == "traces":
            from gerber2rml.analysis import find_narrow_gaps
            from gerber2rml.engine.drc import isolation_bridges
            gaps = find_narrow_gaps(self.state.board.copper,
                                    self.state.board.outline,
                                    self.state.trace.effective_diameter())
            # narrow slivers won't be cleared; SEPARATE nets closer than the
            # bit are worse — guaranteed electrical shorts. Mark + count them.
            shorts = isolation_bridges(self.state.board.copper,
                                       self.state.trace.effective_diameter())
            if shorts:
                self.preview.show_shorts(shorts)
            if shorts:
                self.statusBar().showMessage(
                    f"DRC: {len(shorts)} spot(s) where separate nets sit closer "
                    f"than the bit (worst {shorts[0]['gap']:.2f} mm, marked X) — "
                    f"these WILL short; use a smaller bit or edit the layout"
                    + est, 12000)
                gap_warning = True
            elif not gaps.is_empty:
                self.preview.show_gaps(gaps)
                self.statusBar().showMessage(
                    "Warning: copper gaps too narrow to isolate (shown red)" + est, 8000)
                gap_warning = True
            if shorts and not gaps.is_empty:
                self.preview.show_gaps(gaps)
        if not gap_warning:
            self.statusBar().showMessage(
                f"Preview updated in {time.time() - t0:.2f}s{est}", 5000)

    def _estimate_str(self, toolpaths, job):
        """' · est. run ~<time>' for the given toolpaths + job feeds (mm/s), or
        '' if there's nothing to estimate."""
        if not toolpaths:
            return ""
        try:
            from gerber2rml.engine.estimate import (estimate_toolpaths_seconds,
                                                     format_duration)
            s = estimate_toolpaths_seconds(toolpaths, job.xy_feed, job.plunge_feed)
            return f"  ·  est. run ~{format_duration(s)}"
        except Exception:
            return ""

    def _est_text(self, toolpaths, job):
        """Persistent control-bar estimate, e.g. 'est ~3m 44s', or '—' if there's
        nothing to estimate for the current op."""
        if not toolpaths:
            return "—"
        try:
            from gerber2rml.engine.estimate import (estimate_toolpaths_seconds,
                                                     format_duration)
            s = estimate_toolpaths_seconds(toolpaths, job.xy_feed, job.plunge_feed)
            return f"est ~{format_duration(s)}"
        except Exception:
            return "—"

    def apply_selected_preset(self):
        from gerber2rml.app.presets import apply_preset
        name = self.preset_combo.currentText()
        if name not in self._presets:
            return
        apply_preset(self.state, self._presets[name])
        self.forms["traces"].set_instance(self.state.trace)
        self.forms["drill"].set_instance(self.state.drill)
        self.forms["cutout"].set_instance(self.state.cutout)
        self._apply_auto_depth()      # auto-depth wins over the preset's depth
        self._sync_vbit_fields()      # grey/derive the V-bit fields for this profile
        # default the rework depth to this profile's trace depth (user can override)
        self.rework_depth_spin.setValue(self.state.trace.cut_depth)
        if self.state.board is not None:
            self.generate_preview()

    def _on_save_preset(self):
        from PySide6.QtWidgets import QInputDialog
        from gerber2rml.app.presets import save_user_preset, load_presets
        name, ok = QInputDialog.getText(self, "Save preset", "Preset name:")
        if ok and name:
            self._sync_state()
            save_user_preset(name, self.state)
            self._presets = load_presets()
            self.preset_combo.clear()
            self.preset_combo.addItems(list(self._presets.keys()))
            self.preset_combo.setCurrentText(name)

    def export_to(self, out_dir):
        self._sync_state()
        if self.double_sided_chk.isChecked():
            from gerber2rml.doublesided import build_double_sided
            # leveling warps only the bottom-side jobs (the probed setup); the top
            # is cut after the flip on the other face, so it's left unleveled.
            level = self._height_map()
            if level is not None:
                QMessageBox.information(
                    self, "Bottom-side leveling",
                    "Bed leveling will warp the BOTTOM-side jobs (align, drill, "
                    "bottom traces, cut-out). The top traces are cut after the flip "
                    "on the other face, so they are left unleveled.")
            return build_double_sided(
                self.state.gerber_dir, out_dir, self.state.name,
                trace=self.state.trace, drill=self.state.drill, cutout=self.state.cutout,
                dowels=self._dowel_spec(), machine=self.state.machine,
                offset=(self.state.place_x, self.state.place_y),
                board_thickness=self.thickness_spin.value(), level=level,
                rotate=self.state.rotate, bed_depth=self.fresh_bed_spin.value(),
                registration=self._registration_mode(),
                fiducials=self._fiducial_spec_from_ui())
        return self.state.export(out_dir, level=self._height_map())

    # ---- bed leveling -----------------------------------------------------

    def _display_outline(self):
        """The board outline currently shown in the preview, in the frame it's
        drawn — so the probe grid lays over the visible board. For double-sided
        that's the registered layout (design frame, or machine frame per side),
        which differs from the single-sided ``state.board``."""
        if self.state.board is None:
            return None
        if self.double_sided_chk.isChecked():
            mode, side = self._resolve_frame()
            if mode == "bed":
                mlay = self._machine_layout()
                if side == "Top":
                    # AS PLACED: the probe grid must land on the board where it
                    # really sits (a crooked flip can shift it by many mm)
                    return self._top_fit_geom(mlay.top_outline)
                return mlay.outline
            return self._double_sided_layout().outline
        return self.state.board.outline

    def _level_bounds(self):
        """Footprint of the displayed board, to lay the probe grid over so the
        points sit on the board you see (not a mismatched frame)."""
        o = self._display_outline()
        if o is None or o.is_empty:
            return None
        return o.bounds

    def _on_build_level_grid(self):
        from gerber2rml.engine.leveling import probe_points
        # Double-sided: leveling is probed/applied in the machine frame of the
        # side being milled. Show a single side so the grid, the overlay and the
        # leveled toolpaths share one frame — keep Bottom/Top if already chosen
        # (for top-side leveling), else default to Bottom (the first cut).
        if self.double_sided_chk.isChecked() and self._ds_side() is None:
            self.view_combo.setCurrentText("Bottom")    # triggers generate_preview
        bounds = self._level_bounds()
        if bounds is None:
            QMessageBox.warning(self, "No board", "Load a Gerber folder first.")
            return
        pts = probe_points(bounds, self.level_nx_spin.value(),
                           self.level_ny_spin.value())
        self.level_table.setRowCount(len(pts))
        for r, (x, y) in enumerate(pts):
            for c, v in ((0, x), (1, y)):
                it = QTableWidgetItem(f"{v:.3f}")
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)   # X/Y read-only
                self.level_table.setItem(r, c, it)
            z = self.level_table.item(r, 2)
            if z is None:
                self.level_table.setItem(r, 2, QTableWidgetItem("0" if r == 0 else ""))
        self.level_gridshow_chk.setChecked(True)    # reveal the grid on the preview
        self._update_grid_overlay()
        self.statusBar().showMessage(
            f"{len(pts)} probe points — measure Z at each and fill the table", 8000)

    def _on_clear_level(self):
        """Wipe the measured Z column so the grid can be re-probed (keeps X/Y).
        Also turns off leveling + the height-map overlay so nothing stale is used."""
        for r in range(self.level_table.rowCount()):
            self.level_table.setItem(r, 2, QTableWidgetItem(""))
        self._probe_z0 = None
        self.level_chk.setChecked(False)
        self.level_show_chk.setChecked(False)
        self.preview.set_level_overlay(None)
        self.statusBar().showMessage(
            "Cleared probe measurements — grid kept, ready to re-probe", 8000)

    def _update_grid_overlay(self):
        """Push the planned probe points to the preview (or clear them)."""
        if not self.level_gridshow_chk.isChecked():
            self.preview.set_probe_grid(None)
            return
        xy, _xyz = self._table_points()
        self.preview.set_probe_grid(xy)

    def _table_points(self):
        """All (x, y) in the table, and the (x, y, z) rows that have a Z filled in."""
        xy, xyz = [], []
        for r in range(self.level_table.rowCount()):
            xi, yi = self.level_table.item(r, 0), self.level_table.item(r, 1)
            if xi is None or yi is None:
                continue
            x, y = float(xi.text()), float(yi.text())
            xy.append((x, y))
            zi = self.level_table.item(r, 2)
            ztxt = zi.text().strip() if zi else ""
            try:
                xyz.append((x, y, float(ztxt)))   # ERR/blank -> ValueError -> skip
            except ValueError:
                pass                              # unmeasured point (interpolated)
        return xy, xyz

    def _on_mesh_check(self):
        """Sanity-check the measured mesh: outliers, depth advice, refinement."""
        from gerber2rml.engine.leveling import (flag_outliers, recommend_depth,
                                                suggest_refinement_rows)
        _xy, xyz = self._table_points()
        if len(xyz) < 5:
            QMessageBox.information(self, "Mesh check",
                                    "Probe (or enter) at least 5 points first.")
            return
        nx, ny = self.level_nx_spin.value(), self.level_ny_spin.value()
        flags = flag_outliers(xyz)
        rec = recommend_depth(xyz, nx, ny)
        sug = suggest_refinement_rows(xyz, nx, ny)
        lines = []
        if flags:
            lines.append("SUSPICIOUS POINTS (no smooth board surface explains them):")
            for k, r in flags[:5]:
                x, y, z = xyz[k]
                lines.append(f"  X{x:.1f} Y{y:.1f}: dz {z:+.3f} sits "
                             f"{r * 1000:.0f} um off the fit — re-probe it")
            lines.append("")
        else:
            lines.append("No single-point outliers vs a smooth surface.")
            lines.append("")
        lines.append("DEPTH: " + rec["detail"])
        try:
            cur = float(self.forms["traces"].value().cut_depth)
            if rec["depth"] > cur + 1e-9:
                lines.append(f"  Current trace cut_depth is {cur:.2f} mm — "
                             f"consider raising it to {rec['depth']:.2f} mm.")
        except Exception:
            pass
        if sug["rows"] or sug["cols"]:
            lines.append("")
            lines.append("GRID TOO COARSE:")
            if sug["rows"]:
                lines.append("  surface jumps >80 um between probe rows — add "
                             "row(s) at y = "
                             + ", ".join(f"{y:.1f}" for y in sug["rows"]))
            if sug["cols"]:
                lines.append("  ...and between columns — add column(s) at x = "
                             + ", ".join(f"{x:.1f}" for x in sug["cols"]))
        msg = "\n".join(lines)
        if sug["rows"]:
            box = QMessageBox(QMessageBox.Information, "Mesh check", msg,
                              QMessageBox.Close, self)
            ins = box.addButton("Insert suggested row(s)", QMessageBox.AcceptRole)
            box.exec()
            if box.clickedButton() is ins:
                self._insert_probe_rows(sug["rows"])
        else:
            QMessageBox.information(self, "Mesh check", msg)

    def _insert_probe_rows(self, new_ys):
        """Insert full probe rows at the given y values (blank Z), keeping the
        table row-major and the grid cartesian — bilinear stays available, and
        'Probe over SPI - Resume' fills exactly the new points."""
        _xy, _xyz = self._table_points()
        rows = []
        for r in range(self.level_table.rowCount()):
            xi, yi, zi = (self.level_table.item(r, c) for c in range(3))
            if xi is None or yi is None:
                continue
            rows.append((float(xi.text()), float(yi.text()),
                         zi.text().strip() if zi else ""))
        xs = sorted({round(x, 3) for x, _y, _z in rows})
        for y in new_ys:
            for x in xs:
                rows.append((x, float(y), ""))
        rows.sort(key=lambda t: (t[1], t[0]))       # row-major, bottom-up
        self.level_table.setRowCount(len(rows))
        for r, (x, y, z) in enumerate(rows):
            self.level_table.setItem(r, 0, QTableWidgetItem(f"{x:.3f}"))
            self.level_table.setItem(r, 1, QTableWidgetItem(f"{y:.3f}"))
            self.level_table.setItem(r, 2, QTableWidgetItem(z))
        ny = len({round(y, 3) for _x, y, _z in rows})
        self.level_ny_spin.blockSignals(True)
        self.level_ny_spin.setValue(ny)
        self.level_ny_spin.blockSignals(False)
        self._update_grid_overlay()
        self.statusBar().showMessage(
            f"Inserted {len(new_ys)} probe row(s) — run 'Probe over SPI' and "
            f"choose Resume to measure only the new points", 12000)

    def _on_export_probe_files(self):
        if not self.level_table.rowCount():
            self._on_build_level_grid()
        xy, _xyz = self._table_points()
        if not xy:
            return
        out = self._pick_out_dir()
        if not out:
            return
        from gerber2rml.engine.leveling import write_probe_files
        written = write_probe_files(out, self.state.name or "board", xy)
        self.statusBar().showMessage(
            f"Wrote {len(written) - 1} probe files + checklist to {out}", 10000)

    def _on_save_level_grid(self):
        """Write the probe grid (X, Y, dz) to a CSV so the height map is recorded."""
        if not self.level_table.rowCount():
            QMessageBox.warning(self, "Nothing to save", "No probe grid yet.")
            return
        from pathlib import Path
        default = f"{self.state.name or 'board'}_heightmap.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save height map",
            str(Path(self._dlg_dir("heightmap", "sessions")) / default),
            "CSV (*.csv)")
        if not path:
            return
        self._dlg_remember("heightmap", path)
        lines = ["x_mm,y_mm,dz_mm"]
        for r in range(self.level_table.rowCount()):
            vals = []
            for c in range(3):
                it = self.level_table.item(r, c)
                vals.append(it.text().strip() if it else "")
            lines.append(",".join(vals))
        Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.statusBar().showMessage(f"Saved height map to {path}", 8000)

    def _on_load_level_grid(self):
        """Load a probe grid (x_mm, y_mm, dz_mm) CSV back into the table — e.g. one
        saved with 'Save CSV' before an update. Infers nx/ny from the points."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Load height map CSV",
            self._dlg_dir("heightmap", "sessions"), "CSV (*.csv)")
        if not path:
            return
        self._dlg_remember("heightmap", path)
        try:
            text = Path(path).read_text(encoding="utf-8")
        except Exception as e:
            QMessageBox.critical(self, "Load failed", str(e))
            return
        rows = []
        for line in text.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 2:
                continue
            try:
                x, y = float(parts[0]), float(parts[1])
            except ValueError:
                continue                            # header / non-numeric line
            z = parts[2] if len(parts) > 2 else ""
            rows.append((x, y, z))
        if not rows:
            QMessageBox.warning(self, "Empty", "No probe points found in the CSV.")
            return
        self.level_table.setRowCount(len(rows))
        for r, (x, y, z) in enumerate(rows):
            for c, val in ((0, f"{x:.3f}"), (1, f"{y:.3f}"), (2, z)):
                it = QTableWidgetItem(val)
                if c < 2:
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.level_table.setItem(r, c, it)
        nx = len({round(x, 2) for x, _y, _z in rows})
        ny = len({round(y, 2) for _x, y, _z in rows})
        if 2 <= nx <= 8:
            self.level_nx_spin.setValue(nx)
        if 2 <= ny <= 8:
            self.level_ny_spin.setValue(ny)
        self.level_gridshow_chk.setChecked(True)
        self._update_grid_overlay()
        self._update_level_overlay()
        self.statusBar().showMessage(
            f"Loaded {len(rows)} probe points from {Path(path).name}", 8000)

    # ---- live machine link (DRO + tool overlay) -------------------------

    _DRO_OFF = "color:#888; font-family:Consolas,monospace; font-size:13px; padding:4px 10px;"
    _DRO_ON = "color:#39ff14; font-family:Consolas,monospace; font-size:13px; padding:4px 10px;"

    def _on_connect_toggled(self, on):
        if on:
            self._start_dro()
        else:
            self._stop_dro()

    def _start_dro(self):
        port = self.level_port_combo.currentText().strip() or "COM5"
        self._dro = _DROPoller(port)
        self._dro.position.connect(self._on_position)
        self._dro.touch_done.connect(self._on_touch_done)
        self._dro.zero_done.connect(self._on_zero_done)
        self._dro.failed.connect(self._on_dro_failed)
        self._dro.start()
        self.connect_btn.setText("Disconnect")
        self.jog_chk.setEnabled(True)
        self.zero_btn.setEnabled(True)
        self.machine_zero_btn.setEnabled(True)
        self.stream_btn.setEnabled(True)
        self.align_btn.setEnabled(True)
        if self._sim_window is not None:
            self._sim_window.set_live_enabled(True)
        self.dro_label.setText(f"●  connecting on {port}…")
        self.dro_label.setStyleSheet(self._DRO_ON)
        self.statusBar().showMessage(
            "Hover the preview and use the arrow keys to jog X/Y "
            "(Shift = 10 mm, Ctrl = 0.1 mm)", 8000)

    def _stop_dro(self):
        # disconnecting must also stop an in-progress grid probe (else the
        # Arduino keeps probing and resumes on its own) — abort it and lift.
        pw = getattr(self, "_probe_worker", None)
        if pw is not None and pw.isRunning():
            pw.abort()
        self._dro_was_on = False              # don't auto-resume after an explicit stop
        self._pause_dro()
        self.preview.set_tool_position(None, None)
        self.jog_chk.setChecked(False)
        self.jog_chk.setEnabled(False)
        self.preview.set_jogging(False)
        self.zero_btn.setEnabled(False)
        self.machine_zero_btn.setEnabled(False)
        self.stream_btn.setEnabled(False)
        self.align_btn.setChecked(False)      # keep the trim value; disarm the pick
        self.align_btn.setEnabled(False)
        self.preview.set_align_pick(False)
        if self._sim_window is not None:
            self._sim_window.set_live_enabled(False)
        self._z_zero = None
        if self.connect_btn.isChecked():
            self.connect_btn.blockSignals(True)
            self.connect_btn.setChecked(False)
            self.connect_btn.blockSignals(False)
        self.connect_btn.setText("Connect")
        self.dro_label.setText("○  machine offline")
        self.dro_label.setStyleSheet(self._DRO_OFF)
        self.touch_label.setText("bit ○")
        self.touch_label.setStyleSheet(self._DRO_OFF)

    def _pause_dro(self):
        """Stop the poller and free the port (for a probe run). Returns whether it
        was running, so it can be resumed."""
        if self._dro is None:
            return False
        try:
            self._dro.position.disconnect(self._on_position)
        except Exception:
            pass
        self._dro.stop()
        self._dro = None
        self._tool_xyz = None
        return True

    def _on_dro_failed(self, msg):
        self._stop_dro()
        QMessageBox.warning(self, "Machine link failed", msg)

    def _on_emergency_stop(self):
        """ABORT everything: stop grid-probe / touch-off / jog, tell the firmware
        to lift the bit to safe Z, and drop the link. Safe to hit any time."""
        stopped = False
        pw = getattr(self, "_probe_worker", None)
        if pw is not None and pw.isRunning():
            pw.abort()                        # ! -> firmware lifts; worker bails
            stopped = True
        rw = getattr(self, "_rework_probe_worker", None)
        if rw is not None and rw.isRunning():
            rw.abort()
            stopped = True
        sw = getattr(self, "_stream_worker", None)
        if sw is not None and sw.isRunning():
            sw.abort()                        # stream sends ! and stops
            stopped = True
        if self._dro is not None:
            self._dro.request_abort()         # ! -> firmware lifts; poller bails
            stopped = True
        self._dro_was_on = False              # never auto-resume after a STOP
        self._stop_dro()
        self.statusBar().showMessage(
            "STOP — lifting the bit to safe Z and disconnecting" if stopped
            else "STOP — nothing was running", 12000)

    def _on_jog_mode_toggled(self, on):
        self.preview.set_jogging(on)
        if on:                                   # jog mode is exclusive with the others
            self.select_chk.setChecked(False)
            self.move_chk.setChecked(False)
            self.measure_chk.setChecked(False)
            self.align_btn.setChecked(False)
            self.statusBar().showMessage(
                "Click a point on the preview to jog the tool there", 6000)

    def _on_jog_to(self, x, y):
        if self._dro is None:
            return
        # the canvas point is in the DESIGN frame; the machine target must be in
        # the MACHINE frame — undo the overlay trim so the bit lands where clicked
        tx, ty = self._overlay_trim
        mx, my = x - tx, y - ty
        self._last_jog_t = time.time()       # our own motion — don't auto-start on it
        self._dro.request_move(round(mx * 1000), round(my * 1000))
        self.statusBar().showMessage(f"Jogging to X {x:.1f}  Y {y:.1f} mm", 4000)

    def _on_align_mode_toggled(self, on):
        """Arm the one-shot overlay-align pick (see the button tooltip)."""
        if on and self._tool_xyz is None:
            self.statusBar().showMessage(
                "Connect the machine and wait for a live position first", 6000)
            self.align_btn.setChecked(False)
            return
        self.preview.set_align_pick(on)
        if on:                                   # exclusive with the other click modes
            self.jog_chk.setChecked(False)
            self.select_chk.setChecked(False)
            self.move_chk.setChecked(False)
            self.measure_chk.setChecked(False)
            self.statusBar().showMessage(
                "Click the design point the bit is PHYSICALLY at (Ctrl+click "
                "clears the trim)", 10000)

    def _on_align_pick(self, x, y, key):
        """The user clicked where the bit really is: trim = clicked design point
        minus the live machine position. Display/jog/progress only — never the
        exported job coordinates."""
        self.align_btn.setChecked(False)         # one-shot; also disarms the canvas
        if "ctrl" in (key or ""):
            self._overlay_trim = (0.0, 0.0)
            self.preview.clear_tool_trail()
            self.statusBar().showMessage("Overlay trim cleared", 6000)
            return
        if self._tool_xyz is None:
            return
        mx, my, _mz = self._tool_xyz
        self._overlay_trim = (x - mx, y - my)
        self.preview.clear_tool_trail()          # old crumbs are in the old frame
        tx, ty = self._overlay_trim
        self.statusBar().showMessage(
            f"Overlay trimmed by dX {tx:+.2f}  dY {ty:+.2f} mm (display, jog and "
            "progress only — the job itself is untouched)", 10000)

    def _on_jog_step(self, dx, dy):
        """Arrow-key relative jog from the preview: move the carriage by (dx, dy)
        mm from its last known position. Relative, so it's correct regardless of
        any G54/preview-frame offset (unlike click-to-jog)."""
        if self._dro is None:
            self.statusBar().showMessage(
                "Connect the machine to jog with the arrow keys", 4000)
            return
        if self._tool_xyz is None:
            self.statusBar().showMessage(
                "Waiting for a live position read before jogging…", 4000)
            return
        x, y, z = self._tool_xyz
        nx, ny = x + dx, y + dy
        self._last_jog_t = time.time()       # our own motion — don't auto-start on it
        self._dro.request_move(round(nx * 1000), round(ny * 1000))
        # optimistically advance the local position so rapid key taps accumulate
        # into one move to the final spot instead of all reading the same stale XY
        self._tool_xyz = (nx, ny, z)
        self.statusBar().showMessage(
            f"Jog {dx:+.1f} {dy:+.1f} mm  ->  X {nx:.1f}  Y {ny:.1f} mm", 3000)

    _RUN_OP = {"Traces": "traces", "Drill": "drill", "Cut-out": "cutout"}

    def _on_track_run(self, on):
        """Arm/disarm live run-progress tracking from the DRO position."""
        if not on:
            self._run_progress = None
            self._run_finished = False
            self.run_bar.setValue(0)
            self.run_eta_lbl.setText("—")
            self.run_track_btn.setText("Track run")
            return
        if not self._arm_tracking():
            self.run_track_btn.setChecked(False)

    def _arm_tracking(self, silent=False):
        """Build the run-progress tracker for the picked op. Returns True on
        success. ``silent`` suppresses warning dialogs (used by auto-start)."""
        if self.state.board is None:
            if not silent:
                QMessageBox.warning(self, "No board", "Load a Gerber folder first.")
            return False
        self._sync_state()
        op = self._RUN_OP[self.run_op_combo.currentText()]
        try:
            toolpaths = self._toolpaths_for(op)
            if self.run_rework_chk.isChecked():
                if not self._rework_regions:
                    if not silent:
                        QMessageBox.warning(self, "No regions",
                                            "Tick off 'selection', or add rework "
                                            "boxes first.")
                    return False
                toolpaths, _lv = self._rework_clip_regions(toolpaths)
        except Exception as e:
            if not silent:
                QMessageBox.warning(self, "Can't track", f"No toolpaths for {op}: {e}")
            return False
        from gerber2rml.engine.progress import RunProgress
        from gerber2rml.engine.estimate import format_duration
        job = self._job_for_op(op)
        self._run_progress = RunProgress(toolpaths, job.xy_feed, job.plunge_feed)
        self._run_finished = False
        self.run_bar.setValue(0)
        self.run_track_btn.setText("Tracking…")
        total = format_duration(self._run_progress.total)
        if self._dro is None:
            self.run_eta_lbl.setText(f"{total} — connect to track")
        else:
            self.run_eta_lbl.setText(f"{total} total")
        return True

    def _maybe_autostart_run(self, x, y, z):
        """Auto-arm tracking when the bit starts moving (a run began in VPanel).
        Needs the machine connected and 'Auto' on; ignored right after a jog and
        while a run is already actively tracking."""
        if not self.run_auto_chk.isChecked() or self._dro is None:
            return
        if self._run_progress is not None and not self._run_finished:
            return                              # already tracking this run
        if time.time() - self._last_jog_t < 2.0:
            self._run_last_pos = (x, y, z)      # a jog is motion we caused — skip
            return
        prev = self._run_last_pos
        self._run_last_pos = (x, y, z)
        if prev is None:
            return
        moved = ((x - prev[0]) ** 2 + (y - prev[1]) ** 2 + (z - prev[2]) ** 2) ** 0.5
        self._run_motion = self._run_motion + 1 if moved > 0.25 else 0
        if self._run_motion >= 3:               # ~0.75 s of continuous motion
            self._run_motion = 0
            if self.run_track_btn.isChecked():  # finished run -> rebuild in place
                self._arm_tracking(silent=True)
            elif self._arm_tracking(silent=True):
                self.run_track_btn.blockSignals(True)
                self.run_track_btn.setChecked(True)
                self.run_track_btn.blockSignals(False)
            self.statusBar().showMessage(
                "Auto-started run tracking from tool motion", 4000)

    _CHIP_ON = ("background:#1d3a2a; color:#6be49a; border:1px solid #2c5a40; "
                "border-radius:9px; padding:1px 9px; font-size:11px;")
    _CHIP_OFF = ("background:#23262c; color:#7c828c; border:1px solid #34383f; "
                 "border-radius:9px; padding:1px 9px; font-size:11px;")

    def _update_chips(self):
        """Refresh the workflow chips (status bar, right side)."""
        if not self._chip_labels:
            for name in ("board", "mesh", "fit", "photo", "boxes", "link"):
                lbl = QLabel("")
                self._chip_labels[name] = lbl
                self.statusBar().addPermanentWidget(lbl)

        def put(name, text, on):
            lbl = self._chip_labels[name]
            if lbl.text() != text:
                lbl.setText(text)
            lbl.setStyleSheet(self._CHIP_ON if on else self._CHIP_OFF)

        put("board", self.state.name if self.state.board is not None
            else "no board", self.state.board is not None)
        try:
            n_mesh = len(self._table_points()[1])
        except Exception:
            n_mesh = 0
        put("mesh", f"mesh {n_mesh}" if n_mesh else "mesh —",
            n_mesh >= 3 and self.level_chk.isChecked())
        if self._top_fit is not None:
            import math as _m
            put("fit", f"fit {_m.degrees(self._top_fit.theta):+.2f}°", True)
        else:
            put("fit", "fit —", False)
        put("photo", "photo ✓" if self._photo_overlay else "photo —",
            bool(self._photo_overlay))
        n_boxes = len(self._rework_regions)
        put("boxes", f"boxes {n_boxes}" if n_boxes else "boxes —", n_boxes > 0)
        put("link", "link ●" if self._dro is not None else "link ○",
            self._dro is not None)

    def _update_run_progress(self, x, y, z):
        self._maybe_autostart_run(x, y, z)
        if self._run_progress is None:
            return
        from gerber2rml.engine.estimate import format_duration
        frac, _el, rem = self._run_progress.update(x, y, z)
        pct = int(round(frac * 100))
        self.run_bar.setValue(pct)
        if frac >= 0.999:
            self._run_finished = True
            self.run_eta_lbl.setText("done")
        else:
            self.run_eta_lbl.setText(f"{format_duration(rem)} left")

    _TOUCH_ON = "color:#ff3b3b; font-family:Consolas,monospace; font-size:13px; padding:4px 10px;"
    _TOUCH_OFF = "color:#39ff14; font-family:Consolas,monospace; font-size:13px; padding:4px 10px;"

    def _on_position(self, x, y, z, touching):
        # reject implausible jumps (garbage SPI reads) but re-sync after a few in
        # a row, so a bad first baseline doesn't freeze the readout.
        if self._tool_xyz is not None:
            px, py, pz = self._tool_xyz
            if abs(x - px) > 40 or abs(y - py) > 40 or abs(z - pz) > 40:
                self._dro_rejects += 1
                if self._dro_rejects < 3:
                    return
        self._dro_rejects = 0
        self._tool_xyz = (x, y, z)
        self._touching = touching
        txt = f"●  X {x:8.2f}   Y {y:8.2f}   Z {z:8.2f}   mm"
        if self._z_zero is not None:
            txt += f"   surf {z - self._z_zero:+.2f}"     # depth below the zeroed surface
        tx, ty = self._overlay_trim
        if tx or ty:
            txt += f"   Δ {tx:+.2f}/{ty:+.2f}"       # active overlay trim
        self.dro_label.setText(txt)
        self.dro_label.setStyleSheet(self._DRO_ON)
        self.touch_label.setText("bit ● TOUCHING" if touching else "bit ○ clear")
        self.touch_label.setStyleSheet(self._TOUCH_ON if touching else self._TOUCH_OFF)
        # overlay, trail and progress matching live in the DESIGN frame — apply
        # the trim; the label above keeps the RAW machine readout (VPanel-equal)
        self.preview.set_tool_position(x + tx, y + ty, touching)
        self._update_run_progress(x + tx, y + ty, z)
        # feed the 3D viewer's live cursor (it follows only while LIVE is on)
        if self._sim_window is not None and self._sim_window.isVisible():
            self._sim_window.set_live_position(x + tx, y + ty)

    def _on_probe_z(self):
        """Probe down from the current XY until the bit touches, then zero Z there."""
        if self._dro is None:
            QMessageBox.warning(self, "Not connected", "Connect the machine first.")
            return
        if self._touching:
            QMessageBox.warning(self, "Already touching",
                                "The bit is already touching — lift it a few mm first.")
            return
        self.zero_btn.setEnabled(False)
        self.statusBar().showMessage("Probing down to the surface…")
        self._dro.request_touchoff()

    def _on_stream_job(self):
        """EXPERIMENTAL SPI streaming — dry run by default, wet run behind a
        second explicit confirmation."""
        if self.state.board is None:
            QMessageBox.warning(self, "No board", "Load a Gerber folder first.")
            return
        self._sync_state()
        op = self._RUN_OP[self.run_op_combo.currentText()]
        try:
            toolpaths = self._toolpaths_for(op)
            if self.run_rework_chk.isChecked() and self._rework_regions:
                toolpaths, _lv = self._rework_clip_regions(toolpaths)
        except Exception as e:
            QMessageBox.warning(self, "No toolpaths", f"No toolpaths for {op}: {e}")
            return
        n_moves = sum(len(tp) for tp in toolpaths)
        box = QMessageBox(
            QMessageBox.Warning, "Stream over SPI (EXPERIMENTAL)",
            f"Stream {n_moves} moves of '{op}' over the SPI link, bypassing "
            f"VPanel.\n\nDRY RUN traces the whole job with Z held 2 mm above "
            f"the work origin — nothing can cut; use it to verify motion and "
            f"calibrate timing.\n\nWET RUN cuts for real: spindle must be "
            f"started in VPanel BY HAND first, Z zeroed on the copper, and "
            f"the speed value validated on dry runs. The speed units are "
            f"Roland-internal and NOT calibrated to mm/s yet.",
            QMessageBox.Cancel, self)
        dry = box.addButton("Dry run (safe)", QMessageBox.AcceptRole)
        wet = box.addButton("Wet run…", QMessageBox.DestructiveRole)
        box.exec()
        if box.clickedButton() is dry:
            dry_run = True
        elif box.clickedButton() is wet:
            if QMessageBox.question(
                    self, "Wet run — really cut?",
                    "Spindle running (VPanel)? Z zeroed on the copper? Dry run "
                    "verified on THIS job?\n\nThe bit will plunge to cut depth "
                    "on the first move.") != QMessageBox.Yes:
                return
            dry_run = False
        else:
            return
        port = self.level_port_combo.currentText().strip() or "COM5"
        self._dro_was_on = self._pause_dro()   # free the port for the stream
        self.stream_btn.setEnabled(False)
        self.statusBar().showMessage(
            f"Streaming {n_moves} moves ({'DRY' if dry_run else 'WET'}) — "
            f"press STOP or close the lid to abort…")
        self._stream_worker = _StreamWorker(port, toolpaths, dry_run=dry_run)
        self._stream_worker.progress.connect(
            lambda i, n: self.run_bar.setValue(int(round(100 * i / max(n, 1)))))
        self._stream_worker.done.connect(self._on_stream_done)
        self._stream_worker.start()

    def _on_stream_done(self, err):
        self.stream_btn.setEnabled(True)
        if self._dro_was_on:
            self._dro_was_on = False
            self._start_dro()
        if err:
            QMessageBox.warning(self, "Stream stopped", err)
            self.statusBar().showMessage("Stream stopped — tool lifted", 10000)
        else:
            self.statusBar().showMessage("Stream complete", 10000)

    def _on_machine_zero(self):
        """Verified touch-off, then the firmware writes origin Z on the surface."""
        if self._dro is None:
            QMessageBox.warning(self, "Not connected", "Connect the machine first.")
            return
        if self._touching:
            QMessageBox.warning(self, "Already touching",
                                "The bit is already touching — lift it a few mm first.")
            return
        self.machine_zero_btn.setEnabled(False)
        self.statusBar().showMessage("Zeroing origin Z on the copper…")
        self._dro.request_zero()

    def _on_zero_done(self, ok, oz):
        self.machine_zero_btn.setEnabled(self._dro is not None)
        if not ok:
            QMessageBox.warning(
                self, "Zero Z failed",
                "No verified contact (NOTOUCH/UNSTABLE), or the firmware is v1 — "
                "reflash hardware/srm20_spi_probe (v2) for the W command.")
            self.statusBar().showMessage("Zero Z: failed", 6000)
            return
        self._z_zero = oz
        self.statusBar().showMessage(
            f"Origin Z written to the machine at the copper surface "
            f"(machine Z {oz:.2f} mm). Verify VPanel G54 Z once before an NC job.",
            12000)

    def _on_touch_done(self, ok, x, y, z):
        self.zero_btn.setEnabled(self._dro is not None)
        if not ok:
            QMessageBox.warning(
                self, "No contact",
                "Descended the full range without contact. Check the touch clips "
                "and start the bit closer to the surface.")
            self.statusBar().showMessage("Touch-off: no contact", 6000)
            return
        self._z_zero = z
        self.statusBar().showMessage(f"Surface found — Z zeroed (machine Z {z:.2f} mm)", 8000)
        self._on_position(x, y, z, True)        # bit is now resting on the surface

    def closeEvent(self, e):
        if self._dro is not None:
            self._dro.stop()
        super().closeEvent(e)

    def _grid_fill_state(self):
        """(filled, unfilled) probe-point counts (ERR/blank count as unfilled)."""
        filled = unfilled = 0
        for r in range(self.level_table.rowCount()):
            if self.level_table.item(r, 0) is None:
                continue
            zi = self.level_table.item(r, 2)
            ztxt = zi.text().strip() if zi else ""
            if ztxt not in ("", "-", "ERR"):
                filled += 1
            else:
                unfilled += 1
        return filled, unfilled

    def _probe_points(self, resume):
        """(points, x0, y0). ``points`` = [(row, dx_um, dy_um)] from the first
        grid point. ``resume`` probes the anchor (row 0, to re-set the dz
        reference) + only the unfilled rows, keeping the rest."""
        rows = []
        for r in range(self.level_table.rowCount()):
            xi, yi = self.level_table.item(r, 0), self.level_table.item(r, 1)
            if xi is None or yi is None:
                continue
            zi = self.level_table.item(r, 2)
            ztxt = zi.text().strip() if zi else ""
            rows.append((r, float(xi.text()), float(yi.text()),
                         ztxt not in ("", "-", "ERR")))
        if not rows:
            return [], 0.0, 0.0
        x0, y0 = rows[0][1], rows[0][2]
        if resume:
            sel = [rows[0]] + [r for r in rows if not r[3] and r[0] != rows[0][0]]
        else:
            sel = rows
        points = [(r, round((x - x0) * 1000), round((y - y0) * 1000))
                  for (r, x, y, _h) in sel]
        return points, x0, y0

    def _on_probe_spi(self):
        """Auto-probe the grid over the SPI link and fill the Z column."""
        if not self.level_table.rowCount():
            self._on_build_level_grid()
        filled, unfilled = self._grid_fill_state()
        if filled + unfilled < 3:
            QMessageBox.warning(self, "No grid", "Build a probe grid first.")
            return
        # part-done grid -> offer to resume rather than start over
        resume = False
        if filled and unfilled:
            ans = QMessageBox.question(
                self, "Resume or re-probe?",
                f"{filled} of {filled + unfilled} points are already measured.\n\n"
                f"Resume: probe only the {unfilled} remaining (re-probes point 1 as "
                f"the reference, keeps the rest).\nRe-probe all: start over.",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            if ans == QMessageBox.Cancel:
                return
            resume = ans == QMessageBox.Yes
        points, x0, y0 = self._probe_points(resume)
        port = self.level_port_combo.currentText().strip() or "COM5"
        if QMessageBox.question(
                self, "Probe over SPI",
                f"Jog the tool ~2-3 mm above grid point 1 "
                f"(X{x0:.1f} Y{y0:.1f}), spindle OFF, prober sketch running, "
                f"Serial Monitor CLOSED.\n\nProbe {len(points)} points on {port}?"
                ) != QMessageBox.Yes:
            return
        self._dro_was_on = self._pause_dro()   # free the port for the probe run
        self._probe_z0 = None
        self.level_probe_btn.setEnabled(False)
        self.statusBar().showMessage(f"Probing {len(points)} points on {port}...")
        self._probe_drift_um = None
        self._probe_worker = _ProbeWorker(
            port, points, retouch_every=self.level_retouch_spin.value())
        self._probe_worker.result.connect(self._on_probe_result)
        self._probe_worker.corrected.connect(self._on_probe_corrected)
        self._probe_worker.drift.connect(self._on_probe_drift)
        self._probe_worker.done.connect(self._on_probe_done)
        self._probe_worker.start()

    def _on_probe_result(self, d):
        """One point came back: fill its Z cell with the deviation (mm)."""
        row = d["id"]
        if d.get("z") is None:
            self.level_table.setItem(row, 2, QTableWidgetItem("ERR"))
        else:
            if self._probe_z0 is None:
                self._probe_z0 = d["z"]         # first good point = reference (dz=0)
            dz = (d["z"] - self._probe_z0) / 1000.0
            self.level_table.setItem(row, 2, QTableWidgetItem(f"{dz:.4f}"))
        self.statusBar().showMessage(f"Probed point {row + 1}/{self.level_table.rowCount()}")

    def _on_probe_corrected(self, res):
        """Drift-corrected final results: re-fill the table (reference resets so
        the deviations are relative to the CORRECTED first point)."""
        self._probe_z0 = None
        for d in res:
            self._on_probe_result(d)

    def _on_probe_drift(self, um):
        self._probe_drift_um = um

    def _on_probe_done(self, err):
        self.level_probe_btn.setEnabled(True)
        if err == "aborted":
            self.statusBar().showMessage("Probing aborted — bit lifted to safe Z", 8000)
        elif err.startswith("STOPPED"):
            QMessageBox.warning(self, "Probing stopped", err)
            self.statusBar().showMessage("Probing stopped, bit lifted", 12000)
        elif err.startswith("missed:"):
            pts = err.split(":", 1)[1]
            self.level_chk.setChecked(True)
            self.level_show_chk.setChecked(True)
            self._update_level_overlay()
            self.statusBar().showMessage(
                f"Probe complete — points {pts} found no copper (skipped; the height "
                f"map interpolates over them)", 14000)
        elif err:
            QMessageBox.critical(self, "Probe failed", err)
            self.statusBar().showMessage("Probe failed", 8000)
        else:
            self.level_chk.setChecked(True)     # leveling is ready to apply
            self.level_show_chk.setChecked(True)  # reveal the surface heatmap
            self._update_level_overlay()
            msg = "Probe complete — Z column filled"
            if self._probe_drift_um is not None:
                msg += (f" (reference drifted {self._probe_drift_um:.0f} um over "
                        f"the run — corrected)")
            try:
                from gerber2rml.engine.leveling import (flag_outliers,
                                                        suggest_refinement_rows)
                _xy, xyz = self._table_points()
                n_flag = len(flag_outliers(xyz))
                n_rows = len(suggest_refinement_rows(
                    xyz, self.level_nx_spin.value(),
                    self.level_ny_spin.value())["rows"])
                if n_flag or n_rows:
                    msg += (f" — Mesh check: {n_flag} suspicious point(s), "
                            f"{n_rows} extra row(s) suggested (click Mesh check)")
            except Exception:
                pass
            self.statusBar().showMessage(msg, 15000)
        if self._dro_was_on:                    # restore the live link after probing
            self._dro_was_on = False
            self._start_dro()

    def _level_heightmap_preview(self):
        """HeightMap from the table for the OVERLAY (ignores the apply checkbox);
        None if fewer than 3 points are measured."""
        _xy, xyz = self._table_points()
        if len(xyz) < 3:
            return None
        from gerber2rml.engine.leveling import HeightMap
        return HeightMap.from_points(xyz, self.level_nx_spin.value(),
                                     self.level_ny_spin.value())

    def _update_level_overlay(self):
        """Sample the measured surface over the board and push it to the preview."""
        if not self.level_show_chk.isChecked() or self.state.board is None:
            self.preview.set_level_overlay(None)
            return
        hmap = self._level_heightmap_preview()
        _xy, xyz = self._table_points()
        # Sample over the DISPLAYED footprint (the same _level_bounds the probe grid
        # is laid over), NOT state.board.outline — for a mirrored bottom side or a
        # placed board those frames differ and the heatmap would land offset.
        bounds = self._level_bounds()
        if hmap is None or bounds is None:
            self.preview.set_level_overlay(None)
            return
        import numpy as np
        x0, y0, x1, y1 = bounds
        xs = np.linspace(x0, x1, 48); ys = np.linspace(y0, y1, 48)
        X, Y = np.meshgrid(xs, ys)
        Z = [[hmap(float(x), float(y)) for x in xs] for y in ys]
        self.preview.set_level_overlay(X, Y, Z, xyz)

    def _on_bed_3d(self):
        """Open the probed surface as a rotatable 3D mesh (OctoPrint-style)."""
        hmap = self._level_heightmap_preview()
        bounds = self._level_bounds()
        if hmap is None or bounds is None or self.state.board is None:
            QMessageBox.warning(self, "No height map",
                                "Probe or enter at least 3 points first.")
            return
        import numpy as np
        x0, y0, x1, y1 = bounds          # displayed frame — matches the probe points
        xs = np.linspace(x0, x1, 40)
        ys = np.linspace(y0, y1, 40)
        Z = np.array([[hmap(float(x), float(y)) for y in ys] for x in xs])  # (nx, ny)
        _xy, xyz = self._table_points()
        try:
            from gerber2rml.gui.bedviz import BedVisualizerWindow
            self._bedviz = BedVisualizerWindow(
                xs, ys, Z, xyz, title=f"{self.state.name or 'board'} - bed", parent=self)
            self._bedviz.show()
        except Exception as e:
            QMessageBox.critical(self, "3D view failed",
                                 f"The 3D bed view needs pyqtgraph + PyOpenGL.\n\n{e}")

    def _height_map(self):
        """Build a HeightMap from the filled-in table, or None if leveling is off
        or fewer than 3 points are measured."""
        if not self.level_chk.isChecked():
            return None
        _xy, xyz = self._table_points()
        if len(xyz) < 3:
            QMessageBox.warning(
                self, "Not enough points",
                "Bed leveling needs at least 3 measured Z values. Exporting "
                "without leveling.")
            return None
        from gerber2rml.engine.leveling import HeightMap
        return HeightMap.from_points(xyz, self.level_nx_spin.value(),
                                     self.level_ny_spin.value())

    def export_image_to(self, out_dir):
        from pathlib import Path
        from gerber2rml.report import board_summary
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        png = out_dir / f"{self.state.name}_preview.png"
        self.preview.figure.savefig(
            str(png), facecolor=self.preview.figure.get_facecolor())
        if self.state.board is not None:
            (out_dir / f"{png.stem}_summary.md").write_text(
                board_summary(self.state.board, self.state.name), encoding="utf-8")
        return png

    def _on_load_clicked(self):
        folder = self._pick_dir("gerber", "Select Gerber folder", sub="")
        if folder:
            try:
                self.load_folder(folder)
                self.preview.set_demo(False)   # the operator's own board, not the demo
                self.generate_preview()
            except Exception as e:
                QMessageBox.critical(self, "Load failed", str(e))

    def _on_export_clicked(self):
        if self.state.gerber_dir is None:
            QMessageBox.warning(self, "Nothing to export", "Load a Gerber folder first.")
            return
        if self.double_sided_chk.isChecked() and self.state.board is not None \
                and self.state.board.copper_top.is_empty:
            QMessageBox.warning(self, "No F.Cu",
                                "Double-sided needs front copper (F.Cu); none found in this export.")
        out = self._pick_out_dir()
        if out:
            try:
                written = self.export_to(out)
            except Exception as e:
                QMessageBox.critical(self, "Export failed", str(e))
                return
            from gerber2rml.engine.estimate import estimate_file_seconds, format_duration
            secs = [estimate_file_seconds(p) for p in written]
            total = sum(s for s in secs if s)
            msg = f"Exported successfully to: {out}"
            if total:
                msg += f"  ·  est. total run ~{format_duration(total)} (see runplan)"
            msg += self._note_tool_wear()
            self.statusBar().showMessage(msg, 12000)

    def _note_tool_wear(self, toolpaths=None):
        """Record this export's cut distance in the per-tool wear ledger and
        return a status suffix (mileage + a WORN warning past the threshold)."""
        try:
            from gerber2rml.engine import toolwear
            job = self.state.trace
            key = f"{job.tool_type} {job.effective_diameter():.2f}mm"
            if toolpaths is None:
                toolpaths = self.state.toolpaths("traces")
            toolwear.record(key, toolwear.cut_distance_mm(toolpaths))
            return toolwear.wear_note(key)
        except Exception:
            return ""

    def _on_export_align_only(self):
        if self.state.gerber_dir is None:
            QMessageBox.warning(self, "Nothing to export", "Load a Gerber folder first.")
            return
        out = self._pick_out_dir()
        if not out:
            return
        self._sync_state()
        from gerber2rml.doublesided import build_align_only
        try:
            path = build_align_only(
                self.state.gerber_dir, out, self.state.name,
                drill=self.state.drill, dowels=self._dowel_spec(),
                machine=self.state.machine,
                board_thickness=self.thickness_spin.value(),
                rotate=self.state.rotate, bed_depth=self.fresh_bed_spin.value())
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))
            return
        self.statusBar().showMessage(
            f"Dowel holes only -> {path.name}  (keep the same XY origin)", 10000)

    def _on_export_top_traces(self):
        """Re-export the top traces warped to a fresh probe of the flipped board.
        Run after milling the bottom, flipping, and probing the top in View=Top."""
        if self.state.gerber_dir is None:
            QMessageBox.warning(self, "Nothing to export", "Load a Gerber folder first.")
            return
        if not self.double_sided_chk.isChecked():
            QMessageBox.warning(self, "Double-sided only",
                                "Top-side leveling only applies to double-sided boards.")
            return
        if self._ds_side() != "Top":
            QMessageBox.warning(
                self, "Set View to Top",
                "Top-side leveling needs the Top side shown so the probe grid sits "
                "in the top frame.\n\nSet View to 'Top', Build grid, Clear Z, probe "
                "the flipped board, then export.")
            return
        level = self._level_heightmap_preview()      # from the (top) table; ignores the checkbox
        if level is None:
            QMessageBox.warning(
                self, "Probe the top first",
                "Probe at least 3 points on the flipped (top) surface before "
                "exporting leveled top traces.")
            return
        self._sync_state()
        # THE 2026-07-03 TRAP: this exporter used to rebuild the layout with the
        # default dowel registration no matter what — in fiducial mode that
        # silently dropped the measured fit AND shifted the whole job into the
        # dowel frame (~12 mm off on a real board). Export in the frame the
        # registration actually defines.
        reg_kwargs = {}
        if self._registration_mode() == "fiducial":
            fid = self._fiducial_spec_from_ui()
            measured = getattr(self, "_fid_measured", None)
            if not measured and self._top_fit is not None:
                # Setup reloaded after a restart: the raw measurements are gone
                # but the fit survives — synthesize equivalent measured points
                # (fitting t(nominal) against nominal returns exactly t).
                from gerber2rml.doublesided import (layout_double_sided,
                                                    nominal_top_fiducials)
                lay = layout_double_sided(
                    self.state.gerber_dir,
                    offset=(self.state.place_x, self.state.place_y),
                    rotate=self.state.rotate, registration="fiducial",
                    fiducials=fid)
                measured = [self._top_fit.apply(x, y)
                            for (x, y) in nominal_top_fiducials(lay)]
            if not measured:
                QMessageBox.warning(
                    self, "Fiducial fit required",
                    "Registration is set to fiducial holes but no fit has been "
                    "measured yet, so there is no frame to export the top "
                    "traces in.\n\nRun 'Fit & export' (step 7 · Flip + align) "
                    "first — it measures the flipped board and exports in one "
                    "go.")
                return
            reg_kwargs = dict(registration="fiducial", fiducials=fid,
                              measured_fiducials=measured,
                              allow_scale=fid.allow_scale)
        out = self._pick_out_dir("Select output folder (same as the job)")
        if not out:
            return
        from gerber2rml.doublesided import build_top_traces
        try:
            path = build_top_traces(
                self.state.gerber_dir, out, self.state.name,
                trace=self.state.trace, dowels=self._dowel_spec(),
                machine=self.state.machine,
                offset=(self.state.place_x, self.state.place_y),
                rotate=self.state.rotate, level=level, **reg_kwargs)
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))
            return
        self.statusBar().showMessage(
            f"Wrote leveled {path.name}"
            + (" (fiducial fit applied)" if reg_kwargs else "")
            + " — run it (then the cut-out)", 10000)

    def _on_fiducial_align(self):
        """Fiducial top-side alignment: measure the flipped board's fiducials,
        fit the transform, and export the warped top traces. Run after milling the
        bottom, flipping and re-placing the board (no pins)."""
        if self.state.gerber_dir is None:
            QMessageBox.warning(self, "Nothing to export", "Load a Gerber folder first.")
            return
        if not self.double_sided_chk.isChecked() or self._registration_mode() != "fiducial":
            QMessageBox.warning(self, "Fiducial mode only",
                                "Enable double-sided and set Method to 'Fiducial holes'.")
            return
        self._sync_state()
        from gerber2rml.doublesided import layout_double_sided, nominal_top_fiducials
        fid = self._fiducial_spec_from_ui()
        lay = layout_double_sided(
            self.state.gerber_dir, offset=(self.state.place_x, self.state.place_y),
            rotate=self.state.rotate, registration="fiducial", fiducials=fid)
        nominal = nominal_top_fiducials(lay)
        dlg = _FiducialAlignDialog(self, nominal,
                                   initial=getattr(self, "_fid_measured", None))
        if dlg.exec() != QDialog.Accepted:
            return
        measured = dlg.measured()
        self._fid_measured = measured        # pre-fill the next run of this dialog
        from gerber2rml.doublesided import build_top_traces
        from gerber2rml.engine.fiducial import fit_transform, rms
        # Fit FIRST and remember it: from here the Top views render AS PLACED
        # (jog/snap/probe grid/rework/tracking follow the physical board) even
        # if the export below is postponed.
        try:
            t = fit_transform(nominal[:len(measured)], measured,
                              allow_scale=fid.allow_scale)
            err = rms(t, nominal[:len(measured)], measured)
        except Exception as e:
            QMessageBox.critical(self, "Fit failed", str(e))
            return
        self._top_fit = t
        self.generate_preview()
        # Intelligence: immediately verify the AS PLACED top job still fits the
        # machine's travel — BEFORE any probing time is invested.
        warn = self._travel_check(self._ds_side_toolpaths("traces", "Top"))
        if warn:
            QMessageBox.warning(self, "Board partly out of reach", warn)
        # XY comes from the fiducial fit; Z from a top-side height map when one
        # has been probed. Exporting unleveled on a warped bed can air-cut, so
        # make skipping it an explicit choice — the recommended path is to stop
        # here, probe (the grid now follows the placed board), and re-run this
        # dialog (your measurements are pre-filled).
        level = self._level_heightmap_preview()
        if level is None:
            if QMessageBox.question(
                    self, "No top-side height map",
                    "Fit stored — the Top views now show the board AS PLACED "
                    "and the probe grid will follow it.\n\nNo height map is "
                    "probed yet, so the top traces would be exported "
                    "UNLEVELED (air-cut risk on an uneven bed).\n\n"
                    "Recommended: No — probe the top now (Build grid, Clear Z, "
                    "Probe over SPI), then run Fit && export again (your "
                    "measurements are kept). Export unleveled anyway?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                    ) != QMessageBox.Yes:
                self.statusBar().showMessage(
                    "Fit stored (AS PLACED) — probe the top, then Fit & export "
                    "again; your fiducial measurements are pre-filled", 12000)
                return
        out = self._pick_out_dir("Select output folder (same as the job)")
        if not out:
            return
        try:
            path = build_top_traces(
                self.state.gerber_dir, out, self.state.name,
                trace=self.state.trace, machine=self.state.machine,
                offset=(self.state.place_x, self.state.place_y),
                rotate=self.state.rotate, registration="fiducial", fiducials=fid,
                measured_fiducials=measured, allow_scale=fid.allow_scale,
                level=level)
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))
            return
        self.statusBar().showMessage(
            f"Wrote {path.name} — fit RMS {err * 1000:.0f} um, "
            f"rot {math.degrees(t.theta):.3f} deg, scale {t.scale:.5f}"
            + (", leveled to the top probe" if level is not None
               else ", UNLEVELED")
            + " — Top views show the board AS PLACED", 12000)

    # ---- save / load the whole setup -----------------------------------
    def _collect_setup(self):
        """Snapshot every setting that defines the current job, as a JSON-able
        dict — including the probed height-map table, the expensive part."""
        import dataclasses
        self._sync_state()
        rows = []
        for r in range(self.level_table.rowCount()):
            rows.append([(self.level_table.item(r, c).text()
                          if self.level_table.item(r, c) else "") for c in range(3)])
        return {
            "version": 1,
            "gerber_dir": str(self.state.gerber_dir) if self.state.gerber_dir else None,
            "name": self.name_edit.text(),
            "machine": self.machine_combo.currentText(),
            "mirror": self.mirror_chk.isChecked(),
            "frame": self.frame_combo.currentIndex(),
            "show_bed": self.show_bed_chk.isChecked(),
            "place_x": self.place_x_spin.value(),
            "place_y": self.place_y_spin.value(),
            "rotation": self._rotation,
            "thickness": self.thickness_spin.value(),
            "auto_depth": self.auto_depth_chk.isChecked(),
            "breakthrough": self.breakthrough_spin.value(),
            "jobs": {op: dataclasses.asdict(self.forms[op].value()) for op in _OPS},
            "double_sided": self.double_sided_chk.isChecked(),
            "view": self.view_combo.currentIndex(),
            "reg": self.reg_combo.currentIndex(),
            "dowel_edge": self.place_combo.currentIndex(),
            "grid_pitch": self.grid_pitch_edit.text(),
            "grid_pin": self.grid_pin_edit.text(),
            "clr_large": self.fresh_clear_large_edit.text(),
            "clr_small": self.fresh_clear_small_edit.text(),
            "bed_bite": self.fresh_bed_spin.value(),
            "reg_method": self.regmethod_combo.currentIndex(),
            "overlay_trim": list(self._overlay_trim),
            "top_fit": ([self._top_fit.theta, self._top_fit.scale,
                         self._top_fit.tx, self._top_fit.ty]
                        if self._top_fit is not None else None),
            # raw fiducial measurements: prefill the align dialog and feed the
            # leveling-panel exporter across an app restart
            "fid_measured": [list(p) for p in
                             (getattr(self, "_fid_measured", None) or [])],
            "photo_overlay": self._photo_overlay,
            "photo_anchors": [list(p) for p in (self._photo_anchor_pts or [])],
            "rework": [{"bbox": list(r["bbox"]), "depth": r["depth"],
                        "follow": r.get("follow", True)}
                       for r in self._rework_regions],
            "fid": {"count": self.fid_count_spin.value(),
                    "place": self.fid_place_combo.currentIndex(),
                    "offset": self.fid_offset_spin.value(),
                    "scale": self.fid_scale_chk.isChecked(),
                    "flip": self.fid_flip_combo.currentIndex(),
                    "points": [list(p) for p in self._fid_points]},
            "stock": {"w": self.stock_w_spin.value(), "h": self.stock_h_spin.value(),
                      "x": self.stock_x_spin.value(), "y": self.stock_y_spin.value(),
                      "show": self.stock_show_chk.isChecked()},
            "level": {"nx": self.level_nx_spin.value(), "ny": self.level_ny_spin.value(),
                      "apply": self.level_chk.isChecked(), "rows": rows},
        }

    def _apply_setup(self, d, session_dir=None):
        """Restore a setup dict from :meth:`_collect_setup`. Tolerant of missing
        keys and renamed/removed job fields, so a setup survives a code update.
        ``session_dir`` (where the setup file lives) resolves the session-local
        photo copy when the original photo path is gone."""
        import dataclasses
        from gerber2rml.config import TraceJob, DrillJob, CutoutJob

        def _spin(sp, v):
            sp.blockSignals(True); sp.setValue(v); sp.blockSignals(False)

        def _chk(c, v):
            c.blockSignals(True); c.setChecked(bool(v)); c.blockSignals(False)

        def _combo(c, i):
            c.blockSignals(True); c.setCurrentIndex(int(i)); c.blockSignals(False)

        self.machine_combo.setCurrentText(d.get("machine", self.machine_combo.currentText()))
        _chk(self.mirror_chk, d.get("mirror", True))
        self.name_edit.setText(d.get("name", "board"))

        loaded = False
        gd = d.get("gerber_dir")
        if gd and Path(gd).is_dir():
            try:
                self.load_folder(gd); loaded = True
            except Exception as e:
                QMessageBox.warning(self, "Could not reload board", str(e))

        cls = {"traces": TraceJob, "drill": DrillJob, "cutout": CutoutJob}
        for op, jd in d.get("jobs", {}).items():
            if op in cls:
                known = {f.name for f in dataclasses.fields(cls[op])}
                try:
                    self.forms[op].set_instance(
                        cls[op](**{k: v for k, v in jd.items() if k in known}))
                except Exception:
                    pass

        _spin(self.place_x_spin, d.get("place_x", 0.0))
        _spin(self.place_y_spin, d.get("place_y", 0.0))
        self._rotation = int(d.get("rotation", 0)) % 360
        self.rotate_lbl.setText(f"{self._rotation}°")
        self.state.set_rotation(self._rotation)
        _spin(self.thickness_spin, d.get("thickness", 1.6))
        _chk(self.auto_depth_chk, d.get("auto_depth", True))
        _spin(self.breakthrough_spin, d.get("breakthrough", 0.1))
        _combo(self.frame_combo, d.get("frame", 0))
        _chk(self.show_bed_chk, d.get("show_bed", True))

        _combo(self.reg_combo, d.get("reg", 0))
        _combo(self.place_combo, d.get("dowel_edge", 0))
        self.grid_pitch_edit.setText(d.get("grid_pitch", "14.2"))
        self.grid_pin_edit.setText(d.get("grid_pin", "4.0"))
        self.fresh_clear_large_edit.setText(d.get("clr_large", "0.2"))
        self.fresh_clear_small_edit.setText(d.get("clr_small", "0.15"))
        _spin(self.fresh_bed_spin, d.get("bed_bite", 5.0))
        _combo(self.regmethod_combo, d.get("reg_method", 0))
        trim = d.get("overlay_trim", [0.0, 0.0])
        self._overlay_trim = (float(trim[0]), float(trim[1]))
        tf = d.get("top_fit")
        if tf:
            from gerber2rml.engine.fiducial import Transform
            self._top_fit = Transform(*[float(v) for v in tf])
        fm = d.get("fid_measured")
        if fm:
            self._fid_measured = [(float(x), float(y)) for x, y in fm]
        fd = d.get("fid", {})
        _spin(self.fid_count_spin, fd.get("count", 4))
        _combo(self.fid_place_combo, fd.get("place", 0))
        _spin(self.fid_offset_spin, fd.get("offset", 4.0))
        _chk(self.fid_scale_chk, fd.get("scale", False))
        _combo(self.fid_flip_combo, fd.get("flip", 0))
        self._fid_points = [list(p) for p in fd.get("points", [])]
        self.fid_offset_spin.setEnabled(self.fid_place_combo.currentIndex() != 2)
        _combo(self.view_combo, d.get("view", 0))
        _chk(self.double_sided_chk, d.get("double_sided", False))
        self._update_ds_controls()
        self.level_top_btn.setEnabled(self.double_sided_chk.isChecked())

        st = d.get("stock", {})
        for sp, k in ((self.stock_w_spin, "w"), (self.stock_h_spin, "h"),
                      (self.stock_x_spin, "x"), (self.stock_y_spin, "y")):
            _spin(sp, st.get(k, 0.0))
        _chk(self.stock_show_chk, st.get("show", False))

        lv = d.get("level", {})
        _spin(self.level_nx_spin, lv.get("nx", 3))
        _spin(self.level_ny_spin, lv.get("ny", 3))
        rows = lv.get("rows", [])
        self.level_table.setRowCount(len(rows))
        for r, cells in enumerate(rows):
            for c, txt in enumerate(cells[:3]):
                it = QTableWidgetItem(txt)
                if c < 2:
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.level_table.setItem(r, c, it)
        _chk(self.level_chk, lv.get("apply", False))

        self._apply_auto_depth()
        self._sync_vbit_fields()      # grey/derive V-bit fields + tool graphic
        self._update_stock_preview()
        self._update_grid_overlay()
        self._update_level_overlay()
        if loaded:
            self.generate_preview()
        # Rework boxes: restore with their per-box depths (colors reassigned).
        self._rework_regions = []
        for r in d.get("rework") or []:
            try:
                color = self._REWORK_COLORS[len(self._rework_regions)
                                            % len(self._REWORK_COLORS)]
                self._rework_regions.append({
                    "bbox": tuple(float(v) for v in r["bbox"]),
                    "depth": float(r.get("depth", 0.15)),
                    "follow": bool(r.get("follow", True)),
                    "color": color})
            except Exception:
                pass                  # one bad row never blocks the load
        self._refresh_rework()
        # Chosen photo-anchor holes: restored before the overlay so a re-shot
        # photo can be clicked against the same holes as the saved one.
        pa = [tuple(float(v) for v in p) for p in (d.get("photo_anchors") or [])]
        self._photo_anchor_pts = pa or None
        self.preview.set_photo_anchors(self._photo_anchor_pts)
        # Photo overlay: re-decode + re-fit from the saved anchor pairs. The
        # original path is tried first, then the session-local copy written
        # by Save setup (so setups survive the photo moving or being deleted).
        po = d.get("photo_overlay")
        if loaded and po:
            src = po.get("path")
            if not (src and Path(src).exists()):
                cp = po.get("photo_copy")
                src = (str(Path(session_dir) / cp)
                       if cp and session_dir and (Path(session_dir) / cp).exists()
                       else None)
            if src:
                try:
                    img = self._decode_photo(src)
                    self.photo_alpha_slider.setValue(
                        int(round(float(po.get("alpha", 0.55)) * 100)))
                    self.trace_dim_slider.setValue(
                        int(round(float(po.get("trace_alpha", 1.0)) * 100)))
                    self._apply_photo_overlay(img, po["photo_pts"],
                                              po["machine_pts"], src)
                    self._photo_overlay["photo_copy"] = po.get("photo_copy")
                except Exception:
                    pass              # a stale/moved photo never blocks a load
        self.statusBar().showMessage(
            "Setup loaded" if loaded else
            "Setup loaded (board not found — load the Gerber folder manually)", 10000)

    def _set_app_icon(self):
        """Window/taskbar icon: bundled asset in the installed app, the
        packaging copy in a dev checkout. The exe/desktop icon comes from the
        PyInstaller icon= (same artwork, packaging/gen_icon.py)."""
        import sys
        from PySide6.QtGui import QIcon
        candidates = []
        if hasattr(sys, "_MEIPASS"):
            candidates.append(Path(sys._MEIPASS) / "assets" / "srm-cam-256.png")
        candidates.append(Path(__file__).resolve().parents[2]
                          / "packaging" / "srm-cam-256.png")
        for p in candidates:
            if p.exists():
                self.setWindowIcon(QIcon(str(p)))
                return

    # ---- file-dialog helpers: start where the user last was ---------------
    def _dlg_dir(self, key, sub="exports"):
        """Start directory for a dialog: last-used for ``key``, else the
        workspace subfolder ``sub`` (Documents/SRM-CAM/<sub>)."""
        try:
            from gerber2rml.gui.workspace import remembered_dir
            return remembered_dir(key, sub)
        except Exception:
            return ""

    def _dlg_remember(self, key, path):
        try:
            from gerber2rml.gui.workspace import remember_dir
            remember_dir(key, path)
        except Exception:
            pass

    def _pick_dir(self, key, title, sub="exports"):
        d = QFileDialog.getExistingDirectory(self, title, self._dlg_dir(key, sub))
        if d:
            self._dlg_remember(key, d)
        return d

    def _pick_out_dir(self, title="Select output folder"):
        return self._pick_dir("out", title)

    def _on_save_setup(self):
        default = f"{self.name_edit.text() or 'board'}_setup.json"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save setup",
            str(Path(self._dlg_dir("session", "sessions")) / default),
            "Setup (*.json)")
        if not path:
            return
        try:
            self._write_setup(Path(path))
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))
            return
        self._dlg_remember("session", path)
        self.statusBar().showMessage(f"Saved setup to {Path(path).name}", 8000)

    def _write_setup(self, path):
        """Write the setup JSON to ``path``. If a photo overlay is active and
        its source file still exists, drop a copy next to the session so the
        setup remains self-contained even if the original photo moves."""
        import json
        import shutil
        d = self._collect_setup()
        po = d.get("photo_overlay")
        if po and po.get("path") and Path(po["path"]).is_file():
            src = Path(po["path"])
            copy_name = f"{path.stem}_photo{src.suffix.lower()}"
            dst = path.parent / copy_name
            try:
                if src.resolve() != dst.resolve():
                    shutil.copy2(src, dst)
                po["photo_copy"] = copy_name
                self._photo_overlay["photo_copy"] = copy_name
            except Exception:
                pass                    # photo copy is best-effort, never blocks
        path.write_text(json.dumps(d, indent=2), encoding="utf-8")

    def _on_load_setup(self):
        import json
        path, _ = QFileDialog.getOpenFileName(
            self, "Load setup", self._dlg_dir("session", "sessions"),
            "Setup (*.json)")
        if not path:
            return
        try:
            d = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as e:
            QMessageBox.critical(self, "Load failed", str(e))
            return
        self._dlg_remember("session", path)
        self._apply_setup(d, session_dir=Path(path).parent)

    def _diag_bounds(self):
        """Placed job bounds (board + dowels) in the cut/machine frame, for the
        bed-fit check. Includes both sides' outlines for double-sided."""
        if self.double_sided_chk.isChecked():
            mlay = self._machine_layout()
            xs = [mlay.outline.bounds, mlay.top_outline.bounds]
            x0 = min(b[0] for b in xs); y0 = min(b[1] for b in xs)
            x1 = max(b[2] for b in xs); y1 = max(b[3] for b in xs)
            holes = mlay.align_holes
        else:
            x0, y0, x1, y1 = self.state.board.outline.bounds
            holes = self.state.board.holes
        for hx, hy, hd in holes:
            r = max(hd, 0.1) / 2.0
            x0, y0 = min(x0, hx - r), min(y0, hy - r)
            x1, y1 = max(x1, hx + r), max(y1, hy + r)
        return (x0, y0, x1, y1)

    def _on_diagnostics(self):
        """Run pre-flight checks (bed fit, Z reach, holes vs bit) and show them."""
        if self.state.board is None:
            QMessageBox.warning(self, "No board", "Load a Gerber folder first.")
            return
        self._sync_state()
        from gerber2rml.engine.diagnostics import (cut_depths, preflight,
                                                   format_report, worst)
        dowel_depth = None
        if self.double_sided_chk.isChecked() and self._dowel_spec().mode == "fresh":
            dowel_depth = self.thickness_spin.value() + self.fresh_bed_spin.value()
        depths = cut_depths(self.state.trace, self.state.drill, self.state.cutout,
                            dowel_depth)
        holes = (self._machine_layout().holes if self.double_sided_chk.isChecked()
                 else self.state.board.holes)
        leveled = (self.level_chk.isChecked()
                   and self._level_heightmap_preview() is not None)
        checks = preflight(depths=depths, bed=BACKENDS[self.state.machine].bed,
                           design_bounds=self._diag_bounds(), surface_z=self._z_zero,
                           holes=holes, bit_diameter=self.state.drill.bit_diameter,
                           trace=self.state.trace, leveled=leveled)
        lvl = worst(checks)
        box = QMessageBox(self)
        box.setWindowTitle("Pre-flight diagnostics")
        box.setIcon({"ok": QMessageBox.Information, "warn": QMessageBox.Warning,
                     "fail": QMessageBox.Critical}[lvl])
        box.setText("Pre-flight checks — "
                    + {"ok": "all clear", "warn": "review the warnings",
                       "fail": "FIX before cutting"}[lvl])
        box.setInformativeText(format_report(checks))
        box.exec()
        self.statusBar().showMessage(f"Diagnostics: {lvl.upper()}", 8000)

    def _on_export_image(self):
        if self.state.board is None:
            QMessageBox.warning(self, "Nothing to export", "Load a Gerber folder first.")
            return
        out = self._pick_out_dir()
        if out:
            try:
                png = self.export_image_to(out)
            except Exception as e:
                QMessageBox.critical(self, "Export failed", str(e))
                return
            self.statusBar().showMessage(f"Saved {png.name} + summary", 8000)

    def _drill_toolpaths(self, holes):
        """All drilling as one flat toolpath list, matching the exported files
        (honours single-bit interpolation / per-diameter plunging)."""
        from gerber2rml.engine.drill import drill_jobs
        return [tp for _fname, paths in drill_jobs(holes, self.state.drill, "x")
                for tp in paths]

    def _toolpaths_for(self, op):
        """Bed/machine-frame toolpaths for ``op`` in the current mode (the same
        frame the preview and the live DRO marker use)."""
        if self.double_sided_chk.isChecked():
            side = self._ds_side()
            if side is not None and op != "drill":
                # single side: machine-frame paths for that side (matches preview)
                return self._ds_side_toolpaths(op, side)
            from gerber2rml.engine.traces import isolate
            from gerber2rml.engine.cutout import cut_outline
            lay = self._double_sided_layout()
            if op == "traces":
                return isolate(lay.bottom_copper, self.state.trace,
                               outline=lay.outline)
            if op == "cutout":
                return cut_outline(lay.outline, self.state.cutout)
            return self._drill_toolpaths(lay.holes)
        if op == "drill":
            return self._drill_toolpaths(self.state.board.holes)
        return self.state.toolpaths(op)

    def _job_for_op(self, op):
        """The job config (feeds/depths) for ``op``."""
        return {"traces": self.state.trace, "drill": self.state.drill,
                "cutout": self.state.cutout}[op]

    def _current_toolpaths(self):
        """(op, toolpaths) for the active tab/mode -- what the preview shows."""
        op = _OPS[self.tabs.currentIndex()]
        return op, self._toolpaths_for(op)

    def _sim_board_bounds(self):
        """PCB outline bounds (x0, y0, x1, y1) for the side currently shown, so
        the 3D viewer can draw the stock slab the cuts go into. None if no board."""
        if self.state.board is None:
            return None
        if self.double_sided_chk.isChecked():
            mlay = self._machine_layout()
            outline = mlay.top_outline if self._ds_side() == "Top" else mlay.outline
            return tuple(outline.bounds)
        return tuple(self.state.board.outline.bounds)

    def _open_sim_window(self, toolpaths, label, board=None, bed=None, thickness=1.6):
        try:
            from gerber2rml.gui.sim3d import Simulation3DWindow
        except Exception as e:
            QMessageBox.critical(
                self, "3D unavailable",
                f"3D simulation needs pyqtgraph + PyOpenGL installed.\n\n{e}")
            return
        # Top-level window (no parent). A QMainWindow parented to another
        # QMainWindow with an embedded QOpenGLWidget renders fine in an
        # offscreen grab but can come up blank on screen; a parentless window
        # matches the path that's known to render. self._sim_window keeps the
        # reference so it isn't garbage-collected.
        self._sim_window = Simulation3DWindow(toolpaths, title=label,
                                              board=board, bed=bed, thickness=thickness)
        self._sim_window.set_live_enabled(self._dro is not None)
        self._sim_window.show()
        self._sim_window.raise_()
        self._sim_window.activateWindow()

    def _on_simulate_file(self):
        from pathlib import Path
        from gerber2rml.engine.gcode_parse import parse_file
        path, _ = QFileDialog.getOpenFileName(
            self, "Open toolpath file to simulate", self._dlg_dir("out"),
            "Toolpath files (*.nc *.rml *.gcode *.g);;All files (*)")
        if not path:
            return
        self._dlg_remember("out", path)
        try:
            toolpaths = parse_file(path)
        except Exception as e:
            QMessageBox.critical(self, "Could not read file", str(e))
            return
        if not toolpaths or not any(toolpaths):
            QMessageBox.information(self, "Nothing to simulate",
                                    "No tool moves found in that file.")
            return
        self._open_sim_window(toolpaths, f"{Path(path).name} (3D)")

    def _on_simulate_3d(self):
        if self.state.board is None:
            QMessageBox.warning(self, "Nothing to simulate", "Load a Gerber folder first.")
            return
        self._sync_state()
        op, toolpaths = self._current_toolpaths()
        label = op
        # active rework regions on a clippable op -> simulate just those parts.
        # Double-sided is reworkable only when a single side (Bottom/Top) is
        # shown; _current_toolpaths already returns that side's machine paths.
        ds = self.double_sided_chk.isChecked()
        if self._rework_regions and op != "drill" and (not ds or self._ds_side() is not None):
            clipped, _leveled = self._rework_clip_regions(toolpaths)
            if clipped:
                toolpaths, label = clipped, f"{op} rework"
        if not toolpaths:
            QMessageBox.information(self, "Nothing to simulate",
                                    "No toolpaths for this view.")
            return
        bed = BACKENDS[self.state.machine].bed if self.show_bed_chk.isChecked() else None
        self._open_sim_window(toolpaths, f"{self.state.name} - {label} (3D)",
                              board=self._sim_board_bounds(), bed=bed,
                              thickness=self.thickness_spin.value())

    def _on_select_toggled(self, checked):
        self.preview.set_selecting(checked)
        if checked:
            self.move_chk.setChecked(False)   # rework-select and move are exclusive
            self.measure_chk.setChecked(False)
            self.align_btn.setChecked(False)
            self.statusBar().showMessage(
                "Rework: drag a box over the area to re-cut, then Export selected NC",
                8000)

    def _on_rotate(self):
        """Rotate the whole job another 90° (reorients the exported cut). Works
        for single- and double-sided (the dowels rotate with the board)."""
        if self.state.board is None:
            QMessageBox.warning(self, "No board", "Load a Gerber folder first.")
            return
        self._rotation = (self._rotation + 90) % 360
        self.rotate_lbl.setText(f"{self._rotation}°")
        self.state.set_rotation(self._rotation)
        self.generate_preview()
        self.statusBar().showMessage(f"Rotated to {self._rotation}°", 4000)

    def _on_measure_toggled(self, checked):
        self.preview.set_measuring(checked)
        if checked:                           # ruler is exclusive with the drag modes
            self.select_chk.setChecked(False)
            self.move_chk.setChecked(False)
            self.align_btn.setChecked(False)
            if self.jog_chk.isChecked():
                self.jog_chk.setChecked(False)
            self.statusBar().showMessage(
                "Ruler: drag from one board corner to another - it snaps to "
                "edges and hole centres", 8000)

    def _apply_auto_depth(self):
        """When auto-depth is on, set the drill + cut-out total depth from the
        measured stock thickness (+ breakthrough) and lock those fields."""
        auto = self.auto_depth_chk.isChecked()
        self.breakthrough_spin.setEnabled(auto)
        total = round(self.thickness_spin.value() + self.breakthrough_spin.value(), 3)
        for op in ("drill", "cutout"):
            form = self.forms[op]
            if auto:
                form.set_field_value("total_depth", total)
            form.enable_field("total_depth", not auto)

    def _on_depth_source_changed(self, *_):
        self._apply_auto_depth()
        self.generate_preview()

    def _sync_vbit_fields(self, *_):
        """For a V-bit, the cut depth and effective width are DERIVED from the
        target width, so grey those fields out and mirror the computed values
        into them. For a flat endmill, leave everything editable (the original
        behaviour). Uses ``set_field_value`` so this never re-fires valueChanged."""
        form = self.forms["traces"]
        job = form.value()
        vbit = job.tool_type == "vbit"
        # cut_depth and bit_diameter are meaningless for a vbit -> derived/greyed.
        form.enable_field("cut_depth", not vbit)
        form.enable_field("bit_diameter", not vbit)
        # tip/angle/target only matter for a vbit.
        for name in ("tip_diameter", "included_angle", "target_width"):
            form.enable_field(name, vbit)
        if vbit:
            form.set_field_value("cut_depth", round(job.effective_cut_depth(), 3))
            form.set_field_value("bit_diameter", round(job.effective_diameter(), 3))
        self.bit_viz.set_job(job)          # keep the tool cross-section live

    def _on_move_toggled(self, checked):
        self.preview.set_moving(checked)
        if checked:
            self.select_chk.setChecked(False)
            self.measure_chk.setChecked(False)
            self.align_btn.setChecked(False)
            self.statusBar().showMessage(
                "Move: drag the design to reposition it on the bed", 8000)

    def _on_move_delta(self, dx, dy):
        """Drag committed in the preview -> fold the shift into the placement."""
        self.place_x_spin.blockSignals(True)
        self.place_x_spin.setValue(self.place_x_spin.value() + dx)  # spinbox clamps to range
        self.place_x_spin.blockSignals(False)
        # setting Y triggers a single regenerate_preview at the new placement
        self.place_y_spin.setValue(self.place_y_spin.value() + dy)

    # ---- copper stock alignment -----------------------------------------
    def _update_stock_preview(self, *_):
        """Push the measured copper rectangle to the preview (or hide it)."""
        if not self.stock_show_chk.isChecked():
            self.preview.set_stock(None)
            return
        self.preview.set_stock((self.stock_x_spin.value(), self.stock_y_spin.value(),
                                self.stock_w_spin.value(), self.stock_h_spin.value()))

    def _on_stock_corner_from_tool(self):
        """Capture the live tool XY as the copper's front-left corner."""
        if self._tool_xyz is None:
            self.statusBar().showMessage(
                "Connect the machine and jog the bit to the copper corner first", 6000)
            return
        x, y, _z = self._tool_xyz
        self.stock_x_spin.setValue(max(0.0, x))     # valueChanged -> _update_stock_preview
        self.stock_y_spin.setValue(max(0.0, y))
        self.stock_show_chk.setChecked(True)
        self.statusBar().showMessage(f"Copper corner set to X {x:.1f}  Y {y:.1f}", 6000)

    def _job_bounds(self):
        """Bounds of everything that lands on the copper (board + dowels) in the
        currently displayed frame, or None."""
        o = self._display_outline()
        if o is None or o.is_empty:
            return None
        x0, y0, x1, y1 = o.bounds
        if self.double_sided_chk.isChecked():
            lay = self._machine_layout() if self._ds_side() else self._double_sided_layout()
            for (hx, hy, hd) in lay.align_holes:
                r = max(hd, 0.1) / 2.0
                x0, y0 = min(x0, hx - r), min(y0, hy - r)
                x1, y1 = max(x1, hx + r), max(y1, hy + r)
        return (x0, y0, x1, y1)

    def _on_center_design_on_stock(self):
        """Shift the placement so the job is centred on the copper stock."""
        if self.state.board is None:
            QMessageBox.warning(self, "No board", "Load a Gerber folder first.")
            return
        if self.stock_w_spin.value() <= 0 or self.stock_h_spin.value() <= 0:
            QMessageBox.warning(self, "No stock size",
                                "Enter the copper width and height first.")
            return
        jb = self._job_bounds()
        if jb is None:
            return
        cx, cy = (jb[0] + jb[2]) / 2.0, (jb[1] + jb[3]) / 2.0
        tx = self.stock_x_spin.value() + self.stock_w_spin.value() / 2.0
        ty = self.stock_y_spin.value() + self.stock_h_spin.value() / 2.0
        self.place_x_spin.blockSignals(True)
        self.place_x_spin.setValue(self.place_x_spin.value() + (tx - cx))
        self.place_x_spin.blockSignals(False)
        self.place_y_spin.setValue(self.place_y_spin.value() + (ty - cy))
        self.statusBar().showMessage("Design centred on the copper stock", 5000)

    def _on_region_added(self, bbox):
        """A drag committed a box -> add a region at the current defaults."""
        color = self._REWORK_COLORS[len(self._rework_regions) % len(self._REWORK_COLORS)]
        self._rework_regions.append({
            "bbox": bbox, "depth": self.rework_depth_spin.value(),
            "follow": self.rework_level_chk.isChecked(), "color": color})
        self._refresh_rework()

    def _clear_rework(self):
        self._rework_regions = []
        self._refresh_rework()

    # ---- rework photo overlay -------------------------------------------
    @staticmethod
    def _decode_photo(path, max_dim=2400):
        """Image file -> HxWx4 uint8 RGBA. Downscaled so anchor clicks stay
        snappy; the SAME array is used for clicking and warping, so the
        homography is consistent whatever the original resolution."""
        from PySide6.QtGui import QImage
        import numpy as np
        img = QImage(str(path))
        if img.isNull():
            raise ValueError(f"could not read image: {path}")
        if max(img.width(), img.height()) > max_dim:
            img = img.scaled(max_dim, max_dim, Qt.KeepAspectRatio,
                             Qt.SmoothTransformation)
        img = img.convertToFormat(QImage.Format_RGBA8888)
        h, w, bpl = img.height(), img.width(), img.bytesPerLine()
        buf = np.frombuffer(img.constBits(), np.uint8, count=h * bpl)
        return buf.reshape(h, bpl)[:, :w * 4].reshape(h, w, 4).copy()

    def _displayed_holes(self):
        """Every drilled feature available in the current view as (x, y, d) —
        the board's own holes (drawn or carried as reference data) AND any
        dowel/fiducial pins, in the SAME frame the preview draws (AS PLACED on
        a fitted top side), so a photo anchored on them lines up with what you
        see."""
        out, seen = [], set()
        for h in (list(self.preview._full_holes or [])
                  + list(getattr(self.preview, "_ref_holes", None) or [])
                  + list(self.preview._pins or [])):
            key = (round(h[0], 4), round(h[1], 4))
            if key not in seen:
                seen.add(key)
                out.append(h)
        return out

    def _photo_anchor_holes(self):
        """The photo anchors as [(label, (x, y)), ...]: the operator's own
        picks when they chose some (Anchors...), else the 4 corner-most
        displayed holes."""
        chosen = self._photo_anchors_from_picks()
        if chosen:
            return chosen
        holes = [(x, y) for (x, y, _d) in self._displayed_holes()]
        if len(holes) < 4:
            return None
        corners = [max(holes, key=lambda p: -p[0] - p[1]),   # bottom-left
                   max(holes, key=lambda p: p[0] - p[1]),    # bottom-right
                   max(holes, key=lambda p: p[0] + p[1]),    # top-right
                   max(holes, key=lambda p: -p[0] + p[1])]   # top-left
        if len(set(corners)) < 4:
            return None
        names = ("bottom-left", "bottom-right", "top-right", "top-left")
        return list(zip(names, corners))

    def _photo_anchors_from_picks(self):
        """The operator-picked anchors, re-snapped to the holes the preview is
        showing right now (the frame changes with the view/side, so the stored
        points are re-matched rather than trusted). None when nothing was
        picked or the picks no longer match this view."""
        picks = getattr(self, "_photo_anchor_pts", None)
        if not picks:
            return None
        holes = self._displayed_holes()
        if not holes:
            return None
        out = []
        for (px, py) in picks:
            hx, hy, d = min(holes, key=lambda h: math.hypot(h[0] - px, h[1] - py))
            if math.hypot(hx - px, hy - py) > 0.25:     # different frame/board
                return None
            out.append((f"hole {len(out) + 1} (\N{LATIN CAPITAL LETTER O WITH STROKE}"
                        f"{d:.2f} mm)", (hx, hy)))
        return out if len(out) >= 4 else None

    def _on_pick_photo_anchors(self):
        """Choose which drilled holes anchor the photo. Fiducial/dowel holes
        only exist on double-sided jobs — for single-sided rework any 4+
        ordinary drill holes work, as long as they're ones you can find again
        in the photo."""
        if self.state.board is None:
            QMessageBox.warning(self, "No board", "Load a Gerber folder first.")
            return
        holes = self._displayed_holes()
        if len(holes) < 4:
            QMessageBox.warning(
                self, "No holes",
                "This board has fewer than 4 drilled holes in the preview, so "
                "there is nothing to anchor a photo on. Drill a few registration "
                "holes in the waste, or use double-sided fiducials.")
            return
        from gerber2rml.gui.photodlg import HolePickDialog
        dlg = HolePickDialog(self, holes, self.preview._outline_xy,
                             preset=getattr(self, "_photo_anchor_pts", None))
        if dlg.exec() != QDialog.Accepted:
            return
        anchors = dlg.anchors()
        self._photo_anchor_pts = [p for _n, p in anchors]
        self.preview.set_photo_anchors(self._photo_anchor_pts)
        self.statusBar().showMessage(
            f"{len(anchors)} anchor holes chosen (numbered on the preview) — "
            "load the photo and click them in that order", 10000)

    def _on_clear_photo_anchors(self):
        self._photo_anchor_pts = None
        self.preview.set_photo_anchors(None)

    def _photo_flow_anchors(self):
        """Shared preconditions for every photo source; None = not ready."""
        if self.state.board is None:
            QMessageBox.warning(self, "No board", "Load a Gerber folder first.")
            return None
        anchors = self._photo_anchor_holes()
        if not anchors:
            QMessageBox.warning(
                self, "No anchors",
                "Need at least 4 distinct drilled holes in the preview to "
                "anchor a photo. Show the Traces, Drill or Cutout preview — "
                "and if the auto-picked corner holes are hard to spot in the "
                "photo, use <b>Anchors...</b> to choose your own.")
            return None
        return anchors

    def _on_load_photo(self):
        anchors = self._photo_flow_anchors()
        if anchors is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Board photo", self._dlg_dir("photo", "photos"),
            "Images (*.jpg *.jpeg *.png *.bmp)")
        if not path:
            return
        self._dlg_remember("photo", path)
        self._run_photo_anchor_flow(path, anchors)

    def _on_phone_photo(self):
        anchors = self._photo_flow_anchors()
        if anchors is None:
            return
        from gerber2rml.gui.phonephoto import PhonePhotoDialog
        from gerber2rml.gui.workspace import workspace_root
        dlg = PhonePhotoDialog(self, workspace_root() / "photos")
        if dlg.exec() != QDialog.Accepted or not dlg.photo_path:
            return
        path = self._autocrop_photo_file(dlg.photo_path)
        if path != dlg.photo_path:
            self.statusBar().showMessage(
                "Auto-cropped the photo to the copper board", 5000)
        self._run_photo_anchor_flow(path, anchors)

    def _autocrop_photo_file(self, path):
        """Crop a raw phone photo to the copper stock (the phone shot has the
        whole machine in frame). Writes <name>_crop.jpg at FULL resolution
        next to the original — full res matters: Detect-from-photo re-reads
        the file at native resolution. Falls back to the original path when
        no convincing board is found (odd lighting, already cropped)."""
        try:
            from gerber2rml.engine.autocrop import copper_bbox
            box = copper_bbox(self._decode_photo(path, max_dim=1000))
            if box is None:
                return path
            x0, y0, x1, y1 = box
            if (x1 - x0) * (y1 - y0) > 0.90:     # already basically the board
                return path
            from PySide6.QtCore import QRect
            from PySide6.QtGui import QImage
            img = QImage(str(path))
            if img.isNull():
                return path
            w, h = img.width(), img.height()
            rect = QRect(int(x0 * w), int(y0 * h),
                         max(1, round((x1 - x0) * w)),
                         max(1, round((y1 - y0) * h)))
            out = Path(path).with_name(Path(path).stem + "_crop.jpg")
            if img.copy(rect).save(str(out), "JPG", 92):
                return str(out)
        except Exception:
            pass                                  # any hiccup -> use the raw
        return path

    def _run_photo_anchor_flow(self, path, anchors):
        try:
            img = self._decode_photo(path)
        except Exception as e:
            QMessageBox.critical(self, "Photo failed", str(e))
            return
        from gerber2rml.gui.photodlg import PhotoAnchorDialog
        # the design map beside the photo: with ordinary drill holes as
        # anchors, "machine X 43.2 Y 18.7" is not something you can find on a
        # board by eye — the map shows exactly which hole is being asked for
        dlg = PhotoAnchorDialog(self, img, anchors,
                                board={"holes": self._displayed_holes(),
                                       "outline": self.preview._outline_xy})
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            worst = self._apply_photo_overlay(
                img, dlg.photo_points(), [p for _n, p in anchors], path)
        except Exception as e:
            QMessageBox.critical(self, "Fit failed", str(e))
            return
        msg = f"Photo aligned — worst anchor residual {worst * 1000:.0f} um"
        if worst > 0.8:
            QMessageBox.warning(
                self, "Rough fit",
                msg + ".\n\nA residual that big usually means one click "
                "missed its hole. Load the photo again and re-click "
                "(right-click undoes a click).")
        self.statusBar().showMessage(msg, 8000)

    def _apply_photo_overlay(self, img, photo_pts, machine_pts, path=""):
        """Fit photo->machine homography, warp, and show under the preview.
        Returns the worst anchor residual (mm). Factored out of the dialog
        flow so a restore (or a test) can re-apply saved anchor pairs."""
        from gerber2rml.engine.photofit import (fit_homography, residuals,
                                                warp_photo)
        H = fit_homography(photo_pts, machine_pts)
        res = residuals(H, photo_pts, machine_pts)
        db = self.preview._design_bounds()
        if db is None:
            bed = BACKENDS[self.state.machine].bed or (203.2, 152.4)
            db = (0.0, 0.0, bed[0], bed[1])
        m = 5.0
        rgba, extent = warp_photo(img, H, (db[0] - m, db[1] - m,
                                           db[2] + m, db[3] + m))
        alpha = self.photo_alpha_slider.value() / 100.0
        self.preview.set_photo(rgba, extent, alpha)
        self._photo_overlay = {"path": str(path),
                               "photo_pts": [list(p) for p in photo_pts],
                               "machine_pts": [list(p) for p in machine_pts],
                               "alpha": alpha,
                               "trace_alpha": self.trace_dim_slider.value() / 100.0}
        return float(res.max())

    def _on_clear_photo(self):
        self._photo_overlay = None
        self.preview.set_photo(None)
        self.trace_dim_slider.setValue(100)   # nothing to see through anymore

    def _on_photo_alpha(self, v):
        if self._photo_overlay:
            self._photo_overlay["alpha"] = v / 100.0
        self.preview.set_photo_alpha(v / 100.0)

    def _on_trace_dim(self, v):
        if self._photo_overlay:
            self._photo_overlay["trace_alpha"] = v / 100.0
        self.preview.set_trace_alpha(v / 100.0)

    def _on_feed_card(self):
        """Feed-ladder card: export the NC, or score a photo of the cut card."""
        box = QMessageBox(QMessageBox.Question, "Feed card",
                          "The feed-ladder card mills the same isolation "
                          "pattern at 4/6/8/10/12/15 mm/s on scrap (needs "
                          "~50 x 40 mm from X18.6 Y18.6). Cut it, photograph "
                          "it, and Score recommends the fastest clean feed.",
                          QMessageBox.Cancel, self)
        exp = box.addButton("Export card NC…", QMessageBox.AcceptRole)
        sco = box.addButton("Score card photo…", QMessageBox.ActionRole)
        box.exec()
        if box.clickedButton() is exp:
            self._export_feed_card()
        elif box.clickedButton() is sco:
            self._score_feed_card()

    def _export_feed_card(self):
        from gerber2rml.engine.testcard import render_feed_ladder
        out = self._pick_out_dir("Select output folder for the feed card")
        if not out:
            return
        try:
            text, bbox = render_feed_ladder(plunge_feed=2.0)
        except Exception as e:
            QMessageBox.critical(self, "Feed card failed", str(e))
            return
        path = Path(out) / "feed_testcard.nc"
        path.write_text(text)
        self.statusBar().showMessage(
            f"Wrote {path.name} — scrap must cover X {bbox[0]:.1f}..{bbox[2]:.1f} "
            f"Y {bbox[1]:.1f}..{bbox[3]:.1f}, zero Z on the scrap surface", 15000)

    def _score_feed_card(self):
        from gerber2rml.engine.cutcheck import CutCheckError
        from gerber2rml.engine.feedscore import score_feed_card
        from gerber2rml.engine.photofit import fit_homography, warp_photo
        from gerber2rml.engine.testcard import feed_ladder_layout
        path, _ = QFileDialog.getOpenFileName(
            self, "Photo of the CUT feed card", self._dlg_dir("photo", "photos"),
            "Images (*.jpg *.jpeg *.png *.bmp)")
        if not path:
            return
        self._dlg_remember("photo", path)
        try:
            img = self._decode_photo(path)
        except Exception as e:
            QMessageBox.critical(self, "Could not read image", str(e))
            return
        blocks, anchors = feed_ladder_layout()
        from gerber2rml.gui.photodlg import PhotoAnchorDialog
        dlg = PhotoAnchorDialog(self, img, anchors)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            H = fit_homography(dlg.photo_points(), [p for _n, p in anchors])
            xs = [p for b in blocks for p in (b["ring"][0],)]
            x0 = min(min(b["serpentine"][0][0] for b in blocks), min(xs)) - 4
            x1 = max(max(p[0] for b in blocks for p in b["serpentine"]), max(xs)) + 4
            y0 = min(b["serpentine"][0][1] for b in blocks) - 4
            y1 = max(b["ring"][1] for b in blocks) + 8
            rgba, extent = warp_photo(img, H, (x0, y0, x1, y1))
            r = score_feed_card(rgba, extent, blocks)
        except CutCheckError as e:
            QMessageBox.warning(self, "Can't judge this photo", str(e))
            return
        except Exception as e:
            QMessageBox.critical(self, "Scoring failed", str(e))
            return
        lines = [f"{b['feed']:>5.1f} mm/s   channel cut {b['cut'] * 100:5.1f}%   "
                 f"land intact {b['land'] * 100:5.1f}%"
                 for b in sorted(r["blocks"], key=lambda b: b["feed"])]
        rec = (f"\nRecommended XY feed: {r['recommended']:.0f} mm/s"
               if r["recommended"] is not None else
               "\nNo block is clearly clean — check the photo/lighting.")
        QMessageBox.information(self, "Feed card score",
                                "\n".join(lines) + "\n" + rec)
        if r["recommended"] is not None:
            self.statusBar().showMessage(
                f"Feed card: use {r['recommended']:.0f} mm/s (set it in the "
                f"traces job form)", 15000)

    def _on_probe_rework_boxes(self):
        """Probe each rework box center over SPI and deepen boxes where the
        real surface sits higher than the mesh believed (the exact failure
        that caused the rework in the first place)."""
        if not self._rework_regions:
            QMessageBox.information(self, "No boxes", "Draw rework boxes first.")
            return
        if self._level_heightmap_preview() is None:
            QMessageBox.information(
                self, "No mesh",
                "The comparison needs the bed-leveling mesh loaded (the rework "
                "export uses it, so probe or load it first).")
            return
        it0x = self.level_table.item(0, 0)
        it0y = self.level_table.item(0, 1)
        if it0x is None or it0y is None:
            QMessageBox.information(self, "No reference",
                                    "Leveling table has no reference point.")
            return
        x0, y0 = float(it0x.text()), float(it0y.text())
        points = [(0, 0, 0)]
        for i, r in enumerate(self._rework_regions):
            bx0, by0, bx1, by1 = r["bbox"]
            cx, cy = (bx0 + bx1) / 2.0, (by0 + by1) / 2.0
            points.append((i + 1, round((cx - x0) * 1000),
                           round((cy - y0) * 1000)))
        port = self.level_port_combo.currentText().strip() or "COM5"
        if QMessageBox.question(
                self, "Probe rework boxes",
                f"Jog the tool ~2-3 mm above the MESH REFERENCE point "
                f"(X{x0:.1f} Y{y0:.1f} — leveling grid point 1), spindle OFF, "
                f"prober running.\n\nProbe the reference + "
                f"{len(self._rework_regions)} box center(s) on {port}?"
                ) != QMessageBox.Yes:
            return
        self._dro_was_on = self._pause_dro()
        self._rework_probe_results = []
        self.statusBar().showMessage("Probing rework box centers…")
        self._rework_probe_worker = _ProbeWorker(port, points)
        self._rework_probe_worker.result.connect(
            lambda d: self._rework_probe_results.append(d))
        self._rework_probe_worker.done.connect(self._on_rework_probe_done)
        self._rework_probe_worker.start()

    def _on_rework_probe_done(self, err):
        if self._dro_was_on:
            self._dro_was_on = False
            self._start_dro()
        if err and not err.startswith("missed:"):
            QMessageBox.warning(self, "Probe failed", err)
            return
        n = self._apply_rework_probe(self._rework_probe_results)
        if n is None:
            return
        adjusted, skipped = n
        msg = (f"Rework boxes probed: {len(adjusted)} deepened to match the "
               f"real surface" if adjusted else
               "Rework boxes probed: mesh already matches the real surface")
        if skipped:
            msg += f" ({skipped} box(es) had no contact — unchanged)"
        QMessageBox.information(self, "Probe rework boxes", msg)
        self.statusBar().showMessage(msg, 12000)

    def _apply_rework_probe(self, results, min_delta=0.005):
        """Compare measured box-center dz against the mesh and deepen boxes
        where the surface is HIGHER than modeled (never shallower — the goal
        is a guaranteed through-cut). Returns (adjusted list, skipped count)."""
        by_id = {r["id"]: r["z"] for r in results if r.get("z") is not None}
        if 0 not in by_id:
            QMessageBox.warning(self, "No reference",
                                "The reference point had no contact — nothing "
                                "was adjusted.")
            return None
        hmap = self._level_heightmap_preview()
        z0 = by_id[0]
        adjusted, skipped = [], 0
        for i, r in enumerate(self._rework_regions):
            zid = i + 1
            if zid not in by_id:
                skipped += 1
                continue
            bx0, by0, bx1, by1 = r["bbox"]
            cx, cy = (bx0 + bx1) / 2.0, (by0 + by1) / 2.0
            measured = (by_id[zid] - z0) / 1000.0
            modeled = float(hmap(cx, cy)) if hmap is not None else 0.0
            delta = measured - modeled
            if delta > min_delta:
                r["depth"] = round(r["depth"] + delta, 3)
                adjusted.append((i, delta))
        self._refresh_rework()
        return adjusted, skipped

    def _on_detect_rework(self):
        """Propose rework boxes from the aligned photo: channel stretches that
        still look like copper become boxes at the current New-box depth."""
        from gerber2rml.engine.cutcheck import CutCheckError, detect_uncut
        if self.preview._photo is None:
            QMessageBox.information(
                self, "No photo",
                "Load and align a board photo first (Photo row above).")
            return
        channels = [list(seg) for seg in (list(self.preview._full_cuts)
                                          + list(self.preview._full_top_cuts))
                    if len(seg) >= 2]
        if not channels:
            QMessageBox.information(
                self, "No toolpaths",
                "Generate the traces preview first — the detector walks its "
                "isolation channels.")
            return
        # The profile classifier needs the FULL-RESOLUTION photo: re-warp from
        # the original file at 16 px/mm (the preview overlay is downscaled and
        # the cross-profile signature dies with it).
        po = self._photo_overlay
        src = po.get("path") if po else None
        if not (src and Path(src).exists()):
            QMessageBox.information(
                self, "Original photo needed",
                "The detector reads the photo at full resolution, but the "
                "original file isn't reachable. Load the photo again "
                "(Load photo…) and retry.")
            return
        from gerber2rml.engine.photofit import fit_homography, warp_photo
        try:
            img_small = self._decode_photo(src)
            img_full = self._decode_photo(src, max_dim=100000)
            scale = img_full.shape[1] / img_small.shape[1]
            H = fit_homography([(u * scale, v * scale)
                                for (u, v) in po["photo_pts"]],
                               po["machine_pts"])
            db = self.preview._design_bounds()
            if db is None:
                bed = BACKENDS[self.state.machine].bed or (203.2, 152.4)
                db = (0.0, 0.0, bed[0], bed[1])
            rgba, extent = warp_photo(img_full, H,
                                      (db[0] - 2, db[1] - 2,
                                       db[2] + 2, db[3] + 2), px_per_mm=16)
        except Exception as e:
            QMessageBox.critical(self, "Photo processing failed", str(e))
            return
        bit = float(self.forms["traces"].value().bit_diameter)
        try:
            r = detect_uncut(rgba, extent, channels, bit_d=max(bit, 0.4),
                             exclude_outline=self.preview._outline_xy)
        except CutCheckError as e:
            QMessageBox.warning(self, "Can't judge this photo", str(e))
            return
        cov = (f"{r['n_suspect_tiles']} of {r['n_tiles']} readable 8 mm tiles "
               f"look failed; {r['decided_frac'] * 100:.0f}% of samples read "
               f"clearly")
        if not r["boxes"]:
            QMessageBox.information(
                self, "Detect from photo",
                f"No failed channels found.\n\n{cov}.\n\nNote: this sees "
                f"channels with no bright cut signature (never-cut or clearly "
                f"shallow). Marginal depth is better judged with Probe boxes "
                f"/ Mesh check.")
            self.statusBar().showMessage(f"Photo check: clean ({cov})", 10000)
            return
        for b in r["boxes"]:
            self._on_region_added(tuple(b))
        QMessageBox.information(
            self, "Detect from photo",
            f"{len(r['boxes'])} suspect area(s) proposed as rework boxes, "
            f"MOST evidence first — table order = confidence ({cov}).\n\n"
            f"Review them on the preview — the last few are usually the "
            f"doubtful ones (dust, glare); delete those, then export the "
            f"rework job.")
        self.statusBar().showMessage(
            f"Photo check: {len(r['boxes'])} suspect area(s) boxed ({cov})", 12000)

    def _delete_rework_region(self, i):
        if 0 <= i < len(self._rework_regions):
            del self._rework_regions[i]
            self._refresh_rework()

    def _rework_draw_list(self):
        return [(r["bbox"], r["color"], f'{r["depth"]:.3f} mm')
                for r in self._rework_regions]

    def _refresh_rework(self):
        """Rebuild the region table and push the draw list to the canvas."""
        from PySide6.QtWidgets import QDoubleSpinBox, QCheckBox, QPushButton
        t = self.rework_table
        t.setRowCount(len(self._rework_regions))
        for i, r in enumerate(self._rework_regions):
            x0, y0, x1, y1 = r["bbox"]
            sw = QTableWidgetItem("●"); sw.setForeground(QColor(r["color"]))
            t.setItem(i, 0, sw)
            t.setItem(i, 1, QTableWidgetItem(f"{abs(x1 - x0):.1f}x{abs(y1 - y0):.1f}"))
            ds = QDoubleSpinBox(); ds.setRange(0.0, 5.0); ds.setSingleStep(0.01)
            ds.setDecimals(3); ds.setValue(r["depth"]); ds.setSuffix(" mm")
            ds.valueChanged.connect(lambda v, i=i: self._set_region_depth(i, v))
            t.setCellWidget(i, 2, ds)
            cb = QCheckBox(); cb.setChecked(r["follow"])
            cb.toggled.connect(lambda on, i=i: self._set_region_follow(i, on))
            t.setCellWidget(i, 3, cb)
            dl = QPushButton("X")
            dl.clicked.connect(lambda _=False, i=i: self._delete_rework_region(i))
            t.setCellWidget(i, 4, dl)
        self.preview.set_rework_regions(self._rework_draw_list())

    def _set_region_depth(self, i, v):
        if 0 <= i < len(self._rework_regions):
            self._rework_regions[i]["depth"] = v
            self.preview.set_rework_regions(self._rework_draw_list())  # relabel box

    def _set_region_follow(self, i, on):
        if 0 <= i < len(self._rework_regions):
            self._rework_regions[i]["follow"] = bool(on)

    def _rework_clip_regions(self, toolpaths):
        """Clip ``toolpaths`` to every rework region at its own depth, applying
        each region's height-map follow if set. Returns ``(paths, n_leveled)``."""
        from gerber2rml.engine.select import clip_toolpaths_to_regions
        hmap = self._level_heightmap_preview()
        paths, n_leveled = [], 0
        for r in self._rework_regions:
            clip = clip_toolpaths_to_regions(toolpaths, [(r["bbox"], -r["depth"])])
            if clip and r["follow"] and hmap is not None:
                from gerber2rml.engine.leveling import apply_leveling
                clip = apply_leveling(clip, hmap)
                n_leveled += 1
            paths.extend(clip)
        return paths, n_leveled

    def _on_export_selected(self):
        from pathlib import Path
        if self.state.board is None:
            QMessageBox.warning(self, "Nothing to export", "Load a Gerber folder first.")
            return
        if not self._rework_regions:
            QMessageBox.warning(self, "No regions",
                                "Enable 'Add areas' and drag one or more boxes first.")
            return
        op = _OPS[self.tabs.currentIndex()]
        ds = self.double_sided_chk.isChecked()
        side = self._ds_side()
        if op == "drill":
            QMessageBox.warning(self, "Not available",
                                "Rework works on the traces or cutout preview, not drilling.")
            return
        if ds and side is None:
            QMessageBox.warning(self, "Pick a side",
                                "Double-sided board: set View to Bottom or Top "
                                "to rework that side.")
            return
        self._sync_state()
        toolpaths = self._ds_side_toolpaths(op, side) if ds else self.state.toolpaths(op)
        clipped, n_leveled = self._rework_clip_regions(toolpaths)
        if not clipped:
            QMessageBox.information(self, "Empty selection",
                                    "No toolpaths fall inside the boxes.")
            return
        out = self._pick_out_dir()
        if not out:
            return
        backend = BACKENDS[self.state.machine]
        job = self.state.trace if op == "traces" else self.state.cutout
        try:
            text = backend.render(clipped, xy_feed=job.xy_feed,
                                  plunge_feed=job.plunge_feed)
            side_tag = f"{side.lower()}_" if side else ""
            path = Path(out) / f"{self.state.name}_{side_tag}{op}_rework{backend.ext}"
            path.write_text(text)
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))
            return
        self.statusBar().showMessage(
            f"Wrote {path.name}: {len(self._rework_regions)} region(s), "
            f"{len(clipped)} path(s)"
            f"{f', {n_leveled} height-map leveled' if n_leveled else ''}"
            f"{self._note_tool_wear(clipped)}", 10000)

_STYLESHEET = """
QWidget { color: #dde3ea; font-size: 13px; font-family: 'Segoe UI Variable', 'Inter', 'Roboto', sans-serif; }
QMainWindow, QScrollArea, #settingsPanel { background: #14171c; }
QScrollArea { border: none; }

#sidebar {
    background: #181c22;
    border-right: 1px solid #262c35;
    outline: none;
    padding: 10px 0px;
}
#sidebar::item {
    padding: 12px 20px;
    color: #8b94a1;
    font-size: 14px;
    font-weight: 500;
}
#sidebar::item:hover {
    background: #1f242c;
    color: #dde3ea;
}
#sidebar::item:selected {
    background: #12262b;
    color: #4dd0e1;
    border-left: 3px solid #4dd0e1;
}

QGroupBox {
    background: #1b2027; border: 1px solid #262c35; border-radius: 10px;
    margin-top: 18px; padding-top: 8px;
}
QGroupBox::title {
    subcontrol-origin: margin; subcontrol-position: top left;
    left: 14px; top: 4px; padding: 2px 6px;
    color: #8fb8c9; font-size: 12px; font-weight: 700; text-transform: uppercase;
    letter-spacing: 1px;
}
QLabel { background: transparent; color: #a5adb9; font-weight: 500; }
#helpText { color: #8fb8c9; font-size: 13px; font-style: italic; margin-bottom: 4px; border: 1px solid #1e3a42; background: #14232a; border-radius: 6px; padding: 8px; }

QPushButton {
    background: #232a33; border: 1px solid #313a46; border-radius: 6px;
    padding: 8px 14px; font-weight: 500;
}
QPushButton:hover { background: #2b3440; border-color: #4dd0e1; }
QPushButton:pressed { background: #1b2027; }
QPushButton:disabled { color: #525b66; background: #191d23; border-color: #262c35; }
QPushButton#primaryBtn { background: #4dd0e1; border: none; color: #0d1418; font-weight: 700; }
QPushButton#primaryBtn:hover { background: #80e5f2; }
QPushButton#primaryBtn:pressed { background: #26b8cc; }
QPushButton#primaryBtn:disabled { background: #1e3a42; color: #52707a; }
QPushButton#stopBtn { background: #d64541; border: none; color: #ffffff; font-weight: 700; }
QPushButton#stopBtn:hover { background: #e8615d; }
QPushButton#stopBtn:pressed { background: #a83531; }

/* the machine dock keeps AMBER accents: amber = live machine, everywhere */
#machineBar { background: #181c22; border-top: 1px solid #262c35; }
#progressBar { background: #181c22; }
QProgressBar {
    background: #232a33; border: 1px solid #313a46; border-radius: 6px;
    min-height: 18px; text-align: center; color: #dde3ea;
}
QProgressBar::chunk { background: #ffb000; border-radius: 5px; }

QComboBox, QLineEdit, QAbstractSpinBox {
    background: #232a33; border: 1px solid #313a46; border-radius: 6px;
    padding: 6px 10px; min-height: 20px; selection-background-color: #4dd0e1;
    selection-color: #0d1418;
}
QComboBox:hover, QLineEdit:hover, QAbstractSpinBox:hover { border-color: #4dd0e1; }
QComboBox:focus, QLineEdit:focus, QAbstractSpinBox:focus { border-color: #4dd0e1; }
QComboBox:disabled, QAbstractSpinBox:disabled { color: #525b66; background: #191d23; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView {
    background: #232a33; border: 1px solid #313a46; border-radius: 6px;
    selection-background-color: #4dd0e1; selection-color: #0d1418; outline: none;
}

QCheckBox { spacing: 10px; background: transparent; color: #dde3ea; font-weight: 500; }
QCheckBox:hover { color: #80e5f2; }
QCheckBox:pressed { color: #4dd0e1; }
QCheckBox:checked { color: #4dd0e1; }
QCheckBox:checked:hover { color: #80e5f2; }
QCheckBox::indicator {
    width: 18px; height: 18px; border-radius: 4px;
    border: 1px solid #3d4754; background: #232a33;
}
QCheckBox::indicator:hover { border-color: #4dd0e1; }
QCheckBox::indicator:checked { background: #4dd0e1; border-color: #4dd0e1; }
QCheckBox::indicator:checked:hover { background: #80e5f2; border-color: #80e5f2; }

QTabWidget::pane { border: 1px solid #262c35; border-radius: 8px; top: -1px; background: #1b2027; }
QTabBar::tab {
    background: transparent; color: #8b94a1; padding: 8px 18px; margin-right: 2px;
    border-top-left-radius: 8px; border-top-right-radius: 8px; font-weight: 600;
}
QTabBar::tab:selected {
    background: #1b2027; color: #4dd0e1;
    border: 1px solid #262c35; border-bottom: none;
}
QTabBar::tab:hover:!selected { color: #dde3ea; }

QScrollBar:vertical { background: transparent; width: 12px; margin: 2px; }
QScrollBar::handle:vertical { background: #313a46; border-radius: 6px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #3d4754; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QSlider::groove:horizontal { height: 4px; background: #313a46; border-radius: 2px; }
QSlider::handle:horizontal {
    background: #4dd0e1; width: 16px; margin: -6px 0; border-radius: 8px;
}
QSlider::handle:horizontal:hover { background: #80e5f2; }

QStatusBar { background: #14171c; color: #8b94a1; font-weight: 500; }
QToolTip {
    color: #dde3ea; background-color: #232a33; border: 1px solid #313a46;
    border-radius: 6px; padding: 6px 8px; font-size: 12px;
}
"""

def apply_dark_theme(app):
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(20, 23, 28))
    palette.setColor(QPalette.WindowText, QColor(221, 227, 234))
    palette.setColor(QPalette.Base, QColor(35, 42, 51))
    palette.setColor(QPalette.AlternateBase, QColor(27, 32, 39))
    palette.setColor(QPalette.ToolTipBase, QColor(35, 42, 51))
    palette.setColor(QPalette.ToolTipText, QColor(221, 227, 234))
    palette.setColor(QPalette.Text, QColor(221, 227, 234))
    palette.setColor(QPalette.Button, QColor(35, 42, 51))
    palette.setColor(QPalette.ButtonText, QColor(221, 227, 234))
    palette.setColor(QPalette.BrightText, Qt.red)
    palette.setColor(QPalette.Link, QColor(77, 208, 225))
    palette.setColor(QPalette.Highlight, QColor(77, 208, 225))
    palette.setColor(QPalette.HighlightedText, QColor(13, 20, 24))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor(85, 85, 85))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(85, 85, 85))
    app.setPalette(palette)
    app.setStyleSheet(_STYLESHEET)

def _configure_opengl():
    """Pick the OpenGL backend *before* the QApplication exists.

    On Windows Qt often defaults to an ANGLE (OpenGL-ES-over-Direct3D) context,
    under which pyqtgraph 0.14's desktop GLSL shaders fail to link --
    ``GL_INVALID_VALUE`` on ``glUseProgram`` -- and the 3D viewer renders
    nothing. Requesting the native desktop driver fixes it. Override with
    ``GERBER2RML_GL=software`` (Mesa llvmpipe) on machines without a usable GPU
    driver (headless/RDP/VM), or ``=angle`` to restore the old behaviour."""
    import os
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtGui import QSurfaceFormat
    mode = os.environ.get("GERBER2RML_GL", "desktop").lower()
    attr = {
        "desktop": Qt.ApplicationAttribute.AA_UseDesktopOpenGL,
        "software": Qt.ApplicationAttribute.AA_UseSoftwareOpenGL,
        "angle": Qt.ApplicationAttribute.AA_UseOpenGLES,
    }.get(mode, Qt.ApplicationAttribute.AA_UseDesktopOpenGL)
    QCoreApplication.setAttribute(attr, True)
    # Share GL resources across contexts. Without this, closing the 3D viewer
    # destroys its GL context and invalidates pyqtgraph's cached shader programs;
    # the next viewer gets a fresh, non-sharing context and glUseProgram fails
    # (GL_INVALID_VALUE) -> blank. Sharing keeps the programs valid across windows.
    QCoreApplication.setAttribute(
        Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    fmt = QSurfaceFormat()
    fmt.setVersion(2, 1)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CompatibilityProfile)
    fmt.setDepthBufferSize(24)
    QSurfaceFormat.setDefaultFormat(fmt)


# Demo board loaded on launch so the GUI isn't empty. Resolves both from a source
# checkout (repo-root/examples) and from a PyInstaller build, where bundled data
# lands under sys._MEIPASS. Absent in a bare copy -> the app just starts empty.
def _demo_dir():
    base = getattr(sys, "_MEIPASS", None)
    root = Path(base) if base else Path(__file__).resolve().parents[2]
    return root / "examples" / "preload_example"


_DEMO_DIR = _demo_dir()


def _preload_demo(win):
    """Open the GUI with a demo board loaded + previewed. Best-effort: silently
    starts empty if the demo folder is missing or fails to load."""
    try:
        if _DEMO_DIR.is_dir():
            win.load_folder(str(_DEMO_DIR))
            win.generate_preview()
            win.preview.set_demo(True)      # persistent badge until they load their own
    except Exception:
        pass


def main():
    if QApplication.instance() is None:
        _configure_opengl()
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("srm-cam")
    app.setApplicationName("SRM-CAM")
    apply_dark_theme(app)
    win = MainWindow()
    _preload_demo(win)
    win.show()
    win.tour.maybe_autostart()       # runs the guided walkthrough on first launch
    win.maybe_offer_kicad_plugin()   # asked once per plugin version, never nags
    win.start_update_check()         # background; silent unless there is one
    return app.exec()

if __name__ == "__main__":
    raise SystemExit(main())
