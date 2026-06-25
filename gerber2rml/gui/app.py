"""gerber2rml desktop app: load Gerbers, edit variables, preview, export RML."""
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QPushButton,
    QLineEdit, QComboBox, QTabWidget, QCheckBox, QLabel, QFileDialog, QMessageBox,
    QSplitter, QGroupBox, QStyle, QFormLayout, QDoubleSpinBox, QScrollArea,
    QSpinBox, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QListWidget, QStackedWidget
)
from PySide6.QtCore import Qt, QThread, Signal, QMutex
from PySide6.QtGui import QPalette, QColor
import time

from gerber2rml.app.state import ProjectState
from gerber2rml.app.preview import toolpath_segments
from gerber2rml.backends import BACKENDS
from gerber2rml.gui.form import DataclassForm
from gerber2rml.gui.canvas import PreviewCanvas

_OPS = ["traces", "drill", "cutout"]


class _ProbeWorker(QThread):
    """Runs the SPI grid probe off the GUI thread; emits one result per point."""
    result = Signal(dict)
    done = Signal(str)            # "" on success, else an error message

    def __init__(self, port, points):
        super().__init__()
        self._port, self._points = port, points
        self._abort = False

    def abort(self):
        """Request a STOP: the next read bails and the firmware lifts the tool."""
        self._abort = True

    def run(self):
        from gerber2rml.engine.spi_probe import probe_grid
        try:
            res = probe_grid(self._port, self._points,
                             on_result=lambda d: self.result.emit(d),
                             should_abort=lambda: self._abort)
            if self._abort:
                self.done.emit("aborted")
                return
            bad = next((r for r in res if "runaway" in str(r.get("error", "")).lower()),
                       None)
            if bad is not None:                # runaway -> tool lifted, grid stopped
                self.done.emit(
                    f"RUNAWAY at point {bad['id'] + 1}: {bad['error']}. "
                    f"Probing stopped and the bit lifted — check the probe wiring "
                    f"and that every grid point sits on copper.")
            else:
                self.done.emit("")
        except Exception as e:                 # serial/timeout/parse -> report to UI
            self.done.emit(str(e))


class _DROPoller(QThread):
    """Holds the Arduino link open and polls live position (~4 Hz) for the DRO."""
    position = Signal(float, float, float, bool)   # x, y, z mm + probe touching
    touch_done = Signal(bool, float, float, float)  # ok, x, y, z (mm) of surface
    failed = Signal(str)

    def __init__(self, port):
        super().__init__()
        self._port, self._run = port, True
        self._lock = QMutex()
        self._pending_move = None       # (x_um, y_um) queued jog target
        self._pending_touch = False     # queued touch-off request
        self._abort = False             # STOP: lift the tool and stop polling

    def request_abort(self):
        """STOP: drop any queued motion; the loop sends ``!`` (lift) and exits."""
        self._lock.lock()
        self._abort = True
        self._pending_move = None
        self._pending_touch = False
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
                ab = self._abort
                self._pending_move = None
                self._pending_touch = False
                self._lock.unlock()
                if ab:
                    spi_probe.send_abort(ser)                 # lift the tool, then stop
                    break
                try:
                    if mv is not None:
                        spi_probe.jog_to(ser, mv[0], mv[1])   # lifts then travels XY
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
                self.msleep(60 if (self._pending_move or self._pending_touch) else 250)
        finally:
            try:
                ser.close()
            except Exception:
                pass

    def stop(self):
        self._run = False
        self.wait(3000)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("gerber2rml - Premium CAM")
        self.resize(1100, 750)
        self.state = ProjectState()

        # Toolbar / Top Controls
        self.load_btn = QPushButton("Load Gerber folder...")
        self.load_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self.load_btn.clicked.connect(self._on_load_clicked)
        
        self.export_btn = QPushButton("Export toolpaths...")
        self.export_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        self.export_btn.clicked.connect(self._on_export_clicked)

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
        self.mirror_chk.toggled.connect(self._on_mirror_toggled)
        self.double_sided_chk = QCheckBox("Double-sided")
        self.double_sided_chk.toggled.connect(self._on_double_sided_toggled)
        self._ds_cache = None   # (gerber_dir, layout) so live edits don't re-read disk
        self._ds_mcache = None  # machine-frame layout cache (single-side rework/preview)

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
            sp.setRange(0.0, 500.0); sp.setSingleStep(1.0); sp.setDecimals(1)
            sp.setSuffix(" mm")
            sp.setToolTip(f"Move the whole job {ax} on the bed from the front-left home")
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
        self.stock_here_btn = QPushButton("Corner = tool")
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
        self.level_port_combo = QComboBox()
        self.level_port_combo.setMaximumWidth(90)
        self.level_port_combo.setToolTip("Serial port of the Arduino prober (Device Manager > Ports).")
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
            "first, then travels XY). Needs the machine connected.")
        self.jog_chk.toggled.connect(self._on_jog_mode_toggled)
        self.zero_btn = QPushButton("Probe Z")
        self.zero_btn.setEnabled(False)
        self.zero_btn.setToolTip(
            "Lower the bit from here until it touches the plate, stop at the "
            "surface, and set that Z as the work-surface zero. Needs the touch "
            "clips connected; start a few mm above the surface.")
        self.zero_btn.clicked.connect(self._on_probe_z)
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
        self.align_only_btn = QPushButton("Cut dowels only...")
        self.align_only_btn.setToolTip(
            "Export ONLY the dowel-hole G-code (no traces/drills/cutout). Use to "
            "test-fit the rods, then bump the clearance and re-cut just the holes. "
            "Keep the SAME XY origin so the re-cut lands on the existing holes.")
        self.align_only_btn.clicked.connect(self._on_export_align_only)
        self._fresh_row = QWidget()
        _fresh_row_l = QHBoxLayout(self._fresh_row)
        _fresh_row_l.setContentsMargins(0, 0, 0, 0)
        _fresh_row_l.addWidget(QLabel("clr L"))
        _fresh_row_l.addWidget(self.fresh_clear_large_edit)
        _fresh_row_l.addWidget(QLabel("S"))
        _fresh_row_l.addWidget(self.fresh_clear_small_edit)
        _fresh_row_l.addWidget(self.align_only_btn)
        self._fresh_row.setEnabled(False)   # enabled only in fresh mode

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
        self.select_chk = QCheckBox("Select area")
        self.select_chk.toggled.connect(self._on_select_toggled)
        self.clear_sel_btn = QPushButton("Clear")
        self.clear_sel_btn.clicked.connect(lambda: self.preview.clear_selection())
        self.export_sel_btn = QPushButton("Export selected NC...")
        self.export_sel_btn.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        self.export_sel_btn.clicked.connect(self._on_export_selected)
        self.export_sel_btn.setEnabled(False)

        # Operation parameters (hidden, managed by presets)
        self.forms = {"traces": DataclassForm(self.state.trace),
                      "drill": DataclassForm(self.state.drill),
                      "cutout": DataclassForm(self.state.cutout)}
        for op in _OPS:
            self.forms[op].valueChanged.connect(self.generate_preview)

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

        # ---------- Settings Sidebar & Stacked Widget ----------
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(180)
        self.sidebar.addItems([
            "Project & Tools", 
            "Double-Sided", 
            "Bed Leveling", 
            "Rework"
        ])
        
        self.stacked_widget = QStackedWidget()
        self.sidebar.currentRowChanged.connect(self.stacked_widget.setCurrentIndex)

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

        self.sidebar.setCurrentRow(0)

        # ===== BASIC: the things you set every time =====
        board_group, bl = _group("Board")
        bl.addRow(_row(self.load_btn, self.export_btn))
        bl.addRow("Name", self.name_edit)
        bl.addRow("Preset", _row(self.preset_combo, self.apply_preset_btn,
                                 self.save_preset_btn, stretch_first=True))
        bl.addRow("Stock", self.thickness_spin)
        bl.addRow("", self._auto_depth_row)
        l_proj.addWidget(board_group)

        ops_group = QGroupBox("Preview Mode")
        _ol = QVBoxLayout(ops_group); _ol.setContentsMargins(10, 14, 10, 10)
        _ol.addWidget(self.tabs)
        l_proj.addWidget(ops_group)

        # ===== VIEW / PLACEMENT =====
        view_group, vl = _group("View / machine")
        vl.addRow("Machine", self.machine_combo)
        vl.addRow("Preview", self.frame_combo)
        vl.addRow("", self.mirror_chk)
        vl.addRow("", self.show_bed_chk)
        vl.addRow(_row(self.sim3d_btn, self.sim_file_btn))
        vl.addRow(_row(self.export_img_btn))
        l_proj.addWidget(view_group)

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
                           self.level_save_btn, self.level_clear_btn))
        _ll.addWidget(_row(QLabel("port"), self.level_port_combo, self.level_probe_btn,
                           self.level_gridshow_chk, self.level_show_chk,
                           self.level_3d_btn, stretch_first=False))
        _ll.addWidget(self.level_table)
        _ll.addWidget(_row(self.level_top_btn))
        l_level.addWidget(level_group)
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
        _dsf.addRow("Reg.", self.reg_combo)
        _dsf.addRow("Dowels", self.place_combo)
        _dsf.addRow("Grid", self._grid_row)
        _dsf.addRow("Fresh", self._fresh_row)
        self._ds_controls.setVisible(False)
        _dl.addWidget(self._ds_controls)
        l_double.addWidget(ds_group)
        l_double.addStretch(1)

        # ===== REWORK =====
        rework_group = QGroupBox("Rework (2nd pass)")
        _rl = QVBoxLayout(rework_group); _rl.setContentsMargins(14, 16, 14, 12); _rl.setSpacing(8)
        _rl.addWidget(_row(self.select_chk, self.clear_sel_btn, stretch_first=True))
        _rl.addWidget(self.export_sel_btn)
        l_rework.addWidget(rework_group)
        l_rework.addStretch(1)

        settings_container = QWidget()
        sc_layout = QHBoxLayout(settings_container)
        sc_layout.setContentsMargins(0, 0, 0, 0)
        sc_layout.setSpacing(0)
        sc_layout.addWidget(self.sidebar)
        sc_layout.addWidget(self.stacked_widget)
        settings_container.setMinimumWidth(450)

        self.preview = PreviewCanvas()
        self.preview.on_selection_changed = self._on_selection_changed
        self.preview.on_move_delta = self._on_move_delta
        self.preview.on_jog_to = self._on_jog_to
        self.preview.on_jog_step = self._on_jog_step

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(settings_container)
        splitter.addWidget(self.preview)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([550, 550])     # centered initially

        # Machine bar across the top: live DRO readout + connect toggle.
        machine_bar = QWidget()
        machine_bar.setObjectName("machineBar")
        _mb = QHBoxLayout(machine_bar)
        _mb.setContentsMargins(8, 2, 8, 2)
        _mb.addWidget(self.dro_label)
        _mb.addWidget(self.touch_label)
        _mb.addStretch(1)
        _mb.addWidget(self.zero_btn)
        _mb.addWidget(self.jog_chk)
        _mb.addWidget(self.connect_btn)
        _mb.addWidget(self.stop_btn)

        central = QWidget()
        _cv = QVBoxLayout(central)
        _cv.setContentsMargins(0, 0, 0, 0)
        _cv.setSpacing(0)
        _cv.addWidget(machine_bar)
        _cv.addWidget(splitter, 1)
        self.setCentralWidget(central)
        self.statusBar().showMessage("Ready", 5000)

        # open with the first preset applied (FR-4 conservative) so the form
        # values match the selected preset in the dropdown
        self.apply_selected_preset()

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
        spec = self._dowel_spec()
        off = (self.state.place_x, self.state.place_y)
        key = (str(self.state.gerber_dir), spec.mode, spec.placement, spec.pitch_x,
               spec.grid_pin, spec.clearance_large, spec.clearance_small, off,
               self.state.rotate)
        if self._ds_cache is None or self._ds_cache[0] != key:
            self._ds_cache = (key, preview_layout_double_sided(
                self.state.gerber_dir, dowels=spec, offset=off,
                rotate=self.state.rotate))
        return self._ds_cache[1]

    def _machine_layout(self):
        """Machine-frame layout — the board exactly as each side is cut (bottom
        mirrored, top reflected). Single-side preview and rework use this so an
        on-screen box maps to the real toolpath coordinates, not the design-frame
        X-ray used by the 'Both sides' registration view."""
        from gerber2rml.doublesided import layout_double_sided
        spec = self._dowel_spec()
        off = (self.state.place_x, self.state.place_y)
        key = (str(self.state.gerber_dir), spec.mode, spec.placement, spec.pitch_x,
               spec.grid_pin, spec.clearance_large, spec.clearance_small, off,
               self.state.rotate)
        if self._ds_mcache is None or self._ds_mcache[0] != key:
            self._ds_mcache = (key, layout_double_sided(
                self.state.gerber_dir, dowels=spec, offset=off,
                rotate=self.state.rotate))
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
        paths and the result runs in the same frame as the full job."""
        from gerber2rml.engine.traces import isolate
        from gerber2rml.engine.cutout import cut_outline
        mlay = self._machine_layout()
        if op == "cutout":
            return cut_outline(mlay.outline, self.state.cutout)
        if side == "Top":
            return isolate(mlay.top_copper, self.state.trace, outline=mlay.top_outline)
        return isolate(mlay.bottom_copper, self.state.trace, outline=mlay.outline)

    def _on_advanced_toggled(self, on):
        pass

    def _update_ds_controls(self):
        """Reveal the registration controls only when double-sided is on, enable
        the View/Reg/Dowels selectors with it, and show the grid/fresh fields
        only for the matching mode."""
        ds = self.double_sided_chk.isChecked()
        self._ds_controls.setVisible(ds)            # hide the sub-controls until on
        for w in (self.view_combo, self.reg_combo, self.place_combo):
            w.setEnabled(ds)                        # were disabled at init; enable with DS
        is_grid = self.reg_combo.currentIndex() == 1
        self._grid_row.setEnabled(ds and is_grid)
        self._fresh_row.setEnabled(ds and not is_grid)

    def _on_double_sided_toggled(self, checked):
        self._update_ds_controls()
        self.level_top_btn.setEnabled(checked)   # top-side leveling is DS-only
        self.generate_preview()

    def _on_reg_changed(self, *_):
        self._update_ds_controls()
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

    def _preview_double_sided(self, op):
        """Show the registered board with the two dowel/alignment holes so the
        operator can check the flip registration and pin placement before
        milling. The View selector picks bottom (cyan), top (magenta), or both
        overlaid; the dowels are always shown. Board holes are shown on the
        drill tab only."""
        from gerber2rml.engine.traces import isolate
        side = self._ds_side()
        if side is not None and op != "drill":
            # Single side: show it in the MACHINE frame (as actually cut) so a
            # rework box maps to real toolpath coordinates. Keep the channel
            # contract: Bottom -> bottom cuts, Top -> top cuts.
            mlay = self._machine_layout()
            cuts, rapids = toolpath_segments(self._ds_side_toolpaths(op, side))
            outline = mlay.top_outline if side == "Top" else mlay.outline
            self.preview.set_board_outline(self._poly_xy(outline))
            if side == "Top":
                self.preview.show_segments([], [], top_cuts=cuts, pins=mlay.align_holes)
            else:
                self.preview.show_segments(cuts, rapids, pins=mlay.align_holes)
            return
        # Both sides (or the drill tab): design-frame X-ray for registration.
        lay = self._double_sided_layout()
        self.preview.set_board_outline(self._poly_xy(lay.outline))
        view = self.view_combo.currentText()
        bottom_cuts, bottom_rapids, top_cuts = [], [], []
        if view in ("Both sides", "Bottom"):
            bottom_cuts, bottom_rapids = toolpath_segments(
                isolate(lay.bottom_copper, self.state.trace, outline=lay.outline))
        if view in ("Both sides", "Top"):
            top_cuts, _ = toolpath_segments(
                isolate(lay.top_copper, self.state.trace, outline=lay.outline))
        holes = lay.holes if op == "drill" else None
        self.preview.show_segments(bottom_cuts, bottom_rapids, holes=holes,
                                   top_cuts=top_cuts, pins=lay.align_holes)

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
        if self.double_sided_chk.isChecked():
            self.frame_combo.setEnabled(False)
            side = self._ds_side()
            if side == "Bottom":
                self.preview.set_frame("AS MILLED  ·  bottom (mirrored)", AMBER)
            elif side == "Top":
                self.preview.set_frame("AS MILLED  ·  top (reflected)", AMBER)
            else:
                self.preview.set_frame(
                    "AS DESIGNED  ·  X-ray, both layers register", GREEN)
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
        # keep the rework export button in sync with the active tab / mode
        self._on_selection_changed(self.preview.selection_bbox())
        if self.state.board is None:
            return
        self._sync_state()
        self._apply_preview_frame()
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
            return
        if op == "drill":
            cuts, rapids = toolpath_segments(self.state.toolpaths("traces"))
            self.preview.show_segments(cuts, rapids, holes=self.state.board.holes)
            est = self._estimate_str(self._drill_toolpaths(self.state.board.holes),
                                     self.state.drill)
            self.statusBar().showMessage(self._drill_status() + est, 8000)
            return
        tps = self.state.toolpaths(op)
        cuts, rapids = toolpath_segments(tps)
        self.preview.show_segments(cuts, rapids)
        est = self._estimate_str(tps, self.state.trace if op == "traces"
                                 else self.state.cutout)
        if op == "traces":
            from gerber2rml.analysis import find_narrow_gaps
            gaps = find_narrow_gaps(self.state.board.copper,
                                    self.state.board.outline,
                                    self.state.trace.bit_diameter)
            if not gaps.is_empty:
                self.preview.show_gaps(gaps)
                self.statusBar().showMessage(
                    "Warning: copper gaps too narrow to isolate (shown red)" + est, 8000)
                gap_warning = True
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
                rotate=self.state.rotate)
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
            side = self._ds_side()
            if side is not None:
                mlay = self._machine_layout()
                return mlay.top_outline if side == "Top" else mlay.outline
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
            if ztxt not in ("", "-"):
                xyz.append((x, y, float(ztxt)))
        return xy, xyz

    def _on_export_probe_files(self):
        if not self.level_table.rowCount():
            self._on_build_level_grid()
        xy, _xyz = self._table_points()
        if not xy:
            return
        out = QFileDialog.getExistingDirectory(self, "Select output folder")
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
        path, _ = QFileDialog.getSaveFileName(self, "Save height map", default,
                                              "CSV (*.csv)")
        if not path:
            return
        lines = ["x_mm,y_mm,dz_mm"]
        for r in range(self.level_table.rowCount()):
            vals = []
            for c in range(3):
                it = self.level_table.item(r, c)
                vals.append(it.text().strip() if it else "")
            lines.append(",".join(vals))
        Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.statusBar().showMessage(f"Saved height map to {path}", 8000)

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
        self._dro.failed.connect(self._on_dro_failed)
        self._dro.start()
        self.connect_btn.setText("Disconnect")
        self.jog_chk.setEnabled(True)
        self.zero_btn.setEnabled(True)
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
            self.statusBar().showMessage(
                "Click a point on the preview to jog the tool there", 6000)

    def _on_jog_to(self, x, y):
        if self._dro is None:
            return
        self._dro.request_move(round(x * 1000), round(y * 1000))
        self.statusBar().showMessage(f"Jogging to X {x:.1f}  Y {y:.1f} mm", 4000)

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
        self._dro.request_move(round(nx * 1000), round(ny * 1000))
        # optimistically advance the local position so rapid key taps accumulate
        # into one move to the final spot instead of all reading the same stale XY
        self._tool_xyz = (nx, ny, z)
        self.statusBar().showMessage(
            f"Jog {dx:+.1f} {dy:+.1f} mm  ->  X {nx:.1f}  Y {ny:.1f} mm", 3000)

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
        self.dro_label.setText(txt)
        self.dro_label.setStyleSheet(self._DRO_ON)
        self.touch_label.setText("bit ● TOUCHING" if touching else "bit ○ clear")
        self.touch_label.setStyleSheet(self._TOUCH_ON if touching else self._TOUCH_OFF)
        self.preview.set_tool_position(x, y, touching)

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

    def _on_probe_spi(self):
        """Auto-probe the grid over the SPI link and fill the Z column."""
        if not self.level_table.rowCount():
            self._on_build_level_grid()
        xy, _xyz = self._table_points()
        if len(xy) < 3:
            QMessageBox.warning(self, "No grid", "Build a probe grid first.")
            return
        x0, y0 = xy[0]                          # datum = first grid point
        # datum-local offsets in microns; ids are table row indices
        points = [(i, round((x - x0) * 1000), round((y - y0) * 1000))
                  for i, (x, y) in enumerate(xy)]
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
        self._probe_worker = _ProbeWorker(port, points)
        self._probe_worker.result.connect(self._on_probe_result)
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

    def _on_probe_done(self, err):
        self.level_probe_btn.setEnabled(True)
        if err == "aborted":
            self.statusBar().showMessage("Probing aborted — bit lifted to safe Z", 8000)
        elif err.startswith("RUNAWAY"):
            QMessageBox.warning(self, "Runaway stopped", err)
            self.statusBar().showMessage(
                "Runaway detected — probing stopped, bit lifted", 12000)
        elif err:
            QMessageBox.critical(self, "Probe failed", err)
            self.statusBar().showMessage("Probe failed", 8000)
        else:
            self.level_chk.setChecked(True)     # leveling is ready to apply
            self.level_show_chk.setChecked(True)  # reveal the surface heatmap
            self._update_level_overlay()
            self.statusBar().showMessage("Probe complete — Z column filled", 10000)
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
        if hmap is None:
            self.preview.set_level_overlay(None)
            return
        import numpy as np
        x0, y0, x1, y1 = self.state.board.outline.bounds
        xs = np.linspace(x0, x1, 48); ys = np.linspace(y0, y1, 48)
        X, Y = np.meshgrid(xs, ys)
        Z = [[hmap(float(x), float(y)) for x in xs] for y in ys]
        self.preview.set_level_overlay(X, Y, Z, xyz)

    def _on_bed_3d(self):
        """Open the probed surface as a rotatable 3D mesh (OctoPrint-style)."""
        hmap = self._level_heightmap_preview()
        if hmap is None or self.state.board is None:
            QMessageBox.warning(self, "No height map",
                                "Probe or enter at least 3 points first.")
            return
        import numpy as np
        x0, y0, x1, y1 = self.state.board.outline.bounds
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
        folder = QFileDialog.getExistingDirectory(self, "Select Gerber folder")
        if folder:
            try:
                self.load_folder(folder)
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
        out = QFileDialog.getExistingDirectory(self, "Select output folder")
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
            self.statusBar().showMessage(msg, 12000)

    def _on_export_align_only(self):
        if self.state.gerber_dir is None:
            QMessageBox.warning(self, "Nothing to export", "Load a Gerber folder first.")
            return
        out = QFileDialog.getExistingDirectory(self, "Select output folder")
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
                rotate=self.state.rotate)
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
        out = QFileDialog.getExistingDirectory(self, "Select output folder (same as the job)")
        if not out:
            return
        self._sync_state()
        from gerber2rml.doublesided import build_top_traces
        try:
            path = build_top_traces(
                self.state.gerber_dir, out, self.state.name,
                trace=self.state.trace, dowels=self._dowel_spec(),
                machine=self.state.machine,
                offset=(self.state.place_x, self.state.place_y),
                rotate=self.state.rotate, level=level)
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))
            return
        self.statusBar().showMessage(
            f"Wrote leveled {path.name} — run it (then the cut-out)", 10000)

    def _on_export_image(self):
        if self.state.board is None:
            QMessageBox.warning(self, "Nothing to export", "Load a Gerber folder first.")
            return
        out = QFileDialog.getExistingDirectory(self, "Select output folder")
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

    def _current_toolpaths(self):
        """(op, toolpaths) for the active tab/mode -- what the preview shows."""
        op = _OPS[self.tabs.currentIndex()]
        if self.double_sided_chk.isChecked():
            side = self._ds_side()
            if side is not None and op != "drill":
                # single side: machine-frame paths for that side (matches preview)
                return op, self._ds_side_toolpaths(op, side)
            from gerber2rml.engine.traces import isolate
            from gerber2rml.engine.cutout import cut_outline
            lay = self._double_sided_layout()
            if op == "traces":
                return op, isolate(lay.bottom_copper, self.state.trace,
                                   outline=lay.outline)
            if op == "cutout":
                return op, cut_outline(lay.outline, self.state.cutout)
            return op, self._drill_toolpaths(lay.holes)
        if op == "drill":
            return op, self._drill_toolpaths(self.state.board.holes)
        return op, self.state.toolpaths(op)

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
        self._sim_window.show()
        self._sim_window.raise_()
        self._sim_window.activateWindow()

    def _on_simulate_file(self):
        from pathlib import Path
        from gerber2rml.engine.gcode_parse import parse_file
        path, _ = QFileDialog.getOpenFileName(
            self, "Open toolpath file to simulate", "",
            "Toolpath files (*.nc *.rml *.gcode *.g);;All files (*)")
        if not path:
            return
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
        # an active rework box on a clippable op -> simulate just that part.
        # Double-sided is reworkable only when a single side (Bottom/Top) is
        # shown; _current_toolpaths already returns that side's machine paths.
        bbox = self.preview.selection_bbox()
        ds = self.double_sided_chk.isChecked()
        if bbox is not None and op != "drill" and (not ds or self._ds_side() is not None):
            from gerber2rml.engine.select import clip_toolpaths_to_bbox
            clipped = clip_toolpaths_to_bbox(toolpaths, bbox)
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

    def _on_move_toggled(self, checked):
        self.preview.set_moving(checked)
        if checked:
            self.select_chk.setChecked(False)
            self.measure_chk.setChecked(False)
            self.statusBar().showMessage(
                "Move: drag the design to reposition it on the bed", 8000)

    def _on_move_delta(self, dx, dy):
        """Drag committed in the preview -> fold the shift into the placement."""
        self.place_x_spin.blockSignals(True)
        self.place_x_spin.setValue(max(0.0, self.place_x_spin.value() + dx))
        self.place_x_spin.blockSignals(False)
        # setting Y triggers a single regenerate_preview at the new placement
        self.place_y_spin.setValue(max(0.0, self.place_y_spin.value() + dy))

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
        self.place_x_spin.setValue(max(0.0, self.place_x_spin.value() + (tx - cx)))
        self.place_x_spin.blockSignals(False)
        self.place_y_spin.setValue(max(0.0, self.place_y_spin.value() + (ty - cy)))
        self.statusBar().showMessage("Design centred on the copper stock", 5000)

    def _on_selection_changed(self, bbox):
        op = _OPS[self.tabs.currentIndex()]
        ds = self.double_sided_chk.isChecked()
        # reworkable single-sided, or double-sided with one side (Bottom/Top) shown
        has_box = (bbox is not None and op != "drill"
                   and (not ds or self._ds_side() is not None))
        self.export_sel_btn.setEnabled(has_box)
        if bbox is not None:
            w = abs(bbox[2] - bbox[0]); h = abs(bbox[3] - bbox[1])
            side = self._ds_side()
            tag = f"{side.lower()} {op}" if side else op
            self.statusBar().showMessage(
                f"Selected {w:.1f} x {h:.1f} mm for {tag} rework", 6000)

    def _on_export_selected(self):
        from pathlib import Path
        from gerber2rml.engine.select import clip_toolpaths_to_bbox
        if self.state.board is None:
            QMessageBox.warning(self, "Nothing to export", "Load a Gerber folder first.")
            return
        bbox = self.preview.selection_bbox()
        if bbox is None:
            QMessageBox.warning(self, "No selection",
                                "Enable 'Select area' and drag a box first.")
            return
        op = _OPS[self.tabs.currentIndex()]
        ds = self.double_sided_chk.isChecked()
        side = self._ds_side()
        if op == "drill":
            QMessageBox.warning(self, "Not available",
                                "Rework export works on the traces or cutout "
                                "preview, not drilling.")
            return
        if ds and side is None:
            QMessageBox.warning(self, "Pick a side",
                                "Double-sided board: set View to Bottom or Top "
                                "to rework that side.")
            return
        self._sync_state()
        toolpaths = self._ds_side_toolpaths(op, side) if ds else self.state.toolpaths(op)
        clipped = clip_toolpaths_to_bbox(toolpaths, bbox)
        if not clipped:
            QMessageBox.information(self, "Empty selection",
                                    "No toolpaths fall inside the selected box.")
            return
        out = QFileDialog.getExistingDirectory(self, "Select output folder")
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
            f"Wrote {path.name} ({len(clipped)} rework path(s))", 10000)

_STYLESHEET = """
QWidget { color: #e4e4e6; font-size: 13px; font-family: 'Segoe UI Variable', 'Inter', 'Roboto', sans-serif; }
QMainWindow, QScrollArea, #settingsPanel { background: #121212; }
QScrollArea { border: none; }

#sidebar {
    background: #181818;
    border-right: 1px solid #2e2e2e;
    outline: none;
    padding: 10px 0px;
}
#sidebar::item {
    padding: 12px 20px;
    color: #a0a0a5;
    font-size: 14px;
    font-weight: 500;
}
#sidebar::item:hover {
    background: #202020;
    color: #e4e4e6;
}
#sidebar::item:selected {
    background: #261c14;
    color: #ff9800;
    border-left: 3px solid #ff9800;
}

QGroupBox {
    background: #1e1e1e; border: 1px solid #2e2e2e; border-radius: 12px;
    margin-top: 18px; padding-top: 8px;
}
QGroupBox::title {
    subcontrol-origin: margin; subcontrol-position: top left;
    left: 14px; top: 4px; padding: 2px 6px;
    color: #ff9800; font-size: 12px; font-weight: 700; text-transform: uppercase;
}
QLabel { background: transparent; color: #b0b3b8; font-weight: 500; }
#helpText { color: #ff9800; font-size: 13px; font-style: italic; margin-bottom: 4px; border: 1px solid #443210; background: #1a1510; border-radius: 6px; padding: 8px; }

QPushButton {
    background: #2a2a2a; border: 1px solid #3e3e3e; border-radius: 6px;
    padding: 8px 14px; font-weight: 500;
}
QPushButton:hover { background: #353535; border-color: #ffb74d; }
QPushButton:pressed { background: #1f1f1f; }
QPushButton:disabled { color: #555555; background: #1a1a1a; border-color: #2a2a2a; }
QPushButton#primaryBtn { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ffb74d, stop:1 #f57c00); border: none; color: #121212; font-weight: 700; }
QPushButton#primaryBtn:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ffcc80, stop:1 #fb8c00); }
QPushButton#primaryBtn:pressed { background: #e65100; }
QPushButton#primaryBtn:disabled { background: #3e2723; color: #8d6e63; }
QPushButton#stopBtn { background: #c0392b; border: none; color: #ffffff; font-weight: 700; }
QPushButton#stopBtn:hover { background: #e04434; }
QPushButton#stopBtn:pressed { background: #962d22; }

QComboBox, QLineEdit, QAbstractSpinBox {
    background: #242424; border: 1px solid #3a3a3a; border-radius: 6px;
    padding: 6px 10px; min-height: 20px; selection-background-color: #ff9800;
}
QComboBox:hover, QLineEdit:hover, QAbstractSpinBox:hover { border-color: #ffb74d; }
QComboBox:focus, QLineEdit:focus, QAbstractSpinBox:focus { border-color: #ff9800; }
QComboBox:disabled, QAbstractSpinBox:disabled { color: #555555; background: #1a1a1a; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView {
    background: #242424; border: 1px solid #3a3a3a; border-radius: 6px;
    selection-background-color: #ff9800; selection-color: #121212; outline: none;
}

QCheckBox { spacing: 10px; background: transparent; color: #e4e4e6; font-weight: 500; }
QCheckBox:hover { color: #ffb74d; }
QCheckBox:pressed { color: #ff9800; }
QCheckBox:checked { color: #ff9800; }
QCheckBox:checked:hover { color: #ffb74d; }
QCheckBox::indicator {
    width: 18px; height: 18px; border-radius: 4px;
    border: 1px solid #4a4a4a; background: #242424;
}
QCheckBox::indicator:hover { border-color: #ffb74d; }
QCheckBox::indicator:checked { background: #ff9800; border-color: #ff9800; }
QCheckBox::indicator:checked:hover { background: #ffb74d; border-color: #ffb74d; }

QTabWidget::pane { border: 1px solid #2e2e2e; border-radius: 8px; top: -1px; background: #1e1e1e; }
QTabBar::tab {
    background: transparent; color: #a0a0a5; padding: 8px 18px; margin-right: 2px;
    border-top-left-radius: 8px; border-top-right-radius: 8px; font-weight: 600;
}
QTabBar::tab:selected {
    background: #1e1e1e; color: #ff9800;
    border: 1px solid #2e2e2e; border-bottom: none;
}
QTabBar::tab:hover:!selected { color: #e4e4e6; }

QScrollBar:vertical { background: transparent; width: 12px; margin: 2px; }
QScrollBar::handle:vertical { background: #3a3a3a; border-radius: 6px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #4a4a4a; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QSlider::groove:horizontal { height: 4px; background: #3a3a3a; border-radius: 2px; }
QSlider::handle:horizontal {
    background: #ff9800; width: 16px; margin: -6px 0; border-radius: 8px;
}
QSlider::handle:horizontal:hover { background: #ffb74d; }

QStatusBar { background: #121212; color: #a0a0a5; font-weight: 500; }
QToolTip {
    color: #e4e4e6; background-color: #242424; border: 1px solid #3a3a3a;
    border-radius: 6px; padding: 6px 8px; font-size: 12px;
}
"""

def apply_dark_theme(app):
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(18, 18, 18))
    palette.setColor(QPalette.WindowText, QColor(228, 228, 230))
    palette.setColor(QPalette.Base, QColor(36, 36, 36))
    palette.setColor(QPalette.AlternateBase, QColor(30, 30, 30))
    palette.setColor(QPalette.ToolTipBase, QColor(36, 36, 36))
    palette.setColor(QPalette.ToolTipText, QColor(228, 228, 230))
    palette.setColor(QPalette.Text, QColor(228, 228, 230))
    palette.setColor(QPalette.Button, QColor(42, 42, 42))
    palette.setColor(QPalette.ButtonText, QColor(228, 228, 230))
    palette.setColor(QPalette.BrightText, Qt.red)
    palette.setColor(QPalette.Link, QColor(255, 152, 0))
    palette.setColor(QPalette.Highlight, QColor(255, 152, 0))
    palette.setColor(QPalette.HighlightedText, QColor(18, 18, 18))
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


def main():
    if QApplication.instance() is None:
        _configure_opengl()
    app = QApplication.instance() or QApplication([])
    apply_dark_theme(app)
    win = MainWindow()
    
    # Preload requested gerber folder and set double-sided
    try:
        default_gerber = r"C:\Users\s246132\62768-energy-system\hardware\kicad\production\c2000_feedback\gerbers"
        import os
        if os.path.exists(default_gerber):
            win.load_folder(default_gerber)
            win.double_sided_chk.setChecked(True)
            win.generate_preview()
    except Exception as e:
        print(f"Failed to preload gerbers: {e}")
        
    win.show()
    return app.exec()

if __name__ == "__main__":
    raise SystemExit(main())
