from dataclasses import fields, replace
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QWidget, QFormLayout, QDoubleSpinBox, QSpinBox,
                               QCheckBox, QComboBox, QLineEdit)

_TOOLTIPS = {
    "bit_diameter": "Diameter of the endmill or drill bit.",
    "tool_type": ("Flat endmill (constant width) or V-bit engraver (width grows "
                  "with depth — set a target width and the depth is derived)."),
    "tip_diameter": "V-bit only: the flat width at the very tip of the V (T).",
    "included_angle": "V-bit only: the full included angle of the V tip in degrees.",
    "target_width": ("V-bit only: desired effective cut width. The plunge depth is "
                     "back-solved from this via W = T + 2*D*tan(angle/2)."),
    "single_bit": ("Use ONE bit for all holes: plunge holes that match the bit, "
                   "interpolate (mill a circle) for larger ones, in a single file. "
                   "Off = one file per hole diameter, plunged with a matching bit."),
    "cut_depth": "Depth of material removed per pass. For drills, this is the peck depth.",
    "total_depth": "Total depth to cut through the material.",
    "offsets": "Number of isolation passes. Set to -1 to clear all copper.",
    "stepover": "Distance between parallel passes, expressed as a fraction of the bit diameter.",
    "xy_feed": "Horizontal cutting speed in mm/s.",
    "plunge_feed": "Vertical plunging speed into the material in mm/s.",
    "travel_z": "Safe Z height for rapid movements above the material.",
    "tabs": "Number of holding tabs to leave on the cutout path.",
    "tab_width": "Width of each holding tab in mm.",
    "peck_retract": "How far the drill lifts between pecks to clear swarf.",
}

# The form labelled every field with its Python attribute name - "xy feed",
# "travel z", "cut depth" - in a UI where every other label is capitalised, and
# with no units anywhere. "stepover 0.500" is a FRACTION and "travel z 2.000" is
# millimetres, formatted identically. The app already knows how to do this: the
# stock thickness spin has shown " mm" all along.
_LABELS = {
    "bit_diameter": "Bit diameter",
    "tool_type": "Tool type",
    "tip_diameter": "V-bit tip width",
    "included_angle": "V-bit angle",
    "target_width": "Target cut width",
    "single_bit": "One bit for all holes",
    "cut_depth": "Depth per pass",
    "total_depth": "Total depth",
    "offsets": "Isolation passes",
    "stepover": "Stepover (of bit dia.)",
    "xy_feed": "Cutting speed",
    "plunge_feed": "Plunge speed",
    "travel_z": "Travel height",
    "tabs": "Holding tabs",
    "tab_width": "Tab width",
    "peck_retract": "Peck retract",
}

_SUFFIX = {
    "bit_diameter": " mm", "tip_diameter": " mm", "target_width": " mm",
    "cut_depth": " mm", "total_depth": " mm", "travel_z": " mm",
    "tab_width": " mm", "peck_retract": " mm",
    "xy_feed": " mm/s", "plunge_feed": " mm/s",
    "included_angle": "°",
}

# Every float field was setRange(-1000, 100000): a negative feed, a 100 m cut
# depth and a 100000 mm bit were all accepted in silence. These are the ranges
# an SRM-20 can actually be asked for.
_RANGES = {
    "bit_diameter": (0.05, 6.0), "tip_diameter": (0.0, 3.0),
    "target_width": (0.05, 6.0), "cut_depth": (0.001, 10.0),
    "total_depth": (0.001, 60.0), "travel_z": (0.1, 40.0),
    "tab_width": (0.1, 20.0), "peck_retract": (0.05, 10.0),
    "xy_feed": (0.1, 60.0), "plunge_feed": (0.1, 60.0),
    "included_angle": (5.0, 180.0), "stepover": (0.05, 1.0),
}

class DataclassForm(QWidget):
    valueChanged = Signal()

    def __init__(self, instance, parent=None, choices=None):
        super().__init__(parent)
        self._instance = instance
        self._editors = {}
        self._choices = choices or {}      # {field_name: [allowed str values]}
        self._updating = False
        layout = QFormLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        for f in fields(instance):
            val = getattr(instance, f.name)
            if isinstance(val, bool):
                w = QCheckBox(); w.setChecked(val)
                w.toggled.connect(self._on_changed)
            elif isinstance(val, int):
                w = QSpinBox(); w.setRange(-1, 100000); w.setValue(val)
                w.valueChanged.connect(self._on_changed)
            elif isinstance(val, str):
                if f.name in self._choices:
                    w = QComboBox(); w.addItems(self._choices[f.name])
                    w.setCurrentText(val)
                    w.currentTextChanged.connect(self._on_changed)
                else:
                    w = QLineEdit(val)
                    w.textChanged.connect(self._on_changed)
            else:  # float
                w = QDoubleSpinBox(); w.setDecimals(3)
                lo, hi = _RANGES.get(f.name, (-1000.0, 100000.0))
                w.setRange(lo, hi)
                if f.name in _SUFFIX:
                    w.setSuffix(_SUFFIX[f.name])
                w.setSingleStep(0.1); w.setValue(float(val))
                w.valueChanged.connect(self._on_changed)
            if f.name in _TOOLTIPS:
                w.setToolTip(_TOOLTIPS[f.name])
            self._editors[f.name] = w
            layout.addRow(_LABELS.get(f.name, f.name.replace("_", " ")), w)

    def _on_changed(self, *args):
        if not self._updating:
            self.valueChanged.emit()

    def _read(self, name):
        w = self._editors[name]
        if isinstance(w, QCheckBox):
            return w.isChecked()
        if isinstance(w, QComboBox):
            return w.currentText()
        if isinstance(w, QLineEdit):
            return w.text()
        return w.value()

    def set_field(self, name, value):
        w = self._editors[name]
        if isinstance(w, QCheckBox):
            w.setChecked(bool(value))
        elif isinstance(w, QComboBox):
            w.setCurrentText(str(value))
        elif isinstance(w, QLineEdit):
            w.setText(str(value))
        else:
            w.setValue(value)

    def set_field_value(self, name, value):
        """Set one editor's value WITHOUT emitting valueChanged (programmatic
        update, e.g. a derived depth)."""
        self._updating = True
        try:
            self.set_field(name, value)
        finally:
            self._updating = False

    def enable_field(self, name, on):
        """Grey out / re-enable a single editor (e.g. a field that is now derived)."""
        self._editors[name].setEnabled(bool(on))

    def set_instance(self, instance):
        """Replace the backing instance and push its values into the editors."""
        self._instance = instance
        self._updating = True
        try:
            for name in self._editors:
                self.set_field(name, getattr(instance, name))
        finally:
            self._updating = False

    def value(self):
        return replace(self._instance, **{n: self._read(n) for n in self._editors})
