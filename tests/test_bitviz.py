"""Tests for the tool-profile cross-section widget."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import math
from PySide6.QtWidgets import QApplication
from gerber2rml.config import TraceJob
from gerber2rml.gui.bitviz import BitProfileWidget

_app = QApplication.instance() or QApplication([])


def _vbit():
    return TraceJob(tool_type="vbit", tip_diameter=0.1, included_angle=30.0,
                    target_width=0.2)


def test_bitviz_renders_vbit_and_flat_without_error():
    w = BitProfileWidget()
    w.resize(320, 150)
    w.grab()                                   # empty state must not raise
    w.set_job(_vbit())
    w.grab()
    w.set_job(TraceJob(tool_type="flat", bit_diameter=0.8, cut_depth=0.15))
    w.grab()


def test_bitviz_width_at_matches_job_math():
    w = BitProfileWidget()
    job = _vbit()
    w.set_job(job)
    # W = T + 2*D*tan(theta/2): at 0.3 mm deep a 30deg/0.1 tip cuts ~0.261 mm
    assert math.isclose(w.width_at(0.3), job.width_at_depth(0.3))
    assert math.isclose(w.width_at(0.3), 0.1 + 0.6 * math.tan(math.radians(15)),
                        rel_tol=1e-9)
    # flat: constant regardless of depth
    w.set_job(TraceJob(tool_type="flat", bit_diameter=0.8))
    assert w.width_at(0.05) == 0.8 and w.width_at(1.0) == 0.8


def test_bitviz_wired_into_main_window():
    from tests.test_window import FIXT  # reuse the fixture path
    from gerber2rml.gui.app import MainWindow
    w = MainWindow()
    # the widget mirrors the active traces job (preset default = flat 0.8)
    assert w.bit_viz._job is not None
    assert w.bit_viz._job.tool_type == w.forms["traces"].value().tool_type
    # switching the form to vbit flows through _sync_vbit_fields into the widget
    w.forms["traces"].set_field("tool_type", "vbit")
    assert w.bit_viz._job.tool_type == "vbit"
