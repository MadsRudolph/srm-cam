"""gerber2rml desktop app: load Gerbers, edit variables, preview, export RML."""
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QPushButton,
    QLineEdit, QComboBox, QTabWidget, QCheckBox, QLabel, QFileDialog, QMessageBox,
    QSplitter, QGroupBox, QStyle, QFormLayout
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

        # which side(s) to show in the double-sided preview
        self.view_combo = QComboBox()
        self.view_combo.addItems(["Both sides", "Bottom", "Top"])
        self.view_combo.setEnabled(False)   # only meaningful when double-sided
        self.view_combo.currentIndexChanged.connect(self.generate_preview)
        
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
        project_layout.addRow("", self.double_sided_chk)
        project_layout.addRow("View:", self.view_combo)
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

    def _double_sided_layout(self):
        """Design-frame layout for the PREVIEW (both layers registered, holes on
        pads, top plain). The export uses the machine-frame layout separately.
        Cached by folder so live form edits don't re-read disk."""
        from gerber2rml.doublesided import preview_layout_double_sided
        key = str(self.state.gerber_dir)
        if self._ds_cache is None or self._ds_cache[0] != key:
            self._ds_cache = (key, preview_layout_double_sided(self.state.gerber_dir))
        return self._ds_cache[1]

    def _on_double_sided_toggled(self, checked):
        self.view_combo.setEnabled(checked)
        self.generate_preview()

    def _preview_double_sided(self, op):
        """Show the registered board with the two dowel/alignment holes so the
        operator can check the flip registration and pin placement before
        milling. The View selector picks bottom (cyan), top (magenta), or both
        overlaid; the dowels are always shown. Board holes are shown on the
        drill tab only."""
        from gerber2rml.engine.traces import isolate
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

    def generate_preview(self):
        # keep the rework export button in sync with the active tab / mode
        self._on_selection_changed(self.preview.selection_bbox())
        if self.state.board is None:
            return
        self._sync_state()
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
                machine=self.state.machine)
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

    def _open_sim_window(self, toolpaths, label):
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
        self._sim_window = Simulation3DWindow(toolpaths, title=label)
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
        # an active rework box on a clippable op -> simulate just that part
        bbox = self.preview.selection_bbox()
        if bbox is not None and op != "drill" and not self.double_sided_chk.isChecked():
            from gerber2rml.engine.select import clip_toolpaths_to_bbox
            clipped = clip_toolpaths_to_bbox(toolpaths, bbox)
            if clipped:
                toolpaths, label = clipped, f"{op} rework"
        if not toolpaths:
            QMessageBox.information(self, "Nothing to simulate",
                                    "No toolpaths for this view.")
            return
        self._open_sim_window(toolpaths, f"{self.state.name} - {label} (3D)")

    def _on_select_toggled(self, checked):
        self.preview.set_selecting(checked)
        if checked:
            self.statusBar().showMessage(
                "Rework: drag a box over the area to re-cut, then Export selected NC",
                8000)

    def _on_selection_changed(self, bbox):
        op = _OPS[self.tabs.currentIndex()]
        has_box = bbox is not None and op != "drill" \
            and not self.double_sided_chk.isChecked()
        self.export_sel_btn.setEnabled(has_box)
        if bbox is not None:
            w = abs(bbox[2] - bbox[0]); h = abs(bbox[3] - bbox[1])
            self.statusBar().showMessage(
                f"Selected {w:.1f} x {h:.1f} mm for {op} rework", 6000)

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
        if op == "drill" or self.double_sided_chk.isChecked():
            QMessageBox.warning(self, "Not available",
                                "Rework export works on the single-sided traces "
                                "or cutout preview.")
            return
        self._sync_state()
        clipped = clip_toolpaths_to_bbox(self.state.toolpaths(op), bbox)
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
            path = Path(out) / f"{self.state.name}_{op}_rework{backend.ext}"
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
