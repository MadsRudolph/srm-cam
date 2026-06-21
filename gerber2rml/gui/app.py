"""gerber2rml desktop app: load Gerbers, edit variables, preview, export RML."""
import os
from pathlib import Path
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
        top = QHBoxLayout()
        for w in (self.load_btn, QLabel("Name:"), self.name_edit,
                  QLabel("Machine:"), self.machine_combo, self.mirror_chk):
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

    def _sync_state(self):
        self.state.name = self.name_edit.text() or "board"
        self.state.machine = self.machine_combo.currentText()
        self.state.mirror = self.mirror_chk.isChecked()
        self.state.trace = self.forms["traces"].value()
        self.state.drill = self.forms["drill"].value()
        self.state.cutout = self.forms["cutout"].value()

    def load_folder(self, folder):
        self._sync_state()
        self.state.load(folder)

    def generate_preview(self):
        if self.state.board is None:
            return
        self._sync_state()
        op = _OPS[self.tabs.currentIndex()]
        cuts, rapids = toolpath_segments(self.state.toolpaths(op))
        self.preview.show_segments(cuts, rapids)

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
            written = self.export_to(out)
            QMessageBox.information(self, "Exported",
                                    "Wrote:\n" + "\n".join(p.name for p in written))

def main():
    app = QApplication.instance() or QApplication([])
    win = MainWindow(); win.show()
    return app.exec()

if __name__ == "__main__":
    raise SystemExit(main())
