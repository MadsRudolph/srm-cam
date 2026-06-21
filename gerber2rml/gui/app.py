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
        
        self.export_btn = QPushButton("Export .rml...")
        self.export_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        self.export_btn.clicked.connect(self._on_export_clicked)
        self.export_btn.setStyleSheet("font-weight: bold; padding: 5px;")

        self.name_edit = QLineEdit(self.state.name)
        self.machine_combo = QComboBox()
        self.machine_combo.addItems(list(BACKENDS.keys()))
        self.mirror_chk = QCheckBox("Mirror (bottom-up)"); self.mirror_chk.setChecked(True)
        self.mirror_chk.toggled.connect(self._on_mirror_toggled)
        
        from gerber2rml.app.presets import load_presets
        self._presets = load_presets()
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(list(self._presets.keys()))
        self.apply_preset_btn = QPushButton("Apply")
        self.apply_preset_btn.clicked.connect(self.apply_selected_preset)
        self.save_preset_btn = QPushButton("Save...")
        self.save_preset_btn.clicked.connect(self._on_save_preset)

        # Build Settings Panel
        settings_panel = QWidget()
        settings_layout = QVBoxLayout(settings_panel)
        settings_layout.setContentsMargins(10, 10, 10, 10)
        
        # Project Group
        project_group = QGroupBox("Project")
        project_layout = QFormLayout(project_group)
        project_layout.addRow(self.load_btn, self.export_btn)
        project_layout.addRow("Name:", self.name_edit)
        project_layout.addRow("Machine:", self.machine_combo)
        project_layout.addRow("", self.mirror_chk)
        settings_layout.addWidget(project_group)
        
        # Presets Group
        presets_group = QGroupBox("Presets")
        presets_layout = QHBoxLayout(presets_group)
        presets_layout.addWidget(self.preset_combo, 1)
        presets_layout.addWidget(self.apply_preset_btn)
        presets_layout.addWidget(self.save_preset_btn)
        settings_layout.addWidget(presets_group)

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

    def generate_preview(self):
        if self.state.board is None:
            return
        self._sync_state()
        t0 = time.time()
        op = _OPS[self.tabs.currentIndex()]
        if op == "drill":
            cuts, rapids = toolpath_segments(self.state.toolpaths("traces"))
            self.preview.show_segments(cuts, rapids, holes=self.state.board.holes)
        else:
            cuts, rapids = toolpath_segments(self.state.toolpaths(op))
            self.preview.show_segments(cuts, rapids)
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
        return self.state.export(out_dir)

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
        out = QFileDialog.getExistingDirectory(self, "Select output folder")
        if out:
            try:
                written = self.export_to(out)
            except Exception as e:
                QMessageBox.critical(self, "Export failed", str(e))
                return
            self.statusBar().showMessage(f"Exported successfully to: {out}", 10000)

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

def main():
    app = QApplication.instance() or QApplication([])
    apply_dark_theme(app)
    win = MainWindow(); win.show()
    return app.exec()

if __name__ == "__main__":
    raise SystemExit(main())
