"""gerber2rml desktop app: load Gerbers, edit variables, preview, export RML."""
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QPushButton,
    QLineEdit, QComboBox, QTabWidget, QCheckBox, QLabel, QFileDialog, QMessageBox,
)
from gerber2rml.app.state import ProjectState
from gerber2rml.app.preview import toolpath_segments
from gerber2rml.backends import BACKENDS
from gerber2rml.gui.form import DataclassForm
from gerber2rml.gui.canvas import PreviewCanvas

_OPS = ["traces", "drill", "cutout"]

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("gerber2rml - SRM-20 CAM")
        self.state = ProjectState()

        self.load_btn = QPushButton("Load Gerber folder...")
        self.load_btn.clicked.connect(self._on_load_clicked)
        self.name_edit = QLineEdit(self.state.name)
        self.machine_combo = QComboBox()
        self.machine_combo.addItems(list(BACKENDS.keys()))
        self.mirror_chk = QCheckBox("Mirror (bottom-up)"); self.mirror_chk.setChecked(True)
        self.mirror_chk.toggled.connect(self._on_mirror_toggled)
        from gerber2rml.app.presets import load_presets
        self._presets = load_presets()
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(list(self._presets.keys()))
        self.apply_preset_btn = QPushButton("Apply preset")
        self.apply_preset_btn.clicked.connect(self.apply_selected_preset)
        self.save_preset_btn = QPushButton("Save preset...")
        self.save_preset_btn.clicked.connect(self._on_save_preset)
        top = QHBoxLayout()
        for w in (self.load_btn, QLabel("Name:"), self.name_edit,
                  QLabel("Machine:"), self.machine_combo, self.mirror_chk):
            top.addWidget(w)
        for w in (QLabel("Preset:"), self.preset_combo,
                  self.apply_preset_btn, self.save_preset_btn):
            top.addWidget(w)
        top.addStretch(1)

        self.forms = {"traces": DataclassForm(self.state.trace),
                      "drill": DataclassForm(self.state.drill),
                      "cutout": DataclassForm(self.state.cutout)}
        self.tabs = QTabWidget()
        for op in _OPS:
            self.tabs.addTab(self.forms[op], op.capitalize())

        self.preview = PreviewCanvas()
        self.gen_btn = QPushButton("Generate Preview")
        self.gen_btn.clicked.connect(self.generate_preview)
        self.export_btn = QPushButton("Export .rml...")
        self.export_btn.clicked.connect(self._on_export_clicked)
        btns = QHBoxLayout(); btns.addWidget(self.gen_btn); btns.addWidget(self.export_btn)

        left = QVBoxLayout(); left.addWidget(self.tabs); left.addLayout(btns)
        left_w = QWidget(); left_w.setLayout(left)
        body = QHBoxLayout(); body.addWidget(left_w, 0); body.addWidget(self.preview, 1)

        root = QVBoxLayout(); root.addLayout(top); root.addLayout(body)
        central = QWidget(); central.setLayout(root); self.setCentralWidget(central)

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
        op = _OPS[self.tabs.currentIndex()]
        if op == "drill":
            # overlay the holes on the trace context so you can see each hole
            # sit on its pad (drill toolpaths themselves have no XY extent)
            cuts, rapids = toolpath_segments(self.state.toolpaths("traces"))
            self.preview.show_segments(cuts, rapids, holes=self.state.board.holes)
        else:
            cuts, rapids = toolpath_segments(self.state.toolpaths(op))
            self.preview.show_segments(cuts, rapids)

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
            QMessageBox.information(self, "Exported",
                                    "Wrote:\n" + "\n".join(p.name for p in written))

def main():
    app = QApplication.instance() or QApplication([])
    win = MainWindow(); win.show()
    return app.exec()

if __name__ == "__main__":
    raise SystemExit(main())
