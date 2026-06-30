import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from gerber2rml.config import TraceJob
from gerber2rml.gui.form import DataclassForm

_app = QApplication.instance() or QApplication([])

def test_form_reads_dataclass_values():
    form = DataclassForm(TraceJob())
    assert form.value().bit_diameter == 0.4
    assert form.value().offsets == 2

def test_form_edit_reflects_in_value():
    form = DataclassForm(TraceJob())
    form.set_field("bit_diameter", 0.8)
    assert form.value().bit_diameter == 0.8

def test_form_set_instance_refreshes_editors():
    form = DataclassForm(TraceJob())
    form.set_instance(TraceJob(bit_diameter=0.8, offsets=4))
    assert form.value().bit_diameter == 0.8
    assert form.value().offsets == 4


def test_form_round_trips_string_field():
    # tool_type is a str — the form must not crash trying to float() it
    form = DataclassForm(TraceJob())
    assert form.value().tool_type == "flat"


def test_form_string_choices_render_as_combo_and_set():
    form = DataclassForm(TraceJob(), choices={"tool_type": ["flat", "vbit"]})
    form.set_field("tool_type", "vbit")
    assert form.value().tool_type == "vbit"
