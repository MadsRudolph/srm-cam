"""gerber2rml desktop app: load Gerbers, edit variables, preview, export RML."""
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QPushButton,
    QLineEdit, QComboBox, QTabWidget, QCheckBox, QLabel, QFileDialog, QMessageBox,
    QSplitter, QGroupBox, QStyle, QFormLayout, QDoubleSpinBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette, QColor
import time

from gerber2rml.app.state import ProjectState
from gerber2rml.app.preview import toolpath_segments
from gerber2rml.backends import BACKENDS
from gerber2rml.gui.form import DataclassForm
from gerber2rml.gui.canvas import PreviewCanvas

_OPS = ["traces", "drill", "cutout"]

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
        self.export_btn.setStyleSheet("font-weight: bold; padding: 5px;")

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
        self.machine_combo = QComboBox()
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
        self.view_combo.addItems(["Both sides", "Bottom", "Top"])
        self.view_combo.setEnabled(False)   # only meaningful when double-sided
        self.view_combo.currentIndexChanged.connect(self.generate_preview)

        # double-sided registration: fresh-milled dowels vs grid-seated pins
        self.reg_combo = QComboBox()
        self.reg_combo.addItems(["Fresh-milled dowels (1.9+3.1mm)",
                                 "Grid-seated pins (M4 grid)"])
        self.reg_combo.setEnabled(False)
        self.reg_combo.currentIndexChanged.connect(self._on_reg_changed)
        # which edge pair carries the dowels (sets the flip axis)
        self.place_combo = QComboBox()
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
        # fresh-mode: oversize the milled dowel holes for a slip fit if pins bind
        self.fresh_clear_edit = QLineEdit(f"{0.0}")
        self.fresh_clear_edit.setToolTip(
            "Fresh dowels: mm added to each milled hole diameter for a slip fit "
            "(0 = nominal). Bump if the rods bind during a test cut.")
        self.fresh_clear_edit.editingFinished.connect(self._on_reg_changed)
        self.align_only_btn = QPushButton("Cut dowels only...")
        self.align_only_btn.setToolTip(
            "Export ONLY the dowel-hole G-code (no traces/drills/cutout). Use to "
            "test-fit the rods, then bump the clearance and re-cut just the holes. "
            "Keep the SAME XY origin so the re-cut lands on the existing holes.")
        self.align_only_btn.clicked.connect(self._on_export_align_only)
        self._fresh_row = QWidget()
        _fresh_row_l = QHBoxLayout(self._fresh_row)
        _fresh_row_l.setContentsMargins(0, 0, 0, 0)
        _fresh_row_l.addWidget(QLabel("hole clearance"))
        _fresh_row_l.addWidget(self.fresh_clear_edit)
        _fresh_row_l.addWidget(self.align_only_btn)
        self._fresh_row.setEnabled(False)   # enabled only in fresh mode

        from gerber2rml.app.presets import load_presets
        self._presets = load_presets()
        self.preset_combo = QComboBox()
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

        # Build Settings Panel
        settings_panel = QWidget()
        settings_layout = QVBoxLayout(settings_panel)
        settings_layout.setContentsMargins(10, 10, 10, 10)
        
        # Project Group
        project_group = QGroupBox("Project")
        project_layout = QFormLayout(project_group)
        project_layout.addRow(self.load_btn, self.export_btn)
        project_layout.addRow(self.export_img_btn, self.sim3d_btn)
        project_layout.addRow("", self.sim_file_btn)
        project_layout.addRow("Name:", self.name_edit)
        project_layout.addRow("Machine:", self.machine_combo)
        project_layout.addRow("", self.mirror_chk)
        project_layout.addRow("Preview:", self.frame_combo)
        project_layout.addRow("", self.show_bed_chk)
        project_layout.addRow("Place:", self._place_row)
        project_layout.addRow("", self.move_chk)
        project_layout.addRow("Stock:", self.thickness_spin)
        project_layout.addRow("", self._auto_depth_row)
        project_layout.addRow("", self.double_sided_chk)
        project_layout.addRow("View:", self.view_combo)
        project_layout.addRow("Reg.:", self.reg_combo)
        project_layout.addRow("Dowels:", self.place_combo)
        project_layout.addRow("Grid:", self._grid_row)
        project_layout.addRow("Fresh:", self._fresh_row)
        settings_layout.addWidget(project_group)
        
        # Presets Group
        presets_group = QGroupBox("Presets")
        presets_layout = QHBoxLayout(presets_group)
        presets_layout.addWidget(self.preset_combo, 1)
        presets_layout.addWidget(self.apply_preset_btn)
        presets_layout.addWidget(self.save_preset_btn)
        settings_layout.addWidget(presets_group)

        # Rework Group
        rework_group = QGroupBox("Rework (2nd pass)")
        rework_layout = QVBoxLayout(rework_group)
        rework_row = QHBoxLayout()
        rework_row.addWidget(self.select_chk, 1)
        rework_row.addWidget(self.clear_sel_btn)
        rework_layout.addLayout(rework_row)
        rework_layout.addWidget(self.export_sel_btn)
        settings_layout.addWidget(rework_group)

        # Tabs for Operations
        self.forms = {"traces": DataclassForm(self.state.trace),
                      "drill": DataclassForm(self.state.drill),
                      "cutout": DataclassForm(self.state.cutout)}
        self.tabs = QTabWidget()
        for op in _OPS:
            form = self.forms[op]
            form.valueChanged.connect(self.generate_preview)
            self.tabs.addTab(form, op.capitalize())
        self.tabs.currentChanged.connect(self.generate_preview)
        settings_layout.addWidget(self.tabs, 1)

        self.preview = PreviewCanvas()
        self.preview.on_selection_changed = self._on_selection_changed
        self.preview.on_move_delta = self._on_move_delta

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(settings_panel)
        splitter.addWidget(self.preview)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        self.setCentralWidget(splitter)
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
        from gerber2rml.doublesided import DowelSpec
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
                         pin_clearance=_f(self.fresh_clear_edit, 0.0))

    def _double_sided_layout(self):
        """Design-frame layout for the PREVIEW (both layers registered, holes on
        pads, top plain). The export uses the machine-frame layout separately.
        Cached by folder + registration choice so live edits don't re-read disk."""
        from gerber2rml.doublesided import preview_layout_double_sided
        spec = self._dowel_spec()
        off = (self.state.place_x, self.state.place_y)
        key = (str(self.state.gerber_dir), spec.mode, spec.placement, spec.pitch_x,
               spec.grid_pin, spec.pin_clearance, off)
        if self._ds_cache is None or self._ds_cache[0] != key:
            self._ds_cache = (key, preview_layout_double_sided(
                self.state.gerber_dir, dowels=spec, offset=off))
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
               spec.grid_pin, spec.pin_clearance, off)
        if self._ds_mcache is None or self._ds_mcache[0] != key:
            self._ds_mcache = (key, layout_double_sided(
                self.state.gerber_dir, dowels=spec, offset=off))
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

    def _update_ds_controls(self):
        """Enable the registration controls only when double-sided is on, and
        the grid fields only in grid mode."""
        ds = self.double_sided_chk.isChecked()
        self.view_combo.setEnabled(ds)
        self.reg_combo.setEnabled(ds)
        self.place_combo.setEnabled(ds)
        self._grid_row.setEnabled(ds and self.reg_combo.currentIndex() == 1)
        self._fresh_row.setEnabled(ds and self.reg_combo.currentIndex() == 0)

    def _on_double_sided_toggled(self, checked):
        self._update_ds_controls()
        self.generate_preview()

    def _on_reg_changed(self, *_):
        self._update_ds_controls()
        if self.double_sided_chk.isChecked():
            self.generate_preview()

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
            if side == "Top":
                self.preview.show_segments([], [], top_cuts=cuts, pins=mlay.align_holes)
            else:
                self.preview.show_segments(cuts, rapids, pins=mlay.align_holes)
            return
        # Both sides (or the drill tab): design-frame X-ray for registration.
        lay = self._double_sided_layout()
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
            self.statusBar().showMessage(self._drill_status(), 8000)
            return
        cuts, rapids = toolpath_segments(self.state.toolpaths(op))
        self.preview.show_segments(cuts, rapids)
        if op == "traces":
            from gerber2rml.analysis import find_narrow_gaps
            gaps = find_narrow_gaps(self.state.board.copper,
                                    self.state.board.outline,
                                    self.state.trace.bit_diameter)
            if not gaps.is_empty:
                self.preview.show_gaps(gaps)
                self.statusBar().showMessage(
                    "Warning: copper gaps too narrow to isolate (shown red)", 8000)
                gap_warning = True
        if not gap_warning:
            self.statusBar().showMessage(f"Preview updated in {time.time() - t0:.2f}s", 5000)

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
            return build_double_sided(
                self.state.gerber_dir, out_dir, self.state.name,
                trace=self.state.trace, drill=self.state.drill, cutout=self.state.cutout,
                dowels=self._dowel_spec(), machine=self.state.machine,
                offset=(self.state.place_x, self.state.place_y),
                board_thickness=self.thickness_spin.value())
        return self.state.export(out_dir)

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
            self.statusBar().showMessage(f"Exported successfully to: {out}", 10000)

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
                machine=self.state.machine)
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))
            return
        self.statusBar().showMessage(
            f"Dowel holes only -> {path.name}  (keep the same XY origin)", 10000)

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
            self.statusBar().showMessage(
                "Rework: drag a box over the area to re-cut, then Export selected NC",
                8000)

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
            self.statusBar().showMessage(
                "Move: drag the design to reposition it on the bed", 8000)

    def _on_move_delta(self, dx, dy):
        """Drag committed in the preview -> fold the shift into the placement."""
        self.place_x_spin.blockSignals(True)
        self.place_x_spin.setValue(max(0.0, self.place_x_spin.value() + dx))
        self.place_x_spin.blockSignals(False)
        # setting Y triggers a single regenerate_preview at the new placement
        self.place_y_spin.setValue(max(0.0, self.place_y_spin.value() + dy))

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

def apply_dark_theme(app):
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(45, 45, 45))
    palette.setColor(QPalette.WindowText, Qt.white)
    palette.setColor(QPalette.Base, QColor(30, 30, 30))
    palette.setColor(QPalette.AlternateBase, QColor(45, 45, 45))
    palette.setColor(QPalette.ToolTipBase, Qt.white)
    palette.setColor(QPalette.ToolTipText, Qt.white)
    palette.setColor(QPalette.Text, Qt.white)
    palette.setColor(QPalette.Button, QColor(53, 53, 53))
    palette.setColor(QPalette.ButtonText, Qt.white)
    palette.setColor(QPalette.BrightText, Qt.red)
    palette.setColor(QPalette.Link, QColor(42, 130, 218))
    palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.HighlightedText, Qt.black)
    app.setPalette(palette)
    app.setStyleSheet("QToolTip { color: #ffffff; background-color: #2a82da; border: 1px solid white; }")

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
    win = MainWindow(); win.show()
    return app.exec()

if __name__ == "__main__":
    raise SystemExit(main())
