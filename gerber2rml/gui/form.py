"""Build a Qt form from a dataclass instance; read edits back as a new instance."""
from dataclasses import fields, replace
from PySide6.QtWidgets import QWidget, QFormLayout, QDoubleSpinBox, QSpinBox, QCheckBox

class DataclassForm(QWidget):
    def __init__(self, instance, parent=None):
        super().__init__(parent)
        self._instance = instance
        self._editors = {}
        layout = QFormLayout(self)
        for f in fields(instance):
            val = getattr(instance, f.name)
            if isinstance(val, bool):
                w = QCheckBox(); w.setChecked(val)
            elif isinstance(val, int):
                w = QSpinBox(); w.setRange(-1, 100000); w.setValue(val)
            else:  # float
                w = QDoubleSpinBox(); w.setDecimals(3); w.setRange(-1000.0, 100000.0)
                w.setSingleStep(0.1); w.setValue(float(val))
            self._editors[f.name] = w
            layout.addRow(f.name.replace("_", " "), w)

    def _read(self, name):
        w = self._editors[name]
        if isinstance(w, QCheckBox):
            return w.isChecked()
        return w.value()

    def set_field(self, name, value):
        w = self._editors[name]
        if isinstance(w, QCheckBox):
            w.setChecked(bool(value))
        else:
            w.setValue(value)

    def set_instance(self, instance):
        """Replace the backing instance and push its values into the editors."""
        self._instance = instance
        for name in self._editors:
            self.set_field(name, getattr(instance, name))

    def value(self):
        return replace(self._instance, **{n: self._read(n) for n in self._editors})
