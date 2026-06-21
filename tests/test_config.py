"""Tests for job config dataclasses."""
from gerber2rml.config import TraceJob, DrillJob, CutoutJob, BoardConfig


def test_trace_defaults_match_srm20():
    j = TraceJob()
    assert j.bit_diameter == 0.4
    assert j.cut_depth == 0.10
    assert j.offsets == 2
    assert j.xy_feed == 4.0
    assert j.plunge_feed == 1.0


def test_cutout_has_tabs():
    c = CutoutJob()
    assert c.bit_diameter == 0.8
    assert c.tabs == 4
    assert c.tab_width == 1.5


def test_board_thickness_default():
    assert BoardConfig().thickness == 1.6


def test_drill_total_depth():
    assert DrillJob().total_depth == 1.8
